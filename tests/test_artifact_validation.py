from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from artifact_validation import validate_artifact, validate_markdown, validate_opml


VALID_MARKDOWN = """# Main Title

## Key Points

This is a complete generated note with enough explanatory content to pass the minimum size requirement.
It contains a second sentence so the artifact is clearly more than a placeholder or download link.
"""

VALID_OPML = """<?xml version="1.0" encoding="UTF-8"?>
<opml version="2.0">
  <head><title>Topic</title></head>
  <body><outline text="Root"><outline text="Child"/></outline></body>
</opml>
"""


class ArtifactValidationTests(unittest.TestCase):
    def test_accepts_valid_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "notes.md"
            path.write_text(VALID_MARKDOWN, encoding="utf-8")
            result = validate_markdown(path)
            self.assertTrue(result.valid, result.errors)
            self.assertEqual(result.detected_type, "markdown")

    def test_rejects_markdown_without_h1(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "notes.md"
            path.write_text("## Key Points\n\n" + ("Content " * 30), encoding="utf-8")
            result = validate_markdown(path)
            self.assertFalse(result.valid)
            self.assertIn("Missing H1 title", result.errors)

    def test_rejects_markdown_without_h2(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "notes.md"
            path.write_text("# Title\n\n" + ("Content " * 30), encoding="utf-8")
            result = validate_markdown(path)
            self.assertFalse(result.valid)
            self.assertIn("Missing level-2 heading", result.errors)

    def test_rejects_assistant_apology(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "notes.md"
            path.write_text(
                "# Result\n\n## Status\n\nI'm sorry, I can't create the requested file.\n" + ("x" * 100),
                encoding="utf-8",
            )
            result = validate_markdown(path)
            self.assertFalse(result.valid)
            self.assertTrue(any("assistant error" in error for error in result.errors))

    def test_rejects_html_page_saved_as_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "notes.md"
            path.write_text(
                "<html><body><h1># Title</h1><h2>## Topic</h2>" + ("x" * 120) + "</body></html>",
                encoding="utf-8",
            )
            result = validate_markdown(path)
            self.assertFalse(result.valid)
            self.assertTrue(any("HTML page" in error for error in result.errors))

    def test_rejects_too_small_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "notes.md"
            path.write_text("# T\n\n## K\n\nBody", encoding="utf-8")
            result = validate_markdown(path)
            self.assertFalse(result.valid)
            self.assertTrue(any("minimum" in error for error in result.errors))

    def test_accepts_valid_opml(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "topic.opml"
            path.write_text(VALID_OPML, encoding="utf-8")
            result = validate_opml(path)
            self.assertTrue(result.valid, result.errors)
            self.assertEqual(result.detected_type, "opml")

    def test_repairs_unescaped_opml_attributes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "topic.opml"
            path.write_text(
                '<?xml version="1.0"?><opml version="2.0"><head><title>A & B</title></head>'
                '<body><outline text="A & B"/></body></opml>',
                encoding="utf-8",
            )
            result = validate_opml(path)
            self.assertTrue(result.valid, result.errors)
            self.assertIn("A &amp; B", path.read_text(encoding="utf-8"))

    def test_rejects_opml_without_outline(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "topic.opml"
            path.write_text(
                '<?xml version="1.0"?><opml version="2.0"><head/><body/></opml>',
                encoding="utf-8",
            )
            result = validate_opml(path)
            self.assertFalse(result.valid)
            self.assertTrue(any("outline" in error.lower() for error in result.errors))

    def test_dispatches_by_expected_extension_not_temporary_suffix(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".download.incoming.tmp"
            path.write_text(VALID_MARKDOWN, encoding="utf-8")
            result = validate_artifact(path, {".md"})
            self.assertTrue(result.valid, result.errors)
            self.assertEqual(result.detected_type, "markdown")

    def test_rejects_ambiguous_expected_artifact_types(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact.tmp"
            path.write_text(VALID_MARKDOWN, encoding="utf-8")
            result = validate_artifact(path, {".md", ".opml"})
            self.assertFalse(result.valid)
            self.assertTrue(any("more than one" in error for error in result.errors))

    def test_rejects_unsupported_expected_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact.tmp"
            path.write_text("content", encoding="utf-8")
            result = validate_artifact(path, {".pdf"})
            self.assertFalse(result.valid)
            self.assertTrue(any("Unsupported" in error for error in result.errors))


if __name__ == "__main__":
    unittest.main()
