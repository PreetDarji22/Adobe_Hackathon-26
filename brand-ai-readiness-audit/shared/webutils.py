"""
shared/webutils.py

Small, dependency-free (stdlib-only) helpers shared by the audit skills.

Design intent (see root README for rationale):
- Every fetch/parse function is pure and side-effect free where possible, and
  every parsing function accepts raw HTML text directly (not just a URL) so
  it can be unit-tested against local fixtures with no network access.
- No third-party packages are required. This keeps the marketplace portable
  and avoids a pip-install step in unknown grading sandboxes.
- Conservative network behavior: short timeouts, small size caps, no
  automatic re-crawling beyond an explicit link budget, and robots.txt is
  always honored before any non-root URL is fetched.
"""

from __future__ import annotations

import json
import re
import socket
import time
import urllib.error
import urllib.request
import urllib.robotparser
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import urljoin, urlparse

USER_AGENT = "BrandAIReadinessAuditBot/1.0 (+read-only audit; respects robots.txt)"
DEFAULT_TIMEOUT_SECONDS = 8
MAX_CONTENT_BYTES = 3_000_000  # 3MB cap per page fetch
MAX_LINKS_TO_CHECK = 15
MAX_CRAWL_DEPTH = 1


@dataclass
class FetchResult:
    url: str
    status_code: Optional[int]
    headers: dict = field(default_factory=dict)
    html: str = ""
    error: Optional[str] = None
    elapsed_seconds: float = 0.0


def normalize_url(url: str) -> str:
    """Ensure a scheme is present and strip trailing whitespace/fragments."""
    url = url.strip()
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url
    parsed = urlparse(url)
    # Drop fragment; keep path/query as-is.
    return parsed._replace(fragment="").geturl()


def get_domain_root(url: str) -> str:
    parsed = urlparse(normalize_url(url))
    return f"{parsed.scheme}://{parsed.netloc}"


