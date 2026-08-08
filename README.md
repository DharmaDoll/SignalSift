# SignalSift

**SignalSift** is a lightweight, configuration-driven signal collector that filters noise and delivers only what matters.

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

This repository initially ships with a **Security Profile**.

## Security Profile

The current profile focuses on:

- software supply-chain attacks
- important / actively exploited vulnerabilities
- LLM / AI-agent / MCP security

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
Security Profile
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

## Security Profile configuration

Only two operator-facing configuration files are used:

```text
config/sources.yaml
config/filters.yaml
```

They currently represent the Security Profile.

### `sources.yaml`

Defines:

- enabled source
- fetch URL
- fetch type
- source priority
- small source-specific noise filters

### `filters.yaml`

Defines:

- supply-chain indicators
- vulnerability exploitability indicators
- AI / LLM security compound rules
- negative terms
- scoring
- locally relevant watch terms

Do not create a `profiles/` hierarchy until a second real profile exists.

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

Most normal blogs should require only a `sources.yaml` change.

Special structured sources such as CISA KEV may use a small adapter.

## Deduplication

Once an article has successfully been sent to Slack, it should not be sent again.

Notification state is stored on a dedicated Git branch:

```text
state
└── state/notified.json
```

The `main` branch remains focused on code and configuration.

## Secrets

Create the repository secret:

```text
SLACK_WEBHOOK_URL
```

Never commit the webhook URL.

## First run

The first execution does not backfill old articles.

Only recent items inside `initial_lookback_hours` are eligible.

## Source expansion

Additional security sources are intentionally left **commented out** in `config/sources.yaml`.

Before enabling another source, answer:

1. Which real coverage gap does it fill?
2. Does an existing active source already cover the same event class?
3. Can it use the generic RSS / JSON path?
4. What additional noise will it introduce?

Do not add feeds simply because they publish security content.

## Future profiles

A future second profile might eventually justify a structure like:

```text
config/
├── security/
│   ├── sources.yaml
│   └── filters.yaml
└── ai-news/
    ├── sources.yaml
    └── filters.yaml
```

Do not build this structure yet.

Extensibility should emerge from real use cases, not speculative abstraction.
