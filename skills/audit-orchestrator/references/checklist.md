# Audit Orchestration Checklist

This checklist guides the `audit-orchestrator` entrypoint skill when composing sub-skills and producing the final report.

## 1. Input Normalization & Sanity Checks
- [ ] Normalize candidate URL (ensure `https://` or `http://` scheme).
- [ ] Parse target domain netloc for `site` summary metadata.
- [ ] Initialize execution timer for runtime monitoring (< 300s budget).

## 2. Sub-skill Composition Pass
- [ ] **crawl-render-audit**:
  - Run crawl reachability gate, robots.txt allow/disallow/404 RFC compliance, HTTP status.
  - Evaluate non-JS visible text vs script character ratio and empty framework root containers (`#root`, `#app`, `#__next`).
  - Extract and validate JSON-LD structured data blocks.
  - Verify `<title>`, meta description, OpenGraph tags, canonical link, XML sitemap, and same-domain internal links.
- [ ] **freshness-corroboration**:
  - Extract HTTP `Last-Modified`, date meta tags, JSON-LD dates.
  - Evaluate content age against thresholds (>365 days).
  - Extract brand/organization entity candidates from JSON-LD, `og:site_name`, and title suffixes.
  - Collect `facts_to_corroborate` list.
- [ ] **engagement-audit**:
  - Evaluate H1 presence and uniqueness.
  - Check title/H1/meta keyword alignment (context retention).
  - Evaluate same-domain navigation density.
  - Inspect CTA presence across links and button elements (`<button>`, `<input type="button|submit">`).

## 3. Agent-Level External Corroboration (Optional / Agent Tool Step)
- [ ] For each claim in `facts_to_corroborate`, run `web_search` if host agent tool access is available.
- [ ] Verify external directory / registry / news agreement with brand entity claims.

## 4. Synthesis & Schema Enforcement
- [ ] Drop findings with empty evidence strings.
- [ ] Deduplicate near-identical findings across checks.
- [ ] Sort findings by severity rank (`critical` -> `high` -> `medium` -> `low`).
- [ ] Reassign sequential IDs (`F-001`, `F-002`, ...).
- [ ] Calculate severity count summary (`total_findings`, `critical`, `high`, `medium`, `low`).
- [ ] Add evidence-anchored `proactive_suggestions`.
- [ ] Validate report against `shared/report_schema.py`.
