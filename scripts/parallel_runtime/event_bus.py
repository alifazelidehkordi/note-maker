from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


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
    STAGE = "stage"
    RETRY_SCHEDULED = "retry_scheduled"
    GLOBAL_COOLDOWN_REQUESTED = "global_cooldown_requested"
    AUTH_FAILURE = "auth_failure"
    HEARTBEAT = "heartbeat"
    JOB_SUCCEEDED = "job_succeeded"
    JOB_FAILED = "job_failed"
    DIAGNOSTIC_SAVED = "diagnostic_saved"
    WORKER_STOPPED = "worker_stopped"
    WORKER_FATAL = "worker_fatal"


class StageKind(str, Enum):
    PREPARING_BROWSER = "preparing_browser"
    WAITING_FOR_LOGIN = "waiting_for_login"
    UPLOADING = "uploading"
    WAITING_FOR_RESPONSE = "waiting_for_response"
    RESOLVING_DOWNLOAD = "resolving_download"
    VALIDATING = "validating"
    SAVING = "saving"
    COMPLETED = "completed"


class StagePhase(str, Enum):
    STARTED = "started"
    COMPLETED = "completed"


@dataclass(frozen=True)
class StageEventData:
    """Structured stage payload carried by the existing worker event stream."""

    run_id: str
    worker_id: str
    source_filename: str
    stage: StageKind
    phase: StagePhase
    stage_started_at: str
    elapsed_seconds: float
    last_activity_at: str
    attempt: int | None = None

    def to_payload(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "worker_id": self.worker_id,
            "source_filename": self.source_filename,
            "attempt": self.attempt,
            "stage": self.stage.value,
            "phase": self.phase.value,
            "stage_started_at": self.stage_started_at,
            "elapsed_seconds": self.elapsed_seconds,
            "last_activity_at": self.last_activity_at,
        }


@dataclass(frozen=True)
class WorkerCommand:
    kind: CommandKind
    job_payload: dict[str, object] | None = None
    reason: str | None = None

    @classmethod
    def run_job(cls, payload: dict[str, object]) -> WorkerCommand:
        return cls(CommandKind.RUN_JOB, job_payload=payload)

    @classmethod
    def stop(cls, reason: str = "coordinator shutdown") -> WorkerCommand:
        return cls(CommandKind.STOP, reason=reason)


@dataclass(frozen=True)
class WorkerEvent:
    kind: EventKind
    worker_id: str
    runtime_worker_id: str | None = None
    job_key: str | None = None
    payload: Mapping[str, object] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)

    def with_payload(self, **payload: object) -> WorkerEvent:
        return WorkerEvent(
            kind=self.kind,
            worker_id=self.worker_id,
            runtime_worker_id=self.runtime_worker_id,
            job_key=self.job_key,
            payload={**dict(self.payload), **payload},
            created_at=self.created_at,
        )
