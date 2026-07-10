from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import batch_markdown
import batch_pdf


VALID_MARKDOWN = """# Generated Note

## Explanation

This is a complete generated note containing enough explanatory text for the artifact validator and resume manifest.
It includes additional useful content so that the file is safely above the configured minimum size.
"""


class FakeDriver:
    title = "ChatGPT"

    def quit(self):
        pass


class ResumeIntegrationTests(unittest.TestCase):
    def test_pdf_second_run_skips_without_opening_browser(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "inputs"
            output_dir = root / "outputs"
            logs = root / "logs"
            input_dir.mkdir()
            source = input_dir / "one.pdf"
            source.write_bytes(b"pdf-v1")
            prompt = root / "prompt.md"
            prompt.write_text("Create notes", encoding="utf-8")
            driver = FakeDriver()

            def produce(_driver, _prompt, input_path, target_dir, _model, **kwargs):
                ext = kwargs["output_ext"].lstrip(".")
                (target_dir / f"{input_path.stem}.{ext}").write_text(VALID_MARKDOWN, encoding="utf-8")
                return True

            patches = [
                mock.patch.object(batch_pdf.common, "LOGS_DIR", logs),
                mock.patch.object(batch_pdf.core, "LOG_FILE", root / "run.log"),
                mock.patch.object(batch_pdf.common, "bootstrap_session", return_value=driver),
                mock.patch.object(batch_pdf, "process_one", side_effect=produce),
                mock.patch.object(batch_pdf.common, "prune_driver_cookies"),
            ]
            with patches[0], patches[1], patches[2], patches[3] as process, patches[4]:
                code = batch_pdf.run_batch(
                    input_dir=input_dir,
                    output_dir=output_dir,
                    prompt_path=prompt,
                    output_ext="md",
                    keep_browser=True,
                )
            self.assertEqual(code, 0)
            self.assertEqual(process.call_count, 1)

            with mock.patch.object(batch_pdf.common, "LOGS_DIR", logs), mock.patch.object(
                batch_pdf.core, "LOG_FILE", root / "run.log"
            ), mock.patch.object(
                batch_pdf.common, "bootstrap_session", side_effect=AssertionError("browser must not open")
            ), mock.patch.object(
                batch_pdf, "process_one", side_effect=AssertionError("job must not run")
            ):
                code = batch_pdf.run_batch(
                    input_dir=input_dir,
                    output_dir=output_dir,
                    prompt_path=prompt,
                    output_ext="md",
                    close_delay=0,
                )
            self.assertEqual(code, 0)
            summary = json.loads((logs / "last_batch_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["successes"], 1)
            self.assertIn("one.pdf", summary["skipped"])

    def test_pdf_source_change_runs_only_changed_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "inputs"
            output_dir = root / "outputs"
            input_dir.mkdir()
            sources = [input_dir / "one.pdf", input_dir / "two.pdf"]
            for index, source in enumerate(sources):
                source.write_bytes(f"pdf-{index}".encode())
            prompt = root / "prompt.md"
            prompt.write_text("Create notes", encoding="utf-8")
            driver = FakeDriver()

            def produce(_driver, _prompt, input_path, target_dir, _model, **kwargs):
                (target_dir / f"{input_path.stem}.md").write_text(VALID_MARKDOWN, encoding="utf-8")
                return True

            with mock.patch.object(batch_pdf.core, "LOG_FILE", root / "run.log"), mock.patch.object(
                batch_pdf.common, "bootstrap_session", return_value=driver
            ), mock.patch.object(batch_pdf, "process_one", side_effect=produce), mock.patch.object(
                batch_pdf.common, "prune_driver_cookies"
            ):
                self.assertEqual(
                    batch_pdf.run_batch(input_dir, output_dir, prompt, output_ext="md", keep_browser=True),
                    0,
                )

            sources[1].write_bytes(b"pdf-two-changed")
            seen: list[str] = []

            def produce_changed(_driver, _prompt, input_path, target_dir, _model, **kwargs):
                seen.append(input_path.name)
                (target_dir / f"{input_path.stem}.md").write_text(VALID_MARKDOWN + "\nupdated", encoding="utf-8")
                return True

            with mock.patch.object(batch_pdf.core, "LOG_FILE", root / "run.log"), mock.patch.object(
                batch_pdf.common, "bootstrap_session", return_value=driver
            ), mock.patch.object(batch_pdf, "process_one", side_effect=produce_changed), mock.patch.object(
                batch_pdf.common, "prune_driver_cookies"
            ):
                self.assertEqual(
                    batch_pdf.run_batch(input_dir, output_dir, prompt, output_ext="md", keep_browser=True),
                    0,
                )
            self.assertEqual(seen, ["two.pdf"])

    def test_markdown_change_runs_only_changed_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markdown_file = root / "lecture.md"
            markdown_file.write_text(
                "## First\nFirst section source text.\n\n## Second\nSecond section source text.",
                encoding="utf-8",
            )
            output_dir = root / "outputs"
            prompt = root / "prompt.md"
            prompt.write_text("Create notes", encoding="utf-8")
            driver = FakeDriver()

            def produce(**kwargs):
                section = kwargs["section"]
                target_dir = kwargs["output_dir"]
                (target_dir / f"{section.output_stem}.md").write_text(VALID_MARKDOWN, encoding="utf-8")
                return True

            with mock.patch.object(batch_markdown.core, "LOG_FILE", root / "run.log"), mock.patch.object(
                batch_markdown.common, "bootstrap_session", return_value=driver
            ), mock.patch.object(batch_markdown, "process_markdown_section", side_effect=produce), mock.patch.object(
                batch_markdown.common, "prune_driver_cookies"
            ):
                self.assertEqual(
                    batch_markdown.run_batch(
                        markdown_file,
                        output_dir,
                        prompt,
                        output_ext="md",
                        keep_browser=True,
                    ),
                    0,
                )

            markdown_file.write_text(
                "## First\nFirst section source text.\n\n## Second\nSecond section source text changed.",
                encoding="utf-8",
            )
            seen: list[int] = []

            def produce_changed(**kwargs):
                section = kwargs["section"]
                target_dir = kwargs["output_dir"]
                seen.append(section.index)
                (target_dir / f"{section.output_stem}.md").write_text(VALID_MARKDOWN + "\nupdated", encoding="utf-8")
                return True

            with mock.patch.object(batch_markdown.core, "LOG_FILE", root / "run.log"), mock.patch.object(
                batch_markdown.common, "bootstrap_session", return_value=driver
            ), mock.patch.object(batch_markdown, "process_markdown_section", side_effect=produce_changed), mock.patch.object(
                batch_markdown.common, "prune_driver_cookies"
            ):
                self.assertEqual(
                    batch_markdown.run_batch(
                        markdown_file,
                        output_dir,
                        prompt,
                        output_ext="md",
                        keep_browser=True,
                    ),
                    0,
                )
            self.assertEqual(seen, [2])

    def test_adopt_existing_avoids_browser_and_records_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "inputs"
            output_dir = root / "outputs"
            input_dir.mkdir()
            output_dir.mkdir()
            (input_dir / "one.pdf").write_bytes(b"pdf")
            (output_dir / "one.md").write_text(VALID_MARKDOWN, encoding="utf-8")
            prompt = root / "prompt.md"
            prompt.write_text("Create notes", encoding="utf-8")

            with mock.patch.object(batch_pdf.core, "LOG_FILE", root / "run.log"), mock.patch.object(
                batch_pdf.common, "bootstrap_session", side_effect=AssertionError("browser must not open")
            ):
                code = batch_pdf.run_batch(
                    input_dir,
                    output_dir,
                    prompt,
                    output_ext="md",
                    adopt_existing=True,
                )
            self.assertEqual(code, 0)
            manifest_data = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
            entry = manifest_data["items"]["one.pdf::md"]
            self.assertEqual(entry["status"], "completed")
            self.assertTrue(entry["adopted"])
            self.assertEqual(entry["attempts"], 0)


if __name__ == "__main__":
    unittest.main()
