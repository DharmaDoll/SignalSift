# AGENTS.md — SignalSift

## 1. Mission

Build a small security-signal collector that watches a **curated set of high-quality public security sources**, aggressively filters noise, suppresses already-posted articles, and posts only useful items to Slack.

The system is intentionally small.

The value of this project is not the amount of data collected.

The value is:

> **High-quality sources + precise filtering + low-noise delivery.**

Primary topics:

1. software supply-chain attacks
2. important / actively exploited vulnerabilities
3. LLM / AI-agent / MCP security threats

The target user should be able to look at Slack and quickly understand:

- what happened
- why the item was selected
- whether it may matter
- where the primary source is

---

## 3. Core design principles

Follow these principles unless the user explicitly changes them.

### Keep the system small

Do not introduce infrastructure unless it solves a demonstrated problem.

### Keep the engine generic, keep the profile specific

The engine may know concepts such as:

- source
- normalized item
- source pre-filter
- scoring rule
- article key
- notifier
- durable state

The engine should not contain hard-coded assumptions such as:

```text
all items have CVEs
all items are vulnerabilities
all sources are security blogs
all notifications must contain CVSS
```

Security semantics belong primarily in the current profile configuration and a small number of justified adapters.

Do not create a plugin framework or generic profile loader merely to prove extensibility.

The architecture should be reusable without pre-building future abstractions.

Do NOT add by default:

- PostgreSQL
- Redis
- Kafka
- queues
- Kubernetes
- web UI
- authentication
- vector databases
- RAG
- mandatory LLM calls
- generic crawler frameworks
- browser automation
- microservices

Preferred operating footprint:

```text
GitHub Repository
GitHub Actions
Slack Incoming Webhook
```

### Prefer configuration for operations, code for behavior

Use files for values an operator may reasonably change.

For the initial Security Profile:

```text
config/sources.yaml
config/filters.yaml
```

These two files are the Security Profile configuration.

Do not create a `profiles/` directory yet.

If a second real profile is added in the future, configuration can be reorganized then.

Use code for parsing and transformation logic.

Do not turn YAML into a programming language.

Bad:

```yaml
selectors:
  article: "div:nth-child(2) > div > article"
  title: "h2.foo > a"
  date_xpath: "/html/body/..."
  transform:
    - regex_replace: ...
    - jsonpath: ...
```

Prefer a small generic fetcher or a source-specific adapter in code instead.

---

## 4. Deployment model

The primary execution environment is GitHub Actions.

Local developer execution is also a supported operating mode for debugging and manual verification.

Use `uv` as the standard Python environment and dependency workflow:

```bash
uv sync --locked
uv run --locked pytest
uv run --locked signalsift run --dry-run --state-path .local/state/notified.json
```

`uv sync` owns the repository-local `.venv`. Commit `uv.lock`; do not make `pip install -e .` or a separate `requirements.txt` the standard workflow. IDEs and debuggers may use `.venv/bin/python`.

Local real-delivery tests must use a test Slack webhook and a local state path. Dry-run must not send Slack messages or modify state. Do not add an internal or workstation scheduler.

The application itself must be a run-once CLI:

```bash
signalsift run
```

GitHub Actions provides scheduling.

Do not implement an internal scheduler.

The workflow must also support manual execution with `workflow_dispatch`.

Recommended cadence:

```text
every 30 minutes
```

Use non-zero minutes, for example:

```cron
17,47 * * * *
```

---

## 5. High-level pipeline

Keep the processing pipeline explicit:

```text
Source
  ↓
Fetch
  ↓
Normalize
  ↓
Source-level prefilter
  ↓
Global filter / score
  ↓
Article deduplication
  ↓
Slack
  ↓
Persist notified state
```

Each stage should have a small, clear responsibility.

---

## 6. Source abstraction

Different sources have different formats.

Do not solve this by putting all parsing details into YAML.

Use three levels.

### Level 1: generic RSS / Atom / RDF

This should handle most blogs.

```text
source.type = rss
```

A generic RSS fetcher should extract:

- entry id / guid
- title
- URL
- published timestamp
- summary / description
- categories / tags when available

### Level 2: generic JSON / API

Use this only where the response can be handled generically without complex configuration.

```text
source.type = json
```

Do not build a generic JSONPath DSL.

### Level 3: source-specific adapter

Use an adapter only when the source has meaningful source-specific semantics.

Example:

```yaml
type: json
adapter: cisa_kev
```

Adapters belong in code.

Keep the adapter registry simple:

```python
ADAPTERS = {
    "cisa_kev": fetch_cisa_kev,
}
```

Before adding an adapter, first verify that the generic RSS / JSON path cannot handle the source cleanly.

