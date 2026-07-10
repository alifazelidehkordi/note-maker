from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Iterable, Iterator
from uuid import uuid4

from artifact_validation import validate_artifact
from parallel_runtime.models import ExecutionJob, estimate_file_weight, estimate_text_weight

SCHEMA_VERSION = 2
_ALLOWED_STATUSES = {
    "pending",
    "running",
    "completed",
    "failed",
    "invalidated",
    "interrupted",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_text(text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def hash_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def normalize_extensions(values: Iterable[str]) -> tuple[str, ...]:
    normalized = {
        value if value.startswith(".") else f".{value}"
        for raw in values
        if (value := str(raw).strip().lower())
    }
    return tuple(sorted(normalized))


def _seconds_between(start: str | None, end: str) -> float | None:
    if not start:
        return None
    try:
        started = datetime.fromisoformat(start)
        finished = datetime.fromisoformat(end)
    except (TypeError, ValueError):
        return None
    return max(0.0, round((finished - started).total_seconds(), 3))


class JobSpec(ExecutionJob):
    """Compatibility name for the Level-4 ExecutionJob model."""

    @classmethod
    def for_file(
        cls,
        *,
        key: str,
        source: Path,
        prompt: Path,
        prompt_hash: str,
        output: Path,
        expected_extensions: Iterable[str],
        mode: str,
        model: str | None = None,
        title: str | None = None,
        estimated_weight: int | None = None,
        metadata: dict[str, str] | None = None,
    ) -> "JobSpec":
        source = Path(source).resolve()
        return cls(
            key=key,
            source=source,
            source_hash=hash_file(source),
            prompt_path=Path(prompt).resolve(),
            prompt_hash=prompt_hash,
            output=Path(output).resolve(),
            expected_extensions=normalize_extensions(expected_extensions),
            mode=mode,
            model=model,
            title=title,
            estimated_weight=estimated_weight or estimate_file_weight(source),
            metadata=metadata or {},
        )

    @classmethod
    def for_text(
        cls,
        *,
        key: str,
        source: Path,
        source_text: str,
        prompt: Path,
        prompt_hash: str,
        output: Path,
        expected_extensions: Iterable[str],
        mode: str,
        model: str | None = None,
        title: str | None = None,
        estimated_weight: int | None = None,
        metadata: dict[str, str] | None = None,
    ) -> "JobSpec":
        return cls(
            key=key,
            source=Path(source).resolve(),
            source_hash=hash_text(source_text),
            prompt_path=Path(prompt).resolve(),
            prompt_hash=prompt_hash,
            output=Path(output).resolve(),
            expected_extensions=normalize_extensions(expected_extensions),
            mode=mode,
            model=model,
            title=title,
            estimated_weight=estimated_weight or estimate_text_weight(source_text),
            metadata=metadata or {},
        )


class DecisionAction(str, Enum):
    RUN = "run"
    SKIP = "skip"
    ADOPT = "adopt"


@dataclass(frozen=True)
class ResumeDecision:
    action: DecisionAction
    reason: str
    previous_status: str | None = None
    invalidate: bool = False

    @property
    def should_run(self) -> bool:
        return self.action == DecisionAction.RUN


class ManifestError(RuntimeError):
    pass


class ManifestWriteForbiddenError(ManifestError):
    pass


def _default_execution_metadata(entry: dict) -> dict:
    return {
        "estimated_weight": max(1, int(entry.get("estimated_weight", 1) or 1)),
        "metadata": dict(entry.get("metadata") or {}),
        "worker_id": entry.get("worker_id"),
        "claimed_at": entry.get("claimed_at"),
        "last_heartbeat_at": entry.get("last_heartbeat_at"),
        "browser_restarts": int(entry.get("browser_restarts", 0) or 0),
        "duration_seconds": entry.get("duration_seconds"),
        "rate_limit_count": int(entry.get("rate_limit_count", 0) or 0),
    }


def migrate_payload(payload: dict) -> tuple[dict, bool]:
    version = payload.get("schema_version", 1)
    if version == SCHEMA_VERSION:
        migrated = dict(payload)
        migrated.setdefault("runs", {})
        return migrated, False
    if version != 1:
        raise ManifestError(
            f"Unsupported manifest schema_version {version!r}; expected 1 or {SCHEMA_VERSION}."
        )

    migrated = json.loads(json.dumps(payload))
    migrated["schema_version"] = SCHEMA_VERSION
    migrated.setdefault("runs", {})
    migrated["migration"] = {
        "from_schema_version": 1,
        "migrated_at": utc_now(),
    }
    for entry in migrated.get("items", {}).values():
        entry.update({k: v for k, v in _default_execution_metadata(entry).items() if k not in entry})
    return migrated, True


@contextmanager
def _short_write_lock(path: Path, *, timeout: float = 5.0) -> Iterator[None]:
    lock_path = path.parent / f".{path.name}.write.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    token = json.dumps(
        {
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
            "created_at": utc_now(),
        }
    )
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(token)
            break
        except FileExistsError:
            try:
                age = time.time() - lock_path.stat().st_mtime
            except FileNotFoundError:
                continue
            if age > 60:
                lock_path.unlink(missing_ok=True)
                continue
            if time.monotonic() >= deadline:
                raise ManifestError(f"Timed out waiting for manifest write lock: {lock_path}")
            time.sleep(0.02)
    try:
        yield
    finally:
        lock_path.unlink(missing_ok=True)


class ManifestReaderView:
    """Read-only manifest surface safe to pass into planners or workers."""

    def __init__(self, store: "ManifestStore") -> None:
        self.__store = store

    @property
    def path(self) -> Path:
        return self.__store.path

    def get(self, key: str) -> dict | None:
        return self.__store.get(key)

    def inspect(self, job: ExecutionJob, **options) -> ResumeDecision:
        return self.__store.inspect(job, **options)


class ManifestStore:
    """Schema-v2 manifest with coordinator-owned mutation and batched flushes."""

    def __init__(self, path: Path, *, writable: bool = True) -> None:
        self.path = Path(path).resolve()
        self._writable = bool(writable)
        self._owner_pid = os.getpid()
        self._batch_depth = 0
        self._dirty_items: set[str] = set()
        self._dirty_runs: set[str] = set()
        self._dirty_top_level = False
        self.data, self.was_migrated = self._load()

    @classmethod
    def reader(cls, path: Path) -> ManifestReaderView:
        return ManifestReaderView(cls(path, writable=False))

    def as_reader(self) -> ManifestReaderView:
        return ManifestReaderView(self)

    def _empty(self) -> dict:
        now = utc_now()
        return {
            "schema_version": SCHEMA_VERSION,
            "created_at": now,
            "updated_at": now,
            "runs": {},
            "items": {},
        }

    def _read_disk(self) -> dict:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ManifestError(f"Could not read manifest {self.path}: {exc}") from exc
        payload, _ = migrate_payload(payload)
        self._validate(payload)
        return payload

    def _load(self) -> tuple[dict, bool]:
        if not self.path.exists():
            return self._empty(), False
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ManifestError(f"Could not read manifest {self.path}: {exc}") from exc
        payload, migrated = migrate_payload(payload)
        self._validate(payload)
        return payload, migrated

    def _validate(self, payload: dict) -> None:
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise ManifestError("Manifest migration did not produce schema version 2.")
        items = payload.get("items")
        if not isinstance(items, dict):
            raise ManifestError("Manifest field 'items' must be an object.")
        if not isinstance(payload.get("runs", {}), dict):
            raise ManifestError("Manifest field 'runs' must be an object.")
        for key, entry in items.items():
            if not isinstance(entry, dict):
                raise ManifestError(f"Manifest item {key!r} must be an object.")
            status = entry.get("status")
            if status not in _ALLOWED_STATUSES:
                raise ManifestError(f"Manifest item {key!r} has invalid status {status!r}.")

    def _assert_writer(self) -> None:
        if not self._writable:
            raise ManifestWriteForbiddenError(
                "Manifest mutation is coordinator-only; this handle is read-only."
            )
        if os.getpid() != self._owner_pid:
            raise ManifestWriteForbiddenError(
                "Manifest writer cannot be used from a worker process. Send an event to the coordinator instead."
            )

    @property
    def items(self) -> dict[str, dict]:
        return self.data["items"]

    @property
    def runs(self) -> dict[str, dict]:
        return self.data["runs"]

    def get(self, key: str) -> dict | None:
        entry = self.items.get(key)
        return json.loads(json.dumps(entry)) if entry is not None else None

    def get_run(self, run_id: str) -> dict | None:
        entry = self.runs.get(run_id)
        return json.loads(json.dumps(entry)) if entry is not None else None

    @contextmanager
    def batch_update(self) -> Iterator["ManifestStore"]:
        self._assert_writer()
        self._batch_depth += 1
        try:
            yield self
        finally:
            self._batch_depth -= 1
            if self._batch_depth == 0 and self.is_dirty:
                self.save()

    @property
    def is_dirty(self) -> bool:
        return bool(self._dirty_items or self._dirty_runs or self._dirty_top_level)

    def _commit(self) -> None:
        if self._batch_depth == 0:
            self.save()

    @staticmethod
    def _preserve_completed_disk_record(disk: dict | None, local: dict) -> bool:
        """Prevent a stale planner snapshot from downgrading a valid completion."""
        if not disk or disk.get("status") != "completed":
            return False
        if local.get("status") not in {"pending", "interrupted"}:
            return False
        identity_fields = (
            "source_hash",
            "prompt_hash",
            "output",
            "expected_extensions",
            "mode",
            "model",
        )
        if any(disk.get(field) != local.get(field) for field in identity_fields):
            return False
        output = Path(str(disk.get("output", "")))
        expected = disk.get("expected_extensions", ())
        if not output.exists():
            return False
        return validate_artifact(output, expected, repair_opml=False).valid

    def save(self) -> None:
        self._assert_writer()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _short_write_lock(self.path):
            if self.path.exists() and (self._dirty_items or self._dirty_runs):
                payload = self._read_disk()
                for key, value in self.data.items():
                    if key not in {"items", "runs", "updated_at"}:
                        payload[key] = value
                for key in self._dirty_items:
                    local_record = self.data["items"][key]
                    disk_record = payload["items"].get(key)
                    if self._preserve_completed_disk_record(disk_record, local_record):
                        continue
                    payload["items"][key] = local_record
                for run_id in self._dirty_runs:
                    payload["runs"][run_id] = self.data["runs"][run_id]
            else:
                payload = json.loads(json.dumps(self.data))

            payload["schema_version"] = SCHEMA_VERSION
            payload.setdefault("runs", {})
            payload.setdefault("items", {})
            payload["updated_at"] = utc_now()
            self._validate(payload)
            text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            temporary = self.path.parent / f".{self.path.name}.{uuid4().hex}.tmp"
            backup = self.path.with_suffix(self.path.suffix + ".bak")
            try:
                with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                    handle.write(text)
                    handle.flush()
                    os.fsync(handle.fileno())
                if self.path.exists():
                    shutil.copy2(self.path, backup)
                os.replace(temporary, self.path)
            finally:
                temporary.unlink(missing_ok=True)

            self.data = payload
            self._dirty_items.clear()
            self._dirty_runs.clear()
            self._dirty_top_level = False
            self.was_migrated = False

    def _identity_mismatches(self, entry: dict, job: ExecutionJob) -> list[str]:
        checks = {
            "source_hash": job.source_hash,
            "prompt_hash": job.prompt_hash,
            "output": str(job.output),
            "expected_extensions": list(job.expected_extensions),
            "mode": job.mode,
            "model": job.model,
        }
        return [field for field, expected in checks.items() if entry.get(field) != expected]

    def inspect(
        self,
        job: ExecutionJob,
        *,
        overwrite: bool = False,
        resume: bool = True,
        adopt_existing: bool = False,
        retry_failed_only: bool = False,
    ) -> ResumeDecision:
        entry = self.items.get(job.key)

        if overwrite:
            return ResumeDecision(DecisionAction.RUN, "overwrite requested", entry.get("status") if entry else None)
        if not resume:
            return ResumeDecision(DecisionAction.RUN, "resume disabled", entry.get("status") if entry else None)

        if entry is None:
            if retry_failed_only:
                return ResumeDecision(DecisionAction.SKIP, "not present as a failed manifest job")
            if job.output.exists() and adopt_existing:
                result = validate_artifact(job.output, job.expected_extensions, repair_opml=False)
                if result.valid:
                    return ResumeDecision(DecisionAction.ADOPT, "valid existing output has no manifest record")
                return ResumeDecision(DecisionAction.RUN, "untracked existing output failed validation", invalidate=True)
            if job.output.exists():
                return ResumeDecision(DecisionAction.RUN, "existing output is not tracked by manifest")
            return ResumeDecision(DecisionAction.RUN, "new job")

        status = str(entry.get("status"))
        mismatches = self._identity_mismatches(entry, job)
        if mismatches:
            if retry_failed_only:
                return ResumeDecision(
                    DecisionAction.SKIP,
                    "job changed but --retry-failed only processes prior failures",
                    status,
                )
            return ResumeDecision(
                DecisionAction.RUN,
                "job inputs changed: " + ", ".join(mismatches),
                status,
                invalidate=True,
            )

        if retry_failed_only and status not in {"failed", "running", "pending", "invalidated", "interrupted"}:
            return ResumeDecision(DecisionAction.SKIP, "job was not previously failed or interrupted", status)

        if status == "completed":
            if not job.output.exists():
                return ResumeDecision(DecisionAction.RUN, "completed output is missing", status, invalidate=True)
            result = validate_artifact(job.output, job.expected_extensions, repair_opml=False)
            if not result.valid:
                return ResumeDecision(
                    DecisionAction.RUN,
                    "completed output failed validation: " + "; ".join(result.errors),
                    status,
                    invalidate=True,
                )
            current_hash = hash_file(job.output)
            if current_hash != entry.get("output_hash"):
                return ResumeDecision(DecisionAction.RUN, "completed output hash changed", status, invalidate=True)
            return ResumeDecision(DecisionAction.SKIP, "completed output is valid", status)

        if status == "failed":
            return ResumeDecision(DecisionAction.RUN, "retrying failed job", status)
        if status in {"running", "interrupted"}:
            return ResumeDecision(DecisionAction.RUN, "recovering interrupted job", status)
        if status == "pending":
            return ResumeDecision(DecisionAction.RUN, "resuming pending job", status)
        return ResumeDecision(DecisionAction.RUN, "rerunning invalidated job", status)

    def _base_record(self, job: ExecutionJob) -> dict:
        existing = self.items.get(job.key, {})
        return {
            "source": str(job.source),
            "source_hash": job.source_hash,
            "prompt": str(job.prompt_path),
            "prompt_hash": job.prompt_hash,
            "output": str(job.output),
            "expected_extensions": list(job.expected_extensions),
            "mode": job.mode,
            "model": job.model,
            "title": job.title,
            "estimated_weight": job.estimated_weight,
            "metadata": dict(job.metadata),
            "status": existing.get("status", "pending"),
            "attempts": int(existing.get("attempts", 0)),
            "started_at": existing.get("started_at"),
            "finished_at": existing.get("finished_at"),
            "output_hash": existing.get("output_hash"),
            "last_error": existing.get("last_error"),
            "diagnostics": existing.get("diagnostics"),
            "adopted": bool(existing.get("adopted", False)),
            "run_id": existing.get("run_id"),
            "worker_id": existing.get("worker_id"),
            "claimed_at": existing.get("claimed_at"),
            "last_heartbeat_at": existing.get("last_heartbeat_at"),
            "browser_restarts": int(existing.get("browser_restarts", 0) or 0),
            "duration_seconds": existing.get("duration_seconds"),
            "rate_limit_count": int(existing.get("rate_limit_count", 0) or 0),
            "updated_at": utc_now(),
        }

    def _set_record(self, job: ExecutionJob, record: dict) -> None:
        self._assert_writer()
        self.items[job.key] = record
        self._dirty_items.add(job.key)
        self._commit()

    def register_run(
        self,
        run_id: str,
        *,
        mode: str,
        planned_jobs: int,
        estimated_total_weight: int = 0,
        parallel_runs: int = 1,
        browser_provider: str | None = None,
    ) -> None:
        self._assert_writer()
        now = utc_now()
        existing = self.runs.get(run_id, {})
        self.runs[run_id] = {
            **existing,
            "run_id": run_id,
            "mode": mode,
            "status": "planned",
            "created_at": existing.get("created_at", now),
            "updated_at": now,
            "finished_at": None,
            "planned_jobs": int(planned_jobs),
            "estimated_total_weight": int(estimated_total_weight),
            "parallel_runs": int(parallel_runs),
            "browser_provider": browser_provider,
        }
        self._dirty_runs.add(run_id)
        self._commit()

    def finish_run(self, run_id: str, *, status: str, summary_path: Path | None = None) -> None:
        self._assert_writer()
        now = utc_now()
        record = dict(self.runs.get(run_id, {"run_id": run_id, "created_at": now}))
        record.update(
            status=status,
            updated_at=now,
            finished_at=now,
            summary_path=str(summary_path) if summary_path else record.get("summary_path"),
        )
        self.runs[run_id] = record
        self._dirty_runs.add(run_id)
        self._commit()

    def register_worker(
        self,
        run_id: str,
        *,
        worker_id: str,
        pid: int,
        generation: int = 1,
        status: str = "starting",
        runtime_worker_id: str | None = None,
    ) -> None:
        self._assert_writer()
        now = utc_now()
        run = dict(self.runs.get(run_id, {"run_id": run_id, "created_at": now}))
        workers = dict(run.get("workers", {}))
        existing = dict(workers.get(worker_id, {}))
        workers[worker_id] = {
            **existing,
            "worker_id": worker_id,
            "pid": int(pid),
            "generation": int(generation),
            "runtime_worker_id": runtime_worker_id or worker_id,
            "status": status,
            "started_at": existing.get("started_at", now),
            "updated_at": now,
            "last_heartbeat_at": now,
            "current_job": None,
            "last_error": None,
            "restart_count": max(0, int(generation) - 1),
        }
        run["workers"] = workers
        run["status"] = "running"
        run["updated_at"] = now
        self.runs[run_id] = run
        self._dirty_runs.add(run_id)
        self._commit()

    def mark_worker_state(
        self,
        run_id: str,
        *,
        worker_id: str,
        status: str,
        current_job: str | None = None,
        pid: int | None = None,
        last_error: str | None = None,
    ) -> None:
        self._assert_writer()
        now = utc_now()
        run = dict(self.runs.get(run_id, {"run_id": run_id, "created_at": now}))
        workers = dict(run.get("workers", {}))
        worker = dict(workers.get(worker_id, {"worker_id": worker_id, "started_at": now}))
        worker.update(
            status=status,
            current_job=current_job,
            updated_at=now,
            last_heartbeat_at=now,
            last_error=last_error,
        )
        if pid is not None:
            worker["pid"] = int(pid)
        workers[worker_id] = worker
        run["workers"] = workers
        run["updated_at"] = now
        self.runs[run_id] = run
        self._dirty_runs.add(run_id)
        self._commit()

    def heartbeat_worker(self, run_id: str, *, worker_id: str) -> None:
        self._assert_writer()
        run = self.runs.get(run_id)
        if not run:
            return
        workers = dict(run.get("workers", {}))
        worker = dict(workers.get(worker_id, {}))
        if not worker:
            return
        now = utc_now()
        worker["last_heartbeat_at"] = now
        worker["updated_at"] = now
        workers[worker_id] = worker
        run = dict(run)
        run["workers"] = workers
        run["updated_at"] = now
        self.runs[run_id] = run
        self._dirty_runs.add(run_id)
        self._commit()

    def mark_pending(self, job: ExecutionJob, *, reason: str | None = None) -> None:
        record = self._base_record(job)
        record.update(
            status="pending",
            finished_at=None,
            output_hash=None,
            last_error=reason,
            diagnostics=None,
            adopted=False,
            current_attempt=None,
            updated_at=utc_now(),
        )
        self._set_record(job, record)

    def mark_invalidated(self, job: ExecutionJob, *, reason: str) -> None:
        record = self._base_record(job)
        record.update(
            status="invalidated",
            finished_at=None,
            output_hash=None,
            last_error=reason,
            diagnostics=None,
            adopted=False,
            current_attempt=None,
            updated_at=utc_now(),
        )
        self._set_record(job, record)

    def mark_interrupted(self, job: ExecutionJob, *, run_id: str | None = None, reason: str) -> None:
        record = self._base_record(job)
        record.update(
            status="interrupted",
            run_id=run_id or record.get("run_id"),
            current_attempt=None,
            finished_at=utc_now(),
            last_error={"type": "Interrupted", "message": reason},
            updated_at=utc_now(),
        )
        self._set_record(job, record)

    def mark_running(
        self,
        job: ExecutionJob,
        *,
        run_id: str,
        attempt: int,
        worker_id: str = "worker-001",
        claimed_at: str | None = None,
    ) -> None:
        record = self._base_record(job)
        now = utc_now()
        record.update(
            status="running",
            attempts=int(record.get("attempts", 0)) + 1,
            current_attempt=attempt,
            run_id=run_id,
            worker_id=worker_id,
            claimed_at=claimed_at or now,
            last_heartbeat_at=now,
            started_at=record.get("started_at") or now,
            finished_at=None,
            duration_seconds=None,
            output_hash=None,
            last_error=None,
            diagnostics=None,
            adopted=False,
            updated_at=now,
        )
        self._set_record(job, record)

    def mark_heartbeat(self, job: ExecutionJob, *, run_id: str, worker_id: str) -> None:
        record = self._base_record(job)
        record.update(run_id=run_id, worker_id=worker_id, last_heartbeat_at=utc_now(), updated_at=utc_now())
        self._set_record(job, record)

    def mark_completed(
        self,
        job: ExecutionJob,
        *,
        run_id: str,
        adopted: bool = False,
        worker_id: str | None = None,
        browser_restarts: int | None = None,
        rate_limit_count: int | None = None,
    ) -> None:
        result = validate_artifact(job.output, job.expected_extensions, repair_opml=False)
        if not result.valid:
            raise ManifestError(f"Cannot mark invalid output completed for {job.key}: {'; '.join(result.errors)}")
        record = self._base_record(job)
        now = utc_now()
        record.update(
            status="completed",
            run_id=run_id,
            worker_id=worker_id or record.get("worker_id"),
            current_attempt=None,
            started_at=record.get("started_at") or now,
            finished_at=now,
            duration_seconds=_seconds_between(record.get("started_at"), now),
            output_hash=hash_file(job.output),
            last_error=None,
            diagnostics=None,
            adopted=adopted,
            browser_restarts=(record.get("browser_restarts", 0) if browser_restarts is None else browser_restarts),
            rate_limit_count=(record.get("rate_limit_count", 0) if rate_limit_count is None else rate_limit_count),
            updated_at=now,
        )
        self._set_record(job, record)

    def mark_failed(
        self,
        job: ExecutionJob,
        *,
        run_id: str,
        error: BaseException | str,
        diagnostics: Path | str | None = None,
        worker_id: str | None = None,
        browser_restarts: int | None = None,
        rate_limit_count: int | None = None,
    ) -> None:
        record = self._base_record(job)
        now = utc_now()
        record.update(
            status="failed",
            run_id=run_id,
            worker_id=worker_id or record.get("worker_id"),
            current_attempt=None,
            finished_at=now,
            duration_seconds=_seconds_between(record.get("started_at"), now),
            output_hash=None,
            last_error={
                "type": type(error).__name__ if isinstance(error, BaseException) else "Error",
                "message": str(error),
            },
            diagnostics=str(diagnostics) if diagnostics is not None else None,
            adopted=False,
            browser_restarts=(record.get("browser_restarts", 0) if browser_restarts is None else browser_restarts),
            rate_limit_count=(record.get("rate_limit_count", 0) if rate_limit_count is None else rate_limit_count),
            updated_at=now,
        )
        self._set_record(job, record)

    def apply_plan(self, plan, *, worker_id: str = "worker-001") -> None:
        """Commit planner transitions with one manifest write."""
        from parallel_runtime.models import TransitionKind

        with self.batch_update():
            for transition in plan.transitions:
                if transition.kind == TransitionKind.ADOPTED:
                    self.mark_completed(
                        transition.job,
                        run_id=plan.run_id,
                        adopted=True,
                        worker_id=worker_id,
                    )
                elif transition.kind == TransitionKind.INVALIDATED:
                    self.mark_invalidated(transition.job, reason=transition.reason or "job invalidated")
                elif transition.kind == TransitionKind.INTERRUPTED:
                    self.mark_interrupted(
                        transition.job,
                        reason=transition.reason or "previous run interrupted",
                    )
                elif transition.kind == TransitionKind.PENDING:
                    self.mark_pending(transition.job, reason=transition.reason)


class ManifestCoordinator(ManifestStore):
    """Explicit writable manifest owner used by the batch/coordinator process."""

    def __init__(self, path: Path) -> None:
        super().__init__(path, writable=True)
