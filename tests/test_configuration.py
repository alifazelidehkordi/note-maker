from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from note_maker.config import ConfigError, resolve_config


class ConfigurationTests(unittest.TestCase):
    def test_file_profile_environment_and_cli_precedence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "note-maker.toml"
            config.write_text(
                """
[runtime]
browser_provider = "selenium"
parallel_runs = 1

[commands.pdf]
input_dir = "documents"
output_dir = "generated"
output_ext = "opml"

[profiles.fast.runtime]
browser_provider = "patchright"
parallel_runs = 4

[profiles.fast.commands.pdf]
save_diagnostics = true
""".strip()
                + "\n",
                encoding="utf-8",
            )

            resolved = resolve_config(
                "pdf",
                config_path=config,
                profile="fast",
                environ={"NOTE_MAKER_OUTPUT_EXT": "md", "NOTE_MAKER_PARALLEL_RUNS": "2"},
                cli_overrides={"parallel_runs": 3},
            )

            self.assertEqual(resolved.runtime.browser_provider, "patchright")
            self.assertEqual(resolved.runtime.parallel_runs, 3)
            self.assertEqual(resolved.values["output_ext"], "md")
            self.assertTrue(resolved.values["save_diagnostics"])
            self.assertEqual(resolved.values["input_dir"], (root / "documents").resolve())
            self.assertEqual(resolved.values["output_dir"], (root / "generated").resolve())

    def test_missing_profile_fails_with_available_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "note-maker.toml"
            config.write_text("[profiles.safe.runtime]\nparallel_runs = 1\n", encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "available: safe"):
                resolve_config("pdf", config_path=config, profile="missing", environ={})

    def test_invalid_runtime_value_uses_shared_validator(self):
        with self.assertRaisesRegex(ConfigError, "parallel_runs must not exceed"):
            resolve_config(
                "pdf",
                cli_overrides={"parallel_runs": 99},
                environ={},
            )

    def test_invalid_runtime_type_is_reported_as_config_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "note-maker.toml"
            config.write_text('[runtime]\nparallel_runs = "4"\n', encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "Invalid runtime configuration"):
                resolve_config("pdf", config_path=config, environ={})

    def test_markdown_requires_an_explicit_source(self):
        with self.assertRaisesRegex(ConfigError, "markdown_file is required"):
            resolve_config("markdown", environ={})

    def test_string_boolean_is_rejected_instead_of_becoming_truthy(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "note-maker.toml"
            config.write_text('[commands.pdf]\noverwrite = "false"\n', encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "overwrite must be a boolean"):
                resolve_config("pdf", config_path=config, environ={})

    def test_unknown_configuration_key_is_rejected(self):
        with self.assertRaisesRegex(ConfigError, "Unknown configuration key: paralell_runs"):
            resolve_config(
                "pdf",
                cli_overrides={"paralell_runs": 4},
                environ={},
            )

    def test_invalid_command_numeric_ranges_are_rejected(self):
        cases = (
            ("limit", 0, "limit must be at least 1"),
            ("max_attempts", 0, "max_attempts must be at least 1"),
            ("download_timeout", 0, "download_timeout must be at least 1"),
            ("close_delay", -1, "close_delay must not be negative"),
        )
        for key, value, message in cases:
            with self.subTest(key=key), self.assertRaisesRegex(ConfigError, message):
                resolve_config("pdf", cli_overrides={key: value}, environ={})

    def test_invalid_output_extension_is_rejected(self):
        with self.assertRaisesRegex(ConfigError, "output_ext must be one of"):
            resolve_config("pdf", cli_overrides={"output_ext": "txt"}, environ={})

    def test_output_extension_keeps_legacy_normalization(self):
        resolved = resolve_config("pdf", cli_overrides={"output_ext": ".MD"}, environ={})
        self.assertEqual(resolved.values["output_ext"], "md")

    def test_all_documented_command_environment_overrides_are_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resolved = resolve_config(
                "markdown",
                environ={
                    "NOTE_MAKER_MARKDOWN_FILE": "lecture.md",
                    "NOTE_MAKER_MAX_SECTION_ATTEMPTS": "5",
                    "NOTE_MAKER_SECTIONS": "1,3-4",
                    "NOTE_MAKER_CHROME_PROFILE_DIR": "browser-profile",
                },
                cwd=root,
            )
            self.assertEqual(resolved.values["markdown_file"], (root / "lecture.md").resolve())
            self.assertEqual(resolved.values["max_section_attempts"], 5)
            self.assertEqual(resolved.values["sections"], "1,3-4")
            self.assertEqual(
                resolved.values["chrome_profile_dir"],
                (root / "browser-profile").resolve(),
            )

            pdf = resolve_config(
                "pdf",
                environ={"NOTE_MAKER_MAX_ATTEMPTS": "6"},
                cwd=root,
            )
            self.assertEqual(pdf.values["max_attempts"], 6)


if __name__ == "__main__":
    unittest.main()
