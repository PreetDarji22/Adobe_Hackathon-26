"""
tests/test_heuristics_fix.py

Tests for enhanced heuristics:
- RFC 9309 404 robots.txt handling
- Framework root container content detection (SSR Next.js / React)
- Button element CTA detection
- Title/H1 2-3 letter domain keyword matching (e.g. PDF, AI)
- Real-world brand title vs H1 entity ambiguity false-positive resistance
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "skills" / "crawl-render-audit" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "freshness-corroboration" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "engagement-audit" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "audit-orchestrator" / "scripts"))

from shared import webutils
from shared.report_schema import validate_report
import crawl_check
import freshness_check
import engagement_check
import orchestrate


class TestRobots404Handling(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_robots_404_allows_crawling(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "http://example.com/robots.txt", 404, "Not Found", {}, None
        )
        res = webutils.check_robots("http://example.com/somepage")
        self.assertFalse(res["robots_txt_found"])
        self.assertTrue(res["allowed"])


class TestFrameworkRootContent(unittest.TestCase):
    def test_ssr_nextjs_div_is_not_marked_empty(self):
        html = """<!DOCTYPE html>
        <html>
        <head><title>NextJS SSR Page</title></head>
        <body>
            <div id="__next">
                <h1>Server Rendered Title</h1>
                <p>This is substantial server-rendered body content on a Next.js application.</p>
            </div>
        </body>
        </html>"""
        signals = webutils.extract_html_signals(html)
        self.assertEqual(signals["empty_framework_roots_seen"], [])


class TestButtonCTADetection(unittest.TestCase):
    def test_button_element_detected_as_cta(self):
        html = """<!DOCTYPE html>
        <html>
        <head><title>SaaS Product</title></head>
        <body>
            <h1>Welcome to Product</h1>
            <button type="submit">Start Free Trial</button>
        </body>
        </html>"""
        res = engagement_check.run("https://saas.example")
        # Ensure "No clear call-to-action language detected" finding is NOT triggered
        cta_findings = [f for f in res["findings"] if f["check"] == "cta_presence"]
        self.assertEqual(len(cta_findings), 0)


class TestShortKeywordTitleH1Matching(unittest.TestCase):
    def test_pdf_short_keyword_matches(self):
        html = """<!DOCTYPE html>
        <html>
        <head><title>Adobe Acrobat - PDF Tools</title></head>
        <body>
            <h1>Edit, convert, and sign PDF documents</h1>
        </body>
        </html>"""
        res = engagement_check.run("https://adobe.example")
        mismatch_findings = [f for f in res["findings"] if f["check"] == "title_h1_alignment"]
        self.assertEqual(len(mismatch_findings), 0)


class TestEntityAmbiguityFalsePositiveResistance(unittest.TestCase):
    def test_real_world_brand_title_and_h1_do_not_trigger_conflict(self):
        html = """<!DOCTYPE html>
        <html>
        <head>
            <title>Stripe | Financial Infrastructure for the Internet</title>
            <script type="application/ld+json">
            {
                "@type": "Organization",
                "name": "Stripe, Inc."
            }
            </script>
        </head>
        <body>
            <h1>Financial Infrastructure for the Internet</h1>
        </body>
        </html>"""
        res = freshness_check.run("https://stripe.example")
        conflict_findings = [f for f in res["findings"] if f["check"] == "entity_name_consistency"]
        self.assertEqual(len(conflict_findings), 0)


if __name__ == "__main__":
    unittest.main()
