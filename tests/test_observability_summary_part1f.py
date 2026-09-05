from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from note_maker.entrypoint import main as entrypoint_main
from parallel_runtime.event_bus import EventKind, WorkerEvent
from parallel_runtime.event_journal import EventJournal
from parallel_runtime.observability import (
    OBSERVABILITY_SCHEMA_VERSION,
    build_run_observability,
    format_run_observability,
    resolve_run_dir,
)
from parallel_runtime.status import StatusSnapshotStore


def _snapshot(run_id: str, *, state: str = "running") -> dict[str, object]:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "state": state,
        "mode": "pdf-md",
        "browser_provider": "fake",
        "started_at": "2026-09-05T00:00:00+00:00",
        "finished_at": "2026-09-05T00:00:10+00:00" if state == "completed" else None,
        "updated_at": "2026-09-05T00:00:05+00:00",
        "requested_workers": 2,
        "active_worker_limit": 2,
        "counters": {
            "total": 2,
            "completed": 1,
            "succeeded": 1,
            "failed": 0,
            "skipped": 0,
            "running": 1,
            "queued": 0,
            "remaining": 1,
        },
        "workers": [
            {
                "worker_id": "worker-001",
                "runtime_worker_id": "worker-001-g002",
                "generation": 2,
                "status": "busy",
                "job_key": "source-b",
                "source_filename": "source-b.pdf",
                "attempt": 2,
                "stage": "saving",
                "stage_phase": "started",
                "stage_elapsed_seconds": 1.25,
                "last_activity_at": "2026-09-05T00:00:05+00:00",
            }
        ],
        "control": {
            "cooldown_remaining_seconds": 0.0,
            "active_limit": 2,
            "minimum_active_limit": 1,
            "rate_limit_events": 1,
            "auth_failures": 1,
            "circuit_breaker_reason": None,
        },
        "interrupted": False,
    }


