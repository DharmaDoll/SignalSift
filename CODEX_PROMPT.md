# Codex Initial Prompt — SignalSift Security Profile

Implement the MVP described in this repository.

Before writing code, read:

```text
AGENTS.md
README.md
docs/DESIGN.md
config/sources.yaml
config/filters.yaml
```

## Product concept

The product is named **SignalSift**.

SignalSift is a generic, configuration-driven signal collector:

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

The first concrete use case in this repository is the **Security Profile**.

Do not hard-code the core engine so tightly to security that it cannot reasonably be reused.

At the same time, do not build speculative plugin/profile framework code.

The design target is:

```text
generic core by clean boundaries
+
security-specific configuration
```

not:

```text
generic framework for hypothetical future use cases
```

## Current Security Profile

The first profile collects high-signal public information about:

1. software supply-chain attacks
2. important / actively exploited vulnerabilities
3. LLM / AI-agent / MCP security

It delivers selected items to Slack.

## Fixed implementation decisions

Use:

- Python 3.12+
- run-once CLI: `signalsift run`
- GitHub Actions schedule
- GitHub Actions `workflow_dispatch`
- Slack Incoming Webhook
- `config/sources.yaml`
- `config/filters.yaml`
- dedicated `state` branch
- `state/notified.json`
- deterministic filtering
- generic RSS / Atom / RDF as the default source integration
- small source-specific adapters only where justified

Do not use:

- external databases
- Actions Cache as authoritative state
- mandatory LLM calls
- browser automation by default
- generic crawler frameworks
- dynamic plugin loading
- profile inheritance
- unnecessary dependency injection frameworks

## Configuration meaning

The existing files are the current **Security Profile configuration**:

```text
config/sources.yaml
config/filters.yaml
```

Do not move them into `config/security/` yet.

There is only one real profile today.

If a second profile appears later, that refactor can be made then.

## Core-domain separation

Keep these concepts generic:

```text
NormalizedItem
Fetcher
Filter engine
Scoring
Article key
State store
Notifier boundary
```

Do not require every normalized item to contain security-only fields.

Security identifiers such as CVE / GHSA should use generic fields such as:

```text
external_ids[]
```

Security-specific keyword rules live in `filters.yaml`.

Security-specific source choices live in `sources.yaml`.

Security-specific parsing belongs only in justified adapters such as CISA KEV.

## Source implementation rule

For every source, attempt integration in this order:

```text
1. generic RSS / Atom / RDF
2. generic JSON
3. source-specific adapter
4. HTML scraping
```

A normal RSS source must not require a dedicated class.

Do not put CSS selectors, XPath, JSONPath programs, regex transformation pipelines, or mapping DSLs into YAML.

Configuration controls operational values.

Code implements parsing behavior.

## Active versus candidate sources

Implement only currently active entries in `config/sources.yaml`.

Candidate sources are deliberately preserved as commented-out configuration.

Do not:

- uncomment them
- implement adapters for them
- fetch them
- add tests for them

unless needed for the active MVP.

## Filtering

The Security Profile must use deterministic compound rules.

Examples:

```text
AI context
AND
security context
```

and:

```text
vulnerability context
AND
exploitability / impact context
```

Do not notify every CVE.

Do not notify generic AI news.

Each selected item must provide an explainable `why_matched`.

## Deduplication

Once an article is successfully posted to Slack, the same article must not be posted again.

Create `article_key` using:

```text
stable feed GUID
else canonical URL
else source_id + normalized title hash
```

Do not use CVE alone as the article key.

Persist notification state only after Slack confirms success.

## State

Use:

```text
state branch
└── state/notified.json
```

Prevent concurrent state writes with GitHub Actions `concurrency`.

Do not use runner-local storage as durable state.

## First run

If state is absent, only process items newer than:

```text
initial_lookback_hours
```

Do not backfill the historical contents of feeds.

## Tests

Implement local fixtures proving at least:

```text
supply-chain incident             -> notify
supply-chain marketing            -> drop
actively exploited vulnerability  -> notify
ordinary CVE                      -> drop
MCP / LLM security issue          -> notify
generic AI news                   -> drop
same article twice                -> notify once
Slack failure                     -> not persisted
historical first-run item         -> drop
```

Also test that at least two ordinary RSS sources pass through the same generic RSS implementation with no source-specific class.

## Repository discipline

Keep the implementation small.

Target approximately:

```text
src/signalsift/
├── cli.py
├── models.py
├── fetch.py
├── adapters.py
├── filter.py
├── dedupe.py
├── state.py
└── slack.py
```

Do not split files unless actual complexity justifies it.

## Completion criteria

The MVP is complete when:

- `signalsift run` performs one full cycle
- GitHub Actions can schedule it
- enabled sources are processed independently
- source failures are isolated
- normal RSS sources use the generic fetcher
- Security Profile filters are configuration-driven
- duplicate articles are suppressed
- Slack delivery occurs only for selected items
- state survives GitHub-hosted runners
- no external application infrastructure is required
- core types are not unnecessarily coupled to security semantics

When uncertain, choose the smaller implementation.
