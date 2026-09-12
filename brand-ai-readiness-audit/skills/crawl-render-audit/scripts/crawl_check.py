#!/usr/bin/env python3
"""
crawl_check.py -- crawl-render-audit skill

Deterministic, stdlib-only checks for OFF-SITE DISCOVERABILITY:
  - Is the crawler let in at all? (robots.txt, HTTP status)
  - Can it read the page as text, or is the real content only assembled by
    client-side JavaScript after load? (raw-HTML text-to-script ratio,
    empty framework root divs, low visible-text volume)
  - Can it pick out specific facts? (JSON-LD / schema.org presence and
    validity, title/meta description, canonical URL, heading structure)
  - Sitemap presence and a small same-domain internal-link/broken-link pass.

This mirrors Appendix A-C of the Round 3 PDF: crawl access -> readability ->
fact extractability, each a gate the previous one must pass.

Every function that inspects HTML takes raw HTML text directly (not just a
URL) so it is independently unit-testable against local fixtures with no
network access. See tests/test_crawl_check.py.

Usage (standalone, for manual testing):
    python3 crawl_check.py https://example.com
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urljoin

# Make the shared/ package importable regardless of CWD.
_SHARED_DIR = Path(__file__).resolve().parents[3] / "shared"
sys.path.insert(0, str(_SHARED_DIR.parent))

from shared import webutils  # noqa: E402
from shared.report_schema import Finding, SuggestedAction  # noqa: E402

SKILL_NAME = "crawl-render-audit"

# Below this visible-text volume on an otherwise "real" page, treat the page
# as suspiciously thin -- likely JS-dependent or otherwise unreadable.
MIN_EXPECTED_VISIBLE_TEXT_CHARS = 200
# Above this script-to-text ratio, flag a likely JS-render dependency.
JS_DEPENDENCY_SCRIPT_RATIO_THRESHOLD = 0.85


def _finding(
    finding_id: str,
    title: str,
    severity: str,
    evidence: str,
    action_summary: str,
    action_priority: str,
    action_how: str = None,
    action_why: str = None,
    url: str = None,
    confidence: str = "medium",
    check: str = None,
) -> dict:
    return Finding(
        id=finding_id,
        title=title,
        severity=severity,
        evidence=evidence,
        suggested_action=SuggestedAction(
            summary=action_summary, priority=action_priority,
            how=action_how, why=action_why,
        ),
        category="discoverability",
        check=check,
        url=url,
        confidence=confidence,
        source_skill=SKILL_NAME,
    ).to_dict()


def run(url: str, id_prefix: str = "CR") -> dict:
    """Run all crawl/discoverability checks against a single URL.
    Returns {"findings": [...], "raw_evidence": {...}} -- raw_evidence is
    kept so the orchestrator/agent can do further reasoning without
    re-fetching."""
    url = webutils.normalize_url(url)
    findings = []
    counter = 1

    def next_id():
        nonlocal counter
        fid = f"{id_prefix}-{counter:03d}"
        counter += 1
        return fid

    # 1. robots.txt / crawl access gate
    robots = webutils.check_robots(url)
    if robots.get("robots_txt_found") and robots.get("allowed") is False:
        findings.append(_finding(
            next_id(),
            "robots.txt disallows crawling this URL",
            "critical",
            f"robots.txt at {robots['robots_url']} disallows the audited "
            f"user agent from fetching {url}.",
            "Update robots.txt to allow indexing of pages that should be "
            "publicly discoverable, or confirm this URL is intentionally "
            "excluded.",
            "high",
            action_why="If AI crawlers are disallowed, the page cannot be "
                       "cited by assistants no matter how good its content is.",
            url=url, confidence="high", check="robots_txt",
        ))

    # 2. HTTP fetch / status
    result = webutils.fetch(url)
    if result.error or result.status_code is None:
        findings.append(_finding(
            next_id(),
            "Page could not be fetched",
            "critical",
            f"GET {url} failed: {result.error or 'no response'}.",
            "Investigate server/DNS/TLS availability for this URL; a page "
            "that cannot be fetched cannot be indexed or cited.",
            "critical",
            url=url, confidence="high", check="http_fetch",
        ))
        return {"findings": findings, "raw_evidence": {"fetch_error": result.error}}

    if result.status_code >= 400:
        findings.append(_finding(
            next_id(),
            f"Page returned HTTP {result.status_code}",
            "critical" if result.status_code >= 500 else "high",
            f"GET {url} returned status {result.status_code}.",
            "Fix the underlying server/routing issue so the page resolves "
            "with a 200 status.",
            "critical" if result.status_code >= 500 else "high",
            url=url, confidence="high", check="http_status",
        ))

    signals = webutils.extract_html_signals(result.html)
    if "parse_error" in signals:
        findings.append(_finding(
            next_id(), "HTML could not be parsed", "high",
            f"Parsing {url} raised: {signals['parse_error']}",
            "Validate the page's HTML; malformed markup can prevent "
            "machine readers from extracting content reliably.",
            "medium", url=url, confidence="medium", check="html_parse",
        ))
        return {"findings": findings, "raw_evidence": {"signals": signals}}

    # 3. Readability: visible text vs script-heavy / empty framework roots
    thin_text = signals["visible_text_chars"] < MIN_EXPECTED_VISIBLE_TEXT_CHARS
    js_heavy = signals["script_to_text_ratio"] >= JS_DEPENDENCY_SCRIPT_RATIO_THRESHOLD
    empty_root = bool(signals["empty_framework_roots_seen"]) and thin_text
    if thin_text and (js_heavy or empty_root):
        findings.append(_finding(
            next_id(),
            "Page content appears to depend on client-side JavaScript rendering",
            "high",
            f"Raw HTML for {url} contains only {signals['visible_text_chars']} "
            f"visible text characters vs {signals['script_text_chars']} script "
            f"characters (ratio {signals['script_to_text_ratio']}); "
            f"framework root container(s) {signals['empty_framework_roots_seen'] or '[]'} "
            f"were present but effectively empty in the raw HTML.",
            "Server-side render (SSR) or statically pre-render the primary "
            "content, or provide a no-JS fallback with the key facts as "
            "plain text, so crawlers that don't execute JavaScript can "
            "read it.",
            "high",
            action_why="Per the PS: a fact only assembled after page load "
                       "is invisible to readers that don't render JS, so it "
                       "cannot be cited even if a human sees it fine.",
            url=url, confidence="medium", check="js_render_dependency",
        ))
    elif thin_text:
        findings.append(_finding(
            next_id(),
            "Page has very little extractable visible text",
            "medium",
            f"Only {signals['visible_text_chars']} visible text characters "
            f"were found in the raw HTML of {url}.",
            "Ensure the primary facts a user/AI would look for are present "
            "as plain readable text on the page, not only in images or "
            "embedded documents.",
            "medium", url=url, confidence="medium", check="thin_content",
        ))

    # 4. Structured data (JSON-LD / schema.org)
    if signals["jsonld_raw_blocks"] == 0:
        findings.append(_finding(
            next_id(),
            "No JSON-LD structured data detected",
            "medium",
            f"{url} contains 0 <script type=\"application/ld+json\"> blocks "
            f"in the raw HTML.",
            "Add JSON-LD structured data (schema.org) for the entities this "
            "page represents (e.g. Organization, Product, Article, "
            "LocalBusiness) so assistants can extract facts unambiguously "
            "instead of inferring them from prose.",
            "medium",
            action_why="Explicit machine-readable facts are the easiest "
                       "kind for an assistant to quote confidently.",
            url=url, confidence="high", check="structured_data",
        ))
    elif signals["jsonld_parse_errors"] > 0:
        findings.append(_finding(
            next_id(),
            "Invalid JSON-LD found",
            "medium",
            f"{signals['jsonld_parse_errors']} of {signals['jsonld_raw_blocks']} "
            f"JSON-LD block(s) on {url} failed to parse as valid JSON.",
            "Fix the malformed JSON-LD blocks; invalid JSON is typically "
            "skipped entirely by structured-data parsers.",
            "medium", url=url, confidence="high", check="structured_data_validity",
        ))

    # 5. Title / meta description presence
    if not signals["title"]:
        findings.append(_finding(
            next_id(), "Missing <title>", "high",
            f"{url} has no non-empty <title> element.",
            "Add a concise, descriptive <title> stating what the page is "
            "about; it is one of the strongest signals for topical matching.",
            "high", url=url, confidence="high", check="title_tag",
        ))
    if not signals["meta"].get("description"):
        findings.append(_finding(
            next_id(), "Missing meta description", "low",
            f"{url} has no <meta name=\"description\"> tag.",
            "Add a one- to two-sentence meta description summarizing the "
            "page's specific facts (not generic marketing copy).",
            "low", url=url, confidence="high", check="meta_description",
        ))

    # 5b. OpenGraph / Rich preview metadata
    og = signals.get("open_graph", {})
    if not og.get("og:title") and not og.get("og:description"):
        findings.append(_finding(
            next_id(), "Missing OpenGraph / rich preview metadata", "low",
            f"{url} declares no og:title or og:description meta tags.",
            "Add OpenGraph tags (og:title, og:description, og:image) to "
            "ensure AI assistants and social platforms extract structured, "
            "brand-controlled snippet summaries.",
            "low", url=url, confidence="medium", check="opengraph_metadata",
        ))

    # 6. Canonical URL
    if not signals.get("canonical"):
        findings.append(_finding(
            next_id(), "No canonical URL declared", "low",
            f"{url} has no <link rel=\"canonical\"> tag.",
            "Add a self-referencing (or correct) canonical tag to reduce "
            "duplicate-content ambiguity across URL variants.",
            "low", url=url, confidence="medium", check="canonical_url",
        ))

    # 7. Sitemap presence (check declared sitemaps from robots.txt or /sitemap.xml)
    domain_root = webutils.get_domain_root(url)
    declared_sitemaps = robots.get("sitemaps_declared", [])
    sitemap_found = False
    sitemap_status = None

    if declared_sitemaps:
        for s_url in declared_sitemaps:
            sr = webutils.fetch(s_url)
            sitemap_status = sr.status_code
            if sr.status_code and sr.status_code < 400:
                sitemap_found = True
                break
    else:
        sr = webutils.fetch(urljoin(domain_root + "/", "sitemap.xml"))
        sitemap_status = sr.status_code
        if sr.status_code and sr.status_code < 400:
            sitemap_found = True

    if not sitemap_found:
        findings.append(_finding(
            next_id(), "No valid sitemap found", "low",
            f"No accessible XML sitemap found (robots.txt sitemaps: {declared_sitemaps}; "
            f"GET {domain_root}/sitemap.xml returned status {sitemap_status}).",
            "Publish an XML sitemap listing important indexable URLs and declare "
            "it in robots.txt to help crawlers discover pages beyond internal links.",
            "low", confidence="medium", check="sitemap",
        ))

    # 8. Same-domain internal link / broken-link spot check
    internal_links = webutils.resolve_links(url, signals["links"])[: webutils.MAX_LINKS_TO_CHECK]
    broken = []
    for link in internal_links:
        r = webutils.fetch(link, timeout=5)
        if r.status_code is None or r.status_code >= 400:
            broken.append((link, r.status_code or r.error))
    if internal_links and broken:
        sample = "; ".join(f"{u} -> {s}" for u, s in broken[:5])
        findings.append(_finding(
            next_id(),
            "Broken internal links detected",
            "medium",
            f"{len(broken)} of {len(internal_links)} sampled internal links "
            f"from {url} returned an error status. Examples: {sample}",
            "Fix or remove broken internal links; they waste crawl budget "
            "and signal an unmaintained site.",
            "medium", url=url, confidence="high", check="broken_links",
        ))

    return {
        "findings": findings,
        "raw_evidence": {
            "http_status": result.status_code,
            "robots": robots,
            "signals": signals,
            "sitemap_status": sitemap_status,
            "internal_links_checked": len(internal_links),
            "broken_links": broken,
        },
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 crawl_check.py <url>", file=sys.stderr)
        sys.exit(1)
    output = run(sys.argv[1])
    print(json.dumps(output, indent=2, default=str))
