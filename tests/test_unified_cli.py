from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from note_maker.cli import main


class UnifiedCliTests(unittest.TestCase):
    def test_pdf_dry_run_resolves_without_opening_browser(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "note-maker.toml"
            config.write_text(
                """
[runtime]
browser_provider = "patchright"
parallel_runs = 2

[commands.pdf]
input_dir = "incoming"
output_dir = "generated"
prompt = "prompt.md"
""".strip()
                + "\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--config",
                        str(config),
                        "run",
                        "pdf",
                        "--parallel-runs",
                        "3",
                        "--set",
                        "download_timeout=120",
                        "--dry-run",
                    ]
                )
            self.assertEqual(code, 0)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["values"]["parallel_runs"], 3)
            self.assertEqual(payload["values"]["download_timeout"], 120)
            self.assertEqual(payload["values"]["input_dir"], str((root / "incoming").resolve()))

    def test_validate_accepts_structured_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "note.md"
            artifact.write_text(
                "# Generated Note\n\n## Explanation\n\n"
                + "Meaningful generated content. " * 20
                + "\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["validate", str(artifact)])
            self.assertEqual(code, 0)
            self.assertIn("[VALID]", output.getvalue())

    def test_status_reads_machine_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp) / "summary.json"
            summary.write_text(
                json.dumps(
                    {
                        "mode": "pdf-md",
                        "run_id": "run-123",
                        "successes": 4,
                        "failures": [],
                    }
                ),
                encoding="utf-8",
            )
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--json", "status", "--summary", str(summary)])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue())["successes"], 4)


if __name__ == "__main__":
    unittest.main()
