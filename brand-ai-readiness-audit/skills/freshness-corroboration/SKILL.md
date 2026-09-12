---
name: freshness-corroboration
description: Extracts local freshness signals (Last-Modified header, date meta tags, JSON-LD datePublished/dateModified) and entity-name candidates from a single URL, and flags specific factual claims worth cross-checking against independent sources. Use as a sub-skill of audit-orchestrator; the actual cross-source corroboration step requires the invoking agent's own web_search access and is documented as a separate procedure step, not performed by the bundled script.
license: MIT
allowed-tools: ["bash", "web_search", "web_fetch"]
---

# Freshness & Corroboration Audit (trust signals)

## When to use
Called by `audit-orchestrator` for every audited URL, to surface staleness
risk and possible entity-identity ambiguity, and to hand off a short list of
concrete claims for the orchestrator's agent-level corroboration step.

## Inputs
- `url` (required): a single fully-qualified URL.

## Procedure
1. Fetch the page once (reuses the same conservative fetch rules as
   crawl-render-audit: short timeout, size cap).
2. Extract freshness signals: HTTP `Last-Modified` header, recognized date
   meta tags, and `datePublished`/`dateModified`/`dateCreated` from any
   JSON-LD blocks. Take the most recent parseable date as the page's
   freshness signal.
3. If no freshness signal exists at all, flag it (medium severity) — this is
   a discoverability-adjacent problem (an assistant has no basis to judge
   currency), not proof the content is actually stale.
4. If a freshness signal exists and is older than 365 days, flag possible
   staleness (medium, escalating to high past ~2 years) — phrased as "may be
   stale, verify," not "is wrong."
5. Collect entity-name candidates from `<title>`, `<h1>`, and any
   `name` fields in Organization/LocalBusiness/Corporation JSON-LD. If two
   or more meaningfully different names are found, flag possible entity
   ambiguity (low/medium — this is inherently a soft signal).
6. Build `facts_to_corroborate`: a short list of specific, checkable claims
   (entity name, founding date, address, phone) — evidence to hand to the
   orchestrator's agent-level step, **not** a corroboration result itself.
7. Do **not** call any search/fetch tool for other domains from inside this
   script. Cross-source corroboration is explicitly the orchestrator's
   Procedure step 3 (agent-level), so that every "sources agree/disagree"
   claim in the final report is backed by an actual search that happened in
   this run, never fabricated.

## Evidence requirements
Each finding cites the literal date strings found (or their absence), their
source (`http_last_modified` / meta key / JSON-LD field), and computed age
in days. `facts_to_corroborate` entries carry the claim text and why it
matters — no corroboration verdict.

## False-positive guards
- Never assert staleness from a missing signal alone — "no signal" and
  "stale" are reported as two different findings with different evidence.
- Never claim two names are "the same entity, misspelled" or "different
  entities" — only that multiple names were observed; identity resolution
  is left to the agent-level corroboration step if it matters.

## Output
`{"findings": [...], "raw_evidence": {"freshness_signals": {...},
"most_recent_signal": "...", "entity_candidates": [...],
"facts_to_corroborate": [...]}}`.

## Failure handling
On fetch failure, return empty findings and the fetch error in
`raw_evidence` — crawl-render-audit already reports the fetch failure itself
as a finding, so this skill does not duplicate it.
