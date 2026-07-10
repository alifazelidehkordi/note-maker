from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import batch_pdf


class FakeDriver:
    title = "ChatGPT"

    def save_screenshot(self, path: str) -> bool:
        Path(path).write_bytes(b"png")
        return True


class BatchDiagnosticsIntegrationTests(unittest.TestCase):
    def test_pdf_batch_automatically_saves_final_failure_and_summary_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            input_dir = base / "inputs"
            output_dir = base / "outputs"
            log_dir = base / "logs"
            input_dir.mkdir()
            source = input_dir / "source.pdf"
            source.write_bytes(b"pdf")
            prompt = base / "prompt.md"
            prompt.write_text("Create markdown", encoding="utf-8")
            driver = FakeDriver()

            with mock.patch.object(batch_pdf.common, "LOGS_DIR", log_dir), mock.patch.object(
                batch_pdf.common, "bootstrap_session", return_value=driver
            ), mock.patch.object(batch_pdf, "process_one", return_value=False), mock.patch.object(
                batch_pdf.common, "driver_is_alive", return_value=True
            ), mock.patch.object(batch_pdf.common, "reset_chat"), mock.patch.object(
                batch_pdf.common, "prune_driver_cookies"
            ), mock.patch.object(batch_pdf.common.time, "sleep"), mock.patch.object(
                batch_pdf.core, "latest_assistant_text", return_value="no artifact"
            ), mock.patch.object(batch_pdf.core, "LOG_FILE", base / "run.log"):
                code = batch_pdf.run_batch(
                    input_dir=input_dir,
                    output_dir=output_dir,
                    prompt_path=prompt,
                    max_attempts=2,
                    close_delay=0,
                    keep_browser=True,
                    output_ext="md",
                )

            self.assertEqual(code, 2)
            summary = json.loads((log_dir / "last_batch_summary.json").read_text(encoding="utf-8"))
            self.assertIn("source.pdf", summary["diagnostics"])
            diagnostic_dir = Path(summary["diagnostics"]["source.pdf"])
            self.assertTrue((diagnostic_dir / "metadata.json").exists())
            self.assertTrue((diagnostic_dir / "last_response.txt").exists())
            self.assertTrue((diagnostic_dir / "last_state.png").exists())
            metadata = json.loads((diagnostic_dir / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["attempt"], 2)
            self.assertEqual(metadata["stage"], "download")
            self.assertEqual(metadata["expected_extensions"], [".md"])


if __name__ == "__main__":
    unittest.main()
