from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import tomli as tomllib

from note_maker.cli import build_parser, main
from note_maker.config import resolve_config
from note_maker.project import load_session_aliases, set_session_alias


class _Snapshot:
    def __init__(self, root: Path, snapshot_id: str = "anatomy-immutable-123") -> None:
        self.snapshot_id = snapshot_id
        self.path = root / snapshot_id
        self.path.mkdir(parents=True, exist_ok=True)
        self.created_at = "2026-09-05T00:00:00+00:00"
        self.portable = True
        self.auth_markers = ("local-auth-marker",)


class _SnapshotError(Exception):
    pass


class ProjectInitializationTests(unittest.TestCase):
    def test_init_persists_reusable_settings_and_dry_run_reuses_them(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            input_dir = root / "source files"
            output_dir = root / "generated notes"
            prompt = root / "prompt files" / "notes.md"
            input_dir.mkdir()
            output_dir.mkdir()
            prompt.parent.mkdir()
            prompt.write_text("prompt", encoding="utf-8")
            config = root / "note-maker.toml"

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "--config",
                        str(config),
                        "--json",
                        "init",
                        "--input-dir",
                        str(input_dir),
                        "--output-dir",
                        str(output_dir),
                        "--prompt",
                        str(prompt),
                        "--format",
                        "md",
                        "--browser-provider",
                        "patchright",
                        "--workers",
                        "2",
                    ]
                )
            self.assertEqual(code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["parallel_runs"], 2)
            self.assertEqual(payload["browser_provider"], "patchright")

            resolved = resolve_config("pdf", config_path=config, environ={})
            self.assertEqual(resolved.values["input_dir"], input_dir.resolve())
            self.assertEqual(resolved.values["output_dir"], output_dir.resolve())
            self.assertEqual(resolved.values["prompt"], prompt.resolve())
            self.assertEqual(resolved.values["output_ext"], "md")
            self.assertEqual(resolved.runtime.parallel_runs, 2)

            dry_run = io.StringIO()
            with redirect_stdout(dry_run):
                dry_code = main(["--config", str(config), "run", "pdf", "--dry-run"])
            self.assertEqual(dry_code, 0)
            dry_payload = json.loads(dry_run.getvalue())
            self.assertEqual(dry_payload["values"]["input_dir"], str(input_dir.resolve()))
            self.assertEqual(dry_payload["values"]["parallel_runs"], 2)

            text = config.read_text(encoding="utf-8").lower()
            for forbidden in ("password", "credential", "api_key", "access_token"):
                self.assertNotIn(forbidden, text)

    def test_init_refuses_to_overwrite_existing_configuration_without_force(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {}, clear=True):
            config = Path(tmp) / "note-maker.toml"
            original = "# keep me\n[runtime]\nparallel_runs = 1\n"
            config.write_text(original, encoding="utf-8")
            stderr = io.StringIO()
            with redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
                main(["--config", str(config), "init"])
            self.assertEqual(raised.exception.code, 2)
            self.assertIn("already exists", stderr.getvalue())
            self.assertEqual(config.read_text(encoding="utf-8"), original)


