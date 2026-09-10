#!/usr/bin/env python3
"""
orchestrate.py -- audit-orchestrator skill (the marketplace ENTRYPOINT)

Composes crawl-render-audit, freshness-corroboration, and engagement-audit
into a single audit report matching the schema required by the Round 3 PDF.

Pipeline:
    fetch/parse (each sub-skill)
        -> collect raw findings
        -> validate each finding (evidence non-empty, severity justified)
        -> deduplicate near-identical findings
        -> assign final sequential IDs
        -> compute severity summary
        -> validate final report against shared/report_schema.py
        -> emit JSON to stdout (and optionally to a file)

This script is deterministic given the same page content: the same input
HTML always produces the same findings and ordering. The only source of
run-to-run variance is the live page itself changing between fetches.

Usage:
    python3 orchestrate.py https://example.com
    python3 orchestrate.py https://example.com --out report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "skills" / "crawl-render-audit" / "scripts"))
sys.path.insert(0, str(_ROOT / "skills" / "freshness-corroboration" / "scripts"))
sys.path.insert(0, str(_ROOT / "skills" / "engagement-audit" / "scripts"))

from shared import webutils  # noqa: E402
from shared.report_schema import build_summary, validate_report  # noqa: E402
import crawl_check  # noqa: E402
import freshness_check  # noqa: E402
import engagement_check  # noqa: E402

MAX_RUNTIME_WARN_SECONDS = 280  # PS requires < 5 min; warn well before that


def _dedupe(findings: list[dict]) -> list[dict]:
    """Drop findings that are effectively duplicates: same check + same url
    + same title. Keeps the first (deterministic ordering preserved)."""
    seen = set()
    deduped = []
    for f in findings:
        key = (f.get("check"), f.get("url"), f.get("title"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(f)
    return deduped


SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _reassign_ids(findings: list[dict]) -> list[dict]:
    # Sort deterministically by severity rank (critical -> high -> medium -> low)
    findings.sort(key=lambda f: SEVERITY_RANK.get(f.get("severity", "").lower(), 4))
    for i, f in enumerate(findings, start=1):
        f["id"] = f"F-{i:03d}"
    return findings


def _proactive_suggestions(url: str, all_raw_evidence: dict) -> list[dict]:
    """Suggestions that go beyond detected defects, per PS Section 1/2.
    These are intentionally conservative and evidence-anchored -- each one
    only fires when the raw evidence gives a concrete reason to suggest it,
    so this never becomes a canned generic list."""
    suggestions = []
    crawl_signals = all_raw_evidence.get("crawl", {}).get("signals", {})
    jsonld_objects = crawl_signals.get("jsonld_objects", [])

    has_org_or_product_schema = any(
        isinstance(o, dict) and o.get("@type") in (
            "Organization", "Product", "LocalBusiness", "Article", "Corporation"
        )
        for block in jsonld_objects
        for o in (block if isinstance(block, list) else [block])
        if isinstance(o, dict) or isinstance(block, list)
    )
    if jsonld_objects and not has_org_or_product_schema:
        suggestions.append({
            "id": "P-001",
            "summary": "Structured data is present but doesn't cover the "
                       "page's primary entity type",
            "priority": "medium",
            "why": "JSON-LD exists but none of the detected types "
                   "(Organization/Product/LocalBusiness/Article) match "
                   "what this page appears to represent -- expanding "
                   "coverage would let assistants extract the page's core "
                   "facts directly instead of inferring them from prose.",
        })
    elif not jsonld_objects:
        suggestions.append({
            "id": "P-001",
            "summary": "Implement schema.org JSON-LD structured data for core brand entities",
            "priority": "high",
            "why": "No JSON-LD was detected. Adding Organization / Product "
                   "JSON-LD markup provides direct, unambiguous facts for AI assistants "
                   "to quote as authoritative source claims.",
        })

    facts = all_raw_evidence.get("freshness", {}).get("facts_to_corroborate", [])
    if facts:
        suggestions.append({
            "id": "P-002",
            "summary": "Independently corroborate the flagged factual claims",
            "priority": "medium",
            "why": (
                f"{len(facts)} specific claim(s) on this page "
                f"(e.g. {facts[0]['claim']}) were identified as worth "
                "cross-checking against independent sources (directories, "
                "news, registries). Consistent independent corroboration "
                "increases an assistant's confidence in repeating these "
                "facts; the orchestrating agent should run its own "
                "web_search on each and record agreement/disagreement."
            ),
        })

    return suggestions


def run(url: str) -> dict:
    start = datetime.now(timezone.utc)
    url = webutils.normalize_url(url)

    crawl_result = crawl_check.run(url)
    freshness_result = freshness_check.run(url)
    engagement_result = engagement_check.run(url)

    all_findings = (
        crawl_result["findings"]
        + freshness_result["findings"]
        + engagement_result["findings"]
    )

    # Drop any finding without real evidence (false-positive guard, PS Phase 4
    # equivalent) -- defensive, since sub-skills already enforce this.
    all_findings = [f for f in all_findings if f.get("evidence")]

    all_findings = _dedupe(all_findings)
    all_findings = _reassign_ids(all_findings)

    raw_evidence = {
        "crawl": crawl_result.get("raw_evidence", {}),
        "freshness": freshness_result.get("raw_evidence", {}),
        "engagement": engagement_result.get("raw_evidence", {}),
    }
    proactive = _proactive_suggestions(url, raw_evidence)

    report = {
        "site": urlparse(url).netloc,
        "audited_at": start.isoformat(),
        "summary": build_summary(all_findings),
        "findings": all_findings,
        "proactive_suggestions": proactive,
        "runtime_seconds": round(
            (datetime.now(timezone.utc) - start).total_seconds(), 2
        ),
    }

    errors = validate_report(report)
    report["_schema_validation"] = "PASS" if not errors else errors

    if report["runtime_seconds"] > MAX_RUNTIME_WARN_SECONDS:
        report.setdefault("_warnings", []).append(
            f"Runtime {report['runtime_seconds']}s is approaching the "
            f"5-minute budget; consider lowering MAX_LINKS_TO_CHECK."
        )

    return report


def main():
    parser = argparse.ArgumentParser(description="Run the full brand AI-readiness audit.")
    parser.add_argument("url", help="Website URL to audit")
    parser.add_argument("--out", help="Optional path to also write the JSON report to")
    args = parser.parse_args()

    report = run(args.url)
    text = json.dumps(report, indent=2, default=str)
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
