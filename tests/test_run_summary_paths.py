from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import batch_common


class RunSummaryPathTests(unittest.TestCase):
    def test_summary_is_run_specific_and_latest_copy_remains_compatible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            logs = root / "logs"
            with mock.patch.object(batch_common, "LOGS_DIR", logs):
                path = batch_common.write_batch_summary(
                    mode="pdf-md",
                    successes=3,
                    failures=[],
                    output_dir=root / "outputs",
                    extra={"run_id": "run-123"},
                )
            self.assertEqual(path, logs / "runs" / "run-123" / "summary.json")
            run_payload = json.loads(path.read_text(encoding="utf-8"))
            latest_payload = json.loads((logs / "last_batch_summary.json").read_text(encoding="utf-8"))
            pointer = json.loads((logs / "last_batch_summary.pointer.json").read_text(encoding="utf-8"))
            self.assertEqual(run_payload, latest_payload)
            self.assertEqual(pointer["run_id"], "run-123")
            self.assertEqual(pointer["summary"], str(path.resolve()))


if __name__ == "__main__":
    unittest.main()
