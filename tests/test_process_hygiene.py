from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from parallel_runtime.claims import ClaimStore
from parallel_runtime.process_hygiene import cleanup_descendants, descendant_pids, pid_alive


class ProcessHygieneTests(unittest.TestCase):
    @unittest.skipUnless(Path("/proc").is_dir() and hasattr(os, "kill"), "requires Linux /proc")
    def test_orphan_candidate_descendant_is_cleaned(self):
        script = (
            "import subprocess,time,sys; "
            "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
            "print(child.pid, flush=True); time.sleep(30)"
        )
        parent = subprocess.Popen(
            [sys.executable, "-c", script],
            stdout=subprocess.PIPE,
            text=True,
        )
        try:
            child_pid = int(parent.stdout.readline().strip())
            deadline = time.time() + 3
            descendants = ()
            while time.time() < deadline:
                descendants = descendant_pids(parent.pid)
                if child_pid in descendants:
                    break
                time.sleep(0.02)
            self.assertIn(child_pid, descendants)
            parent.terminate()
            parent.wait(timeout=3)
            cleanup_descendants(parent.pid, known_descendants=descendants, grace_seconds=0.1)
            deadline = time.time() + 2
            while time.time() < deadline and pid_alive(child_pid):
                time.sleep(0.02)
            self.assertFalse(pid_alive(child_pid))
        finally:
            if parent.poll() is None:
                parent.kill()
                parent.wait(timeout=3)

    def test_stale_claim_recovery_does_not_remove_live_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ClaimStore(root, stale_after=1.0)
            live = store.try_acquire(
                "live-job",
                run_id="run-a",
                worker_id="worker-1",
                worker_pid=os.getpid(),
            )
            self.assertIsNotNone(live)
            stale_path = store._path("stale-job")
            stale_path.write_text(
                json.dumps(
                    {
                        "job_key": "stale-job",
                        "run_id": "old",
                        "worker_id": "old",
                        "worker_pid": 99999999,
                        "hostname": store.hostname,
                        "token": "stale",
                        "claimed_at": "2000-01-01T00:00:00+00:00",
                        "heartbeat_at": "2000-01-01T00:00:00+00:00",
                    }
                ),
                encoding="utf-8",
            )
            old = time.time() - 10
            os.utime(stale_path, (old, old))
            recovered = store.recover_stale()
            self.assertIn(stale_path, recovered)
            self.assertTrue(live.path.exists())
            store.release(live)


if __name__ == "__main__":
    unittest.main()
