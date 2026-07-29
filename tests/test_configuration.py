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

    def test_markdown_requires_an_explicit_source(self):
        with self.assertRaisesRegex(ConfigError, "markdown_file is required"):
            resolve_config("markdown", environ={})


if __name__ == "__main__":
    unittest.main()
