from __future__ import annotations

import multiprocessing as mp
import signal
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from queue import Empty
from typing import Callable, Iterable

from artifact_validation import validate_artifact
from manifest import ManifestCoordinator, ManifestStore

from .claims import ClaimStore, JobClaim
from .event_bus import EventKind, WorkerCommand, WorkerEvent
from .models import ExecutionJob, RunConfig
from .process_hygiene import cleanup_descendants, descendant_pids, process_tree_rss_mb
from .resilience import GlobalRuntimeController
from .worker import worker_process_main


@dataclass
class CoordinatorResult:
    succeeded: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    diagnostics: dict[str, str] = field(default_factory=dict)
    externally_completed: list[str] = field(default_factory=list)
    worker_restarts: int = 0
    worker_recycles: int = 0
    zombie_processes_cleaned: int = 0
    stale_claims_recovered: int = 0
    interrupted: bool = False
    duration_seconds: float = 0.0
    assignments: dict[str, list[str]] = field(default_factory=dict)
    retry_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    rate_limit_events: int = 0
    auth_failures: int = 0
    global_cooldown_seconds: float = 0.0
    minimum_active_workers: int = 1
    final_active_workers: int = 1
    adaptive_scale_downs: int = 0
    adaptive_scale_ups: int = 0
    circuit_breaker_reason: str | None = None


@dataclass
class _WorkerSlot:
    worker_id: str
    generation: int
    process: object
    command_queue: object
    started_at: float
    last_heartbeat: float
    last_manifest_heartbeat: float
    event_queue: object | None = None
    ready: bool = False
    current_job: ExecutionJob | None = None
    claim: JobClaim | None = None
    stop_sent: bool = False
    requested_job: bool = False
    restarts: int = 0
    completed_jobs: int = 0
    recycle_requested: bool = False
    recycle_reason: str | None = None
    job_started_at: float | None = None


