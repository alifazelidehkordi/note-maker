from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from browser_runtime.downloads import (
    salvage_download,
    score_download_trigger,
    snapshot_directory,
)


class PatchrightDownloadTests(unittest.TestCase):
    def test_trigger_scoring_requires_expected_artifact_context(self):
        self.assertGreater(
            score_download_trigger(
                text="Download Markdown file",
                href="sandbox:/generated.md",
                expected_extensions={".md"},
            ),
            0,
        )
        self.assertEqual(
            score_download_trigger(
                text="Download apps",
                href="https://chatgpt.com/apps",
                expected_extensions={".md"},
            ),
            0,
        )
        self.assertEqual(
            score_download_trigger(
                text="Download OPML",
                expected_extensions={".md"},
            ),
            0,
        )

    def test_unrelated_control_does_not_inherit_format_from_assistant_context(self):
        context = "The generated Markdown artifact Lecture_Notes.md is ready."
        self.assertEqual(
            score_download_trigger(
                text="Coding Citation",
                context=context,
                expected_extensions={".md"},
            ),
            0,
        )
        self.assertGreater(
            score_download_trigger(
                text="Lecture_Notes.md",
                context=context,
                expected_extensions={".md"},
            ),
            0,
        )
        self.assertGreater(
            score_download_trigger(
                text="Download",
                context=context,
                expected_extensions={".md"},
            ),
            0,
        )
        self.assertGreater(
            score_download_trigger(
                text="Download",
                expected_extensions={".opml"},
            ),
            0,
        )

    def test_filesystem_salvage_detects_fresh_overwritten_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "result.md"
            target.write_text("# old\n", encoding="utf-8")
            before = snapshot_directory(root)
            started = time.time_ns()
            time.sleep(0.01)
            target.write_text("# new\n\n## Valid\n", encoding="utf-8")
            found = salvage_download(
                root,
                before,
                expected_extensions={".md"},
                started_at_ns=started,
                timeout=1,
                sleep_interval=0.01,
            )
            self.assertEqual(found, target.resolve())


if __name__ == "__main__":
    unittest.main()
