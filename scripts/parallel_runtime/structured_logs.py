from __future__ import annotations

import json
import os
import re
import threading
from collections.abc import Mapping
from pathlib import Path

from .event_journal import EventJournal

STRUCTURED_LOG_SCHEMA_VERSION = 1
_HEARTBEAT_KIND = "heartbeat"
_ERROR_KINDS = {
    "auth_failure",
    "circuit_breaker_opened",
    "job_claim_timeout",
    "job_failed",
    "worker_fatal",
}
_WARNING_KINDS = {
    "global_cooldown_requested",
    "retry_scheduled",
    "worker_lost",
    "worker_recycled",
}
_SAFE_COMPONENT_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_component(value: object) -> str:
    text = str(value).strip()
    safe = _SAFE_COMPONENT_RE.sub("_", text).strip("._")
    return safe or "unknown-worker"


def _level_for(kind: str, disposition: str) -> str:
    if disposition != "accepted":
        return "WARNING"
    if kind in _ERROR_KINDS or kind.endswith("_failed") or "fatal" in kind:
        return "ERROR"
    if kind in _WARNING_KINDS or kind.startswith("retry_"):
        return "WARNING"
    return "INFO"


def _message_for(kind: str, disposition: str) -> str:
    message = kind.replace("_", " ").strip() or "runtime event"
    if disposition != "accepted":
        message = f"{message} ({disposition.replace('_', ' ')})"
    return message


def read_structured_log(path: Path, *, strict: bool = False) -> list[dict[str, object]]:
    """Read valid JSONL structured-log records.

    Non-strict reads skip malformed records so a torn final write cannot hide
    later records appended after a restart. Strict mode is intended for tests
    and integrity checks.
    """
    resolved = Path(path).expanduser().resolve()
    records: list[dict[str, object]] = []
    with resolved.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                if strict:
                    raise ValueError(
                        f"Malformed structured log record at {resolved}:{line_number}: {exc}"
                    ) from exc
                continue
            if not isinstance(payload, dict):
                if strict:
                    raise ValueError(
                        f"Structured log record at {resolved}:{line_number} must be an object."
                    )
                continue
            version = _optional_int(payload.get("schema_version"))
            if version != STRUCTURED_LOG_SCHEMA_VERSION:
                if strict:
                    raise ValueError(
                        f"Unsupported structured log schema_version {version!r} at "
                        f"{resolved}:{line_number}."
                    )
                continue
            records.append(payload)
    return records


