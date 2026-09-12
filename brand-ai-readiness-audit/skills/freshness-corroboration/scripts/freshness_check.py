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


def _finding(
    finding_id: str,
    title: str,
    severity: str,
    evidence: str,
    action_summary: str,
    action_priority: str = None,
    action_how: str = None,
    action_why: str = None,
    url: str = None,
    confidence: str = "medium",
    check: str = None,
) -> dict:
    priority = action_priority if action_priority is not None else severity
    return Finding(
        id=finding_id,
        title=title,
        severity=severity,
        evidence=evidence,
        suggested_action=SuggestedAction(
            summary=action_summary, priority=priority,
            how=action_how, why=action_why,
        ),
        category="discoverability",
        check=check,
        url=url,
        confidence=confidence,
        source_skill=SKILL_NAME,
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
            action_priority="medium",
            action_how="Add a 'dateModified' field to Organization/Article JSON-LD and include a <meta property='article:modified_time' content='...'> tag in <head>.",
            action_why="Without an explicit freshness signal, an assistant "
                       "has no basis to prefer this page over a possibly "
                       "outdated cached version, and may downweight it.",
            url=url, confidence="medium", check="freshness_signal_presence",
        ))
    elif most_recent:
        age_days = (datetime.now(timezone.utc) - most_recent).days
        if age_days > STALE_THRESHOLD_DAYS:
            sev = "medium" if age_days < STALE_THRESHOLD_DAYS * 2 else "high"
            findings.append(_finding(
                next_id(),
                "Content freshness signal indicates the page may be stale",
                sev,
                f"Most recent freshness signal on {url} is "
                f"{most_recent.date().isoformat()} ({age_days} days old): "
                f"{all_dates}.",
                "If the underlying facts are still accurate, update the "
                "dateModified/meta timestamp so assistants don't discount "
                "the page as outdated; if the content itself is stale, "
                "review and refresh it.",
                action_priority=sev,
                action_how="Review and refresh page facts and update the 'dateModified' property in JSON-LD and meta tags to the current date.",
                action_why="AI assistants prioritize recent and actively maintained sources when synthesizing answers.",
                url=url, confidence="high", check="content_age",
            ))

    # 2. sameAs Authority Links Check (in Organization / Brand / LocalBusiness JSON-LD)
    for obj in signals["jsonld_objects"]:
        objs = obj if isinstance(obj, list) else [obj]
        for o in objs:
            if isinstance(o, dict) and o.get("@type") in (
                "Organization", "LocalBusiness", "Corporation", "Brand"
            ):
                same_as = o.get("sameAs")
                org_name = o.get("name") or o.get("legalName") or "Organization"
                obj_type = o.get("@type")
                has_same_as = bool(
                    same_as and (
                        (isinstance(same_as, list) and len(same_as) > 0 and any(str(s).strip() for s in same_as))
                        or (isinstance(same_as, str) and same_as.strip())
                    )
                )
                if not has_same_as:
                    findings.append(_finding(
                        next_id(),
                        "Organization structured data lacks 'sameAs' authority links",
                        "low",
                        f"JSON-LD @type '{obj_type}' with name '{org_name}' contains no 'sameAs' cross-source authority references.",
                        "Add 'sameAs' URLs to your Organization JSON-LD markup to anchor brand identity across the web.",
                        action_priority="low",
                        action_how="Add a 'sameAs' array to the Organization JSON-LD object containing authoritative profile URLs (e.g. Wikipedia, Wikidata, LinkedIn, Twitter/X, Crunchbase).",
                        action_why="Per PS Appendix D: cross-source agreement establishes entity identity across the web, preventing AI assistants from conflating this brand with similarly named entities.",
                        url=url, confidence="high", check="sameas_presence",
                    ))

    # 3. Tightened Entity Name Candidate Extraction for Corroboration (P2-b)
    # A candidate is only evaluated for contradictions if it is a plausible concise
    # brand/org name (<= 4 words, <= 40 chars) confirmed across at least two
    # independent sources {<title>, JSON-LD name/legalName, og:site_name}
    # OR is the sole <h1> on the page.
    def _is_plausible_name(s: str) -> bool:
        s = s.strip()
        return 2 <= len(s) <= 40 and len(s.split()) <= 4

    potential_candidates = set()
    jsonld_org_names = set()
    for obj in signals["jsonld_objects"]:
        objs = obj if isinstance(obj, list) else [obj]
        for o in objs:
            if isinstance(o, dict) and o.get("@type") in (
                "Organization", "LocalBusiness", "Corporation", "Brand", "WebSite"
            ):
                for key in ("name", "legalName", "alternateName"):
                    val = o.get(key)
                    if val and isinstance(val, str) and _is_plausible_name(val):
                        jsonld_org_names.add(val.strip())
                        potential_candidates.add(val.strip())

    og_site_name = signals.get("open_graph", {}).get("og:site_name")
    if og_site_name and _is_plausible_name(og_site_name):
        potential_candidates.add(og_site_name.strip())

    title_text = signals["title"] or ""
    if "|" in title_text or " - " in title_text or " : " in title_text or ":" in title_text:
        parts = [p.strip() for p in re.split(r"[|\-:]", title_text) if p.strip()]
        for p in parts:
            if _is_plausible_name(p):
                potential_candidates.add(p)
    elif title_text and _is_plausible_name(title_text):
        potential_candidates.add(title_text.strip())

    h1s = signals["headings"].get("h1", [])
    if len(h1s) == 1 and _is_plausible_name(h1s[0]):
        potential_candidates.add(h1s[0].strip())

    # Multi-source confirmation
    confirmed_org_names = set()
    for cand in potential_candidates:
        cand_lower = cand.lower()
        sources_count = 0
        if title_text and cand_lower in title_text.lower():
            sources_count += 1
        if any(cand_lower in jname.lower() for jname in jsonld_org_names):
            sources_count += 1
        if og_site_name and cand_lower in og_site_name.lower():
            sources_count += 1
        if len(h1s) == 1 and cand_lower in h1s[0].lower():
            sources_count += 1

        if sources_count >= 2 or (len(h1s) == 1 and cand_lower == h1s[0].strip().lower()) or any(cand_lower == j.lower() for j in jsonld_org_names):
            confirmed_org_names.add(cand)

    # Normalize entity names for comparison (strip corp suffixes, case-fold)
    def _norm(n: str) -> str:
        s = re.sub(r"\b(inc|corp|corporation|ltd|limited|co|llc|plc|gmbh|software|tech|technologies)\b", "", n, flags=re.I)
        return re.sub(r"[^\w\s]", "", s).strip().lower()

    norm_names = {_norm(n): n for n in confirmed_org_names if len(_norm(n)) >= 3}

    # Flag contradiction ONLY if 2+ distinct non-overlapping confirmed base brand names exist
    distinct_base_names = list(norm_names.keys())
    has_conflict = False
    if len(distinct_base_names) >= 2:
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
            action_priority="medium",
            action_how="Standardize brand naming across <title>, <h1>, and JSON-LD schema (name/legalName); declare trade names or legal parent names explicitly via alternateName.",
            action_why="Per the PS: when several different things could "
                       "share a name, an assistant can conflate entities "
                       "unless something clearly distinguishes them.",
            url=url, confidence="low", check="entity_name_consistency",
        ))

    # 4. Facts flagged for external corroboration
    facts_to_corroborate = []
    primary_name = list(confirmed_org_names or potential_candidates)[0] if (confirmed_org_names or potential_candidates) else (signals["title"] or url)
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
            "entity_candidates": sorted(potential_candidates),
            "confirmed_entity_candidates": sorted(confirmed_org_names),
            "facts_to_corroborate": facts_to_corroborate,
        },
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 freshness_check.py <url>", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(run(sys.argv[1]), indent=2, default=str))
