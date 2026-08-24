# SignalSift

**SignalSift** is a lightweight, configuration-driven signal collector that filters noise and delivers only what matters.

運用を始める方は、まず[docs/OPERATIONS.md](docs/OPERATIONS.md)の手順を確認してください。Fork作成、Actions権限、Webhookなし検証、Slack Secret、本番state、cron、upstream同期までをまとめています。

```text
Source
  ↓
Fetch
  ↓
Normalize
  ↓
Filter / Score
  ↓
Deduplicate
  ↓
Notify
```

The engine is intentionally generic.

This repository ships with two focused security profiles.

## Profiles

The profiles separate:

- **Supply Chain Vulnerability**: software supply-chain attacks and vulnerabilities
- **AI Security**: AI / LLM / Agent / MCP / Skills vulnerabilities and attacks

Its operating principle is simple:

> Read less. Notice important things earlier.

The goal is not to ingest every CVE or every security article.

The goal is to send a small number of high-value Slack messages worth reading.

## Why SignalSift is generic

Security is the first use case, not a hard-coded architectural constraint.

The same core pipeline could later be reused for:

```text
AI / engineering news
outage information
regulatory updates
research publications
release monitoring
```

That does **not** mean the repository should build a generic plugin platform now.

The current design rule is:

```text
generic core
+
specific configuration
```

For now:

```text
SignalSift Core
+
Supply Chain Vulnerability / AI Security profiles
+
Slack
```

is enough.

## Runtime

GitHub Actions triggers the run-once CLI every 30 minutes.

```text
GitHub Actions
      ↓
signalsift run
      ↓
Slack Incoming Webhook
```

No continuously running server is required.

## Local development with `uv`

Local execution is a supported development and debugging workflow. The project uses `uv` and a repository-local `.venv`; do not maintain a separate `requirements.txt` or use `pip install -e .` as the standard setup.

```bash
uv sync --locked
uv run --locked pytest
uv run --locked signalsift run --profile supply-chain-vulnerability --dry-run --state-path .local/state/supply_chain_vulnerability.json
uv run --locked signalsift run --profile ai-security --dry-run --state-path .local/state/ai_security.json
uv run --locked signalsift run --profile supply-chain-vulnerability --dry-run --review-lookback-hours 168 --state-path .local/state/supply_chain_vulnerability.json
```

`uv sync --locked` creates or updates `.venv`. IDEs and debuggers can use `.venv/bin/python` directly.

Dry-run fetches and evaluates items but does not call Slack or modify notification state. The optional `--review-lookback-hours` mode ignores notification history in memory and prints both selected and rejected recent items for filter review. It does not change the production `initial_lookback_hours: 24` policy.

To exercise local state and deduplication without a Slack webhook, use the explicitly local-only simulated delivery mode. It records matched items as simulated successes, never calls Slack, and requires a state path under `.local/`:

```bash
uv run --locked signalsift run --profile ai-security --simulate-delivery --state-path .local/state/ai_security.json
```

Run the same command twice to verify that the second run suppresses previously recorded articles. Never reuse simulated state as the production notification ledger.

Live Slack delivery is available as a run-once CLI path. It uses a Profile-specific webhook and a local state path, kept separate from the GitHub Actions ledger:

```bash
export SLACK_WEBHOOK_URL_SUPPLY_CHAIN_VULNERABILITY="..."
export SLACK_WEBHOOK_URL_AI_SECURITY="..."
uv run --locked signalsift run --profile supply-chain-vulnerability --state-path .local/state/supply_chain_vulnerability.json
uv run --locked signalsift run --profile ai-security --state-path .local/state/ai_security.json
```

Do not commit `.venv`, `.local`, `.env`, or webhook values. Local execution remains run-once; scheduling belongs to GitHub Actions.

## Profile configuration

Each Profile owns its source set, filter, webhook selection, and notification history:

```text
config/supply_chain_sources.yaml
config/ai_security.yaml
```

The two files are intentionally independent. Changing the Supply Chain source list does not change AI Security, and vice versa.

### `supply_chain_sources.yaml`

Defines the Supply Chain Vulnerability profile and its complete source set:

- enabled source
- fetch URL
- fetch type
- source priority
- whether full feed content participates in matching
- optional summary-character limit used only for matching
- small source-specific noise filters for this profile

Flatt, Wiz, SANS ISC, StepSecurity, and Aikido currently have only obvious publication-specific exclusions; SANS ISC excludes the summary-only daily Stormcast entries. Topic selection and source membership are controlled independently in each profile file.

GitHub Security Blog uses its official RSS feed with `match_content: false`; its title, short excerpt, categories, and external IDs are evaluated while the long feed body is excluded from matching.

Google Threat Intelligence also excludes `content` and evaluates only the first 500 summary characters. Its RSS description contains the full article, so this keeps lead context while avoiding incidental matches deep in the body.

### `ai_security.yaml`

Defines:

- its own enabled source set and source-specific noise filters
- one short AI-context OR group
- one short security-context OR group
- AND between those two groups
- `SLACK_WEBHOOK_URL_AI_SECURITY`

The configuration stays flat because each profile owns its own curated sources; a nested profile framework is unnecessary.

## Source compatibility

Source integrations should follow this order:

```text
RSS / Atom / RDF
      ↓
generic JSON
      ↓
source-specific adapter
      ↓
HTML scraping
```

Source changes belong in the configuration file for the Profile being changed.

Special structured sources such as CISA KEV may use a small adapter. Flatt uses a source-specific adapter for its blog index because its RSS descriptions contain full articles and package lists that reduce filtering precision; the adapter reads only index-card metadata and does not crawl article pages.

## Deduplication

Once an article has successfully been sent to Slack, it should not be sent again.

Notification state is stored on a dedicated Git branch:

For HTML index sources whose cards do not expose a publication timestamp, the first live run records the currently visible article keys under `observed` as a baseline without notifying them. Later runs consider only newly observed cards; notification records remain under `items` and are written only after Slack succeeds.

```text
state
├── state/supply_chain_vulnerability.json
└── state/ai_security.json
```

The `main` branch remains focused on code and configuration.

## Secrets

Create separate repository secrets as needed:

```text
SLACK_WEBHOOK_URL_SUPPLY_CHAIN_VULNERABILITY
SLACK_WEBHOOK_URL_AI_SECURITY
```

Never commit the webhook URL.

## First run

The first execution does not backfill old articles.

Only recent items inside `initial_lookback_hours` are eligible.

## Source expansion

Additional security sources are intentionally left **commented out** in `config/supply_chain_sources.yaml`.

Before enabling another source, answer:

1. Which real coverage gap does it fill?
2. Does an existing active source already cover the same event class?
3. Can it use the generic RSS / JSON path?
4. What additional noise will it introduce?

Do not add feeds simply because they publish security content.

## Current profiles

The two real profiles are:

```text
supply-chain-vulnerability → supply-chain and vulnerability information
ai-security                → AI / LLM / Agent / MCP / Skills security
```

They share fetchers and source definitions but keep filters, webhooks, and state independent.
