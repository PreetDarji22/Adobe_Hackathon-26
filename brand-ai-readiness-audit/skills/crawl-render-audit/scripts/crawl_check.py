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
    action_priority: str = None,
    action_how: str = None,
    action_why: str = None,
    url: str = None,
    confidence: str = "medium",
    check: str = None,
) -> dict:
    # Priority matches severity by default for consistency
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
            action_priority="critical",
            action_how="Edit /robots.txt on the domain root to remove Disallow rules blocking general search and audit crawlers from accessing indexable paths.",
            action_why="If crawlers are disallowed, the page cannot be "
                       "cited by assistants no matter how good its content is.",
            url=url, confidence="high", check="robots_txt",
        ))

    # 1b. Named AI crawlers check (evaluated against the actual audited URL)
    disallowed_ai = robots.get("disallowed_ai_agents", [])
    if disallowed_ai:
        is_sitewide = any(
            item.get("matched_rule", "").strip() == "Disallow: /" or "Disallow: /" in item.get("matched_rule", "")
            for item in disallowed_ai
        )
        ai_sev = "critical" if is_sitewide else "high"
        agent_lines = ", ".join(f"{item['agent']} ({item['matched_rule']})" for item in disallowed_ai)
        findings.append(_finding(
            next_id(),
            "robots.txt disallows named AI crawler(s)",
            ai_sev,
            f"robots.txt at {robots.get('robots_url', url)} disallows named AI search crawler(s) from fetching {url}: {agent_lines}.",
            "Update robots.txt to permit access for AI search agents (e.g. GPTBot, ClaudeBot, PerplexityBot, Google-Extended, Applebot-Extended) to index public content.",
            action_priority=ai_sev,
            action_how="Edit /robots.txt on the web server to modify or remove Disallow rules for AI user agents (User-agent: GPTBot, ClaudeBot, PerplexityBot, Google-Extended, Applebot-Extended) on public paths.",
            action_why="Named AI crawlers fetch source content to ground AI answers; blocking them directly prevents the brand from being cited or recommended in AI assistants.",
            url=url, confidence="high", check="ai_crawlers_robots",
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
            action_priority="critical",
            action_how="Inspect DNS records, web server status, firewall rules, and TLS certificates to ensure the URL responds reliably to standard HTTPS requests.",
            url=url, confidence="high", check="http_fetch",
        ))
        return {"findings": findings, "raw_evidence": {"fetch_error": result.error}}

    if result.status_code >= 400:
        sev = "critical" if result.status_code >= 500 else "high"
        findings.append(_finding(
            next_id(),
            f"Page returned HTTP {result.status_code}",
            sev,
            f"GET {url} returned status {result.status_code}.",
            "Fix the underlying server/routing issue so the page resolves "
            "with a 200 status.",
            action_priority=sev,
            action_how="Check web server routing, endpoint handlers, and permission configurations to ensure the URL returns HTTP 200 OK.",
            url=url, confidence="high", check="http_status",
        ))

    signals = webutils.extract_html_signals(result.html)
    if "parse_error" in signals:
        findings.append(_finding(
            next_id(), "HTML could not be parsed", "high",
            f"Parsing {url} raised: {signals['parse_error']}",
            "Validate the page's HTML; malformed markup can prevent "
            "machine readers from extracting content reliably.",
            action_priority="high",
            action_how="Run the HTML markup through a validator to fix unclosed tags, malformed attributes, and encoding issues.",
            url=url, confidence="medium", check="html_parse",
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
            action_priority="high",
            action_how="Implement Server-Side Rendering (SSR) or static pre-rendering, or inject initial server-rendered HTML containing key headings and body text inside <main>.",
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
            action_priority="medium",
            action_how="Add descriptive body text in semantic HTML elements (<p>, <section>, <article>) directly within the initial HTML document body.",
            url=url, confidence="medium", check="thin_content",
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
            action_priority="medium",
            action_how="Add a <script type='application/ld+json'> tag inside <head> declaring schema.org entity data (e.g. Organization, Product, WebSite) with name, url, and description.",
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
            action_priority="medium",
            action_how="Correct JSON syntax errors (such as unescaped quotes or trailing commas) in <script type='application/ld+json'> blocks and validate against schema.org.",
            url=url, confidence="high", check="structured_data_validity",
        ))

    # 5. Title / meta description presence
    if not signals["title"]:
        findings.append(_finding(
            next_id(), "Missing <title>", "high",
            f"{url} has no non-empty <title> element.",
            "Add a concise, descriptive <title> stating what the page is "
            "about; it is one of the strongest signals for topical matching.",
            action_priority="high",
            action_how="Add a <title>Brand Name - Descriptive Topic</title> element in the <head> section of the page.",
            url=url, confidence="high", check="title_tag",
        ))
    if not signals["meta"].get("description"):
        findings.append(_finding(
            next_id(), "Missing meta description", "low",
            f"{url} has no <meta name=\"description\"> tag.",
            "Add a one- to two-sentence meta description summarizing the "
            "page's specific facts (not generic marketing copy).",
            action_priority="low",
            action_how="Add a <meta name='description' content='...'> element in <head> containing a 150-160 character factual summary of the page.",
            url=url, confidence="high", check="meta_description",
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
            action_priority="low",
            action_how="Add <meta property='og:title' content='...'> and <meta property='og:description' content='...'> tags inside <head>.",
            url=url, confidence="medium", check="opengraph_metadata",
        ))

    # 6. Canonical URL
    if not signals.get("canonical"):
        findings.append(_finding(
            next_id(), "No canonical URL declared", "low",
            f"{url} has no <link rel=\"canonical\"> tag.",
            "Add a self-referencing (or correct) canonical tag to reduce "
            "duplicate-content ambiguity across URL variants.",
            action_priority="low",
            action_how="Add a <link rel='canonical' href='...'> tag in <head> pointing to the authoritative URL.",
            url=url, confidence="medium", check="canonical_url",
        ))

    # 7. Sitemap presence (validates declared sitemaps from robots.txt, fallback to /sitemap.xml)
    domain_root = webutils.get_domain_root(url)
    declared_sitemaps = robots.get("sitemaps_declared", [])
    MAX_SITEMAPS_TO_CHECK = 3
    sitemap_found = False
    sitemap_status_details = []

    if declared_sitemaps:
        # Validate at most the first 3 declared sitemaps with a short 5s timeout
        for s_url in declared_sitemaps[:MAX_SITEMAPS_TO_CHECK]:
            sr = webutils.fetch(s_url, timeout=5)
            sitemap_status_details.append((s_url, sr.status_code, sr.error))
            if sr.status_code and sr.status_code < 400:
                sitemap_found = True
                break

        if not sitemap_found:
            all_http_errors = all(code is not None and code >= 400 for _, code, _ in sitemap_status_details)
            summary_str = "; ".join(f"{u} -> HTTP {c or err}" for u, c, err in sitemap_status_details)
            if all_http_errors:
                findings.append(_finding(
                    next_id(),
                    "Declared sitemap in robots.txt could not be fetched",
                    "medium",
                    f"Sitemap URL(s) declared in robots.txt failed to resolve: {summary_str}.",
                    "Verify that sitemaps declared in robots.txt exist and return HTTP 200.",
                    action_priority="medium",
                    action_how="Update the 'Sitemap:' directive in robots.txt to point to valid, accessible XML sitemap URLs, or publish the missing files.",
                    action_why="A declared sitemap that returns 404 or 500 wastes crawler budget and prevents sitemap-based URL discovery.",
                    confidence="high", check="sitemap_declared_broken",
                ))
            else:
                findings.append(_finding(
                    next_id(),
                    "Declared sitemap in robots.txt could not be verified",
                    "low",
                    f"Declared sitemap URL(s) could not be verified due to network/timeout error: {summary_str}.",
                    "Ensure the sitemap server responds promptly without timeouts.",
                    action_priority="low",
                    action_how="Check server response times and availability for sitemap URLs referenced in robots.txt.",
                    confidence="medium", check="sitemap_unverified",
                ))
    else:
        # Fallback probe /sitemap.xml
        fallback_sitemap_url = urljoin(domain_root + "/", "sitemap.xml")
        sr = webutils.fetch(fallback_sitemap_url, timeout=5)
        if sr.status_code and sr.status_code < 400:
            sitemap_found = True
        elif sr.status_code and sr.status_code >= 400:
            findings.append(_finding(
                next_id(),
                "No valid sitemap found",
                "low",
                f"No sitemap declared in robots.txt and GET {fallback_sitemap_url} returned HTTP {sr.status_code}.",
                "Publish an XML sitemap listing important indexable URLs and declare it in robots.txt to help crawlers discover pages.",
                action_priority="low",
                action_how="Generate an XML sitemap at /sitemap.xml and add a 'Sitemap: https://yourdomain.com/sitemap.xml' line in robots.txt.",
                action_why="An XML sitemap helps crawlers discover new and deep pages without relying solely on internal links.",
                confidence="medium", check="sitemap",
            ))
        else:
            findings.append(_finding(
                next_id(),
                "Sitemap probe could not be verified",
                "low",
                f"No sitemap declared in robots.txt and probing {fallback_sitemap_url} failed: {sr.error or 'timeout'}.",
                "Verify XML sitemap availability.",
                action_priority="low",
                action_how="Ensure the web server responds to requests for /sitemap.xml or declare the sitemap location in robots.txt.",
                confidence="low", check="sitemap_unverified",
            ))

    # 7b. /llms.txt check (honest unknown-vs-absent handling)
    llms_url = urljoin(domain_root + "/", "llms.txt")
    llms_res = webutils.fetch(llms_url, timeout=5)
    llms_status = llms_res.status_code
    if llms_status == 404:
        findings.append(_finding(
            next_id(),
            "No /llms.txt file detected",
            "low",
            f"GET {llms_url} returned HTTP 404 (Not Found).",
            "Consider publishing an /llms.txt file to provide a curated, markdown-formatted map of content for AI models.",
            action_priority="low",
            action_how="Create a plain text markdown file at the domain root (/llms.txt) outlining key site sections, documentation, and APIs formatted specifically for LLM consumption.",
            action_why="An /llms.txt file gives AI agents a clean, structured index of your website's highest-value pages.",
            confidence="high", check="llms_txt",
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
            action_priority="medium",
            action_how="Audit internal <a> href attributes across the page and update or remove stale links pointing to broken/404 URLs.",
            url=url, confidence="high", check="broken_links",
        ))

    return {
        "findings": findings,
        "raw_evidence": {
            "http_status": result.status_code,
            "robots": robots,
            "signals": signals,
            "sitemap_found": sitemap_found,
            "sitemap_details": sitemap_status_details,
            "llms_txt_status": llms_status,
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