class ObservabilitySummaryTests(unittest.TestCase):
    def test_summary_correlates_status_journal_logs_and_redaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs_dir = Path(tmp) / "logs"
            run_id = "run-observe"
            journal = EventJournal(run_id, logs_dir=logs_dir)
            journal.append_coordinator_event("run_started")
            journal.append_worker_event(
                WorkerEvent(
                    EventKind.WORKER_READY,
                    worker_id="worker-001",
                    runtime_worker_id="worker-001",
                ),
                generation=1,
            )
            journal.append_worker_event(
                WorkerEvent(
                    EventKind.HEARTBEAT,
                    worker_id="worker-001",
                    runtime_worker_id="worker-001",
                ),
                generation=1,
            )
            journal.append_worker_event(
                WorkerEvent(
                    EventKind.STAGE,
                    worker_id="worker-001",
                    runtime_worker_id="worker-001",
                    job_key="source-a",
                    payload={"stage": "saving", "token": "secret-value"},
                ),
                generation=2,
                disposition="ignored_stale_generation",
            )
            journal.append_worker_event(
                WorkerEvent(
                    EventKind.RETRY_SCHEDULED,
                    worker_id="worker-001",
                    runtime_worker_id="worker-001-g002",
                    job_key="source-b",
                    payload={"attempt": 2},
                ),
                generation=2,
            )
            journal.append_worker_event(
                WorkerEvent(
                    EventKind.AUTH_FAILURE,
                    worker_id="worker-001",
                    runtime_worker_id="worker-001-g002",
                    job_key="source-b",
                    payload={"attempt": 2},
                ),
                generation=2,
            )

            summary = build_run_observability(
                _snapshot(run_id),
                run_dir=journal.path.parent,
                recent_events=10,
                now=datetime(2026, 9, 5, 0, 0, 10, tzinfo=timezone.utc),
            )

            self.assertEqual(summary["schema_version"], OBSERVABILITY_SCHEMA_VERSION)
            self.assertEqual(summary["duration_seconds"], 10.0)
            self.assertEqual(summary["events"]["total"], 6)
            self.assertEqual(summary["events"]["by_kind"]["heartbeat"], 1)
            self.assertEqual(summary["signals"]["retries"], 1)
            self.assertEqual(summary["signals"]["rate_limit_events"], 1)
            self.assertEqual(summary["signals"]["auth_failures"], 1)
            self.assertEqual(summary["operational_logs"]["levels"]["ERROR"], 1)
            self.assertGreaterEqual(summary["operational_logs"]["levels"]["WARNING"], 2)
            self.assertEqual(
                [worker["runtime_worker_id"] for worker in summary["workers"]],
                ["worker-001", "worker-001-g002"],
            )
            current = summary["workers"][1]
            self.assertEqual(current["status"], "busy")
            self.assertEqual(current["stage"], "saving")
            self.assertEqual(current["attempt"], 2)
            self.assertNotIn(
                "heartbeat",
                [event["kind"] for event in summary["recent_events"]],
            )
            stale = next(
                event
                for event in summary["recent_events"]
                if event["disposition"] == "ignored_stale_generation"
            )
            self.assertEqual(stale["payload"]["token"], "[redacted]")
            self.assertEqual(stale["level"], "WARNING")

    def test_missing_optional_telemetry_degrades_without_failing(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "logs" / "runs" / "run-missing"
            run_dir.mkdir(parents=True)
            summary = build_run_observability(
                _snapshot("run-missing"),
                run_dir=run_dir,
                recent_events=4,
                now=datetime(2026, 9, 5, 0, 0, 3, tzinfo=timezone.utc),
            )
            self.assertEqual(summary["events"]["total"], 0)
            self.assertEqual(summary["operational_logs"]["total"], 0)
            self.assertEqual(summary["sources"]["event_journal"], "missing")
            self.assertEqual(summary["sources"]["coordinator_log"], "missing")
            self.assertEqual(summary["sources"]["worker_log_files"], 0)
            self.assertEqual(summary["counters"]["running"], 1)

    def test_torn_journal_and_worker_log_tails_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs_dir = Path(tmp) / "logs"
            journal = EventJournal("run-torn", logs_dir=logs_dir)
            journal.append_worker_event(
                WorkerEvent(
                    EventKind.WORKER_READY,
                    worker_id="worker-001",
                    runtime_worker_id="worker-001",
                ),
                generation=1,
            )
            with journal.path.open("ab") as handle:
                handle.write(b'{"schema_version":1,"kind":"broken"')
            worker_path = journal.path.parent / "workers" / "worker-001.jsonl"
            with worker_path.open("ab") as handle:
                handle.write(b'{"schema_version":1,"level":"INFO"')

            summary = build_run_observability(
                _snapshot("run-torn"),
                run_dir=journal.path.parent,
                recent_events=4,
                now=datetime(2026, 9, 5, 0, 0, 1, tzinfo=timezone.utc),
            )
            self.assertEqual(summary["events"]["total"], 1)
            self.assertEqual(summary["operational_logs"]["total"], 1)
            self.assertEqual(summary["sources"]["event_journal"], "ok")
            self.assertEqual(
                summary["sources"]["worker_logs"]["worker-001.jsonl"],
                "ok",
            )

    def test_run_dir_resolution_supports_latest_and_run_specific_snapshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs = Path(tmp) / "logs"
            run_id = "run-path"
            snapshot = _snapshot(run_id)
            latest = logs / "last_status.json"
            specific = logs / "runs" / run_id / "status.json"
            self.assertEqual(
                resolve_run_dir(latest, snapshot),
                (logs / "runs" / run_id).resolve(),
            )
            self.assertEqual(
                resolve_run_dir(specific, snapshot),
                (logs / "runs" / run_id).resolve(),
            )

    def test_human_summary_has_observable_signals_without_eta_or_percent(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = build_run_observability(
                _snapshot("run-format"),
                run_dir=Path(tmp) / "missing",
                recent_events=0,
                now=datetime(2026, 9, 5, 0, 0, 2, tzinfo=timezone.utc),
            )
        text = format_run_observability(summary)
        self.assertIn("Run run-format — running", text)
        self.assertIn("Signals:", text)
        self.assertIn("Events:", text)
        self.assertNotIn("ETA", text)
        self.assertNotIn("percent", text.lower())


class ObservabilityEntrypointTests(unittest.TestCase):
    def test_status_details_json_is_read_only_and_machine_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs_dir = Path(tmp) / "logs"
            run_id = "run-cli-details"
            store = StatusSnapshotStore(run_id, logs_dir=logs_dir)
            snapshot = store.publish(_snapshot(run_id))
            journal = EventJournal(run_id, logs_dir=logs_dir)
            journal.append_coordinator_event("run_started")
            status_before = store.run_path.read_bytes()
            events_before = journal.path.read_bytes()

            output = io.StringIO()
            with redirect_stdout(output):
                code = entrypoint_main(
                    [
                        "--json",
                        "status",
                        "--details",
                        "--snapshot",
                        str(store.run_path),
                        "--recent-events",
                        "2",
                    ]
                )

            self.assertEqual(code, 0)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["run_id"], run_id)
            self.assertEqual(payload["schema_version"], OBSERVABILITY_SCHEMA_VERSION)
            self.assertEqual(payload["counters"], snapshot["counters"])
            self.assertEqual(store.run_path.read_bytes(), status_before)
            self.assertEqual(journal.path.read_bytes(), events_before)

    def test_status_details_watch_stops_without_sleep_when_terminal(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs_dir = Path(tmp) / "logs"
            run_id = "run-cli-terminal"
            store = StatusSnapshotStore(run_id, logs_dir=logs_dir)
            store.publish(_snapshot(run_id, state="completed"))
            output = io.StringIO()
            with mock.patch("note_maker.entrypoint.time.sleep") as sleep, redirect_stdout(output):
                code = entrypoint_main(
                    [
                        "status",
                        "--details",
                        "--watch",
                        "--snapshot",
                        str(store.run_path),
                    ]
                )
            self.assertEqual(code, 0)
            sleep.assert_not_called()
            self.assertIn("Run run-cli-terminal — completed", output.getvalue())

    def test_entrypoint_delegates_existing_summary_status_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp) / "summary.json"
            summary.write_text(
                json.dumps({"run_id": "legacy-run", "successes": 3, "failures": []}),
                encoding="utf-8",
            )
            output = io.StringIO()
            with redirect_stdout(output):
                code = entrypoint_main(["--json", "status", "--summary", str(summary)])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue())["successes"], 3)


if __name__ == "__main__":
    unittest.main()
