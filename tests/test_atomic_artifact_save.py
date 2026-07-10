from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import batch_common as common
from artifact_validation import ArtifactValidationError


VALID_MARKDOWN = """# Replacement Title

## Key Points

This replacement note has enough useful explanatory text to pass validation safely.
It includes additional content to ensure the minimum artifact size is exceeded.
"""

VALID_OPML_WITH_AMPERSAND = """<?xml version="1.0" encoding="UTF-8"?>
<opml version="2.0">
  <head><title>A & B</title></head>
  <body><outline text="A & B"><outline text="Child"/></outline></body>
</opml>
"""


class AtomicArtifactSaveTests(unittest.TestCase):
    def test_valid_markdown_replaces_existing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            downloaded = root / "downloaded.md"
            output = root / "notes" / "topic.md"
            output.parent.mkdir()
            output.write_text("old healthy output", encoding="utf-8")
            downloaded.write_text(VALID_MARKDOWN, encoding="utf-8")

            result = common.save_artifact_download(downloaded, output)

            self.assertTrue(result.valid)
            self.assertEqual(output.read_text(encoding="utf-8"), VALID_MARKDOWN)
            self.assertFalse(downloaded.exists())

    def test_invalid_markdown_preserves_existing_output_and_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            downloaded = root / "downloaded.md"
            output = root / "notes" / "topic.md"
            output.parent.mkdir()
            old_content = "old healthy output"
            output.write_text(old_content, encoding="utf-8")
            downloaded.write_text("# Incomplete\n", encoding="utf-8")

            with self.assertRaises(ArtifactValidationError) as caught:
                common.save_artifact_download(downloaded, output)

            self.assertEqual(output.read_text(encoding="utf-8"), old_content)
            rejected = caught.exception.rejected_path
            self.assertIsNotNone(rejected)
            self.assertTrue(rejected.exists())
            self.assertEqual(rejected.read_text(encoding="utf-8"), "# Incomplete\n")
            self.assertEqual(rejected.parent.name, "_rejected")

    def test_valid_opml_is_repaired_before_atomic_replace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            downloaded = root / "downloaded.opml"
            output = root / "topic.opml"
            output.write_text("old", encoding="utf-8")
            downloaded.write_text(VALID_OPML_WITH_AMPERSAND, encoding="utf-8")

            result = common.save_artifact_download(downloaded, output)

            self.assertTrue(result.valid)
            self.assertIn("A &amp; B", output.read_text(encoding="utf-8"))

    def test_final_replace_failure_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            downloaded = root / "downloaded.md"
            output = root / "topic.md"
            old_content = "old healthy output"
            output.write_text(old_content, encoding="utf-8")
            downloaded.write_text(VALID_MARKDOWN, encoding="utf-8")

            real_replace = common.os.replace

            def fail_final_replace(source, destination):
                if Path(destination) == output.resolve():
                    raise OSError("simulated atomic replace failure")
                return real_replace(source, destination)

            with patch.object(common.os, "replace", side_effect=fail_final_replace):
                with self.assertRaisesRegex(OSError, "simulated atomic replace failure"):
                    common.save_artifact_download(downloaded, output)

            self.assertEqual(output.read_text(encoding="utf-8"), old_content)
            self.assertFalse(any(output.parent.glob(".*.incoming.tmp")))

    def test_validation_can_be_explicitly_disabled_but_replace_remains_atomic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            downloaded = root / "downloaded.md"
            output = root / "topic.md"
            output.write_text("old", encoding="utf-8")
            downloaded.write_text("tiny", encoding="utf-8")

            result = common.save_artifact_download(downloaded, output, validate=False)

            self.assertTrue(result.valid)
            self.assertEqual(output.read_text(encoding="utf-8"), "tiny")

    def test_same_source_and_destination_is_validated_without_replacing(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "topic.md"
            output.write_text(VALID_MARKDOWN, encoding="utf-8")

            result = common.save_artifact_download(output, output)

            self.assertTrue(result.valid)
            self.assertEqual(output.read_text(encoding="utf-8"), VALID_MARKDOWN)


if __name__ == "__main__":
    unittest.main()
