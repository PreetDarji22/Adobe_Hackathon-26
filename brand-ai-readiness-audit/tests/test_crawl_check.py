import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "skills" / "crawl-render-audit" / "scripts"))

from shared import webutils  # noqa: E402
import crawl_check  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def fake_fetch_factory(html_map, default_status=200):
    """Return a fetch() replacement that serves fixture HTML for the main
    page URL and a 404 for everything else (sitemap, internal links)."""
    def fake_fetch(url, timeout=8):
        for key, (html, status) in html_map.items():
            if key in url:
                return webutils.FetchResult(url=url, status_code=status, html=html)
        return webutils.FetchResult(url=url, status_code=404, html="", error=None)
    return fake_fetch


class TestCrawlCheckGoodSite(unittest.TestCase):
    def setUp(self):
        self.html = load("good_site.html")

    @patch.object(webutils, "check_robots", return_value={"robots_txt_found": True, "allowed": True, "robots_url": "https://acme.example/robots.txt"})
    def test_good_site_has_no_critical_findings(self, _mock_robots):
        with patch.object(webutils, "fetch", side_effect=fake_fetch_factory({"acme.example": (self.html, 200)})):
            result = crawl_check.run("https://acme.example/")
        severities = [f["severity"] for f in result["findings"]]
        self.assertNotIn("critical", severities)
        # Good site has JSON-LD, title, meta description, canonical -> should
        # not flag those specific checks.
        checks_flagged = {f["check"] for f in result["findings"]}
        self.assertNotIn("structured_data", checks_flagged)
        self.assertNotIn("title_tag", checks_flagged)
        self.assertNotIn("meta_description", checks_flagged)
        self.assertNotIn("canonical_url", checks_flagged)


class TestCrawlCheckRobotsDisallow(unittest.TestCase):
    @patch.object(webutils, "check_robots", return_value={"robots_txt_found": True, "allowed": False, "robots_url": "https://blocked.example/robots.txt"})
    def test_disallowed_by_robots_is_critical(self, _mock_robots):
        with patch.object(webutils, "fetch", side_effect=fake_fetch_factory({"blocked.example": ("<html></html>", 200)})):
            result = crawl_check.run("https://blocked.example/")
        robots_findings = [f for f in result["findings"] if f["check"] == "robots_txt"]
        self.assertEqual(len(robots_findings), 1)
        self.assertEqual(robots_findings[0]["severity"], "critical")


class TestCrawlCheckRobotsUnknown(unittest.TestCase):
    @patch.object(webutils, "check_robots", return_value={"robots_txt_found": False, "allowed": None, "robots_url": "https://x.example/robots.txt"})
    def test_unreadable_robots_does_not_produce_disallow_finding(self, _mock_robots):
        with patch.object(webutils, "fetch", side_effect=fake_fetch_factory({"x.example": ("<html><title>t</title><h1>t</h1></html>", 200)})):
            result = crawl_check.run("https://x.example/")
        robots_findings = [f for f in result["findings"] if f["check"] == "robots_txt"]
        self.assertEqual(len(robots_findings), 0)


class TestCrawlCheckJsHeavySite(unittest.TestCase):
    @patch.object(webutils, "check_robots", return_value={"robots_txt_found": True, "allowed": True, "robots_url": "u"})
    def test_js_heavy_site_flags_render_dependency(self, _mock_robots):
        html = load("js_heavy_site.html")
        with patch.object(webutils, "fetch", side_effect=fake_fetch_factory({"spa.example": (html, 200)})):
            result = crawl_check.run("https://spa.example/")
        checks_flagged = {f["check"] for f in result["findings"]}
        self.assertIn("js_render_dependency", checks_flagged)


class TestCrawlCheckFetchFailure(unittest.TestCase):
    @patch.object(webutils, "check_robots", return_value={"robots_txt_found": False, "allowed": None, "robots_url": "u"})
    def test_fetch_error_produces_single_critical_finding(self, _mock_robots):
        def failing_fetch(url, timeout=8):
            return webutils.FetchResult(url=url, status_code=None, error="ConnectionRefused")
        with patch.object(webutils, "fetch", side_effect=failing_fetch):
            result = crawl_check.run("https://down.example/")
        self.assertEqual(len(result["findings"]), 1)
        self.assertEqual(result["findings"][0]["severity"], "critical")


if __name__ == "__main__":
    unittest.main()