def fetch(url: str, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> FetchResult:
    """Read-only GET with a hard timeout and size cap. Never raises."""
    url = normalize_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(MAX_CONTENT_BYTES + 1)
            truncated = len(raw) > MAX_CONTENT_BYTES
            raw = raw[:MAX_CONTENT_BYTES]
            charset = resp.headers.get_content_charset() or "utf-8"
            try:
                text = raw.decode(charset, errors="replace")
            except LookupError:
                text = raw.decode("utf-8", errors="replace")
            elapsed = time.monotonic() - start
            headers = {k: v for k, v in resp.headers.items()}
            if truncated:
                headers["_truncated"] = "true"
            return FetchResult(
                url=url,
                status_code=resp.status,
                headers=headers,
                html=text,
                elapsed_seconds=elapsed,
            )
    except urllib.error.HTTPError as e:
        return FetchResult(
            url=url,
            status_code=e.code,
            error=f"HTTPError: {e.reason}",
            elapsed_seconds=time.monotonic() - start,
        )
    except (urllib.error.URLError, socket.timeout, ValueError) as e:
        return FetchResult(
            url=url,
            status_code=None,
            error=f"{type(e).__name__}: {e}",
            elapsed_seconds=time.monotonic() - start,
        )


MULTI_PART_PUBLIC_SUFFIXES = {
    "co.uk", "gov.uk", "org.uk", "ac.uk", "net.uk", "sch.uk",
    "com.au", "net.au", "org.au", "edu.au", "gov.au",
    "co.jp", "ne.jp", "or.jp", "ac.jp", "go.jp",
    "co.in", "net.in", "org.in", "gen.in", "firm.in", "ind.in", "gov.in", "edu.in",
    "co.nz", "org.nz", "net.nz", "govt.nz",
    "com.br", "org.br", "net.br", "gov.br",
    "com.sg", "org.sg", "edu.sg", "gov.sg",
}

NAMED_AI_AGENTS = (
    "GPTBot",
    "ClaudeBot",
    "PerplexityBot",
    "Google-Extended",
    "Applebot-Extended",
)


def get_registrable_domain(netloc: str) -> str:
    """Return the eTLD+1 / registrable domain for a network location,
    correctly handling multi-part public suffixes (e.g. co.uk, gov.uk)."""
    if not netloc:
        return ""
    host = netloc.split(":")[0].lower().strip()
    parts = host.split(".")
    if len(parts) <= 2:
        return host

    last_two = f"{parts[-2]}.{parts[-1]}"
    if last_two in MULTI_PART_PUBLIC_SUFFIXES:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def check_robots(url: str, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> dict:
    """Return robots.txt permission info for the given URL.
    Per RFC 9309, HTTP 404 (Not Found) means crawling is allowed.
    Only network timeouts / 5xx errors treat access as unknown.

    Checks general access (* and synthetic UA) AND named AI crawlers
    (GPTBot, ClaudeBot, PerplexityBot, Google-Extended, Applebot-Extended)
    specifically against the audited URL."""
    domain_root = get_domain_root(url)
    robots_url = urljoin(domain_root + "/", "robots.txt")
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(robots_url)
    sitemaps = []
    try:
        req = urllib.request.Request(robots_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(200_000).decode("utf-8", errors="replace")
        lines = raw.splitlines()
        for line in lines:
            if line.strip().lower().startswith("sitemap:"):
                parts = line.split(":", 1)
                if len(parts) == 2 and parts[1].strip():
                    sitemaps.append(parts[1].strip())
        rp.parse(lines)
        allowed = rp.can_fetch(USER_AGENT, url) and rp.can_fetch("*", url)

        # Check each named AI crawler against the EXACT audited URL
        ai_agents_checked = {}
        disallowed_ai_agents = []
        for agent in NAMED_AI_AGENTS:
            agent_allowed = rp.can_fetch(agent, url)
            ai_agents_checked[agent] = agent_allowed
            if not agent_allowed:
                # Find matched or relevant disallow lines from raw robots.txt for evidence quoting
                matched_rule = None
                in_agent_section = False
                for line in lines:
                    stripped = line.strip()
                    if stripped.lower().startswith("user-agent:"):
                        ua_val = stripped.split(":", 1)[1].strip()
                        in_agent_section = (ua_val.lower() == agent.lower())
                    elif in_agent_section and stripped.lower().startswith("disallow:"):
                        matched_rule = stripped
                        break
                if not matched_rule:
                    matched_rule = "Disallow (inherited from wildcard or path rule)"
                disallowed_ai_agents.append({
                    "agent": agent,
                    "matched_rule": matched_rule,
                })

        return {
            "robots_txt_found": True,
            "robots_url": robots_url,
            "allowed": allowed,
            "sitemaps_declared": sitemaps,
            "ai_agents_checked": ai_agents_checked,
            "disallowed_ai_agents": disallowed_ai_agents,
            "raw_excerpt": raw[:500],
        }
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {
                "robots_txt_found": False,
                "robots_url": robots_url,
                "allowed": True,  # RFC 9309: 404 means unrestricted access
                "sitemaps_declared": [],
                "ai_agents_checked": {agent: True for agent in NAMED_AI_AGENTS},
                "disallowed_ai_agents": [],
                "error": "HTTPError 404: Not Found (Unrestricted access)",
            }
        return {
            "robots_txt_found": False,
            "robots_url": robots_url,
            "allowed": None,  # 5xx or server error
            "sitemaps_declared": [],
            "ai_agents_checked": {agent: None for agent in NAMED_AI_AGENTS},
            "disallowed_ai_agents": [],
            "error": f"HTTPError {e.code}: {e.reason}",
        }
    except Exception as e:  # noqa: BLE001
        return {
            "robots_txt_found": False,
            "robots_url": robots_url,
            "allowed": None,  # unknown/network timeout
            "sitemaps_declared": [],
            "ai_agents_checked": {agent: None for agent in NAMED_AI_AGENTS},
            "disallowed_ai_agents": [],
            "error": f"{type(e).__name__}: {e}",
        }


class _SimpleHTMLExtractor(HTMLParser):
    """Minimal stdlib HTML extractor: title, meta tags, headings, links,
    button text, OpenGraph tags, JSON-LD script bodies, and a rough
    visible-text vs script-text split."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.meta = {}
        self.open_graph = {}
        self.headings = {f"h{i}": [] for i in range(1, 4)}
        self.links = []          # href values
        self.link_texts = []     # visible anchor text
        self.button_texts = []   # visible text on buttons / submit inputs
        self.jsonld_blocks = []
        self.visible_text_chars = 0
        self.script_text_chars = 0
        self.canonical = None
        self.root_ids_seen_empty = []
        self._in_title = False
        self._in_script = False
        self._script_type = None
        self._current_script_buf = []
        self._in_heading = None
        self._current_heading_buf = []
        self._in_anchor = False
        self._in_button = False
        self._current_button_buf = []
        self._tag_stack = []
        self._skip_text_tags = {"script", "style", "noscript"}

        # Track content inside framework root divs (#root, #app, #__next)
        self._root_div_stack = []  # list of dict: {"id": str, "has_content": bool, "depth": int}

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        self._tag_stack.append(tag)

        # Mark parent root divs as containing child elements
        for r in self._root_div_stack:
            if tag not in ("script", "style"):
                r["has_content"] = True

        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            name = (attrs_d.get("name") or attrs_d.get("property") or "").lower()
            content = attrs_d.get("content", "")
            if name:
                self.meta[name] = content
                if name.startswith(("og:", "twitter:")):
                    self.open_graph[name] = content
        elif tag == "link" and attrs_d.get("rel", "").lower() == "canonical":
            self.canonical = attrs_d.get("href")
        elif tag == "a" and attrs_d.get("href"):
            self.links.append(attrs_d["href"])
            self.link_texts.append("")
            self._in_anchor = True
        elif tag == "button":
            self._in_button = True
            self._current_button_buf = []
        elif tag == "input" and attrs_d.get("type", "").lower() in ("button", "submit"):
            val = attrs_d.get("value", "").strip()
            if val:
                self.button_texts.append(val)
        elif tag in ("h1", "h2", "h3"):
            self._in_heading = tag
            self._current_heading_buf = []
        elif tag == "script":
            self._in_script = True
            self._script_type = (attrs_d.get("type") or "").lower()
            self._current_script_buf = []
        elif tag == "div" and attrs_d.get("id") in ("root", "app", "__next"):
            self._root_div_stack.append({
                "id": attrs_d.get("id"),
                "has_content": False,
                "depth": len(self._tag_stack),
            })

    def handle_endtag(self, tag):
        if self._tag_stack and tag in self._tag_stack:
            while self._tag_stack and self._tag_stack.pop() != tag:
                pass

        # Handle root div pop
        if tag == "div" and self._root_div_stack:
            # Check if matching root div depth
            top_root = self._root_div_stack[-1]
            if len(self._tag_stack) < top_root["depth"]:
                r = self._root_div_stack.pop()
                if not r["has_content"]:
                    self.root_ids_seen_empty.append(r["id"])

        if tag == "title":
            self._in_title = False
        elif tag in ("h1", "h2", "h3") and self._in_heading == tag:
            text = "".join(self._current_heading_buf).strip()
            if text:
                self.headings[tag].append(text)
            self._in_heading = None
        elif tag == "a" and self._in_anchor:
            self._in_anchor = False
        elif tag == "button" and self._in_button:
            btn_text = "".join(self._current_button_buf).strip()
            if btn_text:
                self.button_texts.append(btn_text)
            self._in_button = False
        elif tag == "script":
            body = "".join(self._current_script_buf)
            self.script_text_chars += len(body)
            if self._script_type == "application/ld+json" and body.strip():
                self.jsonld_blocks.append(body)
            self._in_script = False
            self._script_type = None

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._in_script:
            self._current_script_buf.append(data)
            return
        if self._in_heading:
            self._current_heading_buf.append(data)
        if self._in_anchor and self.link_texts:
            self.link_texts[-1] += data
        if self._in_button:
            self._current_button_buf.append(data)
        if self._tag_stack and self._tag_stack[-1] in self._skip_text_tags:
            return
        stripped = data.strip()
        if stripped:
            self.visible_text_chars += len(stripped)
            for r in self._root_div_stack:
                r["has_content"] = True


def extract_html_signals(html: str) -> dict:
    """Parse raw HTML text and return a dict of extracted evidence signals.
    Pure function -- no network -- safe to unit test with fixture strings."""
    parser = _SimpleHTMLExtractor()
    try:
        parser.feed(html)
    except Exception as e:  # noqa: BLE001 - malformed HTML must not crash the audit
        return {"parse_error": f"{type(e).__name__}: {e}"}

    jsonld_objects = []
    jsonld_parse_errors = 0
    for block in parser.jsonld_blocks:
        try:
            parsed = json.loads(block)
            jsonld_objects.append(parsed)
        except json.JSONDecodeError:
            jsonld_parse_errors += 1

    total_text = parser.visible_text_chars + parser.script_text_chars
    script_ratio = (parser.script_text_chars / total_text) if total_text else 0.0

    return {
        "title": parser.title.strip(),
        "meta": parser.meta,
        "open_graph": parser.open_graph,
        "canonical": parser.canonical,
        "headings": parser.headings,
        "links": parser.links,
        "link_texts": [t.strip() for t in parser.link_texts if t.strip()],
        "button_texts": parser.button_texts,
        "jsonld_raw_blocks": len(parser.jsonld_blocks),
        "jsonld_objects": jsonld_objects,
        "jsonld_parse_errors": jsonld_parse_errors,
        "visible_text_chars": parser.visible_text_chars,
        "script_text_chars": parser.script_text_chars,
        "script_to_text_ratio": round(script_ratio, 3),
        "empty_framework_roots_seen": parser.root_ids_seen_empty,
    }


def resolve_links(
    base_url: str,
    links: list[str],
    same_domain_only: bool = True,
    allow_subdomains: bool = False,
) -> list[str]:
    base_netloc = urlparse(normalize_url(base_url)).netloc
    base_reg_domain = get_registrable_domain(base_netloc)
    resolved = []
    seen = set()
    for href in links:
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        link_netloc = parsed.netloc
        if same_domain_only:
            if allow_subdomains:
                link_reg_domain = get_registrable_domain(link_netloc)
                if link_reg_domain != base_reg_domain:
                    continue
            else:
                if link_netloc != base_netloc:
                    continue
        if absolute not in seen:
            seen.add(absolute)
            resolved.append(absolute)
    return resolved