### HTML scraping

HTML scraping is a last resort.

Prefer:

1. RSS / Atom
2. official JSON / API
3. source-specific API adapter
4. HTML scraping

Do not crawl article pages unless feed metadata is insufficient for a likely candidate.

---

## 7. Configuration boundaries

### `config/sources.yaml`

This is the source definition for the current Security Profile.

Contains:

- source ID
- display name
- enabled
- URL
- fetch type
- optional adapter
- priority
- source-specific include/exclude hints

Example:

```yaml
- id: wiz
  name: Wiz
  enabled: true
  type: rss
  url: https://...
  priority: 3

  source_filter:
    include:
      - Wiz Research
    exclude:
      - webinar
      - customer story
```

Source-specific filtering should only remove obvious noise unique to that publication.

Do not duplicate the global security topic rules here.

### `config/filters.yaml`

This is the relevance policy for the current Security Profile.

Contains global security relevance rules.

Examples:

- supply-chain signals
- vulnerability exploitability
- AI-security compound rules
- negative / marketing terms
- scoring weights
- watched technologies

---

## 8. Normalized item

All fetchers and adapters must return the same small model:

```text
id
source_id
title
url
published_at
summary
content
categories[]
external_ids[]
raw_metadata{}
```

`content` may be empty when the feed summary is sufficient.

Downstream filtering, deduplication, and notification must not depend on source-specific schemas.

Keep the normalized model domain-neutral. Security-specific identifiers such as CVE or GHSA belong in `external_ids[]`; do not add dedicated CVE-only fields to the core model.

---

## 9. Security Profile filtering strategy

The system must work without an LLM.

Use deterministic rules first.

### Supply-chain

Strong signals include:

- supply chain attack
- compromised package
- malicious package
- package hijack
- dependency confusion
- typosquatting
- maintainer compromise
- registry compromise
- GitHub Actions compromise
- npm / PyPI / crates.io compromise

### Vulnerabilities

Do NOT notify every CVE.

Require vulnerability context plus meaningful urgency / exploitability.

Examples:

```text
CVE + exploited in the wild
CVE + KEV
vulnerability + unauthenticated RCE
vulnerability + pre-auth RCE
vulnerability + authentication bypass
zero-day
```

### AI / LLM security

Require both AI context AND security context.

AI context examples:

```text
LLM
AI agent
agentic
MCP
Model Context Protocol
Claude Code
Codex
coding assistant
RAG
AI IDE
```

Security context examples:

```text
vulnerability
attack
exploit
prompt injection
tool poisoning
credential theft
data exfiltration
authorization bypass
RCE
malicious package
supply chain
```

Generic AI news must not pass.

---

## 10. Security Profile scoring

Use an explainable integer score.

Recommended model:

```text
source priority                     +1..+3
strong topic match                  +3
active exploitation / KEV           +4
pre-auth RCE / auth bypass / 0-day  +3
watch term                          +4
actionable mitigation / affected    +2

marketing / webinar                 -5
generic product announcement        -3
```

Default Slack threshold:

```text
7
```

Every notification must have a deterministic `why_matched`.

Example:

```text
why_matched:
- supply-chain
- compromised-package
- npm
- source-priority:3
```

---

## 11. Optional LLM usage

An LLM must not be a runtime dependency for the MVP.

A later optional LLM step may be used for:

- short Japanese summary
- summarizing an already-selected article
- borderline relevance classification

If added:

- put it behind a feature flag
- deterministic behavior must remain the fallback
- never send secrets or internal asset data

---

## 12. Article deduplication

Mandatory requirement:

> Once an article has been successfully posted to Slack, do not post that same article again.

Create `article_key` in this order:

1. stable feed GUID / entry ID
2. normalized canonical URL
3. fallback: `source_id + normalized title` hash

URL normalization should remove:

- fragments
- common tracking parameters such as `utm_*`
- redundant trailing slash differences

Do not use a CVE ID alone as `article_key`.

Two separate high-quality articles about the same CVE may both be useful.

Event-level deduplication is a possible later enhancement, not MVP scope.

---

## 13. Persistent state

GitHub-hosted runners are ephemeral.

Do not depend on runner-local files for durable notification history.

Use a dedicated Git branch:

```text
state
```

The branch contains only:

```text
state/notified.json
```

Recommended format:

```json
{
  "version": 1,
  "items": {
    "<article_key>": {
      "source": "wiz",
      "title": "...",
      "url": "https://...",
      "published_at": "...",
      "notified_at": "..."
    }
  }
}
```

Do not use GitHub Actions Cache as the authoritative notification ledger.

Keep records for a bounded period, for example:

```text
180 days
```

---

