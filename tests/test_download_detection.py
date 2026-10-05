from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_chatgpt_temporary_test as core
from browser_runtime.selectors import ASSISTANT_MESSAGE_SELECTOR


class FakeClickable:
    def __init__(self, text: str, *, href: str = "", context: str = "") -> None:
        self.text = text
        self._href = href
        self._context = context

    def is_displayed(self) -> bool:
        return True

    def get_attribute(self, name: str):
        return {
            "href": self._href,
            "title": "",
            "aria-label": "",
        }.get(name, "")

    def find_element(self, *_args):
        return type("Context", (), {"text": self._context})()


class FakeAssistant:
    def __init__(self, elements: list[FakeClickable]) -> None:
        self._elements = elements

    def find_elements(self, *_args):
        return list(self._elements)


class FakeDriver:
    def __init__(self, assistants: list[FakeAssistant]) -> None:
        self._assistants = assistants

    def find_elements(self, by, selector):
        if selector == ASSISTANT_MESSAGE_SELECTOR:
            return list(self._assistants)
        return []


class DownloadDetectionTests(unittest.TestCase):
    def test_rejects_chatgpt_app_download_links(self):
        self.assertFalse(core.is_opml_download_trigger(text="Download apps"))
        self.assertFalse(core.is_opml_download_trigger(text="Get ChatGPT mobile"))

    def test_generic_file_and_notes_words_are_not_enough(self):
        self.assertFalse(
            core.is_artifact_download_trigger(
                text="Download file",
                context="Your notes are ready",
                expected_extensions={".md"},
            )
        )

    def test_unrelated_button_does_not_inherit_artifact_type_from_message(self):
        context = "Your generated Markdown file is ready: Lecture_Notes.md"
        self.assertFalse(
            core.is_artifact_download_trigger(
                text="Coding Citation",
                context=context,
                expected_extensions={".md"},
            )
        )
        self.assertTrue(
            core.is_artifact_download_trigger(
                text="Lecture_Notes.md",
                context=context,
                expected_extensions={".md"},
            )
        )
        self.assertFalse(
            core.is_artifact_download_trigger(
                text="Download",
                context=context,
                expected_extensions={".md"},
            )
        )
        self.assertFalse(
            core.is_artifact_download_trigger(
                text="Download",
                expected_extensions={".opml"},
            )
        )
        self.assertTrue(
            core.is_artifact_download_trigger(
                text="Download",
                href="sandbox:/mnt/data/Lecture_Notes.md",
                context=context,
                expected_extensions={".md"},
            )
        )

    def test_multiple_generic_controls_are_rejected(self):
        context = "The Markdown artifact Lecture_Notes.md is ready."
        for label in ("Download", "Copy", "Share", "Coding Citation"):
            self.assertFalse(
                core.is_artifact_download_trigger(
                    text=label,
                    context=context,
                    expected_extensions={".md"},
                ),
                label,
            )

    def test_trigger_must_match_expected_extension(self):
        self.assertTrue(
            core.is_artifact_download_trigger(
                href="sandbox:/mnt/data/topic.opml",
                expected_extensions={".opml"},
            )
        )
        self.assertFalse(
            core.is_artifact_download_trigger(
                href="sandbox:/mnt/data/topic.opml",
                expected_extensions={".md"},
            )
        )
        self.assertTrue(
            core.is_artifact_download_trigger(
                href="sandbox:/mnt/data/topic.markdown",
                expected_extensions={".md"},
            )
        )

    def test_explicit_format_name_is_accepted(self):
        self.assertTrue(
            core.is_artifact_download_trigger(
                text="Download the Markdown document",
                expected_extensions={".md"},
            )
        )
        self.assertTrue(
            core.is_artifact_download_trigger(
                text="Download the OPML mind map",
                expected_extensions={".opml"},
            )
        )

    def test_file_suffix_is_type_specific(self):
        with tempfile.TemporaryDirectory() as tmp:
            markdown = Path(tmp) / "Lecture_Notes.md"
            markdown.write_text("# Main Title\n\n## Explanation\nContent here.", encoding="utf-8")
            opml = Path(tmp) / "map.opml"
            opml.write_text('<?xml version="1.0"?><opml version="2.0"></opml>', encoding="utf-8")

            self.assertTrue(core.is_artifact_download_file(markdown, {".md"}))
            self.assertFalse(core.is_artifact_download_file(markdown, {".opml"}))
            self.assertTrue(core.is_artifact_download_file(opml, {".opml"}))
            self.assertFalse(core.is_artifact_download_file(opml, {".md"}))

    def test_extensionless_file_is_detected_by_expected_content_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            opml = Path(tmp) / "download"
            opml.write_text('<?xml version="1.0"?><opml version="2.0"></opml>', encoding="utf-8")
            self.assertTrue(core.is_artifact_download_file(opml, {".opml"}))
            self.assertFalse(core.is_artifact_download_file(opml, {".md"}))

            markdown = Path(tmp) / "artifact"
            markdown.write_text("# Title\n\n## Details\nUseful content", encoding="utf-8")
            self.assertTrue(core.is_artifact_download_file(markdown, {".md"}))
            self.assertFalse(core.is_artifact_download_file(markdown, {".opml"}))

    def test_unsupported_expected_extension_is_rejected(self):
        with self.assertRaises(ValueError):
            core.normalize_expected_extensions({".pdf"})

    def test_unchanged_preexisting_file_is_not_selected(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(core, "DOWNLOAD_DIR", Path(tmp)):
            existing = Path(tmp) / "old.md"
            existing.write_text("# Old\n\n## Content\nExisting output", encoding="utf-8")
            before = core.snapshot_downloads()
            started_at_ns = time.time_ns()

            self.assertIsNone(
                core.newest_download(
                    before,
                    expected_extensions={".md"},
                    started_at_ns=started_at_ns,
                )
            )

    def test_new_wrong_extension_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(core, "DOWNLOAD_DIR", Path(tmp)):
            before = core.snapshot_downloads()
            started_at_ns = time.time_ns()
            wrong = Path(tmp) / "map.opml"
            wrong.write_text('<?xml version="1.0"?><opml version="2.0"></opml>', encoding="utf-8")

            self.assertIsNone(
                core.newest_download(
                    before,
                    expected_extensions={".md"},
                    started_at_ns=started_at_ns,
                )
            )

    def test_overwritten_same_filename_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(core, "DOWNLOAD_DIR", Path(tmp)):
            path = Path(tmp) / "result.md"
            path.write_text("# Old\n\n## Data\nOld", encoding="utf-8")
            before = core.snapshot_downloads()
            started_at_ns = time.time_ns()
            path.write_text("# New\n\n## Data\nA much longer replacement artifact", encoding="utf-8")
            now = time.time_ns()
            os.utime(path, ns=(now, now))

            selected = core.newest_download(
                before,
                expected_extensions={".md"},
                started_at_ns=started_at_ns,
            )
            self.assertEqual(selected, path.resolve())

    def test_new_file_with_preserved_old_mtime_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(core, "DOWNLOAD_DIR", Path(tmp)):
            before = core.snapshot_downloads()
            started_at_ns = time.time_ns()
            path = Path(tmp) / "copied.md"
            path.write_text("# Title\n\n## Data\nCopied old file", encoding="utf-8")
            old = started_at_ns - 10_000_000_000
            os.utime(path, ns=(old, old))

            self.assertIsNone(
                core.newest_download(
                    before,
                    expected_extensions={".md"},
                    started_at_ns=started_at_ns,
                )
            )

    def test_matching_candidate_is_preferred_over_wrong_type(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(core, "DOWNLOAD_DIR", Path(tmp)):
            before = core.snapshot_downloads()
            started_at_ns = time.time_ns()
            wrong = Path(tmp) / "newer.opml"
            wrong.write_text('<?xml version="1.0"?><opml version="2.0"></opml>', encoding="utf-8")
            right = Path(tmp) / "notes.md"
            right.write_text("# Notes\n\n## Details\nCorrect artifact", encoding="utf-8")
            now = time.time_ns()
            os.utime(right, ns=(now, now))
            os.utime(wrong, ns=(now + 1_000_000, now + 1_000_000))

            selected = core.newest_download(
                before,
                expected_extensions={".md"},
                started_at_ns=started_at_ns,
            )
            self.assertEqual(selected, right.resolve())

    def test_only_latest_assistant_message_is_scanned_first(self):
        old = FakeClickable("Download old Markdown", href="sandbox:/old.md")
        latest = FakeClickable("Download current Markdown", href="sandbox:/current.md")
        driver = FakeDriver([FakeAssistant([old]), FakeAssistant([latest])])
        marker = Path("/tmp/current.md")
        seen: list[FakeClickable] = []

        def fake_click(_driver, element, _before, **_kwargs):
            seen.append(element)
            return marker

        with mock.patch.object(core, "click_candidate_and_wait", side_effect=fake_click):
            result = core.click_new_download_link(
                driver,
                {},
                expected_extensions={".md"},
                started_at_ns=time.time_ns(),
            )

        self.assertEqual(result, marker)
        self.assertEqual(seen, [latest])
        self.assertNotIn(old, seen)


if __name__ == "__main__":
    unittest.main()
