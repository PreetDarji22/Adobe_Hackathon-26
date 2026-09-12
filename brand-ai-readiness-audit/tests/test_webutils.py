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


if __name__ == "__main__":
    unittest.main()
