from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from process_liveness import pid_is_alive


class ProcessLivenessTests(unittest.TestCase):
    def test_current_process_is_alive(self):
        self.assertTrue(pid_is_alive(os.getpid()))

    def test_non_positive_pids_are_dead(self):
        self.assertFalse(pid_is_alive(0))
        self.assertFalse(pid_is_alive(-1))

    def test_implausibly_large_pid_is_dead(self):
        self.assertFalse(pid_is_alive(999_999_999))


if __name__ == "__main__":
    unittest.main()
