# SignalSift Design


## 0. Product model

SignalSift has two conceptual layers:

```text
┌───────────────────────────────────┐
│          SignalSift Core          │
│ Fetch / Normalize / Filter /      │
│ Score / Dedupe / Notify / State   │
└───────────────────────────────────┘
                  +
┌───────────────────────────────────┐
│         Security Profile          │
│ sources.yaml + filters.yaml       │
│ + justified security adapters     │
└───────────────────────────────────┘
```

The core is intentionally reusable.

The current profile is intentionally security-specific.

This distinction should be preserved without creating unnecessary framework machinery.

The project should be **generic by clean boundaries**, not generic because it contains a large plugin system.


## 1. Objective

The current Security Profile is a security information **signal collector**, not a threat-intelligence platform.

SignalSift itself is more general: it is a small information-sifting pipeline whose first concrete profile happens to be security.

The distinction matters.

A TIP normally optimizes for:

```text
collection
normalization
correlation
enrichment
retention
search
```

This project optimizes for:

```text
precision
timeliness
local usefulness
low notification volume
```

The expected output is a small number of Slack messages worth reading.

---

## 2. Architecture

```text
                 GitHub Actions
                       │
                       ▼
                sources.yaml
                       │
                       ▼
                  Fetch layer
             ┌─────────┼──────────┐
             ▼         ▼          ▼
            RSS       JSON      Adapter
             └─────────┼──────────┘
                       ▼
                NormalizedItem
                       │
                       ▼
              Source pre-filter
                       │
                       ▼
                filters.yaml
                       │
                       ▼
                Filter / Score
                       │
                       ▼
                 article_key
                       │
                       ▼
              state/notified.json
                 │           │
               known       unseen
                 │           │
                drop         ▼
                           Slack
                             │
                          success
                             │
                             ▼
                    persist state branch
```

---

## 3. Why source parsing is code, not configuration

Security publications vary.

Some use RSS.

Some expose JSON.

Some use source-specific structures.

It is tempting to represent all of this in YAML:

```yaml
selector:
jsonpath:
xpath:
regex:
mapping:
transform:
```

Do not do that.

Once configuration describes extraction algorithms, it has become an undocumented programming language.

That creates:

- harder reviews
- fragile configuration
- poor type safety
- difficult tests
- unclear responsibility between config and code

The chosen boundary is:

```text
Configuration = operator choices
Code          = parsing behavior
```

---

## 4. Generic source first

A normal RSS publication must not need a custom adapter.

Example:

```yaml
- id: flatt
  enabled: true
  type: rss
  url: ...
```

The generic fetcher normalizes it.

A special source may declare:

```yaml
- id: cisa_kev
  type: json
  adapter: cisa_kev
```

The adapter exists because KEV has useful semantics such as:

```text
cveID
vendorProject
product
dateAdded
requiredAction
knownRansomwareCampaignUse
```

This is a legitimate code-level specialization.

---

## 5. Source-level filter versus global filter

These must remain separate.

### Source-level filter

Used only for publication-specific noise.

Example:

```text
Wiz:
exclude customer stories / webinars

Aikido:
prefer Vulnerabilities & Threats
```

### Global filter

Used for security relevance.

Example:

```text
AI context
AND
security context
```

Do not copy the main supply-chain / LLM keyword lists into every source entry.

---

## 6. Source portfolio

Initial sources are intentionally small.

### JPCERT/CC

Role:

```text
Japanese operational advisories
domestic relevance
curated security information
```

### CISA KEV

Role:

```text
known exploitation
```

KEV is particularly useful because it answers a much more actionable question than a generic CVE feed:

```text
Is this vulnerability known to be exploited?
```

### GMO Flatt Security

Role:

```text
Japanese deep technical AppSec analysis
software supply-chain analysis
```

### Wiz

Role:

```text
cloud security
major vulnerability research
software supply chain
AI / MCP security research
```

### StepSecurity

Role:

```text
fast software supply-chain incident intelligence
GitHub Actions
npm / package compromise
```

### Aikido

Role:

```text
OSS malware
package compromise
vulnerability research
```

### Google Threat Intelligence / Mandiant

Role:

```text
major threat campaigns
exploitation
incident research
AI-enabled threat activity
```

---

## 7. Candidate sources

