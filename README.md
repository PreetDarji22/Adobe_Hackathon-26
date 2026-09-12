# brand-ai-readiness-audit

An **Agent Skill Marketplace** for Adobe University Hackathon 2026, Round 3.
Given any website URL, it audits both halves of the Round-2 problem —
**AI discoverability** (why assistants don't find/cite the brand) and
**on-site engagement** (why visitors who arrive don't stay) — and emits a
single evidence-backed, severity-ranked JSON report with prioritized fixes.

## What's in this package

```
brand-ai-readiness-audit/
├── marketplace.json          # manifest: lists every skill + the entrypoint
├── README.md                 # this file
├── validate_marketplace.py   # structural self-check (run before zipping)
├── shared/                   # small stdlib-only helpers used by every skill
│   ├── webutils.py           #   fetch, robots.txt, HTML/JSON-LD extraction, domain handling
│   └── report_schema.py      #   Finding/Report dataclasses + schema validator
├── skills/
│   ├── audit-orchestrator/       <- ENTRYPOINT
│   │   ├── SKILL.md
│   │   ├── scripts/orchestrate.py
│   │   └── references/checklist.md
│   ├── crawl-render-audit/       <- off-site discoverability
│   │   ├── SKILL.md
│   │   ├── scripts/crawl_check.py
│   │   └── references/checklist.md
│   ├── freshness-corroboration/  <- freshness & trust signals
│   │   ├── SKILL.md
│   │   ├── scripts/freshness_check.py
│   │   └── references/checklist.md
│   └── engagement-audit/         <- on-site engagement
│       ├── SKILL.md
│       ├── scripts/engagement_check.py
│       └── references/checklist.md
└── tests/                    # 55 offline unit tests (fixtures, no network)
```

## What each skill does

- **audit-orchestrator** (entrypoint): receives the audit request, runs the
  three sub-skills below, merges and deduplicates their findings, assigns
  final IDs, computes the severity summary, adds evidence-anchored proactive
  suggestions, validates the report against the required schema, and
  returns it. It also owns the one step that genuinely needs live agent
  judgment rather than a script: corroborating specific factual claims
  against independent sources using the invoking agent's own `web_search`
  tool (see "Why corroboration isn't scripted" below).
- **crawl-render-audit**: can the page even be crawled, read, and have
  specific facts extracted from it? Checks general robots.txt and named AI
  crawlers (`GPTBot`, `ClaudeBot`, `PerplexityBot`, `Google-Extended`, `Applebot-Extended`),
  HTTP status, JS-render dependency (visible text vs. script-heavy raw HTML),
  JSON-LD/schema.org presence and validity, title/meta/canonical, declared sitemap
  validation with `/sitemap.xml` fallback, optional `/llms.txt` presence, and
  broken internal links.
- **freshness-corroboration**: extracts local freshness signals
  (`Last-Modified`, date meta tags, JSON-LD `dateModified`/`datePublished`),
  validates `sameAs` cross-source authority links in Organization structured data,
  evaluates entity-name candidates using high-confidence sources, flags likely
  staleness or entity ambiguity, and produces a short `facts_to_corroborate` list
  for the orchestrator's agent-level verification step.
- **engagement-audit**: H1 presence/uniqueness, title/H1/meta topical
  alignment (a proxy for "does the landing page match the intent that
  likely brought the visitor here"), subdomain-aware navigation density
  (handling multi-part public suffixes such as `.gov.uk` and `.co.uk` properly),
  and CTA language in link and button elements.

## How the entrypoint composes the others

```
audit-orchestrator (scripts/orchestrate.py)
  ├─ crawl_check.run(url)        -> findings + raw_evidence
  ├─ freshness_check.run(url)    -> findings + raw_evidence (incl. facts_to_corroborate)
  ├─ engagement_check.run(url)   -> findings + raw_evidence
  ├─ [agent step] corroborate facts_to_corroborate via web_search/web_fetch
  ├─ merge -> drop empty-evidence findings -> dedupe -> reassign sequential IDs
  ├─ build severity summary + evidence-anchored proactive_suggestions
  └─ validate_report() against shared/report_schema.py -> emit JSON
```

## Why corroboration isn't scripted

`freshness_check.py` deliberately does **not** call out to other domains
itself. A bundled script has no live search credentials and, more
importantly, scripting "3 sources agree" risks producing a corroboration
verdict that was never actually checked. Instead, the script surfaces
specific, checkable claims (`facts_to_corroborate`), and
`audit-orchestrator`'s `SKILL.md` instructs the invoking agent to check
each one with its own `web_search`/`web_fetch` tool access before folding
the result back into the report. This is the one place the pipeline
intentionally uses agent/LLM reasoning instead of a deterministic check,
and it's isolated so the rest of the audit remains fully deterministic and
runnable with no external service.

## Output format

Matches the minimum schema required by the problem statement (additional
fields such as `proactive_suggestions` and `runtime_seconds` are additive):

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
      "suggested_action": {
        "summary": "Add Product/Offer JSON-LD to every product page.",
        "priority": "high",
        "how": "Add a <script type='application/ld+json'> block in <head> containing Product schema.",
        "why": "Explicit structured data allows AI assistants to cite accurate details."
      }
    }
  ]
}
```

## Setup

No third-party dependencies are required — every script uses only the
Python standard library (`urllib`, `html.parser`, `json`, `urllib.robotparser`,
`dataclasses`). Python 3.9+ is supported.

```bash
cd brand-ai-readiness-audit
python3 --version   # 3.9+
```

## Usage

Run the whole audit through the entrypoint:

```bash
python3 skills/audit-orchestrator/scripts/orchestrate.py https://example.com
python3 skills/audit-orchestrator/scripts/orchestrate.py https://example.com --out report.json
```

Or run an individual sub-skill in isolation:

```bash
python3 skills/crawl-render-audit/scripts/crawl_check.py https://example.com
python3 skills/freshness-corroboration/scripts/freshness_check.py https://example.com
python3 skills/engagement-audit/scripts/engagement_check.py https://example.com
```

## Testing & Validation Status

- **Marketplace Manifest Compliance**: **31/31 PASS** (`validate_marketplace.py`)
- **Offline Unit Test Suite**: **55/55 PASS** across 8 test modules (`unittest` / `pytest`)
- **Package Size**: **0.31 MB** unpacked / **~59 KB** zipped (well within 50MB ceiling)
- **External Dependencies**: **Zero** (100% Python standard library)

### Run Unit Tests (100% Offline)

All 55 tests run offline against local HTML fixtures in `tests/fixtures/` — `webutils.fetch` and `webutils.check_robots` are mocked, so no network access is required:

```bash
# Windows
python -m unittest discover -s tests -v
# or
py -m unittest discover -s tests -v

