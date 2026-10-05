from __future__ import annotations

import json
import os
import time
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

STATUS_SCHEMA_VERSION = 1
TERMINAL_STATES = {"completed", "completed_with_failures", "failed", "interrupted"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_logs_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "logs"


def _replace_with_retry(source: Path, destination: Path, *, attempts: int = 5) -> None:
    for attempt in range(attempts):
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if attempt + 1 >= attempts:
                raise
            time.sleep(0.05 * (attempt + 1))


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_with_retry(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_status_snapshot(path: Path) -> dict[str, object]:
    resolved = Path(path).expanduser().resolve()
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Status snapshot must contain a JSON object: {resolved}")
    version = int(payload.get("schema_version", STATUS_SCHEMA_VERSION))
    if version != STATUS_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported status schema_version {version}; expected {STATUS_SCHEMA_VERSION}."
        )
    return payload


class StatusSnapshotStore:
    """Main-process atomic status snapshots with a stable latest copy."""

    def __init__(self, run_id: str, *, logs_dir: Path | None = None) -> None:
        if not str(run_id).strip():
            raise ValueError("run_id must not be empty")
        self.run_id = str(run_id)
        self.logs_dir = (Path(logs_dir) if logs_dir is not None else default_logs_dir()).resolve()
        self.run_path = self.logs_dir / "runs" / self.run_id / "status.json"
        self.latest_path = self.logs_dir / "last_status.json"

    def publish(self, payload: Mapping[str, object]) -> dict[str, object]:
        snapshot = dict(payload)
        snapshot["schema_version"] = STATUS_SCHEMA_VERSION
        snapshot["run_id"] = self.run_id
        snapshot["updated_at"] = utc_now()
        _write_json_atomic(self.run_path, snapshot)
        _write_json_atomic(self.latest_path, snapshot)
        return snapshot


def compute_counters(
    *,
    total: int,
    initial_succeeded: int = 0,
    initial_skipped: int = 0,
    succeeded: Iterable[str] = (),
    externally_completed: Iterable[str] = (),
    failed: Mapping[str, object] | Iterable[str] = (),
    running: Iterable[str] = (),
    adopted: int = 0,
    resumed_completed: int = 0,
    runnable: int | None = None,
) -> dict[str, int]:
    """Return an exact partition of planned jobs into terminal, running, and queued states."""
    total_count = max(0, int(total))
    runtime_succeeded = set(str(value) for value in succeeded)
    external = set(str(value) for value in externally_completed)
    succeeded_count = max(0, int(initial_succeeded)) + len(runtime_succeeded | external)
    failed_keys = set(str(value) for value in failed)
    failed_count = len(failed_keys)
    skipped_count = max(0, int(initial_skipped))
    terminal = min(total_count, succeeded_count + failed_count + skipped_count)
    remaining = max(0, total_count - terminal)
    running_keys = set(str(value) for value in running)
    running_count = min(len(running_keys), remaining)
    queued_count = max(0, remaining - running_count)
    return {
        "total": total_count,
        "completed": terminal,
        "succeeded": min(succeeded_count, total_count),
        "failed": min(failed_count, total_count),
        "skipped": min(skipped_count, total_count),
        "running": running_count,
        "queued": queued_count,
        "remaining": remaining,
        "adopted": max(0, int(adopted)),
        "resumed_completed": max(0, int(resumed_completed)),
        "externally_completed": len(external),
        "runnable": max(0, int(runnable if runnable is not None else total_count)),
    }


def stage_elapsed_seconds(stage: Mapping[str, object] | None, *, now: datetime | None = None) -> float | None:
    if not stage:
        return None
    recorded = max(0.0, float(stage.get("elapsed_seconds", 0.0) or 0.0))
    if str(stage.get("phase") or "") != "started":
        return round(recorded, 3)
    raw_started = stage.get("stage_started_at")
    if not raw_started:
        return round(recorded, 3)
    try:
        started = datetime.fromisoformat(str(raw_started))
    except ValueError:
        return round(recorded, 3)
    current = now or datetime.now(timezone.utc)
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    elapsed = max(recorded, (current - started).total_seconds())
    return round(max(0.0, elapsed), 3)


def is_terminal_snapshot(snapshot: Mapping[str, object]) -> bool:
    return str(snapshot.get("state") or "") in TERMINAL_STATES


def format_status_snapshot(snapshot: Mapping[str, object]) -> str:
    run_id = str(snapshot.get("run_id") or "unknown")
    state = str(snapshot.get("state") or "unknown")
    counters = dict(snapshot.get("counters") or {})
    lines = [f"Run {run_id} — {state}"]
    if counters:
        lines.append(
            "Progress: "
            f"{int(counters.get('completed', 0))}/{int(counters.get('total', 0))} | "
            f"succeeded {int(counters.get('succeeded', 0))} | "
            f"failed {int(counters.get('failed', 0))} | "
            f"skipped {int(counters.get('skipped', 0))} | "
            f"running {int(counters.get('running', 0))} | "
            f"queued {int(counters.get('queued', 0))}"
        )
    for worker in sorted(
        (dict(value) for value in list(snapshot.get("workers") or [])),
        key=lambda value: str(value.get("worker_id") or ""),
    ):
        worker_id = str(worker.get("worker_id") or "worker")
        worker_state = str(worker.get("status") or "unknown")
        source = worker.get("source_filename") or worker.get("job_key")
        stage = worker.get("stage")
        attempt = worker.get("attempt")
        detail: list[str] = []
        if source:
            detail.append(str(source))
        if attempt is not None:
            detail.append(f"attempt {attempt}")
        if stage:
            elapsed = worker.get("stage_elapsed_seconds")
            if elapsed is None:
                detail.append(str(stage))
            else:
                detail.append(f"{stage} ({float(elapsed):.1f}s)")
        suffix = f" — {', '.join(detail)}" if detail else ""
        lines.append(f"{worker_id} [{worker_state}]{suffix}")
    control = dict(snapshot.get("control") or {})
    cooldown = float(control.get("cooldown_remaining_seconds", 0.0) or 0.0)
    if cooldown > 0:
        lines.append(f"Global cooldown: {cooldown:.0f}s remaining")
    reason = control.get("circuit_breaker_reason")
    if reason:
        lines.append(f"Circuit breaker: {reason}")
    return "\n".join(lines)


def _plan_snapshot(run: Mapping[str, object], *, state: str = "planned") -> dict[str, object]:
    total = int(run.get("total_jobs", run.get("planned_jobs", 0)) or 0)
    counters = compute_counters(
        total=total,
        initial_succeeded=int(run.get("initial_successes", 0) or 0),
        initial_skipped=int(run.get("skipped_count", 0) or 0),
        adopted=int(run.get("adopted_count", 0) or 0),
        resumed_completed=int(run.get("completed_skip_count", 0) or 0),
        runnable=int(run.get("runnable_jobs", run.get("planned_jobs", 0)) or 0),
    )
    return {
        "mode": run.get("mode"),
        "state": state,
        "started_at": run.get("created_at"),
        "finished_at": utc_now() if state in TERMINAL_STATES else None,
        "browser_provider": run.get("browser_provider"),
        "requested_workers": int(run.get("parallel_runs", 1) or 1),
        "active_worker_limit": 0 if not counters["runnable"] else int(run.get("parallel_runs", 1) or 1),
        "counters": counters,
        "workers": [],
        "control": {
            "cooldown_remaining_seconds": 0.0,
            "active_limit": 0 if not counters["runnable"] else int(run.get("parallel_runs", 1) or 1),
            "minimum_active_limit": 0,
            "rate_limit_events": 0,
            "auth_failures": 0,
            "circuit_breaker_reason": None,
        },
        "interrupted": state == "interrupted",
    }


def install_manifest_status_tracking() -> None:
    """Add plan metadata/status publishing to the writable main-process manifest API.

    This is an additive migration hook: worker processes never receive a writable
    manifest handle and never publish shared snapshots.
    """
    from manifest import ManifestStore

    if getattr(ManifestStore, "_part1c_status_tracking_installed", False):
        return
    original_apply_plan = ManifestStore.apply_plan
    original_finish_run = ManifestStore.finish_run

    def apply_plan_with_status(self, plan, *, worker_id: str = "worker-001") -> None:
        original_apply_plan(self, plan, worker_id=worker_id)
        now = utc_now()
        run = dict(self.runs.get(plan.run_id, {"run_id": plan.run_id, "created_at": now}))
        run.update(
            total_jobs=len(plan.candidates),
            runnable_jobs=len(plan.runnable),
            initial_successes=plan.initial_successes,
            completed_skip_count=plan.completed_skip_count,
            skipped_count=max(0, len(plan.skipped) - plan.completed_skip_count),
            adopted_count=len(plan.adopted),
            updated_at=now,
        )
        self.runs[plan.run_id] = run
        self._dirty_runs.add(plan.run_id)
        self._commit()
        try:
            StatusSnapshotStore(plan.run_id).publish(_plan_snapshot(run))
        except (OSError, ValueError, TypeError):
            pass

    def finish_run_with_status(self, run_id: str, *, status: str, summary_path: Path | None = None) -> None:
        original_finish_run(self, run_id, status=status, summary_path=summary_path)
        run = self.get_run(run_id) or {}
        snapshot_store = StatusSnapshotStore(run_id)
        existing: dict[str, object] | None = None
        try:
            if snapshot_store.run_path.is_file():
                existing = read_status_snapshot(snapshot_store.run_path)
        except (OSError, ValueError, json.JSONDecodeError):
            existing = None
        if existing is not None and is_terminal_snapshot(existing):
            if summary_path is not None:
                existing["summary_path"] = str(summary_path)
                try:
                    snapshot_store.publish(existing)
                except (OSError, ValueError, TypeError):
                    pass
            return

        runtime_succeeded: list[str] = []
        runtime_failed: list[str] = []
        for key, entry in self.items.items():
            if entry.get("run_id") != run_id:
                continue
            if entry.get("status") == "completed" and not bool(entry.get("adopted", False)):
                runtime_succeeded.append(key)
            elif entry.get("status") == "failed":
                runtime_failed.append(key)
        total = int(run.get("total_jobs", run.get("planned_jobs", 0)) or 0)
        counters = compute_counters(
            total=total,
            initial_succeeded=int(run.get("initial_successes", 0) or 0),
            initial_skipped=int(run.get("skipped_count", 0) or 0),
            succeeded=runtime_succeeded,
            failed=runtime_failed,
            adopted=int(run.get("adopted_count", 0) or 0),
            resumed_completed=int(run.get("completed_skip_count", 0) or 0),
            runnable=int(run.get("runnable_jobs", run.get("planned_jobs", 0)) or 0),
        )
        final_state = status if status in TERMINAL_STATES else ("failed" if runtime_failed else "completed")
        payload = _plan_snapshot(run, state=final_state)
        payload["counters"] = counters
        payload["summary_path"] = str(summary_path) if summary_path is not None else None
        try:
            snapshot_store.publish(payload)
        except (OSError, ValueError, TypeError):
            pass

    ManifestStore.apply_plan = apply_plan_with_status
    ManifestStore.finish_run = finish_run_with_status
    ManifestStore._part1c_status_tracking_installed = True
