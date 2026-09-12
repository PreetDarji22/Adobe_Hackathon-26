import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "skills" / "freshness-corroboration" / "scripts"))

from shared import webutils  # noqa: E402
import freshness_check  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class TestFreshnessStaleSite(unittest.TestCase):
    def test_stale_meta_date_flagged(self):
        html = load("stale_no_schema_site.html")
        fake = webutils.FetchResult(url="https://old.example/", status_code=200, html=html)
        with patch.object(webutils, "fetch", return_value=fake):
            result = freshness_check.run("https://old.example/")
        checks = {f["check"] for f in result["findings"]}
        self.assertIn("content_age", checks)
        age_finding = next(f for f in result["findings"] if f["check"] == "content_age")
        self.assertIn(age_finding["severity"], ("medium", "high"))


class TestFreshnessNoSignal(unittest.TestCase):
    def test_no_date_signal_flagged(self):
        html = "<html><head><title>No dates here</title></head><body><h1>Hi</h1></body></html>"
        fake = webutils.FetchResult(url="https://nodates.example/", status_code=200, html=html)
        with patch.object(webutils, "fetch", return_value=fake):
            result = freshness_check.run("https://nodates.example/")
        checks = {f["check"] for f in result["findings"]}
        self.assertIn("freshness_signal_presence", checks)


class TestFreshnessGoodSite(unittest.TestCase):
    def test_good_site_builds_facts_to_corroborate(self):
        html = load("good_site.html")
        fake = webutils.FetchResult(url="https://acme.example/", status_code=200, html=html)
        with patch.object(webutils, "fetch", return_value=fake):
            result = freshness_check.run("https://acme.example/")
        facts = result["raw_evidence"]["facts_to_corroborate"]
        self.assertTrue(len(facts) >= 1)
        # Never asserts corroboration happened -- only surfaces claims.
        for f in facts:
            self.assertIn("claim", f)
            self.assertIn("why_it_matters", f)


class TestFreshnessFetchFailure(unittest.TestCase):
    def test_fetch_failure_returns_empty_findings(self):
        fake = webutils.FetchResult(url="https://down.example/", status_code=None, error="timeout")
        with patch.object(webutils, "fetch", return_value=fake):
            result = freshness_check.run("https://down.example/")
        self.assertEqual(result["findings"], [])


class TestFreshnessSameAs(unittest.TestCase):
    def test_missing_sameas_in_organization_schema_is_flagged_low(self):
        # good_site.html has an Organization schema without sameAs
        html = load("good_site.html")
        fake = webutils.FetchResult(url="https://acme.example/", status_code=200, html=html)
        with patch.object(webutils, "fetch", return_value=fake):
            result = freshness_check.run("https://acme.example/")
        sameas_findings = [f for f in result["findings"] if f["check"] == "sameas_presence"]
        self.assertEqual(len(sameas_findings), 1)
        self.assertEqual(sameas_findings[0]["severity"], "low")
        self.assertIn("Acme Widgets", sameas_findings[0]["evidence"])
        self.assertTrue(sameas_findings[0]["suggested_action"]["how"])

    def test_present_sameas_in_organization_schema_is_not_flagged(self):
        # sameas_org_site.html has an Organization schema with sameAs array
        html = load("sameas_org_site.html")
        fake = webutils.FetchResult(url="https://acmecorp.example/", status_code=200, html=html)
        with patch.object(webutils, "fetch", return_value=fake):
            result = freshness_check.run("https://acmecorp.example/")
        sameas_findings = [f for f in result["findings"] if f["check"] == "sameas_presence"]
        self.assertEqual(len(sameas_findings), 0)


class TestEntityCandidateTightening(unittest.TestCase):
    def test_openai_scenario_does_not_flag_section_headings_as_conflicting_brands(self):
        html = """<!DOCTYPE html>
        <html>
        <head>
          <title>OpenAI</title>
          <meta name="description" content="OpenAI is an AI research and deployment company.">
          <script type="application/ld+json">
          {"@context":"https://schema.org","@type":"Organization","name":"OpenAI","sameAs":["https://en.wikipedia.org/wiki/OpenAI"]}
          </script>
        </head>
        <body>
          <h1>Creating safe AGI that benefits all of humanity</h1>
          <h2>Research & Deployment</h2>
          <p>We research generative models and how to align them with human values.</p>
        </body>
        </html>"""
        fake = webutils.FetchResult(url="https://openai.example/", status_code=200, html=html)
        with patch.object(webutils, "fetch", return_value=fake):
            result = freshness_check.run("https://openai.example/")
        conflict_findings = [f for f in result["findings"] if f["check"] == "entity_name_consistency"]
        self.assertEqual(len(conflict_findings), 0)


if __name__ == "__main__":
    unittest.main()

