from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import batch_markdown
import batch_pdf


class FakeDriver:
    pass


class DownloadContractTests(unittest.TestCase):
    @mock.patch.object(batch_pdf.common, "save_artifact_download")
    @mock.patch.object(batch_pdf.core, "resolve_download")
    @mock.patch.object(batch_pdf.core, "wait_until_idle")
    @mock.patch.object(batch_pdf.core, "send_message")
    @mock.patch.object(batch_pdf.core, "assistant_message_count", return_value=0)
    @mock.patch.object(batch_pdf.core, "wait_for_file_upload_complete")
    @mock.patch.object(batch_pdf.core, "attach_file")
    @mock.patch.object(batch_pdf.core, "snapshot_downloads", return_value={})
    @mock.patch.object(batch_pdf.core, "start_new_chat")
    def test_pdf_batch_passes_expected_markdown_extension(
        self,
        _start,
        _snapshot,
        _attach,
        _upload,
        _count,
        _send,
        _idle,
        resolve,
        _save,
    ):
        resolve.return_value = Path("/tmp/download.md")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            batch_pdf.time, "time_ns", return_value=123456
        ):
            input_path = Path(tmp) / "source.pdf"
            input_path.write_bytes(b"pdf")
            result = batch_pdf.process_one(
                FakeDriver(),
                "prompt",
                input_path,
                Path(tmp),
                None,
                download_timeout=17,
                save_diagnostics=False,
                output_ext="md",
            )

        self.assertTrue(result)
        resolve.assert_called_once_with(
            mock.ANY,
            {},
            expected_extensions={".md"},
            started_at_ns=123456,
            timeout=17,
        )

    @mock.patch.object(batch_markdown.common, "save_artifact_download")
    @mock.patch.object(batch_markdown.core, "resolve_download")
    @mock.patch.object(batch_markdown.core, "wait_until_idle")
    @mock.patch.object(batch_markdown.core, "send_message")
    @mock.patch.object(batch_markdown.core, "assistant_message_count", return_value=0)
    @mock.patch.object(batch_markdown.core, "wait_for_file_upload_complete")
    @mock.patch.object(batch_markdown.core, "attach_file")
    @mock.patch.object(batch_markdown.core, "snapshot_downloads", return_value={})
    @mock.patch.object(batch_markdown.core, "start_new_chat")
    def test_markdown_batch_passes_expected_opml_extension(
        self,
        _start,
        _snapshot,
        _attach,
        _upload,
        _count,
        _send,
        _idle,
        resolve,
        _save,
    ):
        resolve.return_value = Path("/tmp/download.opml")
        section = batch_markdown.MarkdownSection(index=1, title="Topic", text="## Topic\nBody")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            batch_markdown.time, "time_ns", return_value=654321
        ):
            section_file = Path(tmp) / "section.md"
            section_file.write_text(section.text, encoding="utf-8")
            result = batch_markdown.process_markdown_section(
                FakeDriver(),
                "prompt",
                section,
                section_file,
                Path(tmp),
                None,
                download_timeout=23,
                save_diagnostics=False,
                output_ext="opml",
            )

        self.assertTrue(result)
        resolve.assert_called_once_with(
            mock.ANY,
            {},
            expected_extensions={".opml"},
            started_at_ns=654321,
            timeout=23,
        )


if __name__ == "__main__":
    unittest.main()
