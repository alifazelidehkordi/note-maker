from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import convert_md_to_pdf
from phase1_acceptance import run_acceptance


class Phase1AcceptanceTests(unittest.TestCase):
    def test_browser_free_release_acceptance(self):
        if convert_md_to_pdf.HTML is None or convert_md_to_pdf.markdown is None:
            self.skipTest("PDF dependencies unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            report = run_acceptance(Path(tmp))

        self.assertTrue(report["passed"], report)
        self.assertEqual(
            [check["name"] for check in report["checks"]],
            [
                "batch_failure_and_diagnostics",
                "retry_failed_and_resume",
                "pdf_book_end_to_end",
            ],
        )
        self.assertTrue(all(check["passed"] for check in report["checks"]))


if __name__ == "__main__":
    unittest.main()
