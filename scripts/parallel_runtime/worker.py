from __future__ import annotations

import importlib
import os
import threading
import traceback
from queue import Empty
from typing import Callable

from .event_bus import CommandKind, EventKind, WorkerEvent
from .models import ExecutionJob, RunConfig, WorkerExecutionResult
from .resilience import FailureCategory, classify_failure


def _load_symbol(path: str):
    module_name, separator, symbol_name = path.partition(":")
    if not separator:
        raise ValueError(f"Import path must use module:symbol syntax: {path}")
    module = importlib.import_module(module_name)
    return getattr(module, symbol_name)


def worker_process_main(
    worker_id: str,
    runtime_worker_id: str,
    run_config_payload: dict[str, object],
    command_queue,
    event_queue,
) -> None:
    """Spawn-safe worker entry point. Workers never open or mutate ManifestStore."""
    config = RunConfig.from_payload(run_config_payload)
    current_job_key: list[str | None] = [None]
    stop_heartbeat = threading.Event()

    def emit(kind: EventKind, *, job_key: str | None = None, **payload: object) -> None:
        event_queue.put(
            WorkerEvent(
                kind=kind,
                worker_id=worker_id,
                runtime_worker_id=runtime_worker_id,
                job_key=job_key if job_key is not None else current_job_key[0],
                payload=payload,
            )
        )

    def heartbeat_loop() -> None:
        while not stop_heartbeat.wait(config.heartbeat_interval):
            emit(
                EventKind.HEARTBEAT,
                pid=os.getpid(),
                runtime_worker_id=runtime_worker_id,
            )

    executor = None
    heartbeat = threading.Thread(
        target=heartbeat_loop,
        name=f"{worker_id}-heartbeat",
        daemon=True,
    )
    try:
        executor_type = _load_symbol(config.executor_path)
        executor = executor_type(
            config=dict(config.executor_config),
            run_id=config.run_id,
            worker_id=runtime_worker_id,
            emit=emit,
        )
        heartbeat.start()
        emit(
            EventKind.WORKER_READY,
            pid=os.getpid(),
            runtime_worker_id=runtime_worker_id,
        )
        emit(EventKind.JOB_REQUESTED, pid=os.getpid())

        while True:
            try:
                command = command_queue.get(timeout=max(0.1, config.heartbeat_interval))
            except Empty:
                continue
            if command.kind == CommandKind.STOP:
                break
            if command.kind != CommandKind.RUN_JOB or command.job_payload is None:
                continue

            job = ExecutionJob.from_payload(command.job_payload)
            current_job_key[0] = job.key
            emit(EventKind.JOB_STARTED, job_key=job.key, pid=os.getpid())
            try:
                result = executor.execute(job)
                if not isinstance(result, WorkerExecutionResult):
                    raise TypeError(
                        f"Executor returned {type(result).__name__}; expected WorkerExecutionResult."
                    )
            except BaseException as exc:
                category = classify_failure(exc)
                if category == FailureCategory.AUTH:
                    emit(EventKind.AUTH_FAILURE, job_key=job.key, error=str(exc))
                elif category == FailureCategory.RATE_LIMIT:
                    retry_after = getattr(exc, "retry_after", None)
                    emit(
                        EventKind.GLOBAL_COOLDOWN_REQUESTED,
                        job_key=job.key,
                        retry_after=retry_after,
                    )
                result = WorkerExecutionResult(
                    success=False,
                    error=f"{type(exc).__name__}: {exc}",
                    failure_category=category.value,
                    retryable=False,
                    retry_after=getattr(exc, "retry_after", None),
                    metadata={"traceback": traceback.format_exc()},
                )

            if not result.success:
                category = result.failure_category
                metadata = dict(result.metadata)
                if category == FailureCategory.AUTH.value and not metadata.get("auth_signaled"):
                    emit(EventKind.AUTH_FAILURE, job_key=job.key, error=result.error)
                elif category == FailureCategory.RATE_LIMIT.value and not metadata.get("rate_limit_signaled"):
                    emit(
                        EventKind.GLOBAL_COOLDOWN_REQUESTED,
                        job_key=job.key,
                        retry_after=result.retry_after,
                    )

            emit(
                EventKind.JOB_SUCCEEDED if result.success else EventKind.JOB_FAILED,
                job_key=job.key,
                **result.to_payload(),
            )
            current_job_key[0] = None
            emit(EventKind.JOB_REQUESTED, pid=os.getpid())
    except BaseException as exc:
        category = classify_failure(exc)
        if category == FailureCategory.AUTH:
            emit(EventKind.AUTH_FAILURE, error=str(exc), startup=True)
        elif category == FailureCategory.RATE_LIMIT:
            emit(
                EventKind.GLOBAL_COOLDOWN_REQUESTED,
                retry_after=getattr(exc, "retry_after", None),
                startup=True,
            )
        emit(
            EventKind.WORKER_FATAL,
            error=f"{type(exc).__name__}: {exc}",
            failure_category=category.value,
            traceback=traceback.format_exc(),
            pid=os.getpid(),
        )
        raise
    finally:
        stop_heartbeat.set()
        if heartbeat.is_alive():
            heartbeat.join(timeout=1.0)
        if executor is not None:
            try:
                executor.close()
            except BaseException as exc:
                emit(EventKind.WORKER_FATAL, error=f"executor close failed: {exc}")
        emit(EventKind.WORKER_STOPPED, pid=os.getpid())
