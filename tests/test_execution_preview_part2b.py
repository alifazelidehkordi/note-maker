from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from note_maker.compat import activate_legacy_imports
from note_maker.entrypoint import main
from note_maker.preview import filter_input_files


VALID_MARKDOWN = (
    "# Generated Note\n\n## Explanation\n\n"
    + "Meaningful generated content for a completed manifest record. " * 5
    + "\n"
)


class ExecutionPreviewPart2BTests(unittest.TestCase):
    def test_filtering_is_ordered_case_sensitive_and_exclude_wins(self):
        files = [
            Path("Alpha.pdf"),
            Path("beta.pdf"),
            Path("Beta Notes.pdf"),
            Path("gamma.docx"),
        ]
        selected = filter_input_files(
            files,
            include_patterns=("*.pdf", "*.docx"),
            exclude_patterns=("Beta*",),
        )
        self.assertEqual([path.name for path in selected], ["Alpha.pdf", "beta.pdf", "gamma.docx"])

    def test_pdf_dry_run_is_real_plan_and_creates_no_output_runtime_or_manifest(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            input_dir = root / "Input Notes With Spaces"
            input_dir.mkdir()
            (input_dir / "Unit 01.pdf").write_bytes(b"one")
            (input_dir / "Unit 02.pdf").write_bytes(b"two")
            (input_dir / "Appendix.docx").write_bytes(b"appendix")
            prompt = root / "Prompt With Spaces.md"
            prompt.write_text("Create a downloadable Markdown note.", encoding="utf-8")
            output_dir = root / "Output Notes"
            runtime_dir = root / "Runtime Data"

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "run",
                        "pdf",
                        "--input-dir",
                        str(input_dir),
                        "--output-dir",
                        str(output_dir),
                        "--prompt",
                        str(prompt),
                        "--output-ext",
                        "md",
                        "--runtime-dir",
                        str(runtime_dir),
                        "--include",
                        "Unit *.pdf",
                        "--exclude",
                        "*02.pdf",
                        "--dry-run",
                    ]
                )

            self.assertEqual(code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["values"]["input_dir"], str(input_dir.resolve()))
            preview = payload["preview"]
            self.assertTrue(preview["read_only"])
            self.assertFalse(preview["browser_will_start"])
            self.assertFalse(preview["manifest_will_be_modified"])
            self.assertEqual(preview["selection"]["discovered_count"], 3)
            self.assertEqual(preview["selection"]["filtered_count"], 1)
            self.assertEqual(preview["selection"]["selected_count"], 1)
            self.assertEqual(preview["plan"]["runnable_count"], 1)
            self.assertEqual(preview["plan"]["jobs"][0]["label"], "Unit 01.pdf")
            self.assertEqual(preview["plan"]["jobs"][0]["action"], "run")
            self.assertFalse(output_dir.exists())
            self.assertFalse(runtime_dir.exists())
            self.assertFalse((output_dir / "manifest.json").exists())
            self.assertFalse((output_dir / ".note-maker-claims").exists())

    def test_pdf_preview_preserves_existing_manifest_bytes_and_resume_decision(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            input_dir = root / "inputs"
            output_dir = root / "outputs"
            input_dir.mkdir()
            output_dir.mkdir()
            source = input_dir / "complete.pdf"
            source.write_bytes(b"source")
            prompt = root / "prompt.md"
            prompt_text = "Create notes"
            prompt.write_text(prompt_text, encoding="utf-8")
            output = output_dir / "complete.md"
            output.write_text(VALID_MARKDOWN, encoding="utf-8")
            manifest_path = output_dir / "manifest.json"

            activate_legacy_imports()
            import batch_pdf  # type: ignore[import-not-found]
            import manifest  # type: ignore[import-not-found]
            from parallel_runtime.job_sources import build_file_candidates  # type: ignore[import-not-found]

            candidate = build_file_candidates(
                [source],
                input_dir=input_dir,
                output_dir=output_dir,
                prompt_path=prompt,
                prompt_hash=manifest.hash_text(prompt_text),
                output_ext="md",
                mode="pdf-md",
                model=None,
                key_builder=batch_pdf._job_key,
            )[0]
            store = manifest.ManifestStore(manifest_path)
            store.mark_completed(candidate.job, run_id="completed-run")
            before = manifest_path.read_bytes()

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "run",
                        "pdf",
                        "--input-dir",
                        str(input_dir),
                        "--output-dir",
                        str(output_dir),
                        "--prompt",
                        str(prompt),
                        "--output-ext",
                        "md",
                        "--manifest",
                        str(manifest_path),
                        "--dry-run",
                    ]
                )

            self.assertEqual(code, 0)
            payload = json.loads(stdout.getvalue())
            job = payload["preview"]["plan"]["jobs"][0]
            self.assertEqual(job["action"], "skip")
            self.assertEqual(job["reason"], "completed output is valid")
            self.assertEqual(payload["preview"]["plan"]["runnable_count"], 0)
            self.assertEqual(manifest_path.read_bytes(), before)

    def test_markdown_dry_run_does_not_materialize_section_files(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            markdown = root / "Lecture With Spaces.md"
            markdown.write_text(
                "# Lecture\n\n## Alpha\nFirst section.\n\n## Beta\nSecond section.\n",
                encoding="utf-8",
            )
            prompt = root / "prompt.md"
            prompt.write_text("Create notes", encoding="utf-8")
            output_dir = root / "markdown output"

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "run",
                        "markdown",
                        "--markdown-file",
                        str(markdown),
                        "--output-dir",
                        str(output_dir),
                        "--prompt",
                        str(prompt),
                        "--output-ext",
                        "md",
                        "--sections",
                        "2",
                        "--dry-run",
                    ]
                )

            self.assertEqual(code, 0)
            payload = json.loads(stdout.getvalue())
            preview = payload["preview"]
            self.assertEqual(preview["selection"]["detected_count"], 2)
            self.assertEqual(preview["selection"]["selected_count"], 1)
            self.assertFalse(preview["selection"]["section_files_will_be_materialized"])
            self.assertEqual(preview["plan"]["jobs"][0]["label"], "section 02 Beta")
            self.assertFalse(output_dir.exists())
            self.assertFalse((output_dir / "_md_sections").exists())
            self.assertFalse((output_dir / "manifest.json").exists())

    def test_real_pdf_run_applies_same_selectors_before_existing_batch_runtime(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            input_dir = root / "inputs"
            input_dir.mkdir()
            (input_dir / "one.pdf").write_bytes(b"1")
            (input_dir / "two.pdf").write_bytes(b"2")
            (input_dir / "three.docx").write_bytes(b"3")
            observed: list[str] = []

            activate_legacy_imports()
            import batch_common  # type: ignore[import-not-found]

            original = batch_common.collect_input_files

            def fake_cli(cleaned: list[str]) -> int:
                self.assertNotIn("--include", cleaned)
                self.assertNotIn("--exclude", cleaned)
                observed.extend(path.name for path in batch_common.collect_input_files(input_dir))
                return 0

            with mock.patch("note_maker.entrypoint.cli.main", side_effect=fake_cli):
                code = main(
                    [
                        "run",
                        "pdf",
                        "--input-dir",
                        str(input_dir),
                        "--include",
                        "*.pdf",
                        "--exclude",
                        "two*",
                    ]
                )

            self.assertEqual(code, 0)
            self.assertEqual(observed, ["one.pdf"])
            self.assertIs(batch_common.collect_input_files, original)

    def test_limit_is_applied_after_file_filters_in_preview(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            input_dir = root / "inputs"
            input_dir.mkdir()
            for name in ("a.pdf", "b.pdf", "c.pdf"):
                (input_dir / name).write_bytes(name.encode("utf-8"))
            prompt = root / "prompt.md"
            prompt.write_text("Create notes", encoding="utf-8")

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "run",
                        "pdf",
                        "--input-dir",
                        str(input_dir),
                        "--output-dir",
                        str(root / "outputs"),
                        "--prompt",
                        str(prompt),
                        "--output-ext",
                        "md",
                        "--include",
                        "*.pdf",
                        "--exclude",
                        "a*",
                        "--limit",
                        "1",
                        "--dry-run",
                    ]
                )

            self.assertEqual(code, 0)
            preview = json.loads(stdout.getvalue())["preview"]
            self.assertEqual(preview["selection"]["filtered_count"], 2)
            self.assertEqual(preview["selection"]["selected_count"], 1)
            self.assertEqual(preview["plan"]["jobs"][0]["label"], "b.pdf")

    def test_pdf_help_documents_selection_options(self):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = main(["run", "pdf", "--help"])
        self.assertEqual(code, 0)
        help_text = stdout.getvalue()
        self.assertIn("--include GLOB", help_text)
        self.assertIn("--exclude GLOB", help_text)
        self.assertIn("case-sensitive", help_text)

    def test_selectors_are_rejected_for_markdown_runs(self):
        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as raised:
            main(["run", "markdown", "--include", "*.md", "--dry-run"])
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
