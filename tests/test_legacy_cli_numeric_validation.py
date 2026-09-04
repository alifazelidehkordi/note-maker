from __future__ import annotations

import io
from contextlib import redirect_stderr
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import batch_markdown
import batch_pdf
import runtime_flags


class LegacyCliNumericValidationTests(unittest.TestCase):
    def test_invalid_pdf_batch_numeric_controls_exit_with_usage_error(self):
        cases = (
            ("--limit", "-1", "limit must not be negative"),
            ("--max-attempts", "0", "max_attempts must be at least 1"),
            ("--download-timeout", "0", "download_timeout must be at least 1"),
            ("--close-delay", "-1", "close_delay must not be negative"),
        )
        for flag, value, message in cases:
            with self.subTest(flag=flag), mock.patch.object(
                sys, "argv", ["batch_pdf.py", flag, value]
            ):
                stderr = io.StringIO()
                with redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
                    batch_pdf.main()
                self.assertEqual(raised.exception.code, 2)
                self.assertIn(message, stderr.getvalue())

    def test_invalid_markdown_batch_numeric_controls_exit_with_usage_error(self):
        cases = (
            ("--limit", "-1", "limit must not be negative"),
            (
                "--max-section-attempts",
                "0",
                "max_section_attempts must be at least 1",
            ),
            ("--download-timeout", "0", "download_timeout must be at least 1"),
            ("--close-delay", "-1", "close_delay must not be negative"),
        )
        for flag, value, message in cases:
            argv = ["batch_markdown.py", "--markdown-file", "lecture.md", flag, value]
            with self.subTest(flag=flag), mock.patch.object(sys, "argv", argv):
                stderr = io.StringIO()
                with redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
                    batch_markdown.main()
                self.assertEqual(raised.exception.code, 2)
                self.assertIn(message, stderr.getvalue())

    def test_zero_limit_and_zero_close_delay_remain_valid(self):
        pdf_args = batch_pdf.build_parser().parse_args(["--limit", "0", "--close-delay", "0"])
        runtime_flags.settings_from_namespace(pdf_args)
        self.assertEqual(pdf_args.limit, 0)
        self.assertEqual(pdf_args.close_delay, 0)

        markdown_args = batch_markdown.build_parser().parse_args(
            ["--markdown-file", "lecture.md", "--limit", "0", "--close-delay", "0"]
        )
        runtime_flags.settings_from_namespace(markdown_args)
        self.assertEqual(markdown_args.limit, 0)
        self.assertEqual(markdown_args.close_delay, 0)


if __name__ == "__main__":
    unittest.main()
