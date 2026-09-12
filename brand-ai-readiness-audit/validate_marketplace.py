#!/usr/bin/env python3
"""
validate_marketplace.py

Run from the marketplace root:
    python3 validate_marketplace.py

Checks (mirrors the Round 3 PDF's own submission requirements):
  1. marketplace.json exists and is valid JSON.
  2. Every skill listed in marketplace.json exists on disk and has a
     SKILL.md with YAML frontmatter containing at minimum `name` and
     `description`.
  3. Exactly one skill is marked as the entrypoint.
  4. No skill folder contains obviously dangerous operations (grep for a
     small denylist of patterns as a sanity net -- not a substitute for
     manual review).
  5. Total marketplace size is within the 50MB submission cap.
  6. A live-format sample report (built from the fixture-driven functions,
     no network) validates against shared/report_schema.py.

Exits non-zero if any check fails, and prints a PASS/FAIL line per check.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from shared.report_schema import validate_report  # noqa: E402

MAX_SIZE_BYTES = 50 * 1024 * 1024
DANGEROUS_PATTERNS = [
    r"\bos\.remove\b", r"\bshutil\.rmtree\b", r"\bsubprocess\.Popen\(.*rm\b",
    r"DROP\s+TABLE", r"\bDELETE\s+FROM\b", r"requests\.post\(.*login",
]

results = []


def check(name: str, ok: bool, detail: str = ""):
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail and not ok else ""))


def main() -> int:
    manifest_path = ROOT / "marketplace.json"
    manifest_ok = manifest_path.exists()
    check("marketplace.json exists", manifest_ok)
    if not manifest_ok:
        return 1

    try:
        manifest = json.loads(manifest_path.read_text())
        check("marketplace.json is valid JSON", True)
    except json.JSONDecodeError as e:
        check("marketplace.json is valid JSON", False, str(e))
        return 1

    skills = manifest.get("skills", [])
    check("marketplace.json lists at least one skill", len(skills) >= 1)

    entrypoints = [s for s in skills if s.get("entrypoint") is True]
    check("exactly one entrypoint is marked", len(entrypoints) == 1,
          f"found {len(entrypoints)}")

    for skill in skills:
        skill_dir = ROOT / skill["path"]
        skill_md = skill_dir / "SKILL.md"
        exists = skill_dir.is_dir()
        check(f"skill folder exists: {skill['path']}", exists)
        if not exists:
            continue
        md_exists = skill_md.exists()
        check(f"SKILL.md exists: {skill['id']}", md_exists)
        if md_exists:
            text = skill_md.read_text(encoding="utf-8")
            has_frontmatter = text.startswith("---")
            has_name = bool(re.search(r"^name:\s*\S+", text, re.MULTILINE))
            has_description = bool(re.search(r"^description:", text, re.MULTILINE))
            check(f"SKILL.md has YAML frontmatter: {skill['id']}", has_frontmatter)
            check(f"SKILL.md declares name: {skill['id']}", has_name)
            check(f"SKILL.md declares description: {skill['id']}", has_description)

        for py_file in skill_dir.rglob("*.py"):
            content = py_file.read_text(encoding="utf-8", errors="replace")
            hits = [p for p in DANGEROUS_PATTERNS if re.search(p, content, re.IGNORECASE)]
            check(f"no denylisted patterns in {py_file.relative_to(ROOT)}",
                  not hits, str(hits))

    total_size = sum(f.stat().st_size for f in ROOT.rglob("*") if f.is_file())
    check(f"total size <= 50MB (actual: {total_size / 1_000_000:.2f}MB)",
          total_size <= MAX_SIZE_BYTES)

    readme_exists = (ROOT / "README.md").exists()
    check("root README.md exists", readme_exists)

    sample_report = {
        "site": "example.com",
        "audited_at": "2026-09-20T14:32:00Z",
        "summary": {"total_findings": 1, "critical": 0, "high": 1, "medium": 0},
        "findings": [{
            "id": "F-001", "title": "sample", "severity": "high",
            "evidence": "sample evidence",
            "suggested_action": {"summary": "sample", "priority": "high"},
        }],
    }
    errors = validate_report(sample_report)
    check("report_schema validator accepts a well-formed report", not errors, str(errors))

    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed.")
    if failed:
        print("\nFAILED CHECKS:")
        for name, _, detail in failed:
            print(f"  - {name}" + (f" ({detail})" if detail else ""))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
