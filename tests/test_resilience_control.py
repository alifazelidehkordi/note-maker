from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
import sys
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from browser_runtime.errors import (
    AuthenticationRequiredError,
    BrowserConfigurationError,
    DownloadNotFoundError,
    RateLimitError,
    UploadCapacityError,
)
from parallel_runtime.resilience import (
    FailureCategory,
    GlobalRuntimeController,
    RetryBudgetPolicy,
    RetryTracker,
    classify_failure,
)
from parallel_runtime.executors import _BrowserExecutorBase
from parallel_runtime.worker import rate_limit_incident_id


class _Clock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class RetryPolicyTests(unittest.TestCase):
    def test_parallel_workers_only_warm_up_the_primary_browser(self):
        primary = _BrowserExecutorBase(
            config={}, run_id="run", worker_id="worker-001", emit=lambda *a, **k: None
        )
        secondary = _BrowserExecutorBase(
            config={}, run_id="run", worker_id="worker-002", emit=lambda *a, **k: None
        )
        recycled_primary = _BrowserExecutorBase(
            config={},
            run_id="run",
            worker_id="worker-001-g002",
            emit=lambda *a, **k: None,
        )
        explicitly_disabled = _BrowserExecutorBase(
            config={"skip_warmup": True},
            run_id="run",
            worker_id="worker-001",
            emit=lambda *a, **k: None,
        )
        self.assertFalse(primary.skip_warmup)
        self.assertTrue(secondary.skip_warmup)
        self.assertFalse(recycled_primary.skip_warmup)
        self.assertTrue(explicitly_disabled.skip_warmup)

    def test_failure_classification_is_typed(self):
        self.assertEqual(classify_failure(AuthenticationRequiredError("login")), FailureCategory.AUTH)
        self.assertEqual(classify_failure(RateLimitError("slow", retry_after=7)), FailureCategory.RATE_LIMIT)
        self.assertEqual(classify_failure(DownloadNotFoundError("missing")), FailureCategory.DOWNLOAD)
        self.assertEqual(classify_failure(ConnectionError("offline")), FailureCategory.NETWORK)

    def test_independent_retry_budgets_are_bounded(self):
        policy = RetryBudgetPolicy(
            content_attempts=2,
            network_retries=2,
            browser_retries=1,
            download_retries=1,
            rate_limit_retries=1,
            backoff_base=1.0,
            backoff_cap=4.0,
            jitter_ratio=0.0,
        )
        tracker = RetryTracker(policy, seed="test")
        first = tracker.record(ConnectionError("offline"))
        second = tracker.record(ConnectionError("offline"))
        third = tracker.record(ConnectionError("offline"))
        self.assertTrue(first.retry)
        self.assertTrue(second.retry)
        self.assertFalse(third.retry)
        self.assertEqual([first.delay_seconds, second.delay_seconds], [1.0, 2.0])
        self.assertEqual(tracker.as_dict()["network"], 3)

    def test_browser_configuration_failure_is_not_retried(self):
        tracker = RetryTracker(RetryBudgetPolicy(browser_retries=5, jitter_ratio=0.0))
        decision = tracker.record(BrowserConfigurationError("sandbox blocked Chromium"))
        self.assertEqual(decision.category, FailureCategory.BROWSER)
        self.assertFalse(decision.retry)
        self.assertEqual(decision.count, 1)

    def test_executor_discards_dead_session_before_reuse(self):
        executor = _BrowserExecutorBase(
            config={"browser_provider": "patchright"},
            run_id="run",
            worker_id="worker-001",
            emit=lambda *a, **k: None,
        )
        dead = object()
        fresh = object()
        provider = object()
        executor.driver = dead
        executor.provider = provider

        with mock.patch("batch_common.driver_is_alive", return_value=False), mock.patch(
            "batch_common.quit_driver"
        ) as quit_driver, mock.patch(
            "batch_common.bootstrap_session", return_value=fresh
        ) as bootstrap:
            self.assertIs(executor._ensure_session(), fresh)

        quit_driver.assert_called_once_with(dead)
        bootstrap.assert_called_once()
        self.assertEqual(executor.browser_restarts, 1)

    def test_executor_resets_per_job_telemetry(self):
        executor = _BrowserExecutorBase(
            config={"browser_provider": "patchright"},
            run_id="run",
            worker_id="worker-001",
            emit=lambda *a, **k: None,
        )
        executor.browser_restarts = 4
        executor.rate_limit_count = 7
        executor._begin_job()
        self.assertEqual(executor.browser_restarts, 0)
        self.assertEqual(executor.rate_limit_count, 0)

    def test_rate_limit_retry_after_overrides_backoff(self):
        tracker = RetryTracker(RetryBudgetPolicy(rate_limit_retries=1, jitter_ratio=0.0))
        decision = tracker.record(RateLimitError("wait", retry_after=17))
        self.assertTrue(decision.retry)
        self.assertEqual(decision.delay_seconds, 17)

    def test_upload_capacity_backoff_does_not_open_global_rate_limit_control(self):
        tracker = RetryTracker(RetryBudgetPolicy(content_attempts=3, jitter_ratio=0.0))
        decision = tracker.record(UploadCapacityError("third upload disabled", retry_after=60))
        self.assertEqual(decision.category, FailureCategory.CONTENT)
        self.assertTrue(decision.retry)
        self.assertEqual(decision.delay_seconds, 60)
        self.assertEqual(decision.retry_after, 60)

    def test_rate_limit_incident_ids_are_unique_within_one_job(self):
        first = rate_limit_incident_id("worker-001", "job-a", 1)
        second = rate_limit_incident_id("worker-001", "job-a", 2)
        self.assertNotEqual(first, second)
        self.assertIn("job-a", first)
        self.assertIn("job-a", second)


