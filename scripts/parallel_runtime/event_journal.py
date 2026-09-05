from __future__ import annotations

import json
import math
import os
import threading
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Mapping

from .event_bus import WorkerEvent


EVENT_JOURNAL_SCHEMA_VERSION = 1
_MAX_STRING_LENGTH = 16_384
_MAX_COLLECTION_ITEMS = 100
_MAX_DEPTH = 6
_REDACTED = "[redacted]"
_SENSITIVE_KEYS = {
    "password",
    "passwd",
    "secret",
    "token",
    "cookie",
    "authorization",
    "api_key",
    "apikey",
    "access_key",
    "refresh_token",
    "session_token",
    "claim_id",
    "credential",
    "credentials",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_logs_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "logs"


def _is_sensitive_key(value: object) -> bool:
    normalized = str(value).strip().lower().replace("-", "_")
    return normalized in _SENSITIVE_KEYS or any(
        normalized.endswith(f"_{candidate}") for candidate in _SENSITIVE_KEYS
    )


def _bounded_text(value: object) -> str:
    text = str(value)
    if len(text) <= _MAX_STRING_LENGTH:
        return text
    return text[:_MAX_STRING_LENGTH] + "…[truncated]"


def _sanitize(value: object, *, key: object | None = None, depth: int = 0) -> object:
    if key is not None and _is_sensitive_key(key):
        return _REDACTED
    if depth >= _MAX_DEPTH:
        return _bounded_text(value)
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else _bounded_text(value)
    if isinstance(value, str):
        stripped = value.lstrip()
        if stripped.lower().startswith("bearer "):
            return _REDACTED
        return _bounded_text(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return _sanitize(value.value, depth=depth + 1)
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for index, (raw_key, raw_value) in enumerate(value.items()):
            if index >= _MAX_COLLECTION_ITEMS:
                result["__truncated_items__"] = max(0, len(value) - _MAX_COLLECTION_ITEMS)
                break
            item_key = str(raw_key)
            result[item_key] = _sanitize(raw_value, key=item_key, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple, set, frozenset)):
        items = list(value)
        if isinstance(value, (set, frozenset)):
            items.sort(key=repr)
        result = [
            _sanitize(item, depth=depth + 1)
            for item in items[:_MAX_COLLECTION_ITEMS]
        ]
        if len(items) > _MAX_COLLECTION_ITEMS:
            result.append(f"…[{len(items) - _MAX_COLLECTION_ITEMS} items truncated]")
        return result
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"
    return _bounded_text(value)


def _runtime_generation(worker_id: str | None, runtime_worker_id: str | None) -> int | None:
    if not worker_id or not runtime_worker_id:
        return None
    if runtime_worker_id == worker_id:
        return 1
    prefix = f"{worker_id}-g"
    if not runtime_worker_id.startswith(prefix):
        return None
    raw = runtime_worker_id[len(prefix) :]
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value >= 1 else None


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def read_event_journal(path: Path, *, strict: bool = False) -> list[dict[str, object]]:
    """Read valid JSONL journal records.

    Non-strict reads skip malformed records so a torn final write from a hard
    process or host failure never hides later valid records appended after a
    restart. Strict mode is available for integrity checks and tests.
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
                        f"Malformed event journal record at {resolved}:{line_number}: {exc}"
                    ) from exc
                continue
            if not isinstance(payload, dict):
                if strict:
                    raise ValueError(
                        f"Event journal record at {resolved}:{line_number} must be an object."
                    )
                continue
            version = _optional_int(payload.get("schema_version"))
            if version != EVENT_JOURNAL_SCHEMA_VERSION:
                if strict:
                    raise ValueError(
                        f"Unsupported event journal schema_version {version!r} at "
                        f"{resolved}:{line_number}."
                    )
                continue
            records.append(payload)
    return records


class EventJournal:
    """Coordinator-owned append-only JSONL event journal for one run."""

    def __init__(
        self,
        run_id: str,
        *,
        logs_dir: Path | None = None,
        path: Path | None = None,
    ) -> None:
        if not str(run_id).strip():
            raise ValueError("run_id must not be empty")
        self.run_id = str(run_id)
        self.logs_dir = (Path(logs_dir) if logs_dir is not None else default_logs_dir()).resolve()
        self.path = (
            Path(path).expanduser().resolve()
            if path is not None
            else self.logs_dir / "runs" / self.run_id / "events.jsonl"
        )
        self._lock = threading.Lock()
        self._boundary_checked = False
        self._next_sequence = self._discover_next_sequence()

    def _discover_next_sequence(self) -> int:
        if not self.path.is_file():
            return 1
        try:
            records = read_event_journal(self.path, strict=False)
        except OSError:
            return 1
        sequence = max(
            (_optional_int(record.get("sequence")) or 0 for record in records),
            default=0,
        )
        return sequence + 1

    @staticmethod
    def _write_all(fd: int, data: bytes) -> None:
        offset = 0
        while offset < len(data):
            written = os.write(fd, data[offset:])
            if written <= 0:
                raise OSError("Could not append event journal record.")
            offset += written

    def _ensure_append_boundary(self) -> None:
        if self._boundary_checked:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_file() and self.path.stat().st_size > 0:
            with self.path.open("rb") as handle:
                handle.seek(-1, os.SEEK_END)
                ends_with_newline = handle.read(1) == b"\n"
            if not ends_with_newline:
                fd = os.open(self.path, os.O_WRONLY | os.O_APPEND)
                try:
                    self._write_all(fd, b"\n")
                    os.fsync(fd)
                finally:
                    os.close(fd)
        self._boundary_checked = True

    def _append(self, record: Mapping[str, object]) -> dict[str, object]:
        with self._lock:
            self._ensure_append_boundary()
            payload = {
                "schema_version": EVENT_JOURNAL_SCHEMA_VERSION,
                "sequence": self._next_sequence,
                "run_id": self.run_id,
                **dict(record),
            }
            sanitized = _sanitize(payload)
            if not isinstance(sanitized, dict):
                raise TypeError("Sanitized event journal record must remain an object.")
            encoded = (
                json.dumps(
                    sanitized,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("utf-8")
            fd = os.open(
                self.path,
                os.O_CREAT | os.O_APPEND | os.O_WRONLY,
                0o600,
            )
            try:
                self._write_all(fd, encoded)
                os.fsync(fd)
            finally:
                os.close(fd)
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
            self._next_sequence += 1
            return sanitized

    def append_worker_event(
        self,
        event: WorkerEvent,
        *,
        generation: int | None = None,
        attempt: int | None = None,
        disposition: str = "accepted",
    ) -> dict[str, object]:
        raw_payload = dict(event.payload)
        source_job_key = raw_payload.get("source_job_key")
        correlated_job_key = (
            str(source_job_key)
            if source_job_key is not None and str(source_job_key).strip()
            else event.job_key
        )
        resolved_attempt = attempt
        if resolved_attempt is None:
            resolved_attempt = _optional_int(raw_payload.get("attempt"))
        event_generation = _runtime_generation(event.worker_id, event.runtime_worker_id)
        resolved_generation = event_generation if event_generation is not None else generation
        record: dict[str, object] = {
            "source": "worker",
            "kind": event.kind.value,
            "disposition": str(disposition),
            "worker_id": event.worker_id,
            "runtime_worker_id": event.runtime_worker_id,
            "generation": resolved_generation,
            "job_key": correlated_job_key,
            "attempt": resolved_attempt,
            "event_created_at": event.created_at,
            "observed_at": utc_now(),
            "payload": raw_payload,
        }
        if generation is not None and event_generation is not None and generation != event_generation:
            record["coordinator_generation"] = generation
        if event.job_key is not None and event.job_key != correlated_job_key:
            record["event_job_key"] = event.job_key
        return self._append(record)

    def append_coordinator_event(
        self,
        kind: str,
        *,
        worker_id: str | None = None,
        runtime_worker_id: str | None = None,
        generation: int | None = None,
        job_key: str | None = None,
        attempt: int | None = None,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        observed_at = utc_now()
        return self._append(
            {
                "source": "coordinator",
                "kind": str(kind),
                "disposition": "accepted",
                "worker_id": worker_id,
                "runtime_worker_id": runtime_worker_id,
                "generation": generation,
                "job_key": job_key,
                "attempt": attempt,
                "event_created_at": observed_at,
                "observed_at": observed_at,
                "payload": dict(payload or {}),
            }
        )
