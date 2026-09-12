import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared.report_schema import build_summary, validate_report  # noqa: E402


class TestBuildSummary(unittest.TestCase):
    def test_counts_by_severity(self):
        findings = [
            {"severity": "critical"}, {"severity": "high"},
            {"severity": "high"}, {"severity": "medium"}, {"severity": "low"},
        ]
        summary = build_summary(findings)
        self.assertEqual(summary["total_findings"], 5)
        self.assertEqual(summary["critical"], 1)
        self.assertEqual(summary["high"], 2)
        self.assertEqual(summary["medium"], 1)
        self.assertEqual(summary["low"], 1)


class TestValidateReport(unittest.TestCase):
    def _valid_report(self):
        return {
            "site": "example.com",
            "audited_at": "2026-09-20T14:32:00Z",
            "summary": {"total_findings": 1, "critical": 0, "high": 1, "medium": 0},
            "findings": [{
                "id": "F-001", "title": "t", "severity": "high",
                "evidence": "e",
                "suggested_action": {"summary": "s", "priority": "high"},
            }],
        }

    def test_valid_report_has_no_errors(self):
        self.assertEqual(validate_report(self._valid_report()), [])

    def test_missing_top_level_field_detected(self):
        report = self._valid_report()
        del report["audited_at"]
        errors = validate_report(report)
        self.assertTrue(any("audited_at" in e for e in errors))

    def test_missing_finding_field_detected(self):
        report = self._valid_report()
        del report["findings"][0]["evidence"]
        errors = validate_report(report)
        self.assertTrue(any("evidence" in e for e in errors))

    def test_invalid_severity_detected(self):
        report = self._valid_report()
        report["findings"][0]["severity"] = "catastrophic"
        errors = validate_report(report)
        self.assertTrue(any("invalid severity" in e for e in errors))

    def test_duplicate_ids_detected(self):
        report = self._valid_report()
        report["findings"].append(dict(report["findings"][0]))
        errors = validate_report(report)
        self.assertTrue(any("duplicate id" in e for e in errors))

    def test_unexplained_priority_severity_mismatch_detected(self):
        report = self._valid_report()
        report["findings"][0]["severity"] = "high"
        report["findings"][0]["suggested_action"]["priority"] = "low"
        errors = validate_report(report)
        self.assertTrue(any("disagrees with suggested_action.priority" in e for e in errors))

    def test_explained_priority_severity_mismatch_allowed(self):
        report = self._valid_report()
        report["findings"][0]["severity"] = "high"
        report["findings"][0]["suggested_action"]["priority"] = "low"
        report["findings"][0]["suggested_action"]["why"] = "Urgency is deferred pending core migration."
        errors = validate_report(report)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()

