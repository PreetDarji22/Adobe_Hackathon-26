"""
shared/report_schema.py

Canonical Finding/Report shapes used by every skill, plus a validator that
checks the final orchestrator output against the schema required by the
Adobe Round 3 problem statement (site, audited_at, summary counts, and
findings[] each with id/title/severity/evidence/suggested_action).

Kept dependency-free (stdlib only).
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

VALID_SEVERITIES = ("critical", "high", "medium", "low")
REQUIRED_FINDING_FIELDS = ("id", "title", "severity", "evidence", "suggested_action")
REQUIRED_ACTION_FIELDS = ("summary", "priority")
REQUIRED_REPORT_FIELDS = ("site", "audited_at", "summary", "findings")
REQUIRED_SUMMARY_FIELDS = ("total_findings", "critical", "high", "medium")


@dataclass
class SuggestedAction:
    summary: str
    priority: str  # critical/high/medium/low
    how: Optional[str] = None
    why: Optional[str] = None


@dataclass
class Finding:
    id: str
    title: str
    severity: str  # critical/high/medium/low
    evidence: str
    suggested_action: SuggestedAction
    category: Optional[str] = None       # "discoverability" | "engagement"
    check: Optional[str] = None          # which deterministic check produced this
    url: Optional[str] = None
    confidence: Optional[str] = None     # "high" | "medium" | "low"
    source_skill: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def build_summary(findings: list[dict]) -> dict:
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for f in findings:
        sev = f.get("severity", "").lower()
        if sev in counts:
            counts[sev] += 1
    return {
        "total_findings": len(findings),
        "critical": counts["critical"],
        "high": counts["high"],
        "medium": counts["medium"],
        "low": counts["low"],
    }


def validate_report(report: dict) -> list[str]:
    """Return a list of human-readable schema violations. Empty list = valid."""
    errors = []
    for field_name in REQUIRED_REPORT_FIELDS:
        if field_name not in report:
            errors.append(f"Missing required report field: '{field_name}'")

    summary = report.get("summary", {})
    for field_name in REQUIRED_SUMMARY_FIELDS:
        if field_name not in summary:
            errors.append(f"Missing required summary field: '{field_name}'")

    findings = report.get("findings", [])
    if not isinstance(findings, list):
        errors.append("'findings' must be a list")
        findings = []

    seen_ids = set()
    for i, f in enumerate(findings):
        for field_name in REQUIRED_FINDING_FIELDS:
            if field_name not in f:
                errors.append(f"finding[{i}] missing required field: '{field_name}'")
        fid = f.get("id")
        if fid in seen_ids:
            errors.append(f"finding[{i}] has duplicate id '{fid}'")
        if fid:
            seen_ids.add(fid)
        sev = f.get("severity")
        if sev and sev.lower() not in VALID_SEVERITIES:
            errors.append(f"finding[{i}] has invalid severity '{sev}'")
        action = f.get("suggested_action", {})
        if not isinstance(action, dict):
            errors.append(f"finding[{i}].suggested_action must be an object")
        else:
            for field_name in REQUIRED_ACTION_FIELDS:
                if field_name not in action:
                    errors.append(
                        f"finding[{i}].suggested_action missing field: '{field_name}'"
                    )
            pri = action.get("priority")
            if pri and pri.lower() not in VALID_SEVERITIES:
                errors.append(f"finding[{i}].suggested_action has invalid priority '{pri}'")
            # Severity / priority reconciliation: must match unless non-empty 'why' explains divergence
            if sev and pri and sev.lower() != pri.lower():
                why = action.get("why")
                if not why or not str(why).strip():
                    errors.append(
                        f"finding[{i}] severity '{sev}' disagrees with suggested_action.priority '{pri}' without an explanatory 'why' field"
                    )
        if not f.get("evidence"):
            errors.append(f"finding[{i}] has empty/missing evidence")

    return errors

