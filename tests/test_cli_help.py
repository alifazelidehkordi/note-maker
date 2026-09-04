from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout

from note_maker.cli import main


class CliHelpTests(unittest.TestCase):
    def test_top_level_help_exits_successfully_and_lists_primary_commands(self):
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            main(["--help"])

        self.assertEqual(raised.exception.code, 0)
        help_text = output.getvalue()
        for command in ("doctor", "status", "validate", "config", "run"):
            with self.subTest(command=command):
                self.assertIn(command, help_text)

    def test_run_help_exits_successfully_and_lists_batch_modes(self):
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            main(["run", "--help"])

        self.assertEqual(raised.exception.code, 0)
        help_text = output.getvalue()
        self.assertIn("pdf", help_text)
        self.assertIn("markdown", help_text)


if __name__ == "__main__":
    unittest.main()
