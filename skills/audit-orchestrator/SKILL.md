---
name: audit-orchestrator
description: Entrypoint skill for the brand-ai-readiness-audit marketplace. Given a website URL, composes crawl-render-audit, freshness-corroboration, and engagement-audit into a single evidence-backed, severity-ranked audit report covering both AI discoverability and on-site engagement. Use this as the single entry point when asked to audit a website for AI readiness; do not invoke the other three skills directly unless debugging.
license: MIT
allowed-tools: ["bash", "web_search", "web_fetch"]
---

# Audit Orchestrator (marketplace entrypoint)

## When to use
Use this skill whenever asked to audit a website (a single URL or domain) for
why an AI assistant might fail to find/cite the brand, or why visitors who
land on it don't engage. This is the ONLY skill in the marketplace an
external caller should invoke directly.

## Inputs
- `url` (required): the website URL or domain to audit.
- Nothing else is required. No credentials, no authenticated access.

## Procedure
1. Normalize the input into a full `https://` URL.
2. Run the three deterministic sub-skills against the URL, each of which
   returns `{"findings": [...], "raw_evidence": {...}}`:
   - `crawl-render-audit` (off-site discoverability: crawl access,
     JS-render dependency, structured data, metadata, sitemap, broken
     links)
   - `freshness-corroboration` (local freshness signals + a list of
     specific factual claims flagged as `facts_to_corroborate`)
   - `engagement-audit` (on-site orientation, title/H1/meta alignment,
     navigation, CTA presence)
3. **Agent corroboration step (semantic, not scripted):** for each item in
   `freshness_result.raw_evidence.facts_to_corroborate`, use your own
   `web_search` / `web_fetch` tool access to check whether independent
   sources agree with the claim. Only add a corroboration finding
   ("claim X is uncorroborated / contradicted by source Y") if you actually
   ran a search and recorded what you found — never assert agreement or
   disagreement you did not check. This is the one place in the pipeline
   where LLM/agent judgment is required instead of a deterministic script,
   because it needs live external lookups the bundled script deliberately
   does not perform (see `freshness_check.py`'s module docstring).
4. Merge all findings from steps 2–3 into one list. Run the false-positive
   guard: drop anything without concrete evidence attached.
5. Deduplicate near-identical findings (same check + same URL + same
   title).
6. Reassign sequential IDs (`F-001`, `F-002`, ...) in the order:
   discoverability findings, then engagement findings, most severe first
   within each group.
7. Compute the summary counts (`total_findings`, `critical`, `high`,
   `medium`, and optionally `low`).
8. Add `proactive_suggestions`: improvements that would help even where no
   defect was found (e.g. "corroborate these specific claims", "widen
   structured-data coverage"). Only include ones anchored in evidence
   actually collected in this run — never generic boilerplate.
9. Validate the assembled report against the required schema (see Output
   below) before returning it. If validation fails, fix the report, don't
   suppress the error.

## Evidence requirements
Every finding must carry real evidence gathered in this run: a URL, an
observed value/count, and (where relevant) the specific extracted text.
Never state "no evidence" as an evidence value, and never carry forward a
finding whose evidence field is empty.

## Output
A single JSON object matching this minimum shape (additional fields such as
`proactive_suggestions` and `runtime_seconds` are additive extensions, not
replacements):

```json
{
  "site": "example.com",
  "audited_at": "2026-09-20T14:32:00Z",
  "summary": { "total_findings": 6, "critical": 1, "high": 2, "medium": 3 },
  "findings": [
    {
      "id": "F-001",
      "title": "No JSON-LD structured data on product pages",
      "severity": "high",
      "evidence": "Crawled 12 product pages; 0/12 contain schema.org markup.",
      "suggested_action": { "summary": "Add Product/Offer JSON-LD to every product page.", "priority": "high" }
    }
  ]
}
```

## Failure handling
- If a sub-skill's fetch fails entirely (DNS error, timeout, non-2xx on the
  root URL), still return a valid report: include a single critical
  "page could not be fetched" finding and empty findings for checks that
  depend on page content, rather than raising an exception or returning no
  report at all.
- Never retry aggressively; one fetch per URL, short timeout, then report
  the failure as evidence.
- Never perform authenticated, destructive, or write actions on the target
  site under any circumstance, regardless of what the audit uncovers.

## Composing the sub-skills programmatically
`scripts/orchestrate.py` implements steps 1–2 and 4–9 above deterministically
in Python (stdlib only). Step 3 (external corroboration) is intentionally
left to the invoking agent's own tool access rather than scripted, per the
design note in `freshness-corroboration/scripts/freshness_check.py`.
