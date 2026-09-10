import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TestMarketplaceValidation(unittest.TestCase):
    def test_validate_marketplace_script_passes(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "validate_marketplace.py")],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(
            result.returncode, 0,
            msg=f"validate_marketplace.py failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
