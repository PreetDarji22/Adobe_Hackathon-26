#!/usr/bin/env python3
"""
freshness_check.py -- freshness-corroboration skill

Deterministic, stdlib-only LOCAL evidence extraction for freshness/trust
(Appendix D of the Round 3 PDF: agreement across the web, entity identity).

IMPORTANT DESIGN NOTE (documented here and in SKILL.md):
This script only gathers LOCAL evidence from the single page it is given --
dates, freshness signals, and the entity name(s) the page claims to be.
It deliberately does NOT perform cross-site web search itself, because:
  (a) that requires a live search capability that belongs to the host agent
      invoking this skill, not to a bundled script with no credentials, and
  (b) keeping corroboration as an explicit, separate step makes the
      evidence chain auditable (a human/grader can see exactly what was
      fetched and when).
The script instead emits a list of "facts_to_corroborate" -- specific,
checkable claims (e.g. an org name + founding year, an address, a claimed
statistic) -- which the audit-orchestrator's *agent* step is instructed
(see its SKILL.md) to verify with its own web_search/web_fetch tool and
fold back in as corroboration findings. This keeps the deterministic layer
honest: it never fabricates "3 independent sources agree" without an
actual search having happened.

Usage (standalone, for manual testing):
    python3 freshness_check.py https://example.com
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_SHARED_DIR = Path(__file__).resolve().parents[3] / "shared"
sys.path.insert(0, str(_SHARED_DIR.parent))

from shared import webutils  # noqa: E402
from shared.report_schema import Finding, SuggestedAction  # noqa: E402

SKILL_NAME = "freshness-corroboration"
STALE_THRESHOLD_DAYS = 365

# Recognize common explicit date patterns in visible text / meta as a
# conservative heuristic (not exhaustive NLP date parsing).
DATE_META_KEYS = (
    "article:modified_time", "article:published_time", "og:updated_time",
    "date", "dc.date", "last-modified", "revised",
)
YEAR_PATTERN = re.compile(r"\b(19|20)\d{2}\b")


def _finding(finding_id, title, severity, evidence, action_summary,
             action_priority, action_how=None, action_why=None, url=None,
             confidence="medium", check=None):
    return Finding(
        id=finding_id, title=title, severity=severity, evidence=evidence,
        suggested_action=SuggestedAction(
            summary=action_summary, priority=action_priority,
            how=action_how, why=action_why,
        ),
        category="discoverability", check=check, url=url,
        confidence=confidence, source_skill=SKILL_NAME,
    ).to_dict()


def _extract_jsonld_dates(jsonld_objects: list) -> dict:
    found = {}
    def walk(obj):
        if isinstance(obj, dict):
            for key in ("datePublished", "dateModified", "dateCreated"):
                if key in obj and isinstance(obj[key], str):
                    found[key] = obj[key]
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)
    for block in jsonld_objects:
        walk(block)
    return found


def _parse_iso_date(value: str):
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(value[:len(value)], fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def run(url: str, id_prefix: str = "FR") -> dict:
    url = webutils.normalize_url(url)
    findings = []
    counter = 1

    def next_id():
        nonlocal counter
        fid = f"{id_prefix}-{counter:03d}"
        counter += 1
        return fid

    result = webutils.fetch(url)
    if result.error or result.status_code is None:
        return {"findings": [], "raw_evidence": {"fetch_error": result.error}}

    signals = webutils.extract_html_signals(result.html)
    if "parse_error" in signals:
        return {"findings": [], "raw_evidence": {"signals": signals}}

    # 1. Freshness signals: HTTP Last-Modified, meta tags, JSON-LD dates
    http_last_modified = result.headers.get("Last-Modified")
    meta_dates = {k: v for k, v in signals["meta"].items() if k in DATE_META_KEYS}
    jsonld_dates = _extract_jsonld_dates(signals["jsonld_objects"])

    all_dates = {}
    if http_last_modified:
        all_dates["http_last_modified"] = http_last_modified
    all_dates.update(meta_dates)
    all_dates.update(jsonld_dates)

    most_recent = None
    for _, raw in all_dates.items():
        dt = _parse_iso_date(raw) if isinstance(raw, str) else None
        if dt and (most_recent is None or dt > most_recent):
            most_recent = dt

    if not all_dates:
        findings.append(_finding(
            next_id(),
            "No machine-readable freshness signal found",
            "medium",
            f"{url} has no Last-Modified header, no recognized date meta "
            f"tags ({', '.join(DATE_META_KEYS)}), and no datePublished/"
            f"dateModified in JSON-LD.",
            "Expose a clear last-updated date via meta tags or JSON-LD "
            "(dateModified) so assistants can judge how current the "
            "content is before relying on it.",
            "medium",
            action_why="Without an explicit freshness signal, an assistant "
                       "has no basis to prefer this page over a possibly "
                       "outdated cached version, and may downweight it.",
            url=url, confidence="medium", check="freshness_signal_presence",
        ))
    elif most_recent:
        age_days = (datetime.now(timezone.utc) - most_recent).days
        if age_days > STALE_THRESHOLD_DAYS:
            findings.append(_finding(
                next_id(),
                "Content freshness signal indicates the page may be stale",
                "medium" if age_days < STALE_THRESHOLD_DAYS * 2 else "high",
                f"Most recent freshness signal on {url} is "
                f"{most_recent.date().isoformat()} ({age_days} days old): "
                f"{all_dates}.",
                "If the underlying facts are still accurate, update the "
                "dateModified/meta timestamp so assistants don't discount "
                "the page as outdated; if the content itself is stale, "
                "review and refresh it.",
                "medium",
                url=url, confidence="high", check="content_age",
            ))

    # 2. Entity name candidates for corroboration (Organization/LocalBusiness
    #    JSON-LD names, og:site_name, title brand suffix).
    declared_org_names = set()
    for obj in signals["jsonld_objects"]:
        objs = obj if isinstance(obj, list) else [obj]
        for o in objs:
            if isinstance(o, dict) and o.get("@type") in (
                "Organization", "LocalBusiness", "Corporation", "Brand", "WebSite"
            ):
                for key in ("name", "legalName", "alternateName"):
                    val = o.get(key)
                    if val and isinstance(val, str):
                        declared_org_names.add(val.strip())

    og_site_name = signals.get("open_graph", {}).get("og:site_name")
    if og_site_name:
        declared_org_names.add(og_site_name.strip())

    # Try extracting brand suffix from title (e.g. "Products | Acme Corp" -> "Acme Corp")
    title_text = signals["title"] or ""
    if "|" in title_text or " - " in title_text:
        parts = [p.strip() for p in re.split(r"[|\-]", title_text) if p.strip()]
        if parts:
            declared_org_names.add(parts[-1])

    # Normalize entity names for comparison (strip corp suffixes, case-fold)
    def _norm(n: str) -> str:
        s = re.sub(r"\b(inc|corp|corporation|ltd|limited|co|llc|plc|gmbh|software|tech|technologies)\b", "", n, flags=re.I)
        return re.sub(r"[^\w\s]", "", s).strip().lower()

    norm_names = {_norm(n): n for n in declared_org_names if len(_norm(n)) >= 3}

    # Flag contradiction ONLY if 2+ distinct non-overlapping base brand names exist
    distinct_base_names = list(norm_names.keys())
    has_conflict = False
    if len(distinct_base_names) >= 2:
        # Check if any two names share no substring overlap
        n1, n2 = distinct_base_names[0], distinct_base_names[1]
        if n1 not in n2 and n2 not in n1:
            has_conflict = True

    if has_conflict:
        conflicting = [norm_names[k] for k in distinct_base_names[:2]]
        findings.append(_finding(
            next_id(),
            "Multiple, possibly inconsistent entity names found on the same page",
            "medium",
            f"Distinct entity name strings found representing the page's "
            f"subject: {conflicting}.",
            "Use one consistent, unambiguous entity name across the "
            "<title>, headings, and structured data. If these names are "
            "supposed to differ (e.g. brand vs. legal entity), make the "
            "relationship explicit in JSON-LD (e.g. alternateName).",
            "low",
            action_why="Per the PS: when several different things could "
                       "share a name, an assistant can conflate entities "
                       "unless something clearly distinguishes them.",
            url=url, confidence="low", check="entity_name_consistency",
        ))

    # 3. Facts flagged for external corroboration -- deliberately NOT
    #    fetched here (see module docstring). The orchestrator/agent is
    #    responsible for actually checking these with its own web_search.
    facts_to_corroborate = []
    primary_name = list(declared_org_names)[0] if declared_org_names else (signals["title"] or url)
    facts_to_corroborate.append({
        "claim": f"Entity presents itself as '{primary_name}'",
        "why_it_matters": "Confirms this is the entity most commonly "
                           "referenced under that name elsewhere on the "
                           "web, reducing identity ambiguity.",
    })
    for obj in signals["jsonld_objects"]:
        objs = obj if isinstance(obj, list) else [obj]
        for o in objs:
            if isinstance(o, dict) and o.get("@type") in (
                "Organization", "LocalBusiness", "Corporation"
            ):
                for key in ("foundingDate", "address", "telephone"):
                    if o.get(key):
                        facts_to_corroborate.append({
                            "claim": f"{key} = {o[key]}",
                            "why_it_matters": "Factual claim that should "
                                               "agree with independent "
                                               "sources (directories, "
                                               "registries, news) to be "
                                               "trusted by an assistant.",
                        })

    return {
        "findings": findings,
        "raw_evidence": {
            "freshness_signals": all_dates,
            "most_recent_signal": most_recent.isoformat() if most_recent else None,
            "entity_candidates": sorted(declared_org_names),
            "facts_to_corroborate": facts_to_corroborate,
        },
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 freshness_check.py <url>", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(run(sys.argv[1]), indent=2, default=str))
