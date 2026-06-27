from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_chatgpt_temporary_test as core


class DownloadDetectionTests(unittest.TestCase):
    def test_rejects_chatgpt_app_download_links(self):
        self.assertFalse(core.is_opml_download_trigger(text="Download apps"))
        self.assertFalse(core.is_opml_download_trigger(text="Get ChatGPT mobile"))

    def test_accepts_opml_download_links(self):
        self.assertTrue(core.is_opml_download_trigger(text="Download the OPML file"))
        self.assertTrue(core.is_opml_download_trigger(href="sandbox:/mnt/data/topic.opml"))
        self.assertTrue(core.is_opml_download_trigger(href="https://example.test/topic.opml"))

    def test_detects_opml_file_by_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "download"
            path.write_text('<?xml version="1.0"?><opml version="2.0"></opml>', encoding="utf-8")
            self.assertTrue(core.is_opml_download_file(path))

    def test_rejects_non_opml_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "download.html"
            path.write_text("<html>Get ChatGPT mobile</html>", encoding="utf-8")
            self.assertFalse(core.is_opml_download_file(path))

    def test_accepts_markdown_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Lecture_Notes.md"
            path.write_text("# Main Title\n\n## Explanation\nContent here.", encoding="utf-8")
            self.assertTrue(core.is_artifact_download_file(path))
            self.assertTrue(core.is_opml_download_file(path))  # alias

    def test_accepts_markdown_by_heading(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "notes.txt"
            path.write_text("# Title\nSome explanation", encoding="utf-8")
            self.assertTrue(core.is_artifact_download_file(path))


if __name__ == "__main__":
    unittest.main()
