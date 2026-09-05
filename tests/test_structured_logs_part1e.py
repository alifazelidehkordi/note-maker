from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from parallel_runtime.event_bus import EventKind, WorkerEvent
from parallel_runtime.event_journal import EventJournal, read_event_journal
from parallel_runtime.structured_logs import StructuredLogStore, read_structured_log


class StructuredLogStorageTests(unittest.TestCase):
    def test_journal_creates_correlated_coordinator_and_worker_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs_dir = Path(tmp) / "logs"
            journal = EventJournal("run-logs", logs_dir=logs_dir)
            assigned = journal.append_coordinator_event(
                "job_assigned",
                worker_id="worker-001",
                runtime_worker_id="worker-001-g002",
                generation=2,
                job_key="source",
                attempt=3,
                payload={"claim_id": "claim-secret", "safe": "visible"},
            )
            staged = journal.append_worker_event(
                WorkerEvent(
                    EventKind.STAGE,
                    worker_id="worker-001",
                    runtime_worker_id="worker-001-g002",
                    job_key="source",
                    payload={
                        "stage": "saving",
                        "phase": "started",
                        "attempt": 3,
                        "token": "worker-secret",
                    },
                ),
                generation=2,
            )

            run_dir = journal.path.parent
            coordinator_records = read_structured_log(
                run_dir / "coordinator.jsonl", strict=True
            )
            worker_records = read_structured_log(
                run_dir / "workers" / "worker-001-g002.jsonl", strict=True
            )

            self.assertEqual(len(coordinator_records), 1)
            self.assertEqual(len(worker_records), 1)
            coordinator = coordinator_records[0]
            worker = worker_records[0]
            self.assertEqual(coordinator["logger"], "coordinator")
            self.assertEqual(coordinator["event_kind"], "job_assigned")
            self.assertEqual(coordinator["journal_sequence"], assigned["sequence"])
            self.assertEqual(coordinator["run_id"], "run-logs")
            self.assertEqual(coordinator["worker_id"], "worker-001")
            self.assertEqual(coordinator["runtime_worker_id"], "worker-001-g002")
            self.assertEqual(coordinator["generation"], 2)
            self.assertEqual(coordinator["job_key"], "source")
            self.assertEqual(coordinator["attempt"], 3)
            self.assertEqual(coordinator["payload"]["claim_id"], "[redacted]")
            self.assertEqual(coordinator["payload"]["safe"], "visible")

            self.assertEqual(worker["logger"], "worker")
            self.assertEqual(worker["event_kind"], "stage")
            self.assertEqual(worker["journal_sequence"], staged["sequence"])
            self.assertEqual(worker["job_key"], "source")
            self.assertEqual(worker["attempt"], 3)
            self.assertEqual(worker["payload"]["token"], "[redacted]")
            self.assertEqual(worker["level"], "INFO")
            self.assertNotIn("percent", worker)
            self.assertNotIn("eta", worker)

    def test_stale_generation_is_warning_and_keeps_both_generations(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = EventJournal("run-stale-log", logs_dir=Path(tmp) / "logs")
            journal.append_worker_event(
                WorkerEvent(
                    EventKind.STAGE,
                    worker_id="worker-001",
                    runtime_worker_id="worker-001",
                    job_key="source",
                    payload={"stage": "saving", "attempt": 1},
                ),
                generation=2,
                disposition="ignored_stale_generation",
            )

            records = read_structured_log(
                journal.path.parent / "workers" / "worker-001.jsonl",
                strict=True,
            )
            self.assertEqual(len(records), 1)
            record = records[0]
            self.assertEqual(record["generation"], 1)
            self.assertEqual(record["coordinator_generation"], 2)
            self.assertEqual(record["disposition"], "ignored_stale_generation")
            self.assertEqual(record["level"], "WARNING")
            self.assertIn("ignored stale generation", record["message"])

    def test_heartbeat_stays_in_journal_but_not_operational_worker_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = EventJournal("run-heartbeat-log", logs_dir=Path(tmp) / "logs")
            journal.append_worker_event(
                WorkerEvent(
                    EventKind.WORKER_READY,
                    worker_id="worker-001",
                    runtime_worker_id="worker-001",
                    payload={"pid": 101},
                ),
                generation=1,
            )
            journal.append_worker_event(
                WorkerEvent(
                    EventKind.HEARTBEAT,
                    worker_id="worker-001",
                    runtime_worker_id="worker-001",
                    payload={"pid": 101},
                ),
                generation=1,
            )

            journal_records = read_event_journal(journal.path, strict=True)
            worker_records = read_structured_log(
                journal.path.parent / "workers" / "worker-001.jsonl",
                strict=True,
            )
            self.assertEqual(
                [record["kind"] for record in journal_records],
                ["worker_ready", "heartbeat"],
            )
            self.assertEqual(
                [record["event_kind"] for record in worker_records],
                ["worker_ready"],
            )

    def test_reopen_after_torn_worker_log_preserves_later_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs_dir = Path(tmp) / "logs"
            first = EventJournal("run-log-recover", logs_dir=logs_dir)
            first.append_worker_event(
                WorkerEvent(
                    EventKind.WORKER_READY,
                    worker_id="worker-001",
                    runtime_worker_id="worker-001",
                ),
                generation=1,
            )
            worker_path = first.path.parent / "workers" / "worker-001.jsonl"
            with worker_path.open("ab") as handle:
                handle.write(b'{"schema_version":1,"level":"INFO"')

            reopened = EventJournal("run-log-recover", logs_dir=logs_dir)
            reopened.append_worker_event(
                WorkerEvent(
                    EventKind.WORKER_STOPPED,
                    worker_id="worker-001",
                    runtime_worker_id="worker-001",
                ),
                generation=1,
            )

            records = read_structured_log(worker_path, strict=False)
            self.assertEqual(
                [record["event_kind"] for record in records],
                ["worker_ready", "worker_stopped"],
            )
            with self.assertRaises(ValueError):
                read_structured_log(worker_path, strict=True)

    def test_runtime_worker_id_cannot_escape_worker_log_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = EventJournal("run-safe-path", logs_dir=Path(tmp) / "logs")
            journal.append_worker_event(
                WorkerEvent(
                    EventKind.WORKER_READY,
                    worker_id="worker-001",
                    runtime_worker_id="../../outside/worker",
                ),
                generation=1,
            )

            worker_dir = journal.path.parent / "workers"
            files = list(worker_dir.glob("*.jsonl"))
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].parent.resolve(), worker_dir.resolve())
            self.assertNotIn("..", files[0].name)
            self.assertFalse((journal.path.parent.parent / "outside").exists())

    def test_structured_log_failure_does_not_break_durable_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = EventJournal("run-log-fail-open", logs_dir=Path(tmp) / "logs")
            with mock.patch.object(
                StructuredLogStore,
                "_append",
                side_effect=OSError("structured log unavailable"),
            ):
                record = journal.append_coordinator_event("run_started")

            self.assertEqual(record["kind"], "run_started")
            persisted = read_event_journal(journal.path, strict=True)
            self.assertEqual([item["kind"] for item in persisted], ["run_started"])
            self.assertIn("structured log unavailable", journal._structured_log_error)


