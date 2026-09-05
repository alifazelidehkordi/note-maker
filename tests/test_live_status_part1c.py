from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from note_maker.cli import main
from parallel_runtime.status import (
    StatusSnapshotStore,
    compute_counters,
    install_manifest_status_tracking,
    read_status_snapshot,
    stage_elapsed_seconds,
)


class StatusSnapshotTests(unittest.TestCase):
    def test_atomic_store_writes_run_specific_and_latest_snapshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs = Path(tmp) / "logs"
            store = StatusSnapshotStore("run-status", logs_dir=logs)
            published = store.publish(
                {
                    "state": "running",
                    "counters": {"total": 2, "running": 1, "queued": 1},
                    "workers": [],
                }
            )

            self.assertEqual(read_status_snapshot(store.run_path), published)
            self.assertEqual(read_status_snapshot(store.latest_path), published)
            self.assertEqual(list(store.run_path.parent.glob("*.tmp")), [])
            self.assertEqual(list(logs.glob("*.tmp")), [])

    def test_counters_form_exact_partition_and_dedupe_external_success(self):
        counters = compute_counters(
            total=9,
            initial_succeeded=2,
            initial_skipped=1,
            succeeded=("a", "b"),
            externally_completed=("b", "c"),
            failed={"d": "failed"},
            running=("e",),
            adopted=1,
            resumed_completed=1,
            runnable=6,
        )

        self.assertEqual(counters["succeeded"], 5)
        self.assertEqual(counters["failed"], 1)
        self.assertEqual(counters["skipped"], 1)
        self.assertEqual(counters["running"], 1)
        self.assertEqual(counters["queued"], 1)
        self.assertEqual(counters["completed"] + counters["remaining"], counters["total"])
        self.assertEqual(
            counters["succeeded"]
            + counters["failed"]
            + counters["skipped"]
            + counters["running"]
            + counters["queued"],
            counters["total"],
        )

    def test_started_stage_elapsed_time_advances_without_fabricated_eta(self):
        stage = {
            "phase": "started",
            "stage_started_at": "2026-09-05T12:00:00+00:00",
            "elapsed_seconds": 2.0,
        }
        elapsed = stage_elapsed_seconds(
            stage,
            now=datetime(2026, 9, 5, 12, 0, 5, tzinfo=timezone.utc),
        )
        self.assertEqual(elapsed, 5.0)
        self.assertNotIn("eta", stage)
        self.assertNotIn("percent", stage)


class ManifestStatusHookTests(unittest.TestCase):
    def test_plan_baseline_is_persisted_once_and_snapshot_is_exact(self):
        from manifest import ManifestStore

        install_manifest_status_tracking()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / "manifest.json"
            store = ManifestStore(manifest_path)
            store.register_run(
                "run-plan",
                mode="pdf-md",
                planned_jobs=2,
                parallel_runs=2,
                browser_provider="patchright",
            )
            plan = SimpleNamespace(
                run_id="run-plan",
                candidates=(1, 2, 3, 4, 5),
                runnable=(1, 2),
                skipped={
                    "already-done": "completed output is valid",
                    "filtered": "not selected",
                },
                adopted=("adopted",),
                completed_skip_count=1,
                initial_successes=2,
                transitions=(),
            )
            with mock.patch(
                "parallel_runtime.status.default_logs_dir", return_value=root / "logs"
            ):
                store.apply_plan(plan)

            run = store.get_run("run-plan")
            self.assertIsNotNone(run)
            assert run is not None
            self.assertEqual(run["total_jobs"], 5)
            self.assertEqual(run["runnable_jobs"], 2)
            self.assertEqual(run["initial_successes"], 2)
            self.assertEqual(run["completed_skip_count"], 1)
            self.assertEqual(run["skipped_count"], 1)
            self.assertEqual(run["adopted_count"], 1)

            snapshot = read_status_snapshot(root / "logs" / "last_status.json")
            counters = dict(snapshot["counters"])
            self.assertEqual(counters["total"], 5)
            self.assertEqual(counters["succeeded"], 2)
            self.assertEqual(counters["skipped"], 1)
            self.assertEqual(counters["queued"], 2)
            self.assertEqual(counters["running"], 0)


class _FakeQueue:
    def put(self, _value) -> None:
        return None

    def close(self) -> None:
        return None

    def join_thread(self) -> None:
        return None


class _FakeContext:
    def Queue(self):
        return _FakeQueue()


class _FakeProcess:
    pid = 4242
    exitcode = None

    def is_alive(self) -> bool:
        return True

    def close(self) -> None:
        return None