class SessionAliasTests(unittest.TestCase):
    def test_session_alias_resolves_for_existing_profile_snapshot_option(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "note-maker.toml"
            config.write_text(
                """
[runtime]
profile_snapshot = "anatomy.v1"

[commands.pdf]
input_dir = "inputs"

[sessions]
"anatomy.v1" = "anatomy-immutable-123"
""".strip()
                + "\n",
                encoding="utf-8",
            )
            resolved = resolve_config("pdf", config_path=config, environ={})
            self.assertEqual(resolved.runtime.profile_snapshot, "anatomy-immutable-123")

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "--config",
                        str(config),
                        "run",
                        "pdf",
                        "--profile-snapshot",
                        "anatomy.v1",
                        "--dry-run",
                    ]
                )
            self.assertEqual(code, 0)
            self.assertEqual(
                json.loads(stdout.getvalue())["values"]["profile_snapshot"],
                "anatomy-immutable-123",
            )

    def test_setting_session_alias_preserves_unrelated_toml_and_quotes_dotted_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "note-maker.toml"
            config.write_text(
                """
# preserved comment
[runtime]
parallel_runs = 2

[profiles.fast.runtime]
parallel_runs = 4

[sessions]
old = "snapshot-old"
""".strip()
                + "\n",
                encoding="utf-8",
            )
            set_session_alias(config, "anatomy.v1", "snapshot-new")
            text = config.read_text(encoding="utf-8")
            self.assertIn("# preserved comment", text)
            self.assertIn("[profiles.fast.runtime]", text)
            self.assertIn('"anatomy.v1" = "snapshot-new"', text)
            document = tomllib.loads(text)
            self.assertEqual(document["sessions"]["anatomy.v1"], "snapshot-new")
            self.assertEqual(document["profiles"]["fast"]["runtime"]["parallel_runs"], 4)

    def test_login_uses_dedicated_profile_then_persists_only_snapshot_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "note-maker.toml"
            config.write_text(
                """
[runtime]
parallel_runs = 1

[profiles.fast.runtime]
parallel_runs = 3

[sessions]
""".strip()
                + "\n",
                encoding="utf-8",
            )
            snapshot = _Snapshot(root / "snapshots")
            manager = object()
            calls: dict[str, object] = {}

            class FakeBootstrap:
                def __init__(self, *, profile_manager: object) -> None:
                    self.profile_manager = profile_manager

                def open_login_browser(self, profile_dir: Path, *, wait: bool = True) -> None:
                    calls["profile_dir"] = profile_dir
                    calls["wait"] = wait

                def create_snapshot(self, profile_dir: Path, *, name: str = "default") -> _Snapshot:
                    calls["snapshot_profile"] = profile_dir
                    calls["snapshot_name"] = name
                    return snapshot

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch(
                    "note_maker.cli._profile_services",
                    return_value=(manager, FakeBootstrap, _SnapshotError),
                ),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                code = main(
                    ["--config", str(config), "--json", "login", "--name", "anatomy.v1"]
                )

            self.assertEqual(code, 0)
            # Windows short-path (RUNNER~1) vs long-path (runneradmin): the
            # CLI resolves the profile dir, so compare resolved paths.
            self.assertEqual(
                Path(calls["profile_dir"]).resolve(),
                (root / "chrome_profile_login" / "anatomy.v1").resolve(),
            )
            self.assertIs(calls["wait"], True)
            self.assertEqual(calls["snapshot_name"], "anatomy.v1")
            self.assertIn("dedicated Chromium", stderr.getvalue())
            payload = json.loads(stdout.getvalue())
            self.assertFalse(payload["server_session_verified"])
            self.assertEqual(load_session_aliases(config)["anatomy.v1"], snapshot.snapshot_id)

            config_text = config.read_text(encoding="utf-8")
            self.assertIn("[profiles.fast.runtime]", config_text)
            self.assertNotIn("local-auth-marker", config_text)

    def test_profiles_list_and_inspect_are_read_only_views_of_aliases_and_snapshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "note-maker.toml"
            config.write_text('[sessions]\nanatomy = "anatomy-immutable-123"\n', encoding="utf-8")
            snapshot_root = root / "profile_templates"
            snapshot = _Snapshot(snapshot_root)

            class FakeManager:
                def __init__(self) -> None:
                    self.snapshot_root = snapshot_root

                def load_snapshot(self, reference: str | Path) -> _Snapshot:
                    if str(reference) != snapshot.snapshot_id:
                        raise _SnapshotError(f"missing snapshot: {reference}")
                    return snapshot

            with mock.patch(
                "note_maker.cli._profile_services",
                return_value=(FakeManager(), object, _SnapshotError),
            ):
                listed = io.StringIO()
                with redirect_stdout(listed):
                    list_code = main(["--config", str(config), "--json", "profiles", "list"])
                inspected = io.StringIO()
                with redirect_stdout(inspected):
                    inspect_code = main(
                        ["--config", str(config), "--json", "profiles", "inspect", "anatomy"]
                    )

            self.assertEqual(list_code, 0)
            list_payload = json.loads(listed.getvalue())
            self.assertEqual(list_payload["sessions"][0]["name"], "anatomy")
            self.assertTrue(list_payload["sessions"][0]["available"])
            self.assertTrue(list_payload["configuration_presets_are_separate"])

            self.assertEqual(inspect_code, 0)
            inspect_payload = json.loads(inspected.getvalue())
            self.assertEqual(inspect_payload["resolved_from_alias"], "anatomy")
            self.assertTrue(inspect_payload["authentication"]["cookie_markers_present"])
            self.assertFalse(inspect_payload["authentication"]["server_session_verified"])
            self.assertIn("not proof", inspect_payload["authentication"]["detail"])


class WorkflowDoctorTests(unittest.TestCase):
    def test_doctor_checks_selected_provider_paths_and_configured_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "inputs"
            output_dir = root / "outputs"
            prompt = root / "prompt.md"
            input_dir.mkdir()
            output_dir.mkdir()
            prompt.write_text("prompt", encoding="utf-8")
            config = root / "note-maker.toml"
            config.write_text(
                """
[runtime]
browser_provider = "patchright"
profile_snapshot = "anatomy"

[commands.pdf]
input_dir = "inputs"
output_dir = "outputs"
prompt = "prompt.md"

[sessions]
anatomy = "anatomy-immutable-123"
""".strip()
                + "\n",
                encoding="utf-8",
            )
            snapshot = _Snapshot(root / "profile_templates")

            class FakeManager:
                def load_snapshot(self, reference: str | Path) -> _Snapshot:
                    self.last_reference = reference
                    if str(reference) != snapshot.snapshot_id:
                        raise _SnapshotError(str(reference))
                    return snapshot

            stdout = io.StringIO()
            with (
                mock.patch(
                    "note_maker.cli.importlib.util.find_spec",
                    side_effect=lambda name: object() if name == "patchright" else None,
                ),
                mock.patch(
                    "note_maker.cli._profile_services",
                    return_value=(FakeManager(), object, _SnapshotError),
                ),
                redirect_stdout(stdout),
            ):
                code = main(["--config", str(config), "--json", "doctor", "--target", "pdf"])

            self.assertEqual(code, 0)
            payload = json.loads(stdout.getvalue())
            checks = {item["name"]: item for item in payload["checks"]}
            self.assertTrue(payload["ok"])
            self.assertIn("dependency:patchright", checks)
            self.assertNotIn("dependency:selenium", checks)
            self.assertTrue(checks["input"]["ok"])
            self.assertTrue(checks["prompt"]["ok"])
            self.assertTrue(checks["output"]["ok"])
            self.assertTrue(checks["session"]["ok"])
            self.assertIn("live server session not verified", checks["session"]["detail"])

    def test_help_distinguishes_configuration_presets_from_browser_sessions(self):
        help_text = " ".join(build_parser().format_help().split())
        self.assertIn("not a browser session", help_text)
        self.assertIn("profiles", help_text)
        self.assertIn("login", help_text)
        self.assertIn("init", help_text)


if __name__ == "__main__":
    unittest.main()
