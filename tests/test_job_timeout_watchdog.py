from __future__ import annotations

from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from parallel_runtime.coordinator import ParallelCoordinator, _WorkerSlot
from parallel_runtime.models import RunConfig


class _AliveProcess:
    pid = 12345
    exitcode = None

    def is_alive(self) -> bool:
        return True


class JobTimeoutWatchdogTests(unittest.TestCase):
    def _config(self, root: Path, *, job_timeout: float) -> RunConfig:
        return RunConfig(
            run_id="watchdog-test",
            manifest_path=root / "manifest.json",
            claims_dir=root / "claims",
            worker_count=1,
            executor_path="parallel_runtime.executors:PdfJobExecutor",
            heartbeat_interval=1.0,
            worker_timeout=10.0,
            job_timeout=job_timeout,
        )

    @staticmethod
    def _slot(*, job_started_at: float) -> _WorkerSlot:
        return _WorkerSlot(
            worker_id="worker-001",
            generation=1,
            process=_AliveProcess(),
            command_queue=object(),
            started_at=90.0,
            last_heartbeat=100.0,
            last_manifest_heartbeat=100.0,
            ready=True,
            current_job=SimpleNamespace(key="file-22"),
            job_started_at=job_started_at,
        )

    def test_run_config_round_trip_preserves_job_timeout(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = self._config(Path(temp_dir), job_timeout=123.5)
            restored = RunConfig.from_payload(config.to_payload())

        self.assertEqual(restored.job_timeout, 123.5)

    def test_negative_job_timeout_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "job_timeout"):
                self._config(Path(temp_dir), job_timeout=-1.0)

    def test_busy_worker_times_out_even_with_fresh_heartbeat(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            coordinator = object.__new__(ParallelCoordinator)
            coordinator.config = self._config(Path(temp_dir), job_timeout=5.0)
            slot = self._slot(job_started_at=90.0)
            coordinator.slots = {slot.worker_id: slot}
            lost: list[tuple[_WorkerSlot, str]] = []
            coordinator._handle_lost_worker = lambda worker, reason: lost.append((worker, reason))
            coordinator._recycle_worker = lambda _worker: None

            with patch("parallel_runtime.coordinator.time.monotonic", return_value=100.0):
                coordinator._check_workers()

        self.assertEqual(len(lost), 1)
        self.assertIs(lost[0][0], slot)
        self.assertEqual(lost[0][1], "job timed out after 5.0s")

    def test_zero_job_timeout_disables_watchdog(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            coordinator = object.__new__(ParallelCoordinator)
            coordinator.config = self._config(Path(temp_dir), job_timeout=0.0)
            slot = self._slot(job_started_at=1.0)
            coordinator.slots = {slot.worker_id: slot}
            lost: list[tuple[_WorkerSlot, str]] = []
            coordinator._handle_lost_worker = lambda worker, reason: lost.append((worker, reason))
            coordinator._recycle_worker = lambda _worker: None

            with patch("parallel_runtime.coordinator.time.monotonic", return_value=100.0):
                coordinator._check_workers()

        self.assertEqual(lost, [])


if __name__ == "__main__":
    unittest.main()
