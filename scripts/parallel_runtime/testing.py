from __future__ import annotations

import hashlib
import json
import os
import signal
import time
from pathlib import Path
from typing import Callable

from .event_bus import EventKind
from .models import ExecutionJob, WorkerExecutionResult
from .resilience import FailureCategory, RetryBudgetPolicy, RetryTracker


class ScriptedExecutor:
    """Spawn-safe deterministic executor used by Level-5 concurrency tests."""

    def __init__(self, *, config: dict[str, object], run_id: str, worker_id: str, emit: Callable) -> None:
        self.config = config
        self.run_id = run_id
        self.worker_id = worker_id
        self.emit = emit
        startup_failure = str(self.config.get("startup_failure") or "").strip().lower()
        if startup_failure == "auth":
            from browser_runtime.errors import AuthenticationRequiredError
            raise AuthenticationRequiredError("scripted authentication failure")
        if startup_failure == "rate_limit":
            from browser_runtime.errors import RateLimitError
            raise RateLimitError(
                "scripted startup rate limit",
                retry_after=int(self.config.get("startup_retry_after", 1)),
            )

    def execute(self, job: ExecutionJob) -> WorkerExecutionResult:
        behavior = dict(self.config.get("behaviors", {})).get(job.key, {})
        if not isinstance(behavior, dict):
            behavior = {}
        marker_root = Path(str(self.config.get("marker_root") or job.output.parent / ".test-markers"))
        marker_root.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(job.key.encode("utf-8")).hexdigest()
        crash_count = max(0, int(behavior.get("crash_count", 0)))
        for index in range(1, crash_count + 1):
            crash_marker = marker_root / f"{digest}-crash-{index:03d}.marker"
            try:
                fd = os.open(
                    crash_marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
                )
            except FileExistsError:
                continue
            else:
                os.close(fd)
                os._exit(int(behavior.get("exit_code", 23)))

        freeze_count = max(0, int(behavior.get("freeze_count", 0)))
        if hasattr(signal, "SIGSTOP"):
            for index in range(1, freeze_count + 1):
                freeze_marker = marker_root / f"{digest}-freeze-{index:03d}.marker"
                try:
                    fd = os.open(
                        freeze_marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
                    )
                except FileExistsError:
                    continue
                else:
                    os.close(fd)
                    os.kill(os.getpid(), signal.SIGSTOP)
                    break

        if (
            behavior.get("ignore_sigterm")
            and hasattr(signal, "SIGTERM")
            and hasattr(signal, "SIG_IGN")
        ):
            signal.signal(signal.SIGTERM, signal.SIG_IGN)

        started_at = time.time()
        cooldown = behavior.get("cooldown_request")
        if cooldown is not None:
            retry_after = float(cooldown)
            self.emit(
                EventKind.GLOBAL_COOLDOWN_REQUESTED,
                retry_after=retry_after,
                scripted=True,
            )
        auth_failure = bool(behavior.get("auth_failure"))
        if auth_failure:
            self.emit(EventKind.AUTH_FAILURE, error="scripted authentication failure")
            return WorkerExecutionResult(
                success=False,
                error="scripted authentication failure",
                failure_category=FailureCategory.AUTH.value,
            )

        transient_failures = max(0, int(behavior.get("network_failures", 0)))
        policy = RetryBudgetPolicy(
            content_attempts=1,
            network_retries=int(self.config.get("network_retries", 4)),
            browser_retries=0,
            download_retries=0,
            rate_limit_retries=0,
            backoff_base=float(self.config.get("retry_backoff_base", 0.01)),
            backoff_cap=float(self.config.get("retry_backoff_cap", 0.05)),
            jitter_ratio=0.0,
        )
        tracker = RetryTracker(policy, seed=job.key)
        for _ in range(transient_failures):
            error = ConnectionError("scripted transient network failure")
            decision = tracker.record(error, default_delay=0.0)
            self.emit(
                EventKind.RETRY_SCHEDULED,
                category=decision.category.value,
                count=decision.count,
                limit=decision.limit,
                delay_seconds=decision.delay_seconds,
                retry=decision.retry,
            )
            if not decision.retry:
                return WorkerExecutionResult(
                    success=False,
                    error=str(error),
                    failure_category=decision.category.value,
                    retry_counts=tracker.as_dict(),
                )
            time.sleep(decision.delay_seconds)

        self.emit(EventKind.ATTEMPT_STARTED, attempt=1, attempt_limit=1)
        time.sleep(float(behavior.get("duration", self.config.get("default_duration", 0.01))))
        if behavior.get("fail"):
            category = str(behavior.get("failure_category") or FailureCategory.CONTENT.value)
            return WorkerExecutionResult(
                success=False,
                error=str(behavior.get("error", "scripted failure")),
                failure_category=category,
            )

        job.output.parent.mkdir(parents=True, exist_ok=True)
        suffix = job.output.suffix.lower()
        if suffix == ".md":
            content = f"# Generated Notes\n\n## {job.title or job.key}\n\n" + ("Generated note content. " * 20) + "\n"
        elif suffix == ".opml":
            content = '<?xml version="1.0"?><opml version="2.0"><head><title>Generated</title></head><body><outline text="Generated"><outline text="Content"/></outline></body></opml>\n'
        else:
            content = "generated artifact\n" * 20
        job.output.write_text(content, encoding="utf-8")
        execution_log = self.config.get("execution_log")
        if execution_log:
            path = Path(str(execution_log))
            path.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "job": job.key,
                "worker": self.worker_id,
                "pid": os.getpid(),
                "run_id": self.run_id,
                "started_at": started_at,
                "completed_at": time.time(),
            }
            fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
        return WorkerExecutionResult(success=True)

    def close(self) -> None:
        return None
