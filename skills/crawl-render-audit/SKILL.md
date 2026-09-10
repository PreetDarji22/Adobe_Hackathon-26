---
name: crawl-render-audit
description: Audits a single URL for off-site AI-discoverability blockers -- robots.txt access, HTTP status, JavaScript-render dependency (raw HTML vs what a non-JS crawler would see), structured data (JSON-LD/schema.org) presence and validity, title/meta description/canonical presence, sitemap presence, and broken same-domain internal links. Use as a sub-skill of audit-orchestrator, or standalone when only the "why can't a crawler read this" half of the audit is needed.
license: MIT
allowed-tools: ["bash"]
---

# Crawl / Render Audit (off-site discoverability)

## When to use
Called by `audit-orchestrator` for every audited URL. Can also be run
standalone (`python3 scripts/crawl_check.py <url>`) to debug discoverability
issues in isolation.

## Inputs
- `url` (required): a single fully-qualified URL.

## Procedure (deterministic, in order)
1. **Crawl access gate:** fetch `robots.txt` from the domain root; check
   whether the audited URL is disallowed for `*` or this bot's user agent.
   If robots.txt cannot be read, treat permission as *unknown*, not
   permitted — never assume access.
2. **Reachability:** `GET` the URL with a short timeout and a size cap.
   Record status code and any transport error verbatim.
3. **Readability:** parse the raw HTML (no JavaScript execution). Compute
   visible-text character count vs. `<script>` character count. Flag a
   likely JS-render dependency only when visible text is thin *and* either
   the script ratio is very high or a known framework root div
   (`#root`/`#app`/`#__next`) is present but empty in the raw HTML — never
   flag JS-dependency from a high script ratio alone on a page that already
   has substantial visible text.
4. **Fact extractability:** check for `<title>`, meta description,
   canonical link, and JSON-LD `<script type="application/ld+json">`
   blocks; attempt to parse each JSON-LD block and record parse failures
   separately from absence.
5. **Sitemap:** check `/sitemap.xml` at the domain root.
6. **Internal link health:** resolve up to 15 same-domain links found on the
   page and issue a lightweight `GET` to each; report the count that error.

## Evidence requirements
Each finding cites: the exact URL checked, the concrete measurement (byte/
character counts, HTTP status, block counts), and — for broken links — a
sample of the failing URLs with their status/error.

## False-positive guards
- Do not report "no JSON-LD" as high/critical severity by itself; it is
  medium at most, since not every page type requires structured data.
- Do not flag thin content when the page is a legitimate redirect/interstitial
  (status code already explains the thinness) — that is reported as an
  HTTP-status finding instead, not a content finding.
- Do not treat a robots.txt fetch failure as "crawling is blocked"; report
  it as unknown/not-found, not as a disallow.

## Output
Returns `{"findings": [Finding, ...], "raw_evidence": {...}}` where each
Finding has `id, title, severity, evidence, suggested_action{summary,
priority}` plus the marketplace's internal `category="discoverability"`,
`check`, `url`, `confidence`, `source_skill` fields. `raw_evidence` is kept
so the orchestrator and any corroboration step can reuse extracted signals
without re-fetching the page.

## Failure handling
If the page cannot be fetched at all, return one critical finding for the
fetch failure and skip content-dependent checks rather than raising.
