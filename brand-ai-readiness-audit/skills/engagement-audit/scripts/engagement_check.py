#!/usr/bin/env python3
"""
engagement_check.py -- engagement-audit skill

Deterministic, stdlib-only checks for ON-SITE ENGAGEMENT (Appendix E of the
Round 3 PDF: does a visitor who lands understand where they are, what this
is, and what to do next -- and is that framing consistent with how they
likely arrived?).

This script extracts EVIDENCE (heading structure, first-paragraph text,
nav link count, CTA-like link text, title/meta-vs-H1 overlap). It flags a
finding only when the evidence crosses a concrete threshold; it explicitly
does NOT flag "missing X" purely because X is a common convention (see
module-level THRESHOLDS and the false-positive guard in SKILL.md's
Procedure section). Purely qualitative judgment (e.g. "is this copy
actually clear") is left to the orchestrating agent, which receives this
raw evidence and applies semantic reasoning on top of it -- this script
never invents a semantic judgment it can't support with extracted text.

Usage (standalone, for manual testing):
    python3 engagement_check.py https://example.com
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_SHARED_DIR = Path(__file__).resolve().parents[3] / "shared"
sys.path.insert(0, str(_SHARED_DIR.parent))

from shared import webutils  # noqa: E402
from shared.report_schema import Finding, SuggestedAction  # noqa: E402

SKILL_NAME = "engagement-audit"

CTA_PATTERNS = re.compile(
    r"\b(buy|shop|sign up|sign in|get started|contact|book|request a demo|"
    r"learn more|subscribe|download|try (it )?free|start free trial|"
    r"add to cart|apply now|schedule)\b",
    re.IGNORECASE,
)
MIN_NAV_LINKS_EXPECTED = 2
MIN_FIRST_TEXT_CHARS_FOR_VALUE_PROP = 40


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
        category="engagement",
        check=check,
        url=url,
        confidence=confidence,
        source_skill=SKILL_NAME,
    ).to_dict()


def run(url: str, id_prefix: str = "EN") -> dict:
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

    h1s = signals["headings"].get("h1", [])
    title = signals["title"] or ""
    meta_desc = signals["meta"].get("description", "")

    # 1. No H1 / multiple conflicting H1s -> orientation risk
    if len(h1s) == 0:
        findings.append(_finding(
            next_id(),
            "No H1 heading found -- unclear page orientation",
            "medium",
            f"{url} has zero <h1> elements in the raw HTML.",
            "Add a single clear H1 stating what this page is / what the "
            "visitor can do here, matching the intent that likely brought "
            "them to this URL.",
            action_priority="medium",
            action_how="Add a single primary <h1> element at the top of the <main> section clearly stating the core subject or service.",
            action_why="An H1 is usually the fastest orientation cue for "
                       "both a human skimming and an assistant summarizing "
                       "the page's purpose.",
            url=url, confidence="high", check="h1_presence",
        ))
    elif len(h1s) > 1:
        findings.append(_finding(
            next_id(),
            "Multiple H1 headings found -- may dilute page focus",
            "low",
            f"{url} has {len(h1s)} <h1> elements: {h1s[:5]}.",
            "Consolidate to a single primary H1 that states the page's "
            "main topic; use H2/H3 for subsections.",
            action_priority="low",
            action_how="Retain a single authoritative <h1> tag for the primary topic and convert secondary headings to <h2> or <h3> elements.",
            url=url, confidence="medium", check="h1_count",
        ))

    # 2. Title/H1/meta-description topical overlap (context-retention proxy)
    STOP_WORDS = {
        "home", "page", "welcome", "about", "with", "from", "your", "that", "this",
        "overview", "online", "free", "site", "web", "official", "main", "view",
    }

    def _keywords(text: str) -> set:
        words = set(re.findall(r"[a-zA-Z]{2,}", text.lower()))
        return {w for w in words if w not in STOP_WORDS}

    title_kw = _keywords(title)
    h1_kw = _keywords(h1s[0]) if h1s else set()
    meta_kw = _keywords(meta_desc)

    def _has_overlap(set1: set, set2: set) -> bool:
        if not set1 or not set2:
            return False
        if set1 & set2:
            return True
        # Check stem/substring overlap (e.g. pdfs vs pdf, convert vs converter)
        for w1 in set1:
            for w2 in set2:
                if (len(w1) >= 3 and len(w2) >= 3) and (w1 in w2 or w2 in w1):
                    return True
        return False

    if title_kw and h1_kw and not _has_overlap(title_kw, h1_kw):
        findings.append(_finding(
            next_id(),
            "Title and H1 share no common keywords",
            "medium",
            f"Title=\"{title}\" vs H1=\"{h1s[0]}\" share no words in "
            f"common.",
            "Align the <title>, H1, and meta description around the same "
            "core topic/intent so a visitor arriving via a search result "
            "or AI answer sees consistent framing, not a mismatch.",
            action_priority="medium",
            action_how="Align core topic and brand keywords across the <title> tag and the primary <h1> heading for topical consistency.",
            action_why="Per the PS: context retention between the likely "
                       "discovery intent and the landing page matters -- a "
                       "mismatch between what was promised and what's shown "
                       "is a common source of visitors leaving immediately.",
            url=url, confidence="low", check="title_h1_alignment",
        ))
    elif title_kw and meta_kw and not _has_overlap(title_kw, meta_kw):
        findings.append(_finding(
            next_id(),
            "Title and meta description share no common keywords",
            "low",
            f"Title=\"{title}\" vs meta description=\"{meta_desc}\" share "
            f"no words in common.",
            "Align the meta description with the title/page topic so "
            "search and AI-generated snippets accurately represent the "
            "page.",
            action_priority="low",
            action_how="Incorporate key brand and topic terms from <title> into the <meta name='description'> content attribute.",
            url=url, confidence="low", check="title_meta_alignment",
        ))

    # 3. Navigation presence (subdomain-aware internal link count)
    internal_links = webutils.resolve_links(
        url, signals["links"], same_domain_only=True, allow_subdomains=True
    )
    if len(internal_links) < MIN_NAV_LINKS_EXPECTED:
        findings.append(_finding(
            next_id(),
            "Very few same-domain links found -- possible navigation dead end",
            "medium",
            f"Only {len(internal_links)} same-domain link(s) found on {url}.",
            "Provide clear paths to related/next content (nav menu, related "
            "links, breadcrumbs) so a visitor who lands here isn't stuck "
            "with nowhere obvious to go.",
            action_priority="medium",
            action_how="Add prominent navigation menus, related links, or breadcrumbs in <header> or <nav> connecting visitors to key site areas.",
            url=url, confidence="medium", check="internal_link_count",
        ))

    # 4. CTA presence (check links AND buttons, with context awareness)
    link_texts = signals.get("link_texts", [])
    button_texts = signals.get("button_texts", [])
    all_clickable_text = " ".join(link_texts + button_texts)
    has_cta = bool(CTA_PATTERNS.search(all_clickable_text))

    # Determine if page is informational/docs where missing commercial CTA is expected
    is_info_page = any(kw in url.lower() for kw in ("/docs", "/doc/", "/blog", "/privacy", "/terms", "/faq", "/article")) or \
                   signals.get("open_graph", {}).get("og:type") == "article"

    if not has_cta and not is_info_page:
        findings.append(_finding(
            next_id(),
            "No clear call-to-action language detected",
            "low",
            f"No CTA-style terms (e.g. 'get started', 'contact', 'sign up', "
            f"'buy') were found in link or button text on {url}.",
            "Add an explicit, specific call-to-action (what the visitor "
            "should do next) near the top of the page rather than relying "
            "on implicit navigation.",
            action_priority="low",
            action_how="Add a clear action link or button (e.g. <a class='cta' href='/signup'>Get Started</a> or <button>Contact Sales</button>) in a prominent position above the fold.",
            url=url, confidence="low", check="cta_presence",
        ))

    return {
        "findings": findings,
        "raw_evidence": {
            "title": title,
            "meta_description": meta_desc,
            "h1s": h1s,
            "internal_link_count": len(internal_links),
            "has_cta_language": has_cta,
        },
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 engagement_check.py <url>", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(run(sys.argv[1]), indent=2, default=str))