class StructuredLogCoordinatorIntegrationTests(unittest.TestCase):
    def test_scripted_process_run_writes_correlated_operational_logs(self):
        from manifest import ManifestCoordinator
        from parallel_runtime.coordinator import ParallelCoordinator
        from parallel_runtime.models import ExecutionJob, RunConfig
        from parallel_runtime.status import StatusSnapshotStore

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_id = "run-process-logs"
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
                title="source",
            )
            config = RunConfig(
                run_id=run_id,
                manifest_path=root / "manifest.json",
                claims_dir=root / "claims",
                worker_count=1,
                executor_path="parallel_runtime.testing:ScriptedExecutor",
                executor_config={"default_duration": 0.01},
                heartbeat_interval=0.1,
                worker_timeout=2.0,
                worker_ready_timeout=5.0,
                startup_stagger=0.0,
                shutdown_grace=1.0,
                poll_interval=0.01,
            )
            manifest = ManifestCoordinator(config.manifest_path)
            manifest.register_run(
                run_id,
                mode="pdf-md",
                planned_jobs=1,
                parallel_runs=1,
                browser_provider="fake",
            )
            journal = EventJournal(run_id, logs_dir=root / "logs")
            coordinator = ParallelCoordinator(
                config,
                (job,),
                manifest=manifest,
                status_store=StatusSnapshotStore(run_id, logs_dir=root / "logs"),
                event_journal=journal,
            )

            result = coordinator.run()

            self.assertEqual(result.succeeded, [job.key])
            coordinator_records = read_structured_log(
                journal.path.parent / "coordinator.jsonl", strict=True
            )
            worker_records = read_structured_log(
                journal.path.parent / "workers" / "worker-001.jsonl", strict=True
            )
            coordinator_kinds = [record["event_kind"] for record in coordinator_records]
            worker_kinds = [record["event_kind"] for record in worker_records]
            for expected in (
                "run_started",
                "worker_spawned",
                "job_assigned",
                "shutdown_started",
                "shutdown_completed",
                "run_finished",
            ):
                self.assertIn(expected, coordinator_kinds)
            for expected in (
                "worker_ready",
                "job_started",
                "attempt_started",
                "job_succeeded",
            ):
                self.assertIn(expected, worker_kinds)
            # WORKER_STOPPED is emitted in the worker's finalizer, but coordinator
            # teardown may close the generation queue before that last event is observed.
            self.assertNotIn("heartbeat", worker_kinds)

            attempt = next(
                record for record in worker_records if record["event_kind"] == "attempt_started"
            )
            self.assertEqual(attempt["run_id"], run_id)
            self.assertEqual(attempt["worker_id"], "worker-001")
            self.assertEqual(attempt["runtime_worker_id"], "worker-001")
            self.assertEqual(attempt["generation"], 1)
            self.assertEqual(attempt["job_key"], job.key)
            self.assertEqual(attempt["attempt"], 1)
            self.assertIsInstance(attempt["journal_sequence"], int)


if __name__ == "__main__":
    unittest.main()