# Linux / macOS
python3 -m unittest discover -s tests -v
```

Covers: HTML/JSON-LD extraction, named AI crawler access checks (`GPTBot`, `ClaudeBot`, `PerplexityBot`, `Google-Extended`, `Applebot-Extended`), declared sitemap validation, `/llms.txt` detection, `sameAs` authority validation, entity candidate extraction tightening, subdomain-aware navigation, priority-severity reconciliation, and end-to-end orchestrator runs.

### Validate Marketplace Package

```bash
# Windows
python validate_marketplace.py

# Linux / macOS
python3 validate_marketplace.py
```

## Safety / guardrails

- **Read-only.** No skill ever writes to, authenticates against, or alters
  the audited site. Only `GET` requests are issued.
- **robots.txt is honored**, and treated as "unknown" (not "allowed") if it
  can't be read — never fails open.
- **Conservative crawling limits**: short timeouts, a per-page size cap, and
  bounded link checking per audit.
- **No pretrained model weights** are bundled.
- **No external service is required** to resolve the marketplace itself.

## Known limitations

- JS-render dependency is detected **heuristically** from raw HTML (visible
  text volume, script-to-text ratio, empty framework-root `div`s) rather
  than by executing JavaScript in a headless browser.
- Engagement checks (title/H1 alignment, CTA presence) are text-based
  heuristics, not visual/UX analysis.
- Freshness corroboration requires the invoking agent to run `web_search` on
  flagged claims.
