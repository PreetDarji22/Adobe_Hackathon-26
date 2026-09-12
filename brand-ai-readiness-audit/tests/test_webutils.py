import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared import webutils  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class TestNormalizeUrl(unittest.TestCase):
    def test_adds_scheme(self):
        self.assertEqual(webutils.normalize_url("example.com"), "https://example.com")

    def test_keeps_existing_scheme(self):
        self.assertEqual(webutils.normalize_url("http://example.com/x"), "http://example.com/x")

    def test_strips_fragment(self):
        self.assertEqual(webutils.normalize_url("https://example.com/x#section"), "https://example.com/x")


class TestExtractHtmlSignals(unittest.TestCase):
    def test_good_site_extracts_title_meta_jsonld_headings(self):
        signals = webutils.extract_html_signals(load("good_site.html"))
        self.assertIn("Acme Widgets", signals["title"])
        self.assertTrue(signals["meta"].get("description"))
        self.assertEqual(signals["jsonld_raw_blocks"], 1)
        self.assertEqual(signals["jsonld_parse_errors"], 0)
        self.assertEqual(len(signals["jsonld_objects"]), 1)
        self.assertEqual(signals["jsonld_objects"][0]["name"], "Acme Widgets")
        self.assertTrue(signals["headings"]["h1"])
        self.assertGreater(signals["visible_text_chars"], 50)
        self.assertEqual(signals["canonical"], "https://acmewidgets.example/")

    def test_js_heavy_site_has_low_visible_text_and_empty_root(self):
        signals = webutils.extract_html_signals(load("js_heavy_site.html"))
        self.assertIn("root", signals["empty_framework_roots_seen"])
        self.assertLess(signals["visible_text_chars"], 50)
        self.assertGreater(signals["script_to_text_ratio"], 0.85)

    def test_thin_nav_site_has_single_link_or_fewer(self):
        signals = webutils.extract_html_signals(load("thin_nav_site.html"))
        self.assertEqual(len(signals["links"]), 0)


class TestResolveLinks(unittest.TestCase):
    def test_filters_mailto_and_fragments(self):
        links = ["mailto:a@b.com", "#top", "/catalog", "https://other.example/x"]
        resolved = webutils.resolve_links("https://acme.example/", links, same_domain_only=True)
        self.assertEqual(resolved, ["https://acme.example/catalog"])

    def test_allows_cross_domain_when_flag_false(self):
        links = ["https://other.example/x"]
        resolved = webutils.resolve_links("https://acme.example/", links, same_domain_only=False)
        self.assertEqual(resolved, ["https://other.example/x"])

    def test_allow_subdomains_resolves_same_registrable_domain(self):
        links = [
            "https://en.wikipedia.org/wiki/Main",
            "https://fr.wikipedia.org/wiki/Accueil",
            "https://unrelated.example/page",
        ]
        resolved = webutils.resolve_links(
            "https://www.wikipedia.org/", links, same_domain_only=True, allow_subdomains=True
        )
        self.assertIn("https://en.wikipedia.org/wiki/Main", resolved)
        self.assertIn("https://fr.wikipedia.org/wiki/Accueil", resolved)
        self.assertNotIn("https://unrelated.example/page", resolved)

    def test_multi_part_public_suffix_does_not_merge_unrelated_domains(self):
        links = [
            "https://www.service.gov.uk/start",
            "https://www.unrelated.co.uk/page",
            "https://other.service.gov.uk/help",
        ]
        # gov.uk is a public suffix -> service.gov.uk is the registrable domain
        resolved = webutils.resolve_links(
            "https://www.service.gov.uk/", links, same_domain_only=True, allow_subdomains=True
        )
        self.assertIn("https://www.service.gov.uk/start", resolved)
        self.assertIn("https://other.service.gov.uk/help", resolved)
        self.assertNotIn("https://www.unrelated.co.uk/page", resolved)


class TestRegistrableDomain(unittest.TestCase):
    def test_standard_domains(self):
        self.assertEqual(webutils.get_registrable_domain("example.com"), "example.com")
        self.assertEqual(webutils.get_registrable_domain("sub.example.com"), "example.com")
        self.assertEqual(webutils.get_registrable_domain("a.b.example.com"), "example.com")

    def test_multi_part_public_suffixes(self):
        self.assertEqual(webutils.get_registrable_domain("www.service.gov.uk"), "service.gov.uk")
        self.assertEqual(webutils.get_registrable_domain("docs.service.gov.uk"), "service.gov.uk")
        self.assertEqual(webutils.get_registrable_domain("shop.brand.co.uk"), "brand.co.uk")
        self.assertEqual(webutils.get_registrable_domain("www.amazon.co.in"), "amazon.co.in")
        self.assertEqual(webutils.get_registrable_domain("news.brand.co.jp"), "brand.co.jp")



class TestCheckRobotsNamedAICrawlers(unittest.TestCase):
    def test_parses_named_ai_agents(self):
        from unittest.mock import patch, MagicMock
        raw_robots = """User-agent: *
Allow: /

User-agent: GPTBot
Disallow: /

User-agent: ClaudeBot
Disallow: /

User-agent: Google-Extended
Disallow: /internal/
"""
        mock_resp = MagicMock()
        mock_resp.read.return_value = raw_robots.encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            res = webutils.check_robots("https://amazon.example/")

        self.assertTrue(res["robots_txt_found"])
        self.assertTrue(res["allowed"])  # * is allowed
        # GPTBot and ClaudeBot are disallowed at /
        disallowed_names = [d["agent"] for d in res["disallowed_ai_agents"]]
        self.assertIn("GPTBot", disallowed_names)
        self.assertIn("ClaudeBot", disallowed_names)
        # Google-Extended is allowed at / (only /internal/ blocked)
        self.assertNotIn("Google-Extended", disallowed_names)


if __name__ == "__main__":
    unittest.main()