class StructuredLogStore:
    """Coordinator-owned structured JSONL views derived from the event journal."""

    def __init__(self, run_id: str, *, run_dir: Path) -> None:
        if not str(run_id).strip():
            raise ValueError("run_id must not be empty")
        self.run_id = str(run_id)
        self.run_dir = Path(run_dir).expanduser().resolve()
        self.coordinator_path = self.run_dir / "coordinator.jsonl"
        self.worker_dir = self.run_dir / "workers"
        self._lock = threading.Lock()
        self._boundary_checked: set[Path] = set()

    def worker_path(self, runtime_worker_id: object) -> Path:
        return self.worker_dir / f"{_safe_component(runtime_worker_id)}.jsonl"

    @staticmethod
    def _write_all(fd: int, data: bytes) -> None:
        offset = 0
        while offset < len(data):
            written = os.write(fd, data[offset:])
            if written <= 0:
                raise OSError("Could not append structured log record.")
            offset += written

    def _ensure_append_boundary(self, path: Path) -> None:
        if path in self._boundary_checked:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file() and path.stat().st_size > 0:
            with path.open("rb") as handle:
                handle.seek(-1, os.SEEK_END)
                ends_with_newline = handle.read(1) == b"\n"
            if not ends_with_newline:
                fd = os.open(path, os.O_WRONLY | os.O_APPEND)
                try:
                    self._write_all(fd, b"\n")
                finally:
                    os.close(fd)
        self._boundary_checked.add(path)

    def _append(self, path: Path, record: Mapping[str, object]) -> dict[str, object]:
        payload = dict(record)
        encoded = (
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        with self._lock:
            self._ensure_append_boundary(path)
            fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
            try:
                self._write_all(fd, encoded)
            finally:
                os.close(fd)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        return payload

    def append_journal_record(
        self,
        journal_record: Mapping[str, object],
    ) -> dict[str, object] | None:
        """Persist one sanitized EventJournal record as an operational log entry."""
        if not journal_record:
            # Compatibility with lightweight test doubles that historically
            # returned an empty mapping from EventJournal-like methods.
            return None
        run_id = str(journal_record.get("run_id") or "")
        if run_id != self.run_id:
            raise ValueError(
                f"Structured log run_id mismatch: expected {self.run_id!r}, got {run_id!r}."
            )
        source = str(journal_record.get("source") or "")
        if source not in {"coordinator", "worker"}:
            raise ValueError(f"Unsupported structured log source: {source!r}")
        kind = str(journal_record.get("kind") or "runtime_event")
        if source == "worker" and kind == _HEARTBEAT_KIND:
            # Heartbeats remain durable in events.jsonl; duplicating every
            # heartbeat into worker operational logs adds noise and I/O without
            # improving diagnosis.
            return None
        disposition = str(journal_record.get("disposition") or "accepted")
        runtime_worker_id = journal_record.get("runtime_worker_id")
        worker_id = journal_record.get("worker_id")
        log_record: dict[str, object] = {
            "schema_version": STRUCTURED_LOG_SCHEMA_VERSION,
            "timestamp": journal_record.get("observed_at")
            or journal_record.get("event_created_at"),
            "level": _level_for(kind, disposition),
            "logger": source,
            "message": _message_for(kind, disposition),
            "event_kind": kind,
            "disposition": disposition,
            "journal_sequence": journal_record.get("sequence"),
            "run_id": self.run_id,
            "worker_id": worker_id,
            "runtime_worker_id": runtime_worker_id,
            "generation": journal_record.get("generation"),
            "coordinator_generation": journal_record.get("coordinator_generation"),
            "job_key": journal_record.get("job_key"),
            "event_job_key": journal_record.get("event_job_key"),
            "attempt": journal_record.get("attempt"),
            "event_created_at": journal_record.get("event_created_at"),
            "observed_at": journal_record.get("observed_at"),
            "payload": journal_record.get("payload") or {},
        }
        if source == "coordinator":
            path = self.coordinator_path
        else:
            path = self.worker_path(runtime_worker_id or worker_id or "unknown-worker")
        return self._append(path, log_record)


def _append_structured_view(journal: EventJournal, record: Mapping[str, object]) -> None:
    store = getattr(journal, "_structured_log_store", None)
    if store is None:
        store = StructuredLogStore(journal.run_id, run_dir=journal.path.parent)
        journal._structured_log_store = store
    try:
        store.append_journal_record(record)
        journal._structured_log_error = None
    except (OSError, TypeError, ValueError) as exc:
        # events.jsonl remains the durable source of truth. Structured views are
        # deliberately non-intrusive and must never change coordinator behavior.
        journal._structured_log_error = f"{type(exc).__name__}: {exc}"


def install_structured_logging() -> None:
    """Attach structured coordinator/worker log views to EventJournal once."""
    if getattr(EventJournal, "_structured_logging_installed", False):
        return

    original_coordinator = EventJournal.append_coordinator_event
    original_worker = EventJournal.append_worker_event

    def append_coordinator_event(self: EventJournal, *args, **kwargs):
        record = original_coordinator(self, *args, **kwargs)
        _append_structured_view(self, record)
        return record

    def append_worker_event(self: EventJournal, *args, **kwargs):
        record = original_worker(self, *args, **kwargs)
        _append_structured_view(self, record)
        return record

    EventJournal.append_coordinator_event = append_coordinator_event
    EventJournal.append_worker_event = append_worker_event
    EventJournal._structured_logging_installed = True
