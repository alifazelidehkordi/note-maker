from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Generic, TypeVar

T = TypeVar("T")


def _normalize_extensions(values: Iterable[str]) -> tuple[str, ...]:
    normalized = {
        value if value.startswith(".") else f".{value}"
        for raw in values
        if (value := str(raw).strip().lower())
    }
    return tuple(sorted(normalized))


def estimate_file_weight(path: Path, *, bytes_per_unit: int = 256 * 1024) -> int:
    """Return a deterministic coarse scheduling weight for a source file."""
    size = max(0, Path(path).stat().st_size)
    return max(1, math.ceil(size / max(1, bytes_per_unit)))


def estimate_text_weight(text: str, *, characters_per_unit: int = 4_000) -> int:
    """Return a deterministic coarse scheduling weight for text/section jobs."""
    return max(1, math.ceil(len(text.encode("utf-8")) / max(1, characters_per_unit)))


@dataclass(frozen=True)
class ExecutionJob:
    """Browser-neutral, serializable job identity used by planners and workers."""

    key: str
    source: Path
    source_hash: str
    prompt_path: Path
    prompt_hash: str
    output: Path
    expected_extensions: tuple[str, ...]
    mode: str
    model: str | None = None
    title: str | None = None
    estimated_weight: int = 1
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise ValueError("ExecutionJob.key must not be empty.")
        if self.estimated_weight < 1:
            raise ValueError("ExecutionJob.estimated_weight must be at least 1.")
        object.__setattr__(self, "source", Path(self.source).resolve())
        object.__setattr__(self, "prompt_path", Path(self.prompt_path).resolve())
        object.__setattr__(self, "output", Path(self.output).resolve())
        object.__setattr__(
            self,
            "expected_extensions",
            _normalize_extensions(self.expected_extensions),
        )
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType({str(k): str(v) for k, v in dict(self.metadata).items()}),
        )

    @property
    def prompt(self) -> Path:
        """Compatibility alias retained for the pre-Level-4 JobSpec API."""
        return self.prompt_path

    def to_payload(self) -> dict[str, object]:
        return {
            "key": self.key,
            "source": str(self.source),
            "source_hash": self.source_hash,
            "prompt_path": str(self.prompt_path),
            "prompt_hash": self.prompt_hash,
            "output": str(self.output),
            "expected_extensions": list(self.expected_extensions),
            "mode": self.mode,
            "model": self.model,
            "title": self.title,
            "estimated_weight": self.estimated_weight,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> ExecutionJob:
        return cls(
            key=str(payload["key"]),
            source=Path(str(payload["source"])),
            source_hash=str(payload["source_hash"]),
            prompt_path=Path(str(payload["prompt_path"])),
            prompt_hash=str(payload["prompt_hash"]),
            output=Path(str(payload["output"])),
            expected_extensions=tuple(str(v) for v in payload.get("expected_extensions", ())),
            mode=str(payload["mode"]),
            model=(None if payload.get("model") is None else str(payload.get("model"))),
            title=(None if payload.get("title") is None else str(payload.get("title"))),
            estimated_weight=int(payload.get("estimated_weight", 1)),
            metadata={str(k): str(v) for k, v in dict(payload.get("metadata", {})).items()},
        )


@dataclass(frozen=True)
class RunConfig:
    """Serializable coordinator configuration shared with spawned workers."""

    run_id: str
    manifest_path: Path
    claims_dir: Path
    worker_count: int
    executor_path: str
    executor_config: Mapping[str, object] = field(default_factory=dict)
    heartbeat_interval: float = 10.0
    worker_timeout: float = 45.0
    worker_ready_timeout: float = 180.0
    startup_stagger: float = 1.0
    max_worker_restarts: int = 2
    shutdown_grace: float = 10.0
    claim_stale_after: float = 90.0
    poll_interval: float = 0.1
    external_claim_wait: float = 300.0
    global_rate_limit_cooldown: float = 180.0
    auth_failures_before_abort: int = 2
    rate_limit_failures_before_abort: int = 6
    rate_limit_window_seconds: float = 300.0
    adaptive_concurrency: bool = False
    adaptive_scale_down_threshold: int = 2
    adaptive_recovery_seconds: float = 900.0
    worker_max_jobs: int = 20
    worker_memory_limit_mb: float = 0.0
    job_timeout: float = 1800.0
    content_attempts: int = 3
    network_retries: int = 4
    browser_retries: int = 3
    download_retries: int = 2
    rate_limit_retries: int = 2
    retry_backoff_base: float = 3.0
    retry_backoff_cap: float = 24.0
    retry_jitter_ratio: float = 0.20
    rest_every: int = 0
    rest_seconds: float = 1800.0
    rest_state: str | None = None
    rest_base_completed: int = 0

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("RunConfig.run_id must not be empty.")
        if self.worker_count < 1:
            raise ValueError("RunConfig.worker_count must be at least 1.")
        if self.heartbeat_interval <= 0:
            raise ValueError("RunConfig.heartbeat_interval must be positive.")
        if self.worker_timeout <= self.heartbeat_interval:
            raise ValueError("RunConfig.worker_timeout must exceed heartbeat_interval.")
        if self.worker_ready_timeout <= 0:
            raise ValueError("RunConfig.worker_ready_timeout must be positive.")
        if self.max_worker_restarts < 0:
            raise ValueError("RunConfig.max_worker_restarts must not be negative.")
        if self.global_rate_limit_cooldown < 0:
            raise ValueError("global_rate_limit_cooldown must not be negative.")
        if self.auth_failures_before_abort < 1:
            raise ValueError("auth_failures_before_abort must be at least 1.")
        if self.rate_limit_failures_before_abort < 0:
            raise ValueError("rate_limit_failures_before_abort must not be negative.")
        if self.worker_max_jobs < 0:
            raise ValueError("worker_max_jobs must not be negative.")
        if self.worker_memory_limit_mb < 0:
            raise ValueError("worker_memory_limit_mb must not be negative.")
        if self.job_timeout < 0:
            raise ValueError("job_timeout must not be negative.")
        for name in ("content_attempts", "network_retries", "browser_retries", "download_retries", "rate_limit_retries"):
            value = int(getattr(self, name))
            if value < (1 if name == "content_attempts" else 0):
                raise ValueError(f"{name} has an invalid value.")
        if self.retry_backoff_base < 0 or self.retry_backoff_cap < 0:
            raise ValueError("retry backoff values must not be negative.")
        if not 0 <= self.retry_jitter_ratio <= 1:
            raise ValueError("retry_jitter_ratio must be between 0 and 1.")
        if self.rest_every < 0:
            raise ValueError("rest_every must not be negative.")
        if self.rest_seconds < 0:
            raise ValueError("rest_seconds must not be negative.")
        if self.rest_base_completed < 0:
            raise ValueError("rest_base_completed must not be negative.")
        object.__setattr__(self, "manifest_path", Path(self.manifest_path).resolve())
        object.__setattr__(self, "claims_dir", Path(self.claims_dir).resolve())
        object.__setattr__(self, "executor_config", MappingProxyType(dict(self.executor_config)))

    def to_payload(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "manifest_path": str(self.manifest_path),
            "claims_dir": str(self.claims_dir),
            "worker_count": self.worker_count,
            "executor_path": self.executor_path,
            "executor_config": dict(self.executor_config),
            "heartbeat_interval": self.heartbeat_interval,
            "worker_timeout": self.worker_timeout,
            "worker_ready_timeout": self.worker_ready_timeout,
            "startup_stagger": self.startup_stagger,
            "max_worker_restarts": self.max_worker_restarts,
            "shutdown_grace": self.shutdown_grace,
            "claim_stale_after": self.claim_stale_after,
            "poll_interval": self.poll_interval,
            "external_claim_wait": self.external_claim_wait,
            "global_rate_limit_cooldown": self.global_rate_limit_cooldown,
            "auth_failures_before_abort": self.auth_failures_before_abort,
            "rate_limit_failures_before_abort": self.rate_limit_failures_before_abort,
            "rate_limit_window_seconds": self.rate_limit_window_seconds,
            "adaptive_concurrency": self.adaptive_concurrency,
            "adaptive_scale_down_threshold": self.adaptive_scale_down_threshold,
            "adaptive_recovery_seconds": self.adaptive_recovery_seconds,
            "worker_max_jobs": self.worker_max_jobs,
            "worker_memory_limit_mb": self.worker_memory_limit_mb,
            "job_timeout": self.job_timeout,
            "content_attempts": self.content_attempts,
            "network_retries": self.network_retries,
            "browser_retries": self.browser_retries,
            "download_retries": self.download_retries,
            "rate_limit_retries": self.rate_limit_retries,
            "retry_backoff_base": self.retry_backoff_base,
            "retry_backoff_cap": self.retry_backoff_cap,
            "retry_jitter_ratio": self.retry_jitter_ratio,
            "rest_every": self.rest_every,
            "rest_seconds": self.rest_seconds,
            "rest_state": self.rest_state,
            "rest_base_completed": self.rest_base_completed,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> RunConfig:
        return cls(
            run_id=str(payload["run_id"]),
            manifest_path=Path(str(payload["manifest_path"])),
            claims_dir=Path(str(payload["claims_dir"])),
            worker_count=int(payload["worker_count"]),
            executor_path=str(payload["executor_path"]),
            executor_config=dict(payload.get("executor_config", {})),
            heartbeat_interval=float(payload.get("heartbeat_interval", 10.0)),
            worker_timeout=float(payload.get("worker_timeout", 45.0)),
            worker_ready_timeout=float(payload.get("worker_ready_timeout", 180.0)),
            startup_stagger=float(payload.get("startup_stagger", 1.0)),
            max_worker_restarts=int(payload.get("max_worker_restarts", 2)),
            shutdown_grace=float(payload.get("shutdown_grace", 10.0)),
            claim_stale_after=float(payload.get("claim_stale_after", 90.0)),
            poll_interval=float(payload.get("poll_interval", 0.1)),
            external_claim_wait=float(payload.get("external_claim_wait", 300.0)),
            global_rate_limit_cooldown=float(payload.get("global_rate_limit_cooldown", 180.0)),
            auth_failures_before_abort=int(payload.get("auth_failures_before_abort", 2)),
            rate_limit_failures_before_abort=int(payload.get("rate_limit_failures_before_abort", 6)),
            rate_limit_window_seconds=float(payload.get("rate_limit_window_seconds", 300.0)),
            adaptive_concurrency=bool(payload.get("adaptive_concurrency", False)),
            adaptive_scale_down_threshold=int(payload.get("adaptive_scale_down_threshold", 2)),
            adaptive_recovery_seconds=float(payload.get("adaptive_recovery_seconds", 900.0)),
            worker_max_jobs=int(payload.get("worker_max_jobs", 20)),
            worker_memory_limit_mb=float(payload.get("worker_memory_limit_mb", 0.0)),
            job_timeout=float(payload.get("job_timeout", 1800.0)),
            content_attempts=int(payload.get("content_attempts", 3)),
            network_retries=int(payload.get("network_retries", 4)),
            browser_retries=int(payload.get("browser_retries", 3)),
            download_retries=int(payload.get("download_retries", 2)),
            rate_limit_retries=int(payload.get("rate_limit_retries", 2)),
            retry_backoff_base=float(payload.get("retry_backoff_base", 3.0)),
            retry_backoff_cap=float(payload.get("retry_backoff_cap", 24.0)),
            retry_jitter_ratio=float(payload.get("retry_jitter_ratio", 0.20)),
            rest_every=int(payload.get("rest_every", 0)),
            rest_seconds=float(payload.get("rest_seconds", 1800.0)),
            rest_state=(
                str(payload["rest_state"])
                if payload.get("rest_state") is not None
                else None
            ),
            rest_base_completed=int(payload.get("rest_base_completed", 0)),
        )


@dataclass(frozen=True)
class WorkerExecutionResult:
    success: bool
    error: str | None = None
    diagnostics: str | None = None
    browser_restarts: int = 0
    rate_limit_count: int = 0
    failure_category: str | None = None
    retryable: bool = False
    download_fallbacks: int = 0
    last_fallback_reason: str | None = None
    delivery_mode: str | None = None
    interrupted_at_stage: str | None = None
    retry_after: float | None = None
    retry_counts: Mapping[str, int] = field(default_factory=dict)
    metadata: Mapping[str, object] = field(default_factory=dict)

    def to_payload(self) -> dict[str, object]:
        return {
            "success": self.success,
            "error": self.error,
            "diagnostics": self.diagnostics,
            "browser_restarts": self.browser_restarts,
            "rate_limit_count": self.rate_limit_count,
            "failure_category": self.failure_category,
            "retryable": self.retryable,
            "retry_after": self.retry_after,
            "retry_counts": dict(self.retry_counts),
            "metadata": dict(self.metadata),
            "download_fallbacks": self.download_fallbacks,
            "last_fallback_reason": self.last_fallback_reason,
            "delivery_mode": self.delivery_mode,
            "interrupted_at_stage": self.interrupted_at_stage,
        }


@dataclass(frozen=True)
class PlanningCandidate(Generic[T]):
    label: str
    payload: T
    job: ExecutionJob


@dataclass(frozen=True)
class PlanningOptions:
    overwrite: bool = False
    resume: bool = True
    adopt_existing: bool = False
    retry_failed_only: bool = False


@dataclass(frozen=True)
class PlannedJob(Generic[T]):
    candidate: PlanningCandidate[T]
    reason: str
    previous_status: str | None = None

    @property
    def job(self) -> ExecutionJob:
        return self.candidate.job

    @property
    def payload(self) -> T:
        return self.candidate.payload

    @property
    def label(self) -> str:
        return self.candidate.label


class TransitionKind(str, Enum):
    PENDING = "pending"
    INVALIDATED = "invalidated"
    ADOPTED = "adopted"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True)
class ManifestTransition:
    kind: TransitionKind
    job: ExecutionJob
    reason: str | None = None


@dataclass(frozen=True)
class JobPlan(Generic[T]):
    run_id: str
    candidates: tuple[PlanningCandidate[T], ...]
    runnable: tuple[PlannedJob[T], ...]
    skipped: Mapping[str, str]
    adopted: tuple[str, ...]
    completed_skip_count: int
    transitions: tuple[ManifestTransition, ...]

    @property
    def requires_worker(self) -> bool:
        return bool(self.runnable)

    @property
    def estimated_total_weight(self) -> int:
        return sum(item.job.estimated_weight for item in self.runnable)

    @property
    def initial_successes(self) -> int:
        return len(self.adopted) + self.completed_skip_count