class ParallelCoordinator:
    """Single-writer coordinator with global resilience and adaptive scheduling."""

    def __init__(
        self,
        config: RunConfig,
        jobs: Iterable[ExecutionJob],
        *,
        manifest: ManifestCoordinator | None = None,
        mp_context=None,
        event_logger: Callable[[str], None] | None = None,
    ) -> None:
        self.config = config
        self.jobs = tuple(jobs)
        self.manifest = manifest or ManifestCoordinator(config.manifest_path)
        self.context = mp_context or mp.get_context("spawn")
        self.event_logger = event_logger
        # Retained for compatibility with callers that close the coordinator queue
        # directly. Worker generations use isolated queues so a force-killed worker
        # cannot poison the event channel used by its replacement.
        self.event_queue = self.context.Queue()
        self.claims = ClaimStore(config.claims_dir, stale_after=config.claim_stale_after)
        self.pending = deque(sorted(self.jobs, key=lambda job: (-job.estimated_weight, job.key)))
        self.slots: dict[str, _WorkerSlot] = {}
        self.result = CoordinatorResult(
            minimum_active_workers=max(1, config.worker_count),
            final_active_workers=max(1, config.worker_count),
        )
        self.control = GlobalRuntimeController(
            requested_limit=config.worker_count,
            cooldown_seconds=config.global_rate_limit_cooldown,
            auth_failures_before_abort=config.auth_failures_before_abort,
            rate_limit_failures_before_abort=config.rate_limit_failures_before_abort,
            rate_limit_window_seconds=config.rate_limit_window_seconds,
            adaptive_enabled=config.adaptive_concurrency,
            adaptive_scale_down_threshold=config.adaptive_scale_down_threshold,
            adaptive_recovery_seconds=config.adaptive_recovery_seconds,
            clock=time.monotonic,
        )
        self._blocked_since: dict[str, float] = {}
        self._started_at = 0.0
        self._last_worker_check = time.monotonic()
        self._shutting_down = False
        self._target_worker_count = min(config.worker_count, max(1, len(self.jobs)))
        self._next_worker_index = 1
        self._next_worker_start_at = 0.0
        self._circuit_applied = False
        self.result.stale_claims_recovered = len(self.claims.recover_stale())

    def _log(self, message: str) -> None:
        if self.event_logger is not None:
            self.event_logger(message)

    @staticmethod
    def _close_queue(queue) -> None:
        try:
            queue.close()
        except (AttributeError, OSError, ValueError):
            return
        try:
            queue.join_thread()
        except (AttributeError, RuntimeError):
            pass

    def _worker_id(self, index: int) -> str:
        return f"worker-{index:03d}"

    @staticmethod
    def _runtime_worker_id(slot: _WorkerSlot) -> str:
        return slot.worker_id if slot.generation == 1 else f"{slot.worker_id}-g{slot.generation:03d}"

    def _next_event(self) -> WorkerEvent | None:
        deadline = time.monotonic() + self.config.poll_interval
        while True:
            for slot in list(self.slots.values()):
                event_queue = slot.event_queue
                if event_queue is None:
                    continue
                try:
                    event = event_queue.get_nowait()
                except Empty:
                    continue
                except (EOFError, OSError, ValueError):
                    continue
                if isinstance(event, WorkerEvent):
                    return event
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            time.sleep(min(0.001, remaining))

    def _drain_pending_events(self) -> None:
        """Process queued worker state before evaluating liveness timeouts."""
        while True:
            handled = False
            for slot in list(self.slots.values()):
                event_queue = slot.event_queue
                if event_queue is None:
                    continue
                try:
                    event = event_queue.get_nowait()
                except Empty:
                    continue
                except (EOFError, OSError, ValueError):
                    continue
                if isinstance(event, WorkerEvent):
                    self._handle_event(event)
                    handled = True
            if not handled:
                return

    def _spawn_worker(self, worker_id: str, *, generation: int = 1, restarts: int = 0) -> _WorkerSlot:
        command_queue = self.context.Queue()
        event_queue = self.context.Queue()
        runtime_worker_id = worker_id if generation == 1 else f"{worker_id}-g{generation:03d}"
        process = self.context.Process(
            target=worker_process_main,
            name=f"note-maker-{self.config.run_id}-{worker_id}-g{generation}",
            args=(
                worker_id,
                runtime_worker_id,
                self.config.to_payload(),
                command_queue,
                event_queue,
            ),
        )
        process.start()
        now = time.monotonic()
        slot = _WorkerSlot(
            worker_id=worker_id,
            generation=generation,
            process=process,
            command_queue=command_queue,
            event_queue=event_queue,
            started_at=now,
            last_heartbeat=now,
            last_manifest_heartbeat=0.0,
            restarts=restarts,
        )
        self.slots[worker_id] = slot
        self.result.assignments.setdefault(worker_id, [])
        if hasattr(self.manifest, "register_worker"):
            self.manifest.register_worker(
                self.config.run_id,
                worker_id=worker_id,
                pid=process.pid,
                generation=generation,
                status="starting",
                runtime_worker_id=runtime_worker_id,
            )
        return slot

    def _start_workers(self) -> None:
        """Startup barrier: only the first worker starts before authentication is proven."""
        if self._target_worker_count <= 0:
            return
        self._spawn_worker(self._worker_id(self._next_worker_index))
        self._next_worker_index += 1
        self._next_worker_start_at = time.monotonic() + self.config.startup_stagger

    def _maybe_start_more_workers(self) -> None:
        if self._shutting_down or self.control.circuit_open_reason is not None:
            return
        if self._next_worker_index > self._target_worker_count:
            return
        first = self.slots.get(self._worker_id(1))
        if first is None or not first.ready:
            return
        if time.monotonic() < self._next_worker_start_at:
            return
        while self._next_worker_index <= self._target_worker_count:
            if time.monotonic() < self._next_worker_start_at:
                return
            index = self._next_worker_index
            self._spawn_worker(self._worker_id(index))
            self._next_worker_index += 1
            self._next_worker_start_at = time.monotonic() + self.config.startup_stagger
            if self.config.startup_stagger > 0:
                return

    def _job_completed_elsewhere(self, job: ExecutionJob) -> bool:
        entry = ManifestStore.reader(self.config.manifest_path).get(job.key)
        if not entry or entry.get("status") != "completed":
            return False
        return validate_artifact(job.output, job.expected_extensions, repair_opml=False).valid

    def _assign(self, slot: _WorkerSlot) -> bool:
        if slot.current_job is not None or not slot.process.is_alive() or slot.recycle_requested:
            return False
        attempts = len(self.pending)
        while attempts > 0 and self.pending:
            attempts -= 1
            job = self.pending.popleft()
            if self._job_completed_elsewhere(job):
                self.result.externally_completed.append(job.key)
                self._blocked_since.pop(job.key, None)
                continue
            claim = self.claims.try_acquire(
                job.key,
                run_id=self.config.run_id,
                worker_id=slot.worker_id,
                worker_pid=int(slot.process.pid or 0),
            )
            if claim is None:
                first_blocked = self._blocked_since.setdefault(job.key, time.monotonic())
                if time.monotonic() - first_blocked > self.config.external_claim_wait:
                    self.result.failed[job.key] = "Timed out waiting for an external job claim."
                    continue
                self.pending.append(job)
                continue
            self._blocked_since.pop(job.key, None)
            if self._job_completed_elsewhere(job):
                self.claims.release(claim)
                self.result.externally_completed.append(job.key)
                continue
            slot.current_job = job
            slot.claim = claim
            slot.job_started_at = time.monotonic()
            slot.requested_job = False
            slot.command_queue.put(WorkerCommand.run_job(job.to_payload()))
            self.result.assignments[slot.worker_id].append(job.key)
            if hasattr(self.manifest, "mark_worker_state"):
                self.manifest.mark_worker_state(
                    self.config.run_id,
                    worker_id=slot.worker_id,
                    status="busy",
                    current_job=job.key,
                )
            return True
        return False

    def _release_current(self, slot: _WorkerSlot) -> ExecutionJob | None:
        job = slot.current_job
        if slot.claim is not None:
            self.claims.release(slot.claim)
        slot.current_job = None
        slot.claim = None
        slot.job_started_at = None
        slot.requested_job = True
        return job

    def _complete_job(self, slot: _WorkerSlot, event: WorkerEvent) -> None:
        job = slot.current_job
        if job is None or event.job_key != job.key:
            return
        payload = dict(event.payload)
        retry_counts = {
            str(key): int(value)
            for key, value in dict(payload.get("retry_counts") or {}).items()
        }
        if retry_counts:
            self.result.retry_counts[job.key] = retry_counts
        if event.kind == EventKind.JOB_SUCCEEDED:
            try:
                self.manifest.mark_completed(
                    job,
                    run_id=self.config.run_id,
                    worker_id=slot.worker_id,
                    browser_restarts=int(payload.get("browser_restarts", 0)),
                    rate_limit_count=int(payload.get("rate_limit_count", 0)),
                )
                self.result.succeeded.append(job.key)
            except Exception as exc:
                message = f"Completion validation failed: {exc}"
                self.manifest.mark_failed(
                    job,
                    run_id=self.config.run_id,
                    worker_id=slot.worker_id,
                    error=message,
                    diagnostics=payload.get("diagnostics"),
                )
                self.result.failed[job.key] = message
        else:
            message = str(payload.get("error") or "Worker reported job failure.")
            self.manifest.mark_failed(
                job,
                run_id=self.config.run_id,
                worker_id=slot.worker_id,
                error=message,
                diagnostics=payload.get("diagnostics"),
                browser_restarts=int(payload.get("browser_restarts", 0)),
                rate_limit_count=int(payload.get("rate_limit_count", 0)),
            )
            self.result.failed[job.key] = message
        if payload.get("diagnostics"):
            self.result.diagnostics[job.key] = str(payload["diagnostics"])
        self._release_current(slot)
        slot.completed_jobs += 1
        if self.config.worker_max_jobs > 0 and slot.completed_jobs >= self.config.worker_max_jobs:
            slot.recycle_requested = True
            slot.recycle_reason = f"worker_max_jobs={self.config.worker_max_jobs} reached"
        if hasattr(self.manifest, "mark_worker_state"):
            self.manifest.mark_worker_state(
                self.config.run_id,
                worker_id=slot.worker_id,
                status="recycling" if slot.recycle_requested else "idle",
                current_job=None,
            )

    def _apply_control_event(self, event: WorkerEvent) -> None:
        if event.kind == EventKind.GLOBAL_COOLDOWN_REQUESTED:
            retry_after = event.payload.get("retry_after")
            before = self.control.snapshot()
            incident_key = event.job_key or event.worker_id
            is_new = self.control.request_cooldown(
                retry_after=None if retry_after is None else float(retry_after),
                incident_key=incident_key,
            )
            after = self.control.snapshot()
            disposition = "new incident" if is_new else "same job; cooldown extended"
            self._log(
                "Global rate-limit cooldown: "
                f"{after.cooldown_remaining:.0f}s remaining, source={incident_key} "
                f"({disposition}, distinct incidents={after.rate_limit_events})."
            )
            if after.active_limit < before.active_limit:
                self._log(
                    "Adaptive concurrency reduced active workers: "
                    f"{before.active_limit} -> {after.active_limit}."
                )
            if after.circuit_open_reason and after.circuit_open_reason != before.circuit_open_reason:
                self._log(f"Circuit breaker opened: {after.circuit_open_reason}.")
        elif event.kind == EventKind.AUTH_FAILURE:
            self.control.record_auth_failure()

    def _handle_event(self, event: WorkerEvent) -> None:
        slot = self.slots.get(event.worker_id)
        if slot is None:
            return
        if event.runtime_worker_id is not None and event.runtime_worker_id != self._runtime_worker_id(slot):
            return
        now = time.monotonic()
        if event.kind in {EventKind.WORKER_READY, EventKind.HEARTBEAT, EventKind.JOB_STARTED}:
            slot.last_heartbeat = now
        if event.kind in {EventKind.GLOBAL_COOLDOWN_REQUESTED, EventKind.AUTH_FAILURE}:
            self._apply_control_event(event)
        if event.kind == EventKind.WORKER_READY:
            slot.ready = True
            slot.requested_job = True
            if hasattr(self.manifest, "mark_worker_state"):
                self.manifest.mark_worker_state(
                    self.config.run_id,
                    worker_id=slot.worker_id,
                    status="idle",
                    pid=int(event.payload.get("pid") or slot.process.pid or 0),
                )
        elif event.kind == EventKind.JOB_REQUESTED:
            slot.requested_job = True
        elif event.kind == EventKind.ATTEMPT_STARTED and slot.current_job is not None:
            self.manifest.mark_running(
                slot.current_job,
                run_id=self.config.run_id,
                attempt=int(event.payload.get("attempt", 1)),
                worker_id=slot.worker_id,
                claimed_at=slot.claim.claimed_at if slot.claim else None,
            )
        elif event.kind == EventKind.HEARTBEAT:
            if slot.claim is not None:
                self.claims.heartbeat(slot.claim)
            if now - slot.last_manifest_heartbeat >= max(10.0, self.config.heartbeat_interval):
                if slot.current_job is not None:
                    self.manifest.mark_heartbeat(
                        slot.current_job,
                        run_id=self.config.run_id,
                        worker_id=slot.worker_id,
                    )
                if hasattr(self.manifest, "heartbeat_worker"):
                    self.manifest.heartbeat_worker(self.config.run_id, worker_id=slot.worker_id)
                slot.last_manifest_heartbeat = now
        elif event.kind in {EventKind.JOB_SUCCEEDED, EventKind.JOB_FAILED}:
            self._complete_job(slot, event)
        elif event.kind == EventKind.DIAGNOSTIC_SAVED and event.job_key:
            path = event.payload.get("path")
            if path:
                self.result.diagnostics[event.job_key] = str(path)
        elif event.kind == EventKind.WORKER_FATAL:
            slot.last_heartbeat = 0.0
        elif event.kind == EventKind.WORKER_STOPPED and hasattr(self.manifest, "mark_worker_state"):
            self.manifest.mark_worker_state(
                self.config.run_id,
                worker_id=slot.worker_id,
                status="stopped",
                current_job=None,
            )

    def _stop_process(self, slot: _WorkerSlot, *, graceful: bool, grace: float = 2.0) -> None:
        pid = int(slot.process.pid or 0)
        descendants = descendant_pids(pid) if pid else ()
        if graceful and slot.process.is_alive():
            try:
                slot.stop_sent = True
                slot.command_queue.put(WorkerCommand.stop())
            except (OSError, ValueError):
                pass
            slot.process.join(timeout=max(0.0, grace))
        if slot.process.is_alive():
            slot.process.terminate()
            slot.process.join(timeout=2.0)
        if slot.process.is_alive():
            slot.process.kill()
            slot.process.join(timeout=2.0)
        cleaned = cleanup_descendants(pid, known_descendants=descendants, grace_seconds=0.25)
        self.result.zombie_processes_cleaned += len(cleaned)
        self._close_queue(slot.command_queue)
        if slot.event_queue is not None:
            self._close_queue(slot.event_queue)
        try:
            slot.process.close()
        except (AttributeError, ValueError):
            pass

    def _handle_lost_worker(self, slot: _WorkerSlot, reason: str) -> None:
        self._stop_process(slot, graceful=False)
        job = self._release_current(slot)
        if job is not None:
            self.manifest.mark_interrupted(job, run_id=self.config.run_id, reason=reason)
            self.pending.appendleft(job)
        if hasattr(self.manifest, "mark_worker_state"):
            self.manifest.mark_worker_state(
                self.config.run_id,
                worker_id=slot.worker_id,
                status="lost",
                current_job=None,
                last_error=reason,
            )
        needs_worker = bool(self.pending) or any(
            other.current_job is not None for other in self.slots.values() if other is not slot
        )
        if (
            needs_worker
            and slot.restarts < self.config.max_worker_restarts
            and not self._shutting_down
            and self.control.circuit_open_reason is None
        ):
            self.result.worker_restarts += 1
            self._spawn_worker(
                slot.worker_id,
                generation=slot.generation + 1,
                restarts=slot.restarts + 1,
            )
        else:
            self.slots.pop(slot.worker_id, None)
            if job is not None and slot.restarts >= self.config.max_worker_restarts:
                if job in self.pending:
                    self.pending.remove(job)
                message = f"Worker restart budget exhausted after: {reason}"
                self.manifest.mark_failed(
                    job,
                    run_id=self.config.run_id,
                    worker_id=slot.worker_id,
                    error=message,
                )
                self.result.failed[job.key] = message

    def _recycle_worker(self, slot: _WorkerSlot) -> None:
        if slot.current_job is not None or self._shutting_down:
            return
        worker_id = slot.worker_id
        generation = slot.generation + 1
        restarts = slot.restarts
        reason = slot.recycle_reason or "worker recycling requested"
        self._stop_process(slot, graceful=True, grace=min(2.0, self.config.shutdown_grace))
        self.slots.pop(worker_id, None)
        self.result.worker_recycles += 1
        if hasattr(self.manifest, "mark_worker_state"):
            self.manifest.mark_worker_state(
                self.config.run_id,
                worker_id=worker_id,
                status="recycled",
                current_job=None,
                last_error=reason,
            )
        if self.pending and self.control.circuit_open_reason is None:
            self._spawn_worker(worker_id, generation=generation, restarts=restarts)

    def _check_workers(self) -> None:
        now = time.monotonic()
        coordinator_was_blind = now - self._last_worker_check >= self.config.worker_timeout
        self._last_worker_check = now
        for slot in list(self.slots.values()):
            if not slot.process.is_alive() and not slot.stop_sent:
                self._handle_lost_worker(
                    slot,
                    f"worker exited unexpectedly with code {slot.process.exitcode}",
                )
                continue
            if slot.process.is_alive() and not slot.stop_sent:
                if not slot.ready and now - slot.started_at > self.config.worker_ready_timeout:
                    self._handle_lost_worker(
                        slot,
                        f"worker readiness timed out after {self.config.worker_ready_timeout:.1f}s",
                    )
                    continue
                if slot.ready and coordinator_was_blind:
                    # A heartbeat timeout is meaningful only while the coordinator
                    # was actually able to observe worker events. After a long
                    # coordinator-side stall, allow one full heartbeat window for
                    # multiprocessing queue feeder threads to surface pending events.
                    slot.last_heartbeat = now
                if slot.ready and now - slot.last_heartbeat > self.config.worker_timeout:
                    self._handle_lost_worker(
                        slot,
                        f"worker heartbeat timed out after {self.config.worker_timeout:.1f}s",
                    )
                    continue
                if (
                    slot.current_job is not None
                    and slot.job_started_at is not None
                    and self.config.job_timeout > 0
                    and now - slot.job_started_at > self.config.job_timeout
                ):
                    self._handle_lost_worker(
                        slot,
                        f"job timed out after {self.config.job_timeout:.1f}s",
                    )
                    continue
                if self.config.worker_memory_limit_mb > 0 and not slot.recycle_requested:
                    rss = process_tree_rss_mb(int(slot.process.pid or 0))
                    if rss is not None and rss > self.config.worker_memory_limit_mb:
                        slot.recycle_requested = True
                        slot.recycle_reason = (
                            f"worker RSS {rss:.1f}MB exceeded "
                            f"{self.config.worker_memory_limit_mb:.1f}MB"
                        )
            if slot.recycle_requested and slot.current_job is None:
                self._recycle_worker(slot)

    def _apply_circuit_breaker(self) -> None:
        reason = self.control.circuit_open_reason
        if reason is None or self._circuit_applied:
            return
        self._circuit_applied = True
        for job in list(self.pending):
            self.manifest.mark_failed(job, run_id=self.config.run_id, error=reason)
            self.result.failed[job.key] = reason
        self.pending.clear()

    def _is_done(self) -> bool:
        return not self.pending and all(slot.current_job is None for slot in self.slots.values())

    def _dispatch_idle_workers(self) -> None:
        self.control.tick()
        self._apply_circuit_breaker()
        if not self.control.dispatch_allowed:
            return
        # After the first authenticated worker opens the startup barrier, wait
        # for the requested initial pool to become ready before dispatching.
        # This avoids one fast worker draining short jobs during process startup.
        if self._next_worker_index <= self._target_worker_count:
            return
        if any(not slot.ready for slot in self.slots.values() if not slot.stop_sent):
            return
        busy = sum(slot.current_job is not None for slot in self.slots.values())
        capacity = max(0, self.control.active_limit - busy)
        if capacity <= 0:
            return
        for slot in list(self.slots.values()):
            if capacity <= 0:
                break
            if slot.ready and slot.requested_job and slot.current_job is None and not slot.recycle_requested:
                if self._assign(slot):
                    capacity -= 1

    def _cleanup_runtime_profiles(self, *, success: bool) -> None:
        """Apply whole-run profile cleanup only from the coordinator process."""
        import os
        from pathlib import Path

        from browser_runtime import ProfileManager

        project_root = Path(__file__).resolve().parents[2]
        runtime_root = Path(
            os.environ.get("CHATGPT_RUNTIME_DIR", project_root / ".runtime")
        ).expanduser().resolve()
        if not (runtime_root / "runs").exists():
            return
        try:
            manager = ProfileManager.from_environment(project_root)
            outcome = manager.cleanup_run(self.config.run_id, success=success)
            self._log(
                f"Run runtime cleanup [{outcome.status.value}]: {self.config.run_id} — "
                f"{outcome.reason}"
            )
        except Exception as exc:
            self._log(
                f"Run runtime cleanup [failed]: {self.config.run_id} — "
                f"{type(exc).__name__}: {exc}"
            )

    def _shutdown(self, *, interrupted: bool = False) -> None:
        self._shutting_down = True
        for slot in list(self.slots.values()):
            if interrupted and slot.current_job is not None:
                self.manifest.mark_interrupted(
                    slot.current_job,
                    run_id=self.config.run_id,
                    reason="coordinator interrupted during shutdown",
                )
            if slot.process.is_alive():
                try:
                    slot.stop_sent = True
                    slot.command_queue.put(WorkerCommand.stop())
                except (OSError, ValueError):
                    pass
        deadline = time.monotonic() + self.config.shutdown_grace
        for slot in list(self.slots.values()):
            slot.process.join(timeout=max(0.0, deadline - time.monotonic()))
        for slot in list(self.slots.values()):
            self._stop_process(slot, graceful=False)
            if slot.claim is not None:
                self.claims.release(slot.claim)
            if hasattr(self.manifest, "mark_worker_state"):
                self.manifest.mark_worker_state(
                    self.config.run_id,
                    worker_id=slot.worker_id,
                    status="stopped",
                    current_job=None,
                )
        self.claims.release_run(self.config.run_id)
        self._cleanup_runtime_profiles(success=not interrupted and not self.result.failed)
        self._close_queue(self.event_queue)

    def _finalize_control_metrics(self) -> None:
        snapshot = self.control.snapshot()
        self.result.rate_limit_events = snapshot.rate_limit_events
        self.result.auth_failures = snapshot.auth_failures
        self.result.global_cooldown_seconds = round(
            snapshot.cooldown_requested_seconds, 3
        )
        self.result.minimum_active_workers = snapshot.minimum_active_limit
        self.result.final_active_workers = snapshot.active_limit
        self.result.adaptive_scale_downs = snapshot.scale_downs
        self.result.adaptive_scale_ups = snapshot.scale_ups
        self.result.circuit_breaker_reason = snapshot.circuit_open_reason

    def run(self) -> CoordinatorResult:
        self._started_at = time.monotonic()
        if not self.jobs:
            return self.result
        interrupted = False
        previous_sigterm = None
        if threading.current_thread() is threading.main_thread() and hasattr(signal, "SIGTERM"):
            previous_sigterm = signal.getsignal(signal.SIGTERM)

            def _request_shutdown(_signum, _frame):
                raise KeyboardInterrupt

            signal.signal(signal.SIGTERM, _request_shutdown)
        self._start_workers()
        try:
            while True:
                event = self._next_event()
                if isinstance(event, WorkerEvent):
                    self._handle_event(event)
                self._drain_pending_events()
                self._maybe_start_more_workers()
                self._check_workers()
                self._dispatch_idle_workers()
                if self._is_done():
                    break
                if not self.slots and self.pending:
                    reason = self.control.circuit_open_reason or "No worker remains available to execute this job."
                    for job in list(self.pending):
                        self.manifest.mark_failed(job, run_id=self.config.run_id, error=reason)
                        self.result.failed[job.key] = reason
                    self.pending.clear()
                    break
        except KeyboardInterrupt:
            interrupted = True
            self.result.interrupted = True
        finally:
            self._shutdown(interrupted=interrupted)
            if previous_sigterm is not None:
                signal.signal(signal.SIGTERM, previous_sigterm)
            self.result.duration_seconds = round(time.monotonic() - self._started_at, 3)
            self._finalize_control_metrics()
        return self.result
