from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from manifest import ManifestCoordinator
from parallel_runtime.coordinator import ParallelCoordinator, _WorkerSlot
from parallel_runtime.event_bus import EventKind, WorkerEvent
from parallel_runtime.event_journal import EventJournal, read_event_journal
from parallel_runtime.models import ExecutionJob, RunConfig
from parallel_runtime.status import StatusSnapshotStore, read_status_snapshot


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


class _CaptureStatusStore:
    def __init__(self) -> None:
        self.payloads: list[dict[str, object]] = []

    def publish(self, payload):
        captured = dict(payload)
        self.payloads.append(captured)
        return captured


class _CaptureJournal:
    path = Path("capture-events.jsonl")

    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []

    def append_coordinator_event(self, kind: str, **_kwargs):
        self.records.append(("coordinator", kind))
        return {}

    def append_worker_event(self, event: WorkerEvent, **_kwargs):
        self.records.append(("worker", event.kind.value))
        return {}


class _FailingJournal:
    path = Path("failing-events.jsonl")

    def append_coordinator_event(self, _kind: str, **_kwargs):
        raise OSError("journal unavailable")

    def append_worker_event(self, _event: WorkerEvent, **_kwargs):
        raise OSError("journal unavailable")


def _make_job(root: Path, key: str = "source") -> ExecutionJob:
    source = root / f"{key}.pdf"
    prompt = root / "prompt.md"
    source.write_bytes(b"source")
    prompt.write_text("prompt", encoding="utf-8")
    return ExecutionJob(
        key=key,
        source=source,
        source_hash=f"{key}-source-hash",
        prompt_path=prompt,
        prompt_hash="prompt-hash",
        output=root / f"{key}.md",
        expected_extensions=(".md",),
        mode="pdf-md",
        title=key,
    )


def _config(root: Path, run_id: str, *, executor_config=None) -> RunConfig:
    return RunConfig(
        run_id=run_id,
        manifest_path=root / "manifest.json",
        claims_dir=root / "claims",
        worker_count=1,
        executor_path="parallel_runtime.testing:ScriptedExecutor",
        executor_config=dict(executor_config or {}),
        heartbeat_interval=0.1,
        worker_timeout=2.0,
        worker_ready_timeout=5.0,
        startup_stagger=0.0,
        shutdown_grace=1.0,
        poll_interval=0.01,
    )


class EventJournalStorageTests(unittest.TestCase):
    def test_records_are_correlated_ordered_and_sensitive_fields_are_redacted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            journal = EventJournal("run-journal", logs_dir=root / "logs")
            first = journal.append_coordinator_event(
                "job_assigned",
                worker_id="worker-001",
                runtime_worker_id="worker-001-g002",
                generation=2,
                job_key="source",
                attempt=3,
                payload={
                    "claim_id": "claim-secret",
                    "authorization": "Bearer abc",
                    "nested": {"api_token": "token-secret", "safe": "visible"},
                },
            )
            second = journal.append_worker_event(
                WorkerEvent(
                    EventKind.GLOBAL_COOLDOWN_REQUESTED,
                    worker_id="worker-001",
                    runtime_worker_id="worker-001-g002",
                    job_key="incident-17",
                    payload={
                        "source_job_key": "source",
                        "attempt": 3,
                        "token": "worker-secret",
                    },
                ),
                generation=2,
            )

            records = read_event_journal(journal.path, strict=True)
            self.assertEqual([record["sequence"] for record in records], [1, 2])
            self.assertEqual(first["payload"]["claim_id"], "[redacted]")
            self.assertEqual(first["payload"]["authorization"], "[redacted]")
            self.assertEqual(first["payload"]["nested"]["api_token"], "[redacted]")
            self.assertEqual(first["payload"]["nested"]["safe"], "visible")
            self.assertEqual(second["job_key"], "source")
            self.assertEqual(second["event_job_key"], "incident-17")
            self.assertEqual(second["attempt"], 3)
            self.assertEqual(records[1]["payload"]["token"], "[redacted]")

    def test_reopen_after_torn_tail_keeps_later_records_readable_and_sequence_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = EventJournal("run-recover", logs_dir=root / "logs")
            first.append_coordinator_event("run_started")
            with first.path.open("ab") as handle:
                handle.write(b'{"schema_version":1,"sequence":2')

            reopened = EventJournal("run-recover", logs_dir=root / "logs")
            reopened.append_coordinator_event("run_finished")

            records = read_event_journal(reopened.path, strict=False)
            self.assertEqual([record["sequence"] for record in records], [1, 2])
            self.assertEqual([record["kind"] for record in records], ["run_started", "run_finished"])
            with self.assertRaises(ValueError):
                read_event_journal(reopened.path, strict=True)

    def test_stale_runtime_generation_is_preserved_separately_from_coordinator_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = EventJournal("run-generation", logs_dir=Path(tmp) / "logs")
            record = journal.append_worker_event(
                WorkerEvent(
                    EventKind.STAGE,
                    worker_id="worker-001",
                    runtime_worker_id="worker-001",
                    job_key="source",
                    payload={"stage": "saving", "attempt": 2},
                ),
                generation=3,
                disposition="ignored_stale_generation",
            )
            self.assertEqual(record["generation"], 1)
            self.assertEqual(record["coordinator_generation"], 3)
            self.assertEqual(record["disposition"], "ignored_stale_generation")


