from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import batch_common
from browser_runtime import BrowserLaunchOptions
from parallel_runtime.event_bus import (
    EventKind,
    StageKind,
    StagePhase,
    WorkerEvent,
)
from parallel_runtime.executors import MarkdownJobExecutor, PdfJobExecutor
from parallel_runtime.models import ExecutionJob
from parallel_runtime.stages import StageReporter
from tests.fakes.fake_browser_provider import (
    FakeBrowserPlan,
    FakeBrowserProvider,
    FakeBrowserSession,
)


VALID_MARKDOWN = """# Generated Note

## Explanation

This deterministic generated note contains enough useful content to pass the Markdown artifact validator while stage events are observed.
"""


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float = 1.0) -> None:
        self.value += seconds


class SlowFakeBrowserSession(FakeBrowserSession):
    def __init__(self, plan: FakeBrowserPlan, clock: FakeClock) -> None:
        super().__init__(plan)
        self.clock = clock

    def _record(self, operation: str, **payload) -> None:
        self.clock.advance()
        super()._record(operation, **payload)


class SlowFakeBrowserProvider(FakeBrowserProvider):
    def __init__(self, plan: FakeBrowserPlan, clock: FakeClock) -> None:
        super().__init__(plan)
        self.clock = clock

    def open_session(self, options: BrowserLaunchOptions | None = None) -> SlowFakeBrowserSession:
        options = options or BrowserLaunchOptions()
        self.open_options.append(options)
        session = SlowFakeBrowserSession(self.plan, self.clock)
        self.sessions.append(session)
        session.set_window_size(options.width, options.height)
        if options.url:
            session.navigate(options.url)
        return session


class StageEventModelTests(unittest.TestCase):
    def test_stage_reporter_carries_identity_timing_and_last_activity(self):
        events: list[tuple[EventKind, dict[str, object]]] = []
        ticks = iter([10.0, 12.5])
        timestamps = iter(
            [
                "2026-09-05T10:00:00+00:00",
                "2026-09-05T10:00:02.500000+00:00",
            ]
        )
        reporter = StageReporter(
            emit=lambda kind, **payload: events.append((kind, payload)),
            run_id="run-stage-test",
            worker_id="worker-002-g003",
            source_filename="source.pdf",
            clock=lambda: next(ticks),
            timestamp=lambda: next(timestamps),
        )
        reporter.set_attempt(2)
        reporter.content_stage(StageKind.UPLOADING)
        reporter.complete_current()

        self.assertEqual([kind for kind, _ in events], [EventKind.STAGE, EventKind.STAGE])
        started = events[0][1]
        completed = events[1][1]
        self.assertEqual(started["run_id"], "run-stage-test")
        self.assertEqual(started["worker_id"], "worker-002-g003")
        self.assertEqual(started["source_filename"], "source.pdf")
        self.assertEqual(started["attempt"], 2)
        self.assertEqual(started["stage"], StageKind.UPLOADING.value)
        self.assertEqual(started["phase"], StagePhase.STARTED.value)
        self.assertEqual(started["elapsed_seconds"], 0.0)
        self.assertEqual(completed["phase"], StagePhase.COMPLETED.value)
        self.assertEqual(completed["elapsed_seconds"], 2.5)
        self.assertEqual(completed["stage_started_at"], started["stage_started_at"])
        self.assertEqual(
            completed["last_activity_at"],
            "2026-09-05T10:00:02.500000+00:00",
        )
        self.assertNotIn("percent", started)
        self.assertNotIn("eta", started)

    def test_existing_worker_events_remain_usable(self):
        event = WorkerEvent(EventKind.JOB_STARTED, "worker-001", job_key="job-1")
        updated = event.with_payload(pid=42)
        self.assertEqual(updated.kind, EventKind.JOB_STARTED)
        self.assertEqual(updated.worker_id, "worker-001")
        self.assertEqual(updated.job_key, "job-1")
        self.assertEqual(updated.payload["pid"], 42)
        self.assertEqual(event.payload, {})


