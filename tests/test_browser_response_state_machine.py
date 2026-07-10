from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from browser_runtime.state_machine import (
    ResponseObservation,
    ResponseState,
    ResponseStateMachine,
)


class BrowserResponseStateMachineTests(unittest.TestCase):
    def test_generation_download_and_stability_transitions_are_deterministic(self):
        machine = ResponseStateMachine(required_assistant_count=1, stable_seconds=2)
        self.assertEqual(
            machine.observe(ResponseObservation(0, False, "initial", now=0)),
            ResponseState.WAITING,
        )
        self.assertEqual(
            machine.observe(ResponseObservation(1, True, "partial", now=1)),
            ResponseState.GENERATING,
        )
        self.assertEqual(
            machine.observe(ResponseObservation(1, False, "done", has_download=True, now=2)),
            ResponseState.DOWNLOAD_READY,
        )

        stable = ResponseStateMachine(required_assistant_count=1, stable_seconds=2)
        self.assertEqual(
            stable.observe(ResponseObservation(1, False, "done", now=3)),
            ResponseState.WAITING,
        )
        self.assertEqual(
            stable.observe(ResponseObservation(1, False, "done", now=4)),
            ResponseState.WAITING,
        )
        self.assertEqual(
            stable.observe(ResponseObservation(1, False, "done", now=6)),
            ResponseState.STABLE,
        )

    def test_rate_limit_has_priority_over_other_states(self):
        machine = ResponseStateMachine(required_assistant_count=1)
        state = machine.observe(
            ResponseObservation(1, True, "done", has_download=True, rate_limited=True, now=1)
        )
        self.assertEqual(state, ResponseState.RATE_LIMITED)


if __name__ == "__main__":
    unittest.main()
