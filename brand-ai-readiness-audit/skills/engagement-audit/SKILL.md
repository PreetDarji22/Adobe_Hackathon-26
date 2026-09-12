---
name: engagement-audit
description: Audits a single URL for on-site engagement friction -- missing/duplicate H1 orientation cues, title/H1/meta-description topical mismatch (context-retention risk), thin same-domain navigation, and absence of clear call-to-action language. Use as a sub-skill of audit-orchestrator, or standalone when only the "why do visitors who arrive leave" half of the audit is needed.
license: MIT
allowed-tools: ["bash"]
---

# Engagement Audit (on-site experience)

## When to use
Called by `audit-orchestrator` for every audited URL, to surface concrete,
evidence-backed reasons a visitor who lands on the page might not stay or
act, independent of the discoverability checks.

## Inputs
- `url` (required): a single fully-qualified URL.

## Procedure
1. Fetch and parse the page (same conservative fetch rules as the other
   skills).
2. **Orientation:** check H1 count. Zero H1s is flagged (medium) as an
   orientation risk; more than one H1 is a lower-severity focus-dilution
   flag.
3. **Context retention:** extract keyword sets from `<title>`, the first
   `<h1>`, and the meta description. If title and H1 share no keywords,
   flag a possible mismatch between what likely brought a visitor here and
   what the page shows (medium). If title and meta description share no
   keywords, flag a lower-severity snippet-mismatch issue.
4. **Navigation:** count internal navigation links using subdomain-aware
   registrable domain resolution (e.g. counting `en.wikipedia.org` from
   `www.wikipedia.org` while isolating distinct domains under multi-part
   suffixes like `.gov.uk` / `.co.uk`). Fewer than 2 is flagged as a possible
   navigation dead end (medium) — a visitor with nowhere obvious to go next.

5. **Call to action:** search link text and headings for common CTA
   language (buy, sign up, get started, contact, subscribe, etc.). Absence
   is flagged at low severity only — this is a soft signal, not proof of a
   problem, since some pages (e.g. reference/documentation) legitimately
   have no CTA.

## Evidence requirements
Each finding quotes the literal extracted text (title, H1 text, meta
description) and/or the concrete count that triggered it (link count, H1
count). Never assert a qualitative judgment ("confusing", "boring") without
quoting the text a human/agent can independently evaluate.

## False-positive guards
- This skill asks "does this concretely affect orientation or engagement?"
  before flagging, not "is this common best practice?" — e.g., missing CTA
  is explicitly kept at low severity because plenty of legitimate pages
  (docs, reference, articles) have none.
- Keyword-overlap checks are a coarse heuristic; findings from them are
  capped at medium severity and marked with lower confidence, since a
  human/agent may recognize a stylistic (not substantive) mismatch.

## Output
`{"findings": [...], "raw_evidence": {"title": ..., "meta_description": ...,
"h1s": [...], "internal_link_count": N, "has_cta_language": bool}}`.

## Failure handling
On fetch failure, return empty findings and the error in `raw_evidence`;
the fetch failure itself is already reported by crawl-render-audit.
