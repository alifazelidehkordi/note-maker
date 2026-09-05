from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from note_maker.entrypoint import main


class IntegratedCliTests(unittest.TestCase):
    def test_preview_reports_invalid_sections_and_encoding_as_usage_errors(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            root = Path(directory)
            source = root / "lecture.md"
            source.write_text("# Lecture\n\n## Topic\nContent.\n", encoding="utf-8")
            prompt = root / "prompt.md"
            output = root / "output"
            arguments = [
                "run",
                "markdown",
                "--markdown-file",
                str(source),
                "--prompt",
                str(prompt),
                "--output-dir",
                str(output),
                "--dry-run",
            ]
            for content, extra, message in (
                (b"Create notes", ["--sections", "invalid"], "Markdown sections"),
                (b"\xff\xfe", [], "UTF-8 prompt"),
            ):
                with self.subTest(message=message):
                    prompt.write_bytes(content)
                    errors = io.StringIO()
                    with redirect_stderr(errors), self.assertRaises(SystemExit) as raised:
                        main(arguments + extra)
                    self.assertEqual(raised.exception.code, 2)
                    self.assertIn(message, errors.getvalue())
                    self.assertNotIn("Traceback", errors.getvalue())
                    self.assertFalse(output.exists())

    def test_project_preview_and_status_details_share_the_console(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            root = Path(directory)
            inputs = root / "inputs"
            inputs.mkdir()
            (inputs / "lecture.pdf").write_bytes(b"fixture")
            prompt = root / "prompt.md"
            prompt.write_text("Create notes", encoding="utf-8")
            config = root / "note-maker.toml"
            common = ["--config", str(config), "--json"]
            with redirect_stdout(io.StringIO()):
                self.assertEqual(
                    main(
                        common
                        + [
                            "init",
                            "--input-dir",
                            str(inputs),
                            "--prompt",
                            str(prompt),
                        ]
                    ),
                    0,
                )
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(common + ["run", "pdf", "--include", "*.pdf", "--dry-run"])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue())["preview"]["plan"]["runnable_count"], 1)

            snapshot = root / "status.json"
            snapshot.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "run_id": "integration",
                        "state": "completed",
                        "workers": [],
                        "counters": {},
                    }
                ),
                encoding="utf-8",
            )
            before = snapshot.read_bytes()
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    common
                    + [
                        "status",
                        "--details",
                        "--snapshot",
                        str(snapshot),
                        "--recent-events",
                        "0",
                    ]
                )
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue())["run_id"], "integration")
            self.assertEqual(snapshot.read_bytes(), before)
            self.assertFalse((root / "outputs").exists())

    def test_help_keeps_interactive_project_and_observability_features_visible(self):
        for arguments, expected in (
            (["--help"], ("interactive", "init", "profiles")),
            (["status", "--help"], ("--details", "--recent-events")),
            (["run", "pdf", "--help"], ("--include", "--exclude")),
        ):
            with self.subTest(arguments=arguments):
                output = io.StringIO()
                with redirect_stdout(output):
                    try:
                        code = main(arguments)
                    except SystemExit as exc:
                        code = exc.code
                self.assertEqual(code, 0)
                for text in expected:
                    self.assertIn(text, output.getvalue())
