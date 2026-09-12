import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "skills" / "engagement-audit" / "scripts"))

from shared import webutils  # noqa: E402
import engagement_check  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class TestEngagementGoodSite(unittest.TestCase):
    def test_good_site_has_no_h1_or_nav_findings(self):
        html = load("good_site.html")
        fake = webutils.FetchResult(url="https://acme.example/", status_code=200, html=html)
        with patch.object(webutils, "fetch", return_value=fake):
            result = engagement_check.run("https://acme.example/")
        checks = {f["check"] for f in result["findings"]}
        self.assertNotIn("h1_presence", checks)
        self.assertNotIn("internal_link_count", checks)
        self.assertNotIn("cta_presence", checks)


class TestEngagementThinNavSite(unittest.TestCase):
    def test_thin_nav_site_flags_navigation_and_cta(self):
        html = load("thin_nav_site.html")
        fake = webutils.FetchResult(url="https://contact.example/", status_code=200, html=html)
        with patch.object(webutils, "fetch", return_value=fake):
            result = engagement_check.run("https://contact.example/")
        checks = {f["check"] for f in result["findings"]}
        self.assertIn("internal_link_count", checks)
        self.assertIn("cta_presence", checks)


class TestEngagementTitleH1Mismatch(unittest.TestCase):
    def test_mismatched_title_and_h1_flagged(self):
        html = load("stale_no_schema_site.html")
        fake = webutils.FetchResult(url="https://mismatch.example/", status_code=200, html=html)
        with patch.object(webutils, "fetch", return_value=fake):
            result = engagement_check.run("https://mismatch.example/")
        checks = {f["check"] for f in result["findings"]}
        self.assertIn("title_h1_alignment", checks)


class TestEngagementNoH1(unittest.TestCase):
    def test_missing_h1_flagged(self):
        html = "<html><head><title>Some Page</title></head><body><p>text</p><a href='/a'>a</a><a href='/b'>b</a></body></html>"
        fake = webutils.FetchResult(url="https://nohead.example/", status_code=200, html=html)
        with patch.object(webutils, "fetch", return_value=fake):
            result = engagement_check.run("https://nohead.example/")
        checks = {f["check"] for f in result["findings"]}
        self.assertIn("h1_presence", checks)


class TestEngagementSubdomainPortal(unittest.TestCase):
    def test_subdomain_portal_does_not_flag_false_dead_end(self):
        # Wikipedia-style portal links exclusively to subdomains (en.wikipedia.org, fr.wikipedia.org)
        html = load("subdomain_portal.html")
        fake = webutils.FetchResult(url="https://www.wikipedia.org/", status_code=200, html=html)
        with patch.object(webutils, "fetch", return_value=fake):
            result = engagement_check.run("https://www.wikipedia.org/")
        checks = {f["check"] for f in result["findings"]}
        self.assertNotIn("internal_link_count", checks)

    def test_distinct_registrable_domains_under_multi_part_suffix_not_merged(self):
        # Page on service.gov.uk linking only to unrelated external co.uk domains
        html = """<!DOCTYPE html>
        <html><head><title>Gov Service</title></head><body>
        <h1>Service Portal</h1>
        <a href="https://www.commercial-site.co.uk">External Commercial</a>
        </body></html>"""
        fake = webutils.FetchResult(url="https://www.service.gov.uk/", status_code=200, html=html)
        with patch.object(webutils, "fetch", return_value=fake):
            result = engagement_check.run("https://www.service.gov.uk/")
        checks = {f["check"] for f in result["findings"]}
        self.assertIn("internal_link_count", checks)


if __name__ == "__main__":
    unittest.main()

