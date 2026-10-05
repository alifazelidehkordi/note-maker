"""Persistent admission control for a scheduled rest (plan item 6).

After every ``interval`` completed files the coordinator pauses new job
admissions for ``seconds``. State persists across coordinator restarts so a
crashed run does not re-trigger the pause. This is a faithful port of the
user's battle-tested ``rest_schedule.py`` (untracked local file, proven over
multi-subject batches); the coordinator supplies the global completed count
(any base offset already included) at the call site, exactly as the original
wrapper did with NOTE_MAKER_REST_BASE_COMPLETED.
"""

from __future__ import annotations

import json
import time
from pathlib import Path


class RestSchedule:
    """Admission-control gate: caps dispatch capacity around rest boundaries."""

    def __init__(
        self,
        path,
        *,
        interval: int = 50,
        seconds: float = 1800,
        clock=time.time,
        logger=None,
    ) -> None:
        self.path = Path(path)
        self.interval = int(interval)
        self.seconds = float(seconds)
        if self.interval <= 0 or self.seconds < 0:
            raise ValueError("Rest interval must be positive and duration nonnegative")
        self.clock = clock
        self.logger = logger
        self.state = (
            json.loads(self.path.read_text())
            if self.path.exists()
            else {"last_pause_after": 0, "until": 0}
        )

    def capacity(self, *, completed: int, busy: int, available: int) -> int:
        """Return the dispatch capacity allowed at this instant.

        ``completed`` is the GLOBAL completed count (any base offset is
        already included by the caller). ``busy`` is the in-flight job
        count; the rest window opens only once in-flight jobs have drained.
        """
        now = self.clock()
        if now < self.state["until"]:
            return 0
        threshold = self.state["last_pause_after"] + self.interval
        if completed >= threshold:
            if busy:
                return 0
            self.state = {
                "last_pause_after": threshold,
                "until": now + self.seconds,
                "interval": self.interval,
                "duration_seconds": self.seconds,
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.state, indent=2))
            tmp.replace(self.path)
            if self.logger:
                self.logger(
                    f"Scheduled rest after {threshold} completed files: "
                    f"{self.seconds:.0f}s, resumes at epoch {self.state['until']:.0f}"
                )
            return 0
        return max(0, min(available, threshold - completed - busy))
