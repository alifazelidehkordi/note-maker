from __future__ import annotations

import io
import json
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from note_maker.cli import (
    _execute_resolved,
    _interactive,
    _validate_resolved_run,
    build_parser,
    main,
)
from note_maker.config import ConfigError, resolve_config
from note_maker.interactive import (
    InteractiveCancelled,
    InteractiveInputError,
    build_interactive_plan,
    discover_prompt_files,
    parse_selection,
    validate_output_dir,
)


class UnifiedCliTests(unittest.TestCase):
    def test_parser_keeps_existing_run_command_and_adds_interactive(self):
        parser = build_parser()
        existing = parser.parse_args(["run", "pdf", "--input-dir", "inputs"])
        interactive = parser.parse_args(["interactive", "--dry-run"])
        self.assertEqual((existing.command, existing.run_command), ("run", "pdf"))
        self.assertEqual(existing.input_dir, Path("inputs"))
        self.assertEqual(interactive.command, "interactive")
        self.assertTrue(interactive.dry_run)

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

    def test_selection_parser_supports_all_lists_and_ranges(self):
        self.assertEqual(parse_selection("", 4), [0, 1, 2, 3])
        self.assertEqual(parse_selection("all", 3), [0, 1, 2])
        self.assertEqual(parse_selection("1,3-4", 4), [0, 2, 3])
        with self.assertRaisesRegex(InteractiveInputError, "between 1 and 3"):
            parse_selection("4", 3)

    def test_prompt_discovery_and_output_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            config_root = root / "config-root"
            (project / "prompts").mkdir(parents=True)
            (config_root / "prompts").mkdir(parents=True)
            project_prompt = project / "prompts" / "project.md"
            custom_prompt = config_root / "prompts" / "custom.txt"
            ignored = config_root / "prompts" / "ignored.json"
            project_prompt.write_text("project prompt", encoding="utf-8")
            custom_prompt.write_text("custom prompt", encoding="utf-8")
            ignored.write_text("{}", encoding="utf-8")
            config = config_root / "note-maker.toml"
            config.write_text("", encoding="utf-8")

            prompts = discover_prompt_files(
                cwd=root,
                project_root=project,
                config_path=config,
                default_prompt=custom_prompt,
            )
            self.assertIn(project_prompt.resolve(), prompts)
            self.assertIn(custom_prompt.resolve(), prompts)
            self.assertNotIn(ignored.resolve(), prompts)

            invalid_output = root / "not-a-directory"
            invalid_output.write_text("occupied", encoding="utf-8")
            with self.assertRaisesRegex(InteractiveInputError, "not a directory"):
                validate_output_dir(invalid_output)

    def test_run_validation_rejects_empty_input_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs = root / "inputs"
            inputs.mkdir()
            prompt = root / "prompt.md"
            prompt.write_text("Create a downloadable note.", encoding="utf-8")
            resolved = resolve_config(
                "pdf",
                cli_overrides={
                    "input_dir": inputs,
                    "prompt": prompt,
                    "output_dir": root / "outputs",
                },
                environ={},
                cwd=root,
            )
            with self.assertRaisesRegex(ConfigError, "No supported PDF, DOCX, or MD"):
                _validate_resolved_run(resolved)

    def test_interactive_plan_uses_profile_and_selected_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs = root / "inputs"
            prompts = root / "prompts"
            inputs.mkdir()
            prompts.mkdir()
            first = inputs / "first.pdf"
            second = inputs / "second.docx"
            first.write_bytes(b"pdf")
            second.write_bytes(b"docx")
            default_prompt = prompts / "default.md"
            default_prompt.write_text("Create a downloadable Markdown note.", encoding="utf-8")
            config = root / "note-maker.toml"
            config.write_text(
                """
[commands.pdf]
input_dir = "inputs"
output_dir = "outputs"
prompt = "prompts/default.md"
output_ext = "md"

[profiles.fast.runtime]
browser_provider = "patchright"
parallel_runs = 2
""".strip()
                + "\n",
                encoding="utf-8",
            )
            answers = iter(["", "2", "", "", "", "", "", "", "y"])
            transcript = io.StringIO()

            plan = build_interactive_plan(
                config_path=config,
                profile="fast",
                input_fn=lambda _prompt: next(answers),
                output=transcript,
                cwd=root,
                project_root=root,
            )

            self.assertEqual(plan.resolved.command, "pdf")
            self.assertEqual(plan.input_files, (second.resolve(),))
            self.assertEqual(plan.resolved.values["prompt"], default_prompt.resolve())
            self.assertEqual(plan.resolved.values["output_dir"], (root / "outputs").resolve())
            self.assertEqual(plan.resolved.runtime.browser_provider, "patchright")
            self.assertEqual(plan.resolved.runtime.parallel_runs, 2)
            self.assertIn("Resolved configuration", transcript.getvalue())
            self.assertIn(str(default_prompt.resolve()), transcript.getvalue())

    def test_keyboard_interrupt_and_cancel_command_are_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(InteractiveCancelled):
                build_interactive_plan(
                    config_path=None,
                    profile=None,
                    input_fn=lambda _prompt: (_ for _ in ()).throw(KeyboardInterrupt),
                    output=io.StringIO(),
                    cwd=root,
                    project_root=root,
                )

        args = types.SimpleNamespace(config=None, profile=None, dry_run=False)
        output = io.StringIO()
        with (
            patch("note_maker.cli.build_interactive_plan", side_effect=InteractiveCancelled),
            redirect_stdout(output),
        ):
            code = _interactive(args)
        self.assertEqual(code, 130)
        self.assertIn("Cancelled", output.getvalue())

    def test_selected_files_reach_existing_pdf_batch_pipeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs = root / "inputs"
            inputs.mkdir()
            first = inputs / "first.pdf"
            second = inputs / "second.docx"
            first.write_bytes(b"pdf")
            second.write_bytes(b"docx")
            prompt = root / "prompt.md"
            prompt.write_text("Create a downloadable note.", encoding="utf-8")
            resolved = resolve_config(
                "pdf",
                cli_overrides={
                    "input_dir": inputs,
                    "prompt": prompt,
                    "output_dir": root / "outputs",
                    "output_ext": "md",
                },
                environ={},
                cwd=root,
            )
            captured: dict[str, object] = {}

            def fake_run_batch(**kwargs: object) -> int:
                execution_input = kwargs["input_dir"]
                self.assertIsInstance(execution_input, Path)
                assert isinstance(execution_input, Path)
                captured.update(kwargs)
                captured["files"] = sorted(path.name for path in execution_input.iterdir())
                return 0

            fake_module = types.ModuleType("batch_pdf")
            fake_module.run_batch = fake_run_batch  # type: ignore[attr-defined]
            with patch.dict(sys.modules, {"batch_pdf": fake_module}):
                code = _execute_resolved(resolved, input_files=[second])

            self.assertEqual(code, 0)
            self.assertEqual(captured["files"], ["second.docx"])
            self.assertEqual(captured["prompt_path"], prompt.resolve())
            self.assertEqual(captured["output_dir"], (root / "outputs").resolve())
            self.assertEqual(captured["output_ext"], "md")


if __name__ == "__main__":
    unittest.main()
