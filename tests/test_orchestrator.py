import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "skills" / "audit-orchestrator" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "crawl-render-audit" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "freshness-corroboration" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "engagement-audit" / "scripts"))

from shared import webutils  # noqa: E402
from shared.report_schema import validate_report  # noqa: E402
import orchestrate  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def fake_fetch_factory(main_html, main_url_fragment):
    def fake_fetch(url, timeout=8):
        if main_url_fragment in url and "sitemap" not in url:
            return webutils.FetchResult(url=url, status_code=200, html=main_html)
        return webutils.FetchResult(url=url, status_code=404, html="")
    return fake_fetch


class TestOrchestratorEndToEnd(unittest.TestCase):
    @patch.object(webutils, "check_robots", return_value={"robots_txt_found": True, "allowed": True, "robots_url": "u"})
    def test_report_matches_schema_for_good_site(self, _mock_robots):
        html = load("good_site.html")
        with patch.object(webutils, "fetch", side_effect=fake_fetch_factory(html, "acme.example")):
            report = orchestrate.run("https://acme.example/")

        errors = validate_report(report)
        self.assertEqual(errors, [], msg=f"Schema errors: {errors}")
        self.assertEqual(report["site"], "acme.example")
        self.assertEqual(report["summary"]["total_findings"], len(report["findings"]))
        # IDs must be sequential and unique.
        ids = [f["id"] for f in report["findings"]]
        self.assertEqual(ids, [f"F-{i:03d}" for i in range(1, len(ids) + 1)])
        self.assertEqual(report["_schema_validation"], "PASS")

    @patch.object(webutils, "check_robots", return_value={"robots_txt_found": True, "allowed": True, "robots_url": "u"})
    def test_report_for_thin_stale_site_has_multiple_findings(self, _mock_robots):
        html = load("stale_no_schema_site.html")
        with patch.object(webutils, "fetch", side_effect=fake_fetch_factory(html, "old.example")):
            report = orchestrate.run("https://old.example/")

        self.assertGreater(report["summary"]["total_findings"], 3)
        self.assertEqual(validate_report(report), [])

    @patch.object(webutils, "check_robots", return_value={"robots_txt_found": False, "allowed": None, "robots_url": "u"})
    def test_unreachable_site_still_produces_valid_report(self, _mock_robots):
        def failing_fetch(url, timeout=8):
            return webutils.FetchResult(url=url, status_code=None, error="DNS failure")
        with patch.object(webutils, "fetch", side_effect=failing_fetch):
            report = orchestrate.run("https://doesnotexist.invalid/")

        self.assertEqual(validate_report(report), [])
        self.assertGreaterEqual(report["summary"]["critical"], 1)

    @patch.object(webutils, "check_robots", return_value={"robots_txt_found": True, "allowed": True, "robots_url": "u"})
    def test_runtime_recorded_and_within_budget(self, _mock_robots):
        html = load("good_site.html")
        with patch.object(webutils, "fetch", side_effect=fake_fetch_factory(html, "acme.example")):
            report = orchestrate.run("https://acme.example/")
        self.assertIn("runtime_seconds", report)
        self.assertLess(report["runtime_seconds"], 280)


if __name__ == "__main__":
    unittest.main()
