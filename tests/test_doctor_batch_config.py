from __future__ import annotations

"""Phase-2 item C: doctor surfaces batch-config health (rest/effort/inline)."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

CONFIG_TEMPLATE = (
    "[runtime]\n"
    'browser_provider = "patchright"\n'
    "rest_every = {rest_every}\n"
    'rest_state = "{rest_state}"\n'
    "\n[commands.pdf]\n"
    'input_dir = "{tmp}/inputs"\n'
    'output_dir = "{tmp}/outputs"\n'
    'output_ext = "md"\n'
)


def run_doctor(config_text, tmp, *, extra_env=None, strict=True):
    toml = Path(tmp) / "note-maker.toml"
    toml.write_text(config_text)
    (Path(tmp) / "inputs").mkdir(exist_ok=True)
    (Path(tmp) / "prompts").mkdir(exist_ok=True)
    (Path(tmp) / "inputs" / "01_a.md").write_text("# A\n\n## Explanation\n\nx. " * 10)
    (Path(tmp) / "prompts" / "prompt-mind-map.md").write_text(
        "# P\n\nProduce a downloadable markdown artifact."
    )
    env = dict(os.environ)
    env.pop("CHATGPT_REQUIRED_EFFORT", None)
    env.pop("NOTE_MAKER_INLINE_MARKDOWN", None)
    if extra_env:
        env.update(extra_env)
    args = [sys.executable, "-m", "note_maker.entrypoint", "--config", str(toml),
            "doctor", "--target", "pdf"]
    if strict:
        args.append("--strict")
    return subprocess.run(args, capture_output=True, text=True, env=env, cwd=tmp, timeout=180)


class DoctorBatchConfigTests(unittest.TestCase):
    def test_unwritable_rest_state_fails_strict_doctor(self):
        with tempfile.TemporaryDirectory() as tmp:
            readonly = Path(tmp) / "readonly"
            readonly.mkdir()
            readonly.chmod(0o500)
            try:
                config = CONFIG_TEMPLATE.format(
                    rest_every=30, rest_state=readonly / "rest.json", tmp=tmp)
                r = run_doctor(config, tmp)
            finally:
                readonly.chmod(0o700)
            self.assertNotEqual(r.returncode, 0, "bad rest_state must fail --strict doctor")
            self.assertIn("rest_schedule", r.stdout)
            self.assertIn("not writable", r.stdout)

    def test_valid_rest_schedule_passes_doctor(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = CONFIG_TEMPLATE.format(
                rest_every=30, rest_state=Path(tmp) / "rest.json", tmp=tmp)
            r = run_doctor(
                config, tmp,
                extra_env={"CHATGPT_REQUIRED_EFFORT": "high",
                           "NOTE_MAKER_INLINE_MARKDOWN": "1"},
            )
            self.assertIn("rest_schedule", r.stdout)
            self.assertIn("required_effort", r.stdout)
            self.assertIn("inline_markdown", r.stdout)

    def test_rest_state_without_interval_flags_a_problem(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = CONFIG_TEMPLATE.format(
                rest_every=0, rest_state=Path(tmp) / "rest.json", tmp=tmp)
            r = run_doctor(config, tmp, strict=False)
            self.assertIn("rest_schedule", r.stdout)
            self.assertIn("rest_every is 0", r.stdout)


if __name__ == "__main__":
    unittest.main()