Candidate sources stay commented out in `sources.yaml`.

They should be enabled only when a real coverage gap appears.

Examples:

### GitHub Security Blog

Useful for:

```text
GitHub platform security
npm ecosystem
GitHub Actions security
official incident / platform guidance
```

### GitHub Security Advisories

Useful when a specific ecosystem or technology watchlist exists.

Do not subscribe to all advisories without narrowing scope.

### Socket Research

Strong package-malware and supply-chain research.

Potential overlap:

```text
StepSecurity
Aikido
```

Enable only if additional speed or coverage is needed.

### OpenSSF malicious-packages

Best treated as structured enrichment or confirmation rather than a direct Slack news stream.

### JVN / JVN iPedia

Useful when there are concrete domestic products to watch.

Broad ingestion is likely too noisy.

### NVD

Useful for lookup and enrichment.

Not recommended as the primary Slack signal source.

---

## 8. Filtering model

A flat keyword list is insufficient.

Example of a bad rule:

```text
LLM OR vulnerability OR supply-chain
```

It will produce large amounts of irrelevant content.

Use compound context.

### AI

```text
AI context
AND
security context
```

### Vulnerability

```text
vulnerability context
AND
exploitability / impact context
```

### Supply chain

Strong supply-chain incident indicators may match directly.

---

## 9. Why deterministic first

The first version should not ask an LLM to classify every article.

Reasons:

- cost
- latency
- nondeterminism
- harder debugging
- unnecessary external dependency
- difficult regression testing

A deterministic rule can explain:

```text
matched because:
- source_priority=3
- supply_chain
- compromised_package
- npm
```

That is valuable during tuning.

An LLM can later summarize items that already passed.

---

## 10. Deduplication boundary

The first version deduplicates **articles**, not security events.

Example:

```text
JPCERT article about CVE-X
Flatt technical analysis of CVE-X
Wiz research about CVE-X
```

These are different articles and may each be useful.

Therefore:

```text
CVE-X != article_key
```

A future `event_key` may correlate them if Slack becomes noisy.

Do not implement it before there is evidence it is needed.

---

## 11. State branch

GitHub-hosted runners are temporary.

The state branch acts as the smallest durable datastore.

```text
main
├── code
└── configuration

state
└── state/notified.json
```

Advantages:

- no external DB
- easy inspection
- easy recovery
- version history
- main branch stays clean
- works entirely inside GitHub

GitHub Actions Cache must not be the authoritative state store.

---

## 12. Delivery semantics

The correct transaction order is:

```text
Slack succeeds
then
persist notified state
```

If Slack succeeds but state persistence fails, a rare duplicate may occur.

That is acceptable.

The opposite ordering can permanently suppress an important alert.

For a security notification system:

```text
rare duplicate > missed alert
```

---

## 13. Future enhancements

Only add these if actual operation demonstrates the need:

```text
event-level deduplication
EPSS enrichment
daily medium-priority digest
Japanese LLM summaries
organization-specific product watchlist
package ecosystem watchlist
Slack thread updates
```

Do not pre-build them.


## 14. Generic core versus Security Profile

The following concepts belong to the generic core:

```text
SourceConfig
NormalizedItem
Fetcher
Adapter boundary
Filter evaluation
Score calculation
Article deduplication
State persistence
Notifier boundary
```

The following concepts belong to the Security Profile:

```text
JPCERT/CC
CISA KEV
Wiz
StepSecurity
Aikido
Flatt Security
Mandiant / GTI

supply-chain keywords
CVE exploitability rules
LLM / MCP security context
security watch terms
```

Security-specific data must not leak unnecessarily into the core model.

For example, prefer:

```text
external_ids = ["CVE-2026-...."]
```

over adding a mandatory:

```text
cve_id
```

field to every item.

This preserves reuse without making the code abstract for abstraction's sake.

## 15. When to introduce explicit profiles

Do not introduce profile directories merely because SignalSift could support them.

Introduce explicit profile selection only after a second real use case exists.

At that point, evaluate whether to move from:

```text
config/sources.yaml
config/filters.yaml
```

to:

```text
config/security/sources.yaml
config/security/filters.yaml

config/<other-profile>/sources.yaml
config/<other-profile>/filters.yaml
```

Until then, the current two-file layout is the simpler and preferred design.