class StageExecutorIntegrationTests(unittest.TestCase):
    def _executor_config(self, output_dir: Path) -> dict[str, object]:
        return {
            "prompt": "create notes",
            "output_dir": str(output_dir),
            "model": None,
            "browser_provider": "fake",
            "max_attempts": 1,
            "download_timeout": 5,
            "skip_warmup": True,
            "save_diagnostics": False,
            "save_page_source": False,
            "output_ext": "md",
            "network_retries": 0,
            "browser_retries": 0,
            "download_retries": 0,
            "rate_limit_retries": 0,
            "retry_backoff_base": 0.0,
            "retry_backoff_cap": 0.0,
            "retry_jitter_ratio": 0.0,
        }

    @staticmethod
    def _fake_bootstrap(_model, *, provider, **_kwargs):
        session = provider.open_session()
        session.wait_until_logged_in()
        return session

    def _assert_complete_stage_sequence(self, events, *, source_filename: str):
        stage_payloads = [payload for kind, payload in events if kind == EventKind.STAGE]
        started = [payload for payload in stage_payloads if payload["phase"] == "started"]
        started_names = [payload["stage"] for payload in started]
        required = [
            StageKind.PREPARING_BROWSER.value,
            StageKind.WAITING_FOR_LOGIN.value,
            StageKind.UPLOADING.value,
            StageKind.WAITING_FOR_RESPONSE.value,
            StageKind.RESOLVING_DOWNLOAD.value,
            StageKind.VALIDATING.value,
            StageKind.SAVING.value,
            StageKind.COMPLETED.value,
        ]
        for stage in required:
            self.assertIn(stage, started_names)
        positions = {stage: started_names.index(stage) for stage in required}
        self.assertEqual(positions[StageKind.PREPARING_BROWSER.value], 0)
        self.assertLess(
            positions[StageKind.WAITING_FOR_LOGIN.value],
            positions[StageKind.UPLOADING.value],
        )
        for previous, current in zip(required[2:], required[3:]):
            self.assertLess(positions[previous], positions[current])

        for payload in stage_payloads:
            self.assertEqual(payload["run_id"], "run-stage-integration")
            self.assertEqual(payload["worker_id"], "worker-001")
            self.assertEqual(payload["source_filename"], source_filename)
            self.assertIn("stage_started_at", payload)
            self.assertIn("elapsed_seconds", payload)
            self.assertIn("last_activity_at", payload)
            self.assertNotIn("percent", payload)
            self.assertNotIn("eta", payload)

        content_stages = {
            StageKind.UPLOADING.value,
            StageKind.WAITING_FOR_RESPONSE.value,
            StageKind.RESOLVING_DOWNLOAD.value,
            StageKind.VALIDATING.value,
            StageKind.SAVING.value,
            StageKind.COMPLETED.value,
        }
        for payload in started:
            if payload["stage"] in content_stages:
                self.assertEqual(payload["attempt"], 1)
        completed = [payload for payload in stage_payloads if payload["phase"] == "completed"]
        self.assertTrue(any(float(payload["elapsed_seconds"]) > 0 for payload in completed))

    def test_slow_fake_provider_exposes_every_pdf_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.pdf"
            source.write_bytes(b"pdf")
            prompt = root / "prompt.md"
            prompt.write_text("prompt", encoding="utf-8")
            candidate = root / "candidate.md"
            candidate.write_text(VALID_MARKDOWN, encoding="utf-8")
            output_dir = root / "output"
            clock = FakeClock()
            provider = SlowFakeBrowserProvider(FakeBrowserPlan(download_path=candidate), clock)
            events: list[tuple[EventKind, dict[str, object]]] = []
            executor = PdfJobExecutor(
                config=self._executor_config(output_dir),
                run_id="run-stage-integration",
                worker_id="worker-001",
                emit=lambda kind, **payload: events.append((kind, payload)),
            )
            job = ExecutionJob(
                key="source.pdf::md",
                source=source,
                source_hash="source-hash",
                prompt_path=prompt,
                prompt_hash="prompt-hash",
                output=output_dir / "source.md",
                expected_extensions=(".md",),
                mode="pdf-md",
                title=source.name,
                metadata={"input_name": source.name},
            )
            executor.provider = provider

            original_validate = batch_common.validate_artifact
            original_fsync = batch_common._fsync_file

            def slow_validate(*args, **kwargs):
                clock.advance(2.0)
                return original_validate(*args, **kwargs)

            def slow_fsync(path):
                clock.advance(2.0)
                return original_fsync(path)

            with (
                mock.patch.object(batch_common, "bootstrap_session", self._fake_bootstrap),
                mock.patch.object(batch_common, "validate_artifact", slow_validate),
                mock.patch.object(batch_common, "_fsync_file", slow_fsync),
                mock.patch("parallel_runtime.stages.time.monotonic", clock),
            ):
                result = executor.execute(job)

            self.assertTrue(result.success)
            self.assertTrue((output_dir / "source.md").exists())
            self._assert_complete_stage_sequence(events, source_filename="source.pdf")

    def test_markdown_executor_uses_same_stage_foundation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "lecture.md"
            source.write_text("# Lecture\n\n## Topic\n\nSource text.\n", encoding="utf-8")
            section_file = root / "01_topic.md"
            section_file.write_text("## Topic\n\nSource text.\n", encoding="utf-8")
            prompt = root / "prompt.md"
            prompt.write_text("prompt", encoding="utf-8")
            candidate = root / "candidate.md"
            candidate.write_text(VALID_MARKDOWN, encoding="utf-8")
            output_dir = root / "output"
            clock = FakeClock()
            provider = SlowFakeBrowserProvider(FakeBrowserPlan(download_path=candidate), clock)
            events: list[tuple[EventKind, dict[str, object]]] = []
            executor = MarkdownJobExecutor(
                config=self._executor_config(output_dir),
                run_id="run-stage-integration",
                worker_id="worker-001",
                emit=lambda kind, **payload: events.append((kind, payload)),
            )
            job = ExecutionJob(
                key="lecture.md::section-0001::md",
                source=source,
                source_hash="source-hash",
                prompt_path=prompt,
                prompt_hash="prompt-hash",
                output=output_dir / "01_topic.md",
                expected_extensions=(".md",),
                mode="markdown-md",
                title="section 01 Topic",
                metadata={
                    "section_index": "1",
                    "section_title": "Topic",
                    "section_file": str(section_file),
                },
            )
            executor.provider = provider

            original_validate = batch_common.validate_artifact
            original_fsync = batch_common._fsync_file

            def slow_validate(*args, **kwargs):
                clock.advance(2.0)
                return original_validate(*args, **kwargs)

            def slow_fsync(path):
                clock.advance(2.0)
                return original_fsync(path)

            with (
                mock.patch.object(batch_common, "bootstrap_session", self._fake_bootstrap),
                mock.patch.object(batch_common, "validate_artifact", slow_validate),
                mock.patch.object(batch_common, "_fsync_file", slow_fsync),
                mock.patch("parallel_runtime.stages.time.monotonic", clock),
            ):
                result = executor.execute(job)

            self.assertTrue(result.success)
            self.assertTrue((output_dir / "01_topic.md").exists())
            self._assert_complete_stage_sequence(events, source_filename="lecture.md")


if __name__ == "__main__":
    unittest.main()
