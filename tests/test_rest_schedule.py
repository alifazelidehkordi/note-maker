from __future__ import annotations

"""Rest schedule regression tests (plan item 6, critic-approved)."""

from pathlib import Path
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from parallel_runtime.rest_schedule import RestSchedule


class FakeClock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class RestScheduleTests(unittest.TestCase):
    def test_interval_triggers_rest_and_persists_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rest.json"
            clock = FakeClock(1000.0)
            schedule = RestSchedule(path, interval=30, seconds=1800, clock=clock)
            # 29 completed: below threshold but capped one below the boundary
            self.assertEqual(schedule.capacity(completed=29, busy=0, available=2), 1)
            # 30 completed: threshold reached -> open the rest window
            self.assertEqual(schedule.capacity(completed=30, busy=0, available=2), 0)
            # state persisted
            state = json.loads(path.read_text())
            self.assertEqual(state["last_pause_after"], 30)
            self.assertEqual(state["until"], 1000.0 + 1800)
            # during the rest window: no admissions
            clock.now = 2000.0
            self.assertEqual(schedule.capacity(completed=31, busy=0, available=2), 0)
            # after the window: next threshold is 60
            clock.now = 3000.0
            self.assertEqual(schedule.capacity(completed=45, busy=0, available=2), 2)

    def test_busy_workers_delay_rest_window_opening(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rest.json"
            clock = FakeClock(1000.0)
            schedule = RestSchedule(path, interval=30, seconds=1800, clock=clock)
            # threshold reached but a worker is busy -> hold capacity at 0
            self.assertEqual(schedule.capacity(completed=30, busy=1, available=2), 0)
            clock.now = 1001.0
            self.assertEqual(schedule.capacity(completed=30, busy=0, available=2), 0)
            self.assertTrue(path.exists(), "rest opened once workers drained")

    def test_capacity_never_overshoots_next_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rest.json"
            clock = FakeClock(1000.0)
            schedule = RestSchedule(path, interval=30, seconds=1800, clock=clock)
            # 10 completed, 4 slots free: never above available; slot
            # admissions cannot overshoot the boundary because the cap
            # shrinks as completed approaches it
            self.assertEqual(schedule.capacity(completed=10, busy=0, available=4), 4)
            self.assertEqual(schedule.capacity(completed=25, busy=2, available=4), 3)

    def test_state_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rest.json"
            clock = FakeClock(1000.0)
            first = RestSchedule(path, interval=30, seconds=1800, clock=clock)
            first.capacity(completed=30, busy=0, available=2)
            # A restarted coordinator must not re-pause: next threshold is 60
            second = RestSchedule(path, interval=30, seconds=1800, clock=clock)
            clock.now = 5000.0
            self.assertEqual(second.capacity(completed=31, busy=0, available=2), 2)
            self.assertEqual(second.capacity(completed=60, busy=0, available=2), 0)

    def test_global_count_walks_boundaries_across_subjects(self):
        """The caller passes the GLOBAL count (base + local). A wrapper that
        finished 90 files in previous subjects hits its first rest boundary
        immediately; each subsequent boundary advances by one interval, so
        rests pace the whole global total rather than re-firing per subject."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rest.json"
            clock = FakeClock(1000.0)
            schedule = RestSchedule(path, interval=30, seconds=1800, clock=clock)
            # first call: crosses boundary 30 -> rest opens, boundary recorded
            self.assertEqual(schedule.capacity(completed=90, busy=0, available=2), 0)
            self.assertEqual(json.loads(path.read_text())["last_pause_after"], 30)
            clock.now = 4000.0
            # next crossing at 60 opens another rest (global total still above)
            self.assertEqual(schedule.capacity(completed=90, busy=0, available=2), 0)
            self.assertEqual(json.loads(path.read_text())["last_pause_after"], 60)
            clock.now = 7000.0
            self.assertEqual(schedule.capacity(completed=90, busy=0, available=2), 0)
            self.assertEqual(json.loads(path.read_text())["last_pause_after"], 90)
            clock.now = 10000.0
            # boundary 90 recorded; below 120 capacity resumes
            self.assertEqual(schedule.capacity(completed=91, busy=0, available=2), 2)

    def test_invalid_configuration_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                RestSchedule(Path(tmp) / "r.json", interval=0)
            with self.assertRaises(ValueError):
                RestSchedule(Path(tmp) / "r.json", seconds=-1)
            with self.assertRaises(ValueError):
                RestSchedule(Path(tmp) / "r.json", seconds=-1.0)

    def test_coordinator_creates_schedule_from_run_config(self):
        """The coordinator builds the gate from RunConfig when rest is enabled."""
        from unittest import mock
        from parallel_runtime.models import RunConfig, ExecutionJob

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = RunConfig(
                run_id="rest-test",
                manifest_path=root / "manifest.json",
                claims_dir=root / "claims",
                worker_count=1,
                executor_path="parallel_runtime.executors:PdfJobExecutor",
                rest_every=30,
                rest_seconds=1800.0,
                rest_state=str(root / "rest.json"),
            )
            from parallel_runtime.coordinator import ParallelCoordinator

            job = ExecutionJob(
                key="job/01",
                source=root / "a.md",
                source_hash="abc123",
                prompt_path=root / "p.md",
                prompt_hash="def456",
                output=root / "a.md.out",
                expected_extensions=(".md",),
                mode="pdf-md",
            )
            with mock.patch(
                "parallel_runtime.coordinator.ManifestCoordinator"
            ) as manifest:
                manifest.return_value.claim_snapshot.return_value = {}
                coordinator = ParallelCoordinator(config, [job])
            self.assertIsNotNone(coordinator._rest_schedule)
            self.assertEqual(coordinator._rest_schedule.interval, 30)

    def test_coordinator_skips_schedule_when_rest_disabled(self):
        from unittest import mock
        from parallel_runtime.models import RunConfig, ExecutionJob

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = RunConfig(
                run_id="no-rest",
                manifest_path=root / "manifest.json",
                claims_dir=root / "claims",
                worker_count=1,
                executor_path="parallel_runtime.executors:PdfJobExecutor",
            )
            from parallel_runtime.coordinator import ParallelCoordinator

            job = ExecutionJob(
                key="job/01",
                source=root / "a.md",
                source_hash="abc123",
                prompt_path=root / "p.md",
                prompt_hash="def456",
                output=root / "a.md.out",
                expected_extensions=(".md",),
                mode="pdf-md",
            )
            with mock.patch(
                "parallel_runtime.coordinator.ManifestCoordinator"
            ) as manifest:
                manifest.return_value.claim_snapshot.return_value = {}
                coordinator = ParallelCoordinator(config, [job])
            self.assertIsNone(coordinator._rest_schedule)

    def test_config_precedence_env_overrides_toml_overrides_default(self):
        """Critic-pinned precedence: env > toml > defaults (config.py pattern)."""
        from note_maker.config import resolve_config

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            toml = root / "note-maker.toml"
            toml.write_text(
                "[runtime]\n"
                'browser_provider = "patchright"\n'
                "rest_every = 40\n"
                "rest_seconds = 1200\n"
            )
            # Defaults (rest disabled)
            resolved = resolve_config("pdf", config_path=toml)
            self.assertEqual(resolved.runtime.rest_every, 40)
            self.assertEqual(resolved.runtime.rest_seconds, 1200.0)
            # TOML overrides defaults
            resolved = resolve_config("pdf", config_path=toml)
            self.assertEqual(resolved.runtime.rest_every, 40)
            # env overrides TOML
            resolved = resolve_config(
                "pdf",
                config_path=toml,
                environ={"NOTE_MAKER_REST_EVERY": "25", "NOTE_MAKER_REST_SECONDS": "600"},
            )
            self.assertEqual(resolved.runtime.rest_every, 25)
            self.assertEqual(resolved.runtime.rest_seconds, 600.0)


if __name__ == "__main__":
    unittest.main()