class CoordinatorStatusTests(unittest.TestCase):
    def test_stage_event_updates_live_worker_snapshot_and_stale_generation_is_ignored(self):
        from manifest import ManifestCoordinator
        from parallel_runtime.coordinator import ParallelCoordinator, _WorkerSlot
        from parallel_runtime.event_bus import EventKind, WorkerEvent
        from parallel_runtime.models import ExecutionJob, RunConfig

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.pdf"
            prompt = root / "prompt.md"
            source.write_bytes(b"source")
            prompt.write_text("prompt", encoding="utf-8")
            job = ExecutionJob(
                key="source",
                source=source,
                source_hash="source-hash",
                prompt_path=prompt,
                prompt_hash="prompt-hash",
                output=root / "source.md",
                expected_extensions=(".md",),
                mode="pdf-md",
            )
            manifest = ManifestCoordinator(root / "manifest.json")
            manifest.register_run(
                "run-live",
                mode="pdf-md",
                planned_jobs=1,
                parallel_runs=1,
                browser_provider="patchright",
            )
            status_store = StatusSnapshotStore("run-live", logs_dir=root / "logs")
            config = RunConfig(
                run_id="run-live",
                manifest_path=root / "manifest.json",
                claims_dir=root / "claims",
                worker_count=1,
                executor_path="parallel_runtime.testing:ScriptedExecutor",
                heartbeat_interval=1.0,
                worker_timeout=5.0,
                worker_ready_timeout=5.0,
                startup_stagger=0.0,
            )
            coordinator = ParallelCoordinator(
                config,
                (job,),
                manifest=manifest,
                mp_context=_FakeContext(),
                status_store=status_store,
            )
            slot = _WorkerSlot(
                worker_id="worker-001",
                generation=1,
                process=_FakeProcess(),
                command_queue=_FakeQueue(),
                started_at=0.0,
                last_heartbeat=0.0,
                last_manifest_heartbeat=0.0,
                ready=True,
                current_job=job,
            )
            coordinator.slots[slot.worker_id] = slot

            coordinator._handle_event(
                WorkerEvent(
                    EventKind.ATTEMPT_STARTED,
                    worker_id="worker-001",
                    runtime_worker_id="worker-001",
                    job_key=job.key,
                    payload={"attempt": 2},
                )
            )
            coordinator._handle_event(
                WorkerEvent(
                    EventKind.STAGE,
                    worker_id="worker-001",
                    runtime_worker_id="worker-001",
                    job_key=job.key,
                    payload={
                        "run_id": "run-live",
                        "worker_id": "worker-001",
                        "source_filename": "source.pdf",
                        "attempt": 2,
                        "stage": "waiting_for_response",
                        "phase": "started",
                        "stage_started_at": "2026-09-05T12:00:00+00:00",
                        "elapsed_seconds": 3.0,
                        "last_activity_at": "2026-09-05T12:00:03+00:00",
                    },
                )
            )

            snapshot = read_status_snapshot(status_store.run_path)
            counters = dict(snapshot["counters"])
            worker = dict(list(snapshot["workers"])[0])
            self.assertEqual(counters["running"], 1)
            self.assertEqual(counters["queued"], 0)
            self.assertEqual(worker["attempt"], 2)
            self.assertEqual(worker["stage"], "waiting_for_response")
            self.assertEqual(worker["source_filename"], "source.pdf")

            slot.generation = 2
            before = dict(slot.stage or {})
            coordinator._handle_event(
                WorkerEvent(
                    EventKind.STAGE,
                    worker_id="worker-001",
                    runtime_worker_id="worker-001",
                    job_key=job.key,
                    payload={"stage": "saving", "phase": "started"},
                )
            )
            self.assertEqual(slot.stage, before)


class StatusCliTests(unittest.TestCase):
    def test_status_reads_live_snapshot_as_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = StatusSnapshotStore("run-cli", logs_dir=Path(tmp))
            store.publish(
                {
                    "state": "running",
                    "counters": {
                        "total": 3,
                        "completed": 1,
                        "succeeded": 1,
                        "failed": 0,
                        "skipped": 0,
                        "running": 1,
                        "queued": 1,
                    },
                    "workers": [],
                }
            )
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--json", "status", "--snapshot", str(store.run_path)])
            self.assertEqual(code, 0)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["run_id"], "run-cli")
            self.assertEqual(payload["counters"]["running"], 1)

    def test_status_watch_stops_immediately_on_terminal_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = StatusSnapshotStore("run-done", logs_dir=Path(tmp))
            store.publish(
                {
                    "state": "completed",
                    "counters": {
                        "total": 2,
                        "completed": 2,
                        "succeeded": 2,
                        "failed": 0,
                        "skipped": 0,
                        "running": 0,
                        "queued": 0,
                    },
                    "workers": [],
                }
            )
            output = io.StringIO()
            with redirect_stdout(output), mock.patch("note_maker.cli.time.sleep") as sleep:
                code = main(
                    [
                        "status",
                        "--snapshot",
                        str(store.run_path),
                        "--watch",
                        "--interval",
                        "0.01",
                    ]
                )
            self.assertEqual(code, 0)
            self.assertIn("Run run-done — completed", output.getvalue())
            sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