## 14. Delivery semantics

Use at-least-once delivery.

Correct order:

```text
load state
↓
fetch
↓
filter
↓
check article_key
↓
Slack POST
↓
Slack success
↓
mark notified
↓
persist state
```

Never mark an article notified before Slack confirms success.

A rare duplicate is preferable to permanently missing an important alert.

---

## 15. Initial run

Do not backfill old feed content into Slack.

When no state exists, only consider items inside:

```text
initial_lookback_hours: 24
```

For CISA KEV, use `dateAdded` when necessary.

---

## 16. Notification

The initial Security Profile uses Slack as its notifier.

Use:

```text
SLACK_WEBHOOK_URL
```

from GitHub Actions Secrets.

The notification boundary should remain small enough that another notifier could be added later, but do not build a full notification plugin framework now.

Never store webhook URLs in repository files.

Keep Slack messages compact.

Example:

```text
🚨 [Supply Chain] AsyncAPI npm packages backdoored

Source: Aikido
Why: supply-chain / malicious-package / npm
Published: 2026-07-14

Five package versions were published with malicious code...

https://...
```

If many items match in a single run, send a compact digest instead of flooding the channel.

---

## 17. GitHub Actions

Create:

```text
.github/workflows/signalsift.yml
```

Requirements:

- `schedule`
- `workflow_dispatch`
- Python 3.12+
- `uv` with a committed `uv.lock`
- repository secret `SLACK_WEBHOOK_URL`
- `permissions: contents: write`
- `concurrency`
- `cancel-in-progress: false`
- run timeout
- persist the state branch only if state changed

Use one concurrency group:

```text
signalsift-state
```

---

## 18. Failure handling

One source failure must not stop other sources.

Log per source:

```text
fetch status
fetched count
candidate count
matched count
duplicate count
notified count
```

Remote content is untrusted.

Requirements:

- TLS verification
- HTTP timeout
- response size limit
- redirect limit
- safe XML parsing
- do not execute feed content
- do not follow arbitrary links automatically
- escape Slack-visible text appropriately

---

## 19. Repository shape

Do not create many files.

Preferred structure:

```text
.
├── .gitignore
├── .github/
│   └── workflows/
│       └── signalsift.yml
├── AGENTS.md
├── README.md
├── LICENSE
├── pyproject.toml
├── uv.lock
├── plan.md
├── config/
│   ├── sources.yaml
│   └── filters.yaml
├── docs/
│   └── SPECIFICATION.md
├── src/
│   └── signalsift/
│       ├── cli.py
│       ├── models.py
│       ├── fetch.py
│       ├── adapters.py
│       ├── filter.py
│       ├── dedupe.py
│       ├── state.py
│       └── slack.py
└── tests/
```

Do not split modules further unless a concrete complexity appears.

Documentation roles are intentionally limited:

- `README.md`: user-facing setup and operation
- `docs/SPECIFICATION.md`: the single source of truth for product behavior and design decisions
- `plan.md`: implementation progress; remove it after the MVP is complete if it no longer adds value

---

## 20. Testing priorities

Prioritize signal quality over framework coverage.

Tests must prove:

- relevant supply-chain incident -> notify
- marketing article mentioning supply chain -> drop
- exploited vulnerability -> notify
- ordinary CVE -> drop
- MCP / AI-agent vulnerability -> notify
- generic AI announcement -> drop
- same article twice -> notify once
- Slack failure -> state is not marked notified
- first run ignores old historical entries

Tests must use local fixtures and must not require live internet access.

---

## 21. Profile evolution rule

SignalSift is generic by architecture, not by speculative framework code.

For this first implementation:

```text
SignalSift Core
    +
Security Profile configuration
    +
Slack notifier
```

is sufficient.

Do NOT add:

- a plugin marketplace
- dynamic Python module loading
- profile inheritance
- profile schema composition
- multi-profile runtime selection
- notifier registries with unused implementations

If a second real use case is introduced later, prefer the smallest refactor that makes both profiles clean.

A future shape might become:

```text
config/
  security/
    sources.yaml
    filters.yaml

  ai-news/
    sources.yaml
    filters.yaml
```

but do not create that structure before it is needed.

The current repository should remain simple while keeping core code free from unnecessary security coupling.

## 22. Implementation order

Implement in this order:

1. config loader
2. normalized item
3. generic RSS / Atom / RDF fetcher
4. CISA KEV adapter
5. source-level include/exclude
6. deterministic filtering / scoring
7. article-key generation
8. state load / save
9. Slack webhook
10. run-once CLI
11. GitHub Actions workflow
12. tests and fixtures

Do not implement optional source adapters before the core path works.

When uncertain, choose the smaller implementation.