class CoordinatorJournalTests(unittest.TestCase):
    def test_empty_run_has_coordinator_start_and_finish_records_without_workers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture = _CaptureJournal()
            status = _CaptureStatusStore()
            coordinator = ParallelCoordinator(
                _config(root, "run-empty"),
                (),
                mp_context=_FakeContext(),
                status_store=status,
                event_journal=capture,
            )
            result = coordinator.run()

            self.assertFalse(result.failed)
            self.assertEqual(
                capture.records,
                [("coordinator", "run_started"), ("coordinator", "run_finished")],
            )
            self.assertEqual(status.payloads[-1]["state"], "completed")

    def test_stale_worker_event_is_journaled_but_cannot_change_current_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = _make_job(root)
            manifest = ManifestCoordinator(root / "manifest.json")
            manifest.register_run(
                "run-stale",
                mode="pdf-md",
                planned_jobs=1,
                parallel_runs=1,
                browser_provider="patchright",
            )
            journal = EventJournal("run-stale", logs_dir=root / "logs")
            coordinator = ParallelCoordinator(
                _config(root, "run-stale"),
                (job,),
                manifest=manifest,
                mp_context=_FakeContext(),
                status_store=StatusSnapshotStore("run-stale", logs_dir=root / "logs"),
                event_journal=journal,
            )
            slot = _WorkerSlot(
                worker_id="worker-001",
                generation=2,
                process=_FakeProcess(),
                command_queue=_FakeQueue(),
                started_at=0.0,
                last_heartbeat=0.0,
                last_manifest_heartbeat=0.0,
                ready=True,
                current_job=job,
                current_attempt=2,
                stage={"stage": "waiting_for_response", "phase": "started"},
            )
            coordinator.slots[slot.worker_id] = slot

            coordinator._handle_event(
                WorkerEvent(
                    EventKind.STAGE,
                    worker_id="worker-001",
                    runtime_worker_id="worker-001",
                    job_key=job.key,
                    payload={"stage": "saving", "phase": "started", "attempt": 1},
                )
            )
            self.assertEqual(slot.stage["stage"], "waiting_for_response")

            coordinator._handle_event(
                WorkerEvent(
                    EventKind.STAGE,
                    worker_id="worker-001",
                    runtime_worker_id="worker-001-g002",
                    job_key=job.key,
                    payload={"stage": "validating", "phase": "started", "attempt": 2},
                )
            )
            self.assertEqual(slot.stage["stage"], "validating")

            records = read_event_journal(journal.path, strict=True)
            self.assertEqual(records[0]["disposition"], "ignored_stale_generation")
            self.assertEqual(records[0]["generation"], 1)
            self.assertEqual(records[0]["coordinator_generation"], 2)
            self.assertEqual(records[1]["disposition"], "accepted")
            self.assertEqual(records[1]["generation"], 2)
            self.assertEqual(records[1]["attempt"], 2)

    def test_journal_failure_is_non_intrusive_and_logged_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            messages: list[str] = []
            coordinator = ParallelCoordinator(
                _config(root, "run-fail-open"),
                (),
                mp_context=_FakeContext(),
                status_store=_CaptureStatusStore(),
                event_journal=_FailingJournal(),
                event_logger=messages.append,
            )
            slot = _WorkerSlot(
                worker_id="worker-001",
                generation=1,
                process=_FakeProcess(),
                command_queue=_FakeQueue(),
                started_at=0.0,
                last_heartbeat=10.0,
                last_manifest_heartbeat=0.0,
                ready=True,
            )
            coordinator.slots[slot.worker_id] = slot
            event = WorkerEvent(
                EventKind.WORKER_FATAL,
                worker_id="worker-001",
                runtime_worker_id="worker-001",
                payload={"error": "scripted"},
            )

            coordinator._handle_event(event)
            coordinator._handle_event(event)

            self.assertEqual(slot.last_heartbeat, 0.0)
            journal_messages = [
                message for message in messages if message.startswith("Event journal update failed:")
            ]
            self.assertEqual(len(journal_messages), 1)

    def test_scripted_process_run_persists_correlated_worker_and_coordinator_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_id = "run-process-journal"
            job = _make_job(root)
            manifest = ManifestCoordinator(root / "manifest.json")
            manifest.register_run(
                run_id,
                mode="pdf-md",
                planned_jobs=1,
                parallel_runs=1,
                browser_provider="fake",
            )
            journal = EventJournal(run_id, logs_dir=root / "logs")
            status_store = StatusSnapshotStore(run_id, logs_dir=root / "logs")
            coordinator = ParallelCoordinator(
                _config(root, run_id, executor_config={"default_duration": 0.01}),
                (job,),
                manifest=manifest,
                status_store=status_store,
                event_journal=journal,
            )

            result = coordinator.run()

            self.assertEqual(result.succeeded, [job.key])
            records = read_event_journal(journal.path, strict=True)
            sequences = [int(record["sequence"]) for record in records]
            self.assertEqual(sequences, list(range(1, len(records) + 1)))
            kinds = [str(record["kind"]) for record in records]
            for expected in (
                "run_started",
                "worker_spawned",
                "worker_ready",
                "job_assigned",
                "job_started",
                "attempt_started",
                "job_succeeded",
                "shutdown_started",
                "shutdown_completed",
                "run_finished",
            ):
                self.assertIn(expected, kinds)

            attempt_records = [
                record for record in records if record.get("kind") == "attempt_started"
            ]
            self.assertEqual(attempt_records[0]["run_id"], run_id)
            self.assertEqual(attempt_records[0]["worker_id"], "worker-001")
            self.assertEqual(attempt_records[0]["runtime_worker_id"], "worker-001")
            self.assertEqual(attempt_records[0]["generation"], 1)
            self.assertEqual(attempt_records[0]["job_key"], job.key)
            self.assertEqual(attempt_records[0]["attempt"], 1)

            snapshot = read_status_snapshot(status_store.run_path)
            self.assertEqual(snapshot["event_journal"], str(journal.path))


if __name__ == "__main__":
    unittest.main()