class GlobalControlTests(unittest.TestCase):
    def test_single_auth_failure_does_not_freeze_below_circuit_threshold(self):
        clock = _Clock()
        control = GlobalRuntimeController(
            requested_limit=2,
            cooldown_seconds=0,
            auth_failures_before_abort=2,
            rate_limit_failures_before_abort=0,
            rate_limit_window_seconds=300,
            adaptive_enabled=False,
            adaptive_scale_down_threshold=2,
            adaptive_recovery_seconds=30,
            clock=clock,
        )
        control.record_auth_failure()
        self.assertTrue(control.dispatch_allowed)
        control.record_auth_failure()
        self.assertFalse(control.dispatch_allowed)

    def test_zero_global_cooldown_ignores_provider_retry_after(self):
        clock = _Clock()
        control = GlobalRuntimeController(
            requested_limit=3,
            cooldown_seconds=0,
            auth_failures_before_abort=2,
            rate_limit_failures_before_abort=0,
            rate_limit_window_seconds=300,
            adaptive_enabled=False,
            adaptive_scale_down_threshold=2,
            adaptive_recovery_seconds=30,
            clock=clock,
        )
        control.request_cooldown(retry_after=180, incident_key="job-a")
        self.assertTrue(control.dispatch_allowed)
        self.assertEqual(control.snapshot().cooldown_remaining, 0)

    def test_cooldown_pauses_dispatch_and_adaptive_limit_recovers(self):
        clock = _Clock()
        control = GlobalRuntimeController(
            requested_limit=4,
            cooldown_seconds=10,
            auth_failures_before_abort=2,
            rate_limit_failures_before_abort=10,
            rate_limit_window_seconds=300,
            adaptive_enabled=True,
            adaptive_scale_down_threshold=2,
            adaptive_recovery_seconds=30,
            clock=clock,
        )
        control.request_cooldown(retry_after=12)
        self.assertFalse(control.dispatch_allowed)
        control.request_cooldown(retry_after=12)
        self.assertEqual(control.active_limit, 3)
        clock.advance(13)
        self.assertTrue(control.dispatch_allowed)
        clock.advance(30)
        control.tick()
        self.assertEqual(control.active_limit, 4)
        snapshot = control.snapshot()
        self.assertEqual(snapshot.scale_downs, 1)
        self.assertEqual(snapshot.scale_ups, 1)
        self.assertEqual(snapshot.cooldown_requested_seconds, 12)

    def test_repeated_same_incident_extends_without_double_counting(self):
        clock = _Clock()
        control = GlobalRuntimeController(
            requested_limit=4,
            cooldown_seconds=10,
            rate_limit_failures_before_abort=2,
            rate_limit_window_seconds=300,
            adaptive_enabled=True,
            adaptive_scale_down_threshold=2,
            adaptive_recovery_seconds=30,
            clock=clock,
        )
        incident = rate_limit_incident_id("worker-001", "job-a", 1)
        self.assertTrue(control.request_cooldown(incident_key=incident))
        clock.advance(5)
        self.assertFalse(
            control.request_cooldown(retry_after=20, incident_key=incident)
        )
        snapshot = control.snapshot()
        self.assertEqual(snapshot.rate_limit_events, 1)
        self.assertEqual(snapshot.active_limit, 4)
        self.assertIsNone(snapshot.circuit_open_reason)
        self.assertGreaterEqual(snapshot.cooldown_remaining, 20)

    def test_distinct_incidents_from_same_job_are_counted(self):
        clock = _Clock()
        control = GlobalRuntimeController(
            requested_limit=4,
            cooldown_seconds=10,
            rate_limit_failures_before_abort=2,
            rate_limit_window_seconds=300,
            adaptive_enabled=True,
            adaptive_scale_down_threshold=2,
            adaptive_recovery_seconds=30,
            clock=clock,
        )
        first = rate_limit_incident_id("worker-001", "job-a", 1)
        second = rate_limit_incident_id("worker-001", "job-a", 2)
        self.assertTrue(control.request_cooldown(incident_key=first))
        clock.advance(5)
        self.assertTrue(control.request_cooldown(incident_key=second))
        snapshot = control.snapshot()
        self.assertEqual(snapshot.rate_limit_events, 2)
        self.assertEqual(snapshot.active_limit, 3)
        self.assertIn("rate-limit circuit", snapshot.circuit_open_reason or "")

    def test_auth_circuit_opens_at_global_threshold(self):
        clock = _Clock()
        control = GlobalRuntimeController(
            requested_limit=3,
            auth_failures_before_abort=2,
            clock=clock,
        )
        control.record_auth_failure()
        self.assertIsNone(control.circuit_open_reason)
        self.assertTrue(control.dispatch_allowed)
        control.record_auth_failure()
        self.assertIn("authentication circuit", control.circuit_open_reason or "")
        self.assertFalse(control.dispatch_allowed)

    def test_rate_limit_circuit_counts_only_events_inside_window(self):
        clock = _Clock()
        control = GlobalRuntimeController(
            requested_limit=1,
            cooldown_seconds=0,
            rate_limit_failures_before_abort=3,
            rate_limit_window_seconds=10,
            clock=clock,
        )
        control.request_cooldown()
        clock.advance(11)
        control.request_cooldown()
        clock.advance(11)
        control.request_cooldown()
        self.assertEqual(control.rate_limit_event_count, 3)
        self.assertIsNone(control.circuit_open_reason)
        control.request_cooldown()
        control.request_cooldown()
        self.assertIn("within 10s", control.circuit_open_reason or "")


if __name__ == "__main__":
    unittest.main()
