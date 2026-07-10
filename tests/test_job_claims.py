from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from parallel_runtime.claims import ClaimStore, JobClaim


class ClaimStoreTests(unittest.TestCase):
    def test_claim_is_atomic_heartbeat_owned_and_releasable(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ClaimStore(Path(tmp), stale_after=1.0)
            claim = store.try_acquire(
                "job-a", run_id="run-a", worker_id="worker-001", worker_pid=os.getpid()
            )
            self.assertIsNotNone(claim)
            self.assertIsNone(
                store.try_acquire(
                    "job-a", run_id="run-b", worker_id="worker-002", worker_pid=os.getpid()
                )
            )
            self.assertTrue(store.heartbeat(claim))
            wrong = JobClaim(
                job_key=claim.job_key,
                run_id=claim.run_id,
                worker_id=claim.worker_id,
                worker_pid=claim.worker_pid,
                token="wrong-token",
                path=claim.path,
                claimed_at=claim.claimed_at,
            )
            self.assertFalse(store.release(wrong))
            self.assertTrue(store.release(claim))
            self.assertFalse(claim.path.exists())

    def test_dead_stale_claim_is_reclaimed(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ClaimStore(Path(tmp), stale_after=1.0)
            first = store.try_acquire(
                "job-a", run_id="run-a", worker_id="worker-001", worker_pid=999_999_999
            )
            payload = json.loads(first.path.read_text(encoding="utf-8"))
            payload["heartbeat_at"] = "2000-01-01T00:00:00+00:00"
            first.path.write_text(json.dumps(payload), encoding="utf-8")
            old = time.time() - 5
            os.utime(first.path, (old, old))

            second = store.try_acquire(
                "job-a", run_id="run-b", worker_id="worker-002", worker_pid=os.getpid()
            )
            self.assertIsNotNone(second)
            self.assertNotEqual(first.token, second.token)
            self.assertEqual(second.run_id, "run-b")


if __name__ == "__main__":
    unittest.main()
