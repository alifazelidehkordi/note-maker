from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from browser_runtime.errors import AuthenticationRequiredError, DownloadNotFoundError, RateLimitError
from parallel_runtime.resilience import (
    FailureCategory,
    GlobalRuntimeController,
    RetryBudgetPolicy,
    RetryTracker,
    classify_failure,
)


class _Clock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class RetryPolicyTests(unittest.TestCase):
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

    def test_rate_limit_retry_after_overrides_backoff(self):
        tracker = RetryTracker(RetryBudgetPolicy(rate_limit_retries=1, jitter_ratio=0.0))
        decision = tracker.record(RateLimitError("wait", retry_after=17))
        self.assertTrue(decision.retry)
        self.assertEqual(decision.delay_seconds, 17)


class GlobalControlTests(unittest.TestCase):
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

    def test_auth_circuit_opens_at_global_threshold(self):
        clock = _Clock()
        control = GlobalRuntimeController(
            requested_limit=3,
            auth_failures_before_abort=2,
            clock=clock,
        )
        control.record_auth_failure()
        self.assertIsNone(control.circuit_open_reason)
        self.assertFalse(control.dispatch_allowed)
        control.record_auth_failure()
        self.assertIn("authentication circuit", control.circuit_open_reason or "")


if __name__ == "__main__":
    unittest.main()
