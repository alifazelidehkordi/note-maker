from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Mapping


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CommandKind(str, Enum):
    RUN_JOB = "run_job"
    STOP = "stop"


class EventKind(str, Enum):
    WORKER_READY = "worker_ready"
    JOB_REQUESTED = "job_requested"
    JOB_STARTED = "job_started"
    ATTEMPT_STARTED = "attempt_started"
    RETRY_SCHEDULED = "retry_scheduled"
    GLOBAL_COOLDOWN_REQUESTED = "global_cooldown_requested"
    AUTH_FAILURE = "auth_failure"
    HEARTBEAT = "heartbeat"
    JOB_SUCCEEDED = "job_succeeded"
    JOB_FAILED = "job_failed"
    DIAGNOSTIC_SAVED = "diagnostic_saved"
    WORKER_STOPPED = "worker_stopped"
    WORKER_FATAL = "worker_fatal"


@dataclass(frozen=True)
class WorkerCommand:
    kind: CommandKind
    job_payload: dict[str, object] | None = None
    reason: str | None = None

    @classmethod
    def run_job(cls, payload: dict[str, object]) -> "WorkerCommand":
        return cls(CommandKind.RUN_JOB, job_payload=payload)

    @classmethod
    def stop(cls, reason: str = "coordinator shutdown") -> "WorkerCommand":
        return cls(CommandKind.STOP, reason=reason)


@dataclass(frozen=True)
class WorkerEvent:
    kind: EventKind
    worker_id: str
    runtime_worker_id: str | None = None
    job_key: str | None = None
    payload: Mapping[str, object] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)

    def with_payload(self, **payload: object) -> "WorkerEvent":
        return WorkerEvent(
            kind=self.kind,
            worker_id=self.worker_id,
            runtime_worker_id=self.runtime_worker_id,
            job_key=self.job_key,
            payload={**dict(self.payload), **payload},
            created_at=self.created_at,
        )
