from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

from .event_journal import read_event_journal
from .status import read_status_snapshot
from .structured_logs import read_structured_log

OBSERVABILITY_SCHEMA_VERSION = 1
DEFAULT_RECENT_EVENTS = 8
_TERMINAL_STATES = {"completed", "completed_with_failures", "failed", "interrupted"}
_HEARTBEAT_KIND = "heartbeat"
_ERROR_KINDS = {"auth_failure", "job_failed", "worker_fatal"}
_WARNING_KINDS = {
    "global_cooldown_requested",
    "retry_scheduled",
    "worker_lost",
    "worker_recycled",
}


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: object) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _timestamp(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _duration_seconds(
    started_at: object,
    finished_at: object,
    *,
    now: datetime | None,
) -> float | None:
    started = _timestamp(started_at)
    if started is None:
        return None
    finished = _timestamp(finished_at) or now or datetime.now(timezone.utc)
    if finished.tzinfo is None:
        finished = finished.replace(tzinfo=timezone.utc)
    return round(max(0.0, (finished - started).total_seconds()), 3)


def _event_level(record: Mapping[str, object]) -> str:
    disposition = str(record.get("disposition") or "accepted")
    kind = str(record.get("kind") or "")
    if disposition != "accepted":
        return "WARNING"
    if kind in _ERROR_KINDS or kind.endswith("_failed") or "fatal" in kind:
        return "ERROR"
    if kind in _WARNING_KINDS or kind.startswith("retry_"):
        return "WARNING"
    return "INFO"


def resolve_run_dir(
    snapshot_path: Path,
    snapshot: Mapping[str, object],
    *,
    run_dir: Path | None = None,
) -> Path:
    """Resolve the per-run telemetry directory without mutating runtime state."""
    if run_dir is not None:
        return Path(run_dir).expanduser().resolve()
    run_id = str(snapshot.get("run_id") or "").strip()
    if not run_id:
        raise ValueError("Live status snapshot does not contain a run_id.")
    resolved = Path(snapshot_path).expanduser().resolve()
    if resolved.parent.name == run_id and resolved.parent.parent.name == "runs":
        return resolved.parent
    return resolved.parent / "runs" / run_id


def _read_journal(path: Path) -> tuple[list[dict[str, object]], str]:
    if not path.is_file():
        return [], "missing"
    try:
        return read_event_journal(path, strict=False), "ok"
    except OSError:
        return [], "unreadable"


def _read_log(path: Path) -> tuple[list[dict[str, object]], str]:
    if not path.is_file():
        return [], "missing"
    try:
        return read_structured_log(path, strict=False), "ok"
    except OSError:
        return [], "unreadable"


def _read_operational_logs(
    run_dir: Path,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    records, coordinator_state = _read_log(run_dir / "coordinator.jsonl")
    worker_states: dict[str, str] = {}
    worker_files = 0
    worker_dir = run_dir / "workers"
    if worker_dir.is_dir():
        for path in sorted(worker_dir.glob("*.jsonl"), key=lambda item: item.name):
            worker_files += 1
            worker_records, state = _read_log(path)
            worker_states[path.name] = state
            records.extend(worker_records)
    return records, {
        "coordinator_log": coordinator_state,
        "worker_log_files": worker_files,
        "worker_logs": worker_states,
    }


def _journal_metrics(records: list[dict[str, object]]) -> dict[str, object]:
    kinds = Counter(str(record.get("kind") or "unknown") for record in records)
    dispositions = Counter(
        str(record.get("disposition") or "unknown") for record in records
    )
    sources = Counter(str(record.get("source") or "unknown") for record in records)
    last = max(records, key=lambda record: _int(record.get("sequence")), default={})
    return {
        "total": len(records),
        "last_sequence": _int(last.get("sequence")),
        "last_observed_at": last.get("observed_at") or last.get("event_created_at"),
        "by_kind": dict(sorted(kinds.items())),
        "by_disposition": dict(sorted(dispositions.items())),
        "by_source": dict(sorted(sources.items())),
    }


def _operational_metrics(records: list[dict[str, object]]) -> dict[str, object]:
    levels = Counter(str(record.get("level") or "INFO").upper() for record in records)
    return {
        "total": len(records),
        "levels": {
            "INFO": levels.get("INFO", 0),
            "WARNING": levels.get("WARNING", 0),
            "ERROR": levels.get("ERROR", 0),
        },
    }


def _signals(
    records: list[dict[str, object]],
    control: Mapping[str, object],
) -> dict[str, int]:
    accepted = Counter(
        str(record.get("kind") or "")
        for record in records
        if str(record.get("disposition") or "accepted") == "accepted"
    )
    return {
        "retries": accepted.get("retry_scheduled", 0),
        "rate_limit_events": max(
            accepted.get("global_cooldown_requested", 0),
            _int(control.get("rate_limit_events")),
        ),
        "auth_failures": max(
            accepted.get("auth_failure", 0),
            _int(control.get("auth_failures")),
        ),
        "worker_lost": accepted.get("worker_lost", 0),
        "worker_recycled": accepted.get("worker_recycled", 0),
        "worker_fatal": accepted.get("worker_fatal", 0),
    }


def _recent_events(
    records: list[dict[str, object]],
    *,
    limit: int,
) -> list[dict[str, object]]:
    selected = [
        record for record in records if str(record.get("kind") or "") != _HEARTBEAT_KIND
    ]
    selected.sort(key=lambda record: _int(record.get("sequence")))
    result: list[dict[str, object]] = []
    for record in selected[-limit:] if limit else []:
        result.append(
            {
                "sequence": _int(record.get("sequence")),
                "observed_at": record.get("observed_at") or record.get("event_created_at"),
                "level": _event_level(record),
                "source": record.get("source"),
                "kind": record.get("kind"),
                "disposition": record.get("disposition"),
                "worker_id": record.get("worker_id"),
                "runtime_worker_id": record.get("runtime_worker_id"),
                "generation": record.get("generation"),
                "coordinator_generation": record.get("coordinator_generation"),
                "job_key": record.get("job_key"),
                "attempt": record.get("attempt"),
                "payload": _mapping(record.get("payload")),
            }
        )
    return result


def _workers(
    snapshot: Mapping[str, object],
    journal: list[dict[str, object]],
    operational: list[dict[str, object]],
) -> list[dict[str, object]]:
    current: dict[str, dict[str, object]] = {}
    raw_workers = snapshot.get("workers")
    if isinstance(raw_workers, list):
        for value in raw_workers:
            worker = _mapping(value)
            runtime_id = str(
                worker.get("runtime_worker_id") or worker.get("worker_id") or ""
            ).strip()
            if runtime_id:
                current[runtime_id] = worker

    latest: dict[str, dict[str, object]] = {}
    for record in journal:
        if str(record.get("source") or "") != "worker":
            continue
        runtime_id = str(
            record.get("runtime_worker_id") or record.get("worker_id") or ""
        ).strip()
        if runtime_id and _int(record.get("sequence")) >= _int(
            latest.get(runtime_id, {}).get("sequence")
        ):
            latest[runtime_id] = record

    levels: dict[str, Counter[str]] = {}
    for record in operational:
        if str(record.get("logger") or "") != "worker":
            continue
        runtime_id = str(
            record.get("runtime_worker_id") or record.get("worker_id") or ""
        ).strip()
        if runtime_id:
            levels.setdefault(runtime_id, Counter())[
                str(record.get("level") or "INFO").upper()
            ] += 1

    result: list[dict[str, object]] = []
    for runtime_id in sorted(set(current) | set(latest) | set(levels)):
        worker = current.get(runtime_id, {})
        event = latest.get(runtime_id, {})
        counts = levels.get(runtime_id, Counter())
        result.append(
            {
                "worker_id": worker.get("worker_id") or event.get("worker_id"),
                "runtime_worker_id": runtime_id,
                "generation": worker.get("generation") or event.get("generation"),
                "status": worker.get("status") or "historical",
                "job_key": worker.get("job_key") or event.get("job_key"),
                "source_filename": worker.get("source_filename"),
                "attempt": worker.get("attempt") or event.get("attempt"),
                "stage": worker.get("stage"),
                "stage_phase": worker.get("stage_phase"),
                "stage_elapsed_seconds": worker.get("stage_elapsed_seconds"),
                "last_activity_at": worker.get("last_activity_at")
                or event.get("observed_at")
                or event.get("event_created_at"),
                "last_event_kind": event.get("kind"),
                "last_event_disposition": event.get("disposition"),
                "operational_levels": {
                    "INFO": counts.get("INFO", 0),
                    "WARNING": counts.get("WARNING", 0),
                    "ERROR": counts.get("ERROR", 0),
                },
            }
        )
    return result


def build_run_observability(
    snapshot: Mapping[str, object],
    *,
    run_dir: Path,
    recent_events: int = DEFAULT_RECENT_EVENTS,
    now: datetime | None = None,
) -> dict[str, object]:
    """Assemble a read-only dashboard summary from existing telemetry artifacts."""
    if recent_events < 0:
        raise ValueError("recent_events must be non-negative")
    run_id = str(snapshot.get("run_id") or "").strip()
    if not run_id:
        raise ValueError("Status snapshot does not contain a run_id.")

    resolved_run_dir = Path(run_dir).expanduser().resolve()
    journal, journal_state = _read_journal(resolved_run_dir / "events.jsonl")
    operational, source_states = _read_operational_logs(resolved_run_dir)
    control = _mapping(snapshot.get("control"))
    state = str(snapshot.get("state") or "unknown")

    return {
        "schema_version": OBSERVABILITY_SCHEMA_VERSION,
        "run_id": run_id,
        "state": state,
        "mode": snapshot.get("mode"),
        "browser_provider": snapshot.get("browser_provider"),
        "started_at": snapshot.get("started_at"),
        "finished_at": snapshot.get("finished_at"),
        "updated_at": snapshot.get("updated_at"),
        "duration_seconds": _duration_seconds(
            snapshot.get("started_at"),
            snapshot.get("finished_at") if state in _TERMINAL_STATES else None,
            now=now,
        ),
        "requested_workers": snapshot.get("requested_workers"),
        "active_worker_limit": snapshot.get("active_worker_limit"),
        "counters": _mapping(snapshot.get("counters")),
        "control": control,
        "signals": _signals(journal, control),
        "events": _journal_metrics(journal),
        "operational_logs": _operational_metrics(operational),
        "workers": _workers(snapshot, journal, operational),
        "recent_events": _recent_events(journal, limit=recent_events),
        "sources": {
            "status": "ok",
            "event_journal": journal_state,
            **source_states,
        },
    }


def load_run_observability(
    snapshot_path: Path,
    *,
    run_dir: Path | None = None,
    recent_events: int = DEFAULT_RECENT_EVENTS,
    now: datetime | None = None,
) -> dict[str, object]:
    """Load a snapshot and its associated telemetry without changing runtime state."""
    resolved_snapshot = Path(snapshot_path).expanduser().resolve()
    snapshot = read_status_snapshot(resolved_snapshot)
    resolved_run_dir = resolve_run_dir(resolved_snapshot, snapshot, run_dir=run_dir)
    return build_run_observability(
        snapshot,
        run_dir=resolved_run_dir,
        recent_events=recent_events,
        now=now,
    )


def format_run_observability(summary: Mapping[str, object]) -> str:
    run_id = str(summary.get("run_id") or "unknown")
    state = str(summary.get("state") or "unknown")
    counters = _mapping(summary.get("counters"))
    signals = _mapping(summary.get("signals"))
    events = _mapping(summary.get("events"))
    levels = _mapping(_mapping(summary.get("operational_logs")).get("levels"))

    lines = [f"Run {run_id} — {state}"]
    if counters:
        lines.append(
            "Progress: "
            f"{_int(counters.get('completed'))}/{_int(counters.get('total'))} | "
            f"succeeded {_int(counters.get('succeeded'))} | "
            f"failed {_int(counters.get('failed'))} | "
            f"skipped {_int(counters.get('skipped'))} | "
            f"running {_int(counters.get('running'))} | "
            f"queued {_int(counters.get('queued'))}"
        )
    duration = _float(summary.get("duration_seconds"))
    if duration is not None:
        lines.append(f"Elapsed: {duration:.1f}s")
    lines.append(
        "Signals: "
        f"retries {_int(signals.get('retries'))} | "
        f"rate limits {_int(signals.get('rate_limit_events'))} | "
        f"auth failures {_int(signals.get('auth_failures'))} | "
        f"worker lost {_int(signals.get('worker_lost'))} | "
        f"worker fatal {_int(signals.get('worker_fatal'))}"
    )
    lines.append(
        "Events: "
        f"{_int(events.get('total'))} journaled | "
        f"warnings {_int(levels.get('WARNING'))} | "
        f"errors {_int(levels.get('ERROR'))}"
    )

    raw_workers = summary.get("workers")
    if isinstance(raw_workers, list):
        for value in raw_workers:
            worker = _mapping(value)
            runtime_id = str(
                worker.get("runtime_worker_id") or worker.get("worker_id") or "worker"
            )
            status = str(worker.get("status") or "unknown")
            details: list[str] = []
            source = worker.get("source_filename") or worker.get("job_key")
            if source:
                details.append(str(source))
            if worker.get("attempt") is not None:
                details.append(f"attempt {worker['attempt']}")
            if worker.get("stage"):
                elapsed = _float(worker.get("stage_elapsed_seconds"))
                stage = str(worker["stage"])
                details.append(stage if elapsed is None else f"{stage} ({elapsed:.1f}s)")
            if worker.get("last_event_kind"):
                details.append(f"last {worker['last_event_kind']}")
            suffix = f" — {', '.join(details)}" if details else ""
            lines.append(f"{runtime_id} [{status}]{suffix}")

    recent = summary.get("recent_events")
    if isinstance(recent, list) and recent:
        lines.append("Recent events:")
        for value in recent:
            event = _mapping(value)
            parts = [
                f"#{_int(event.get('sequence'))}",
                f"[{event.get('level') or 'INFO'}]",
                str(event.get("kind") or "event"),
            ]
            if str(event.get("disposition") or "accepted") != "accepted":
                parts.append(f"({event['disposition']})")
            if event.get("runtime_worker_id"):
                parts.append(str(event["runtime_worker_id"]))
            if event.get("job_key"):
                parts.append(str(event["job_key"]))
            lines.append("  " + " ".join(parts))

    sources = _mapping(summary.get("sources"))
    degraded = [
        f"{key}={value}"
        for key, value in sorted(sources.items())
        if key not in {"worker_logs", "worker_log_files"} and value != "ok"
    ]
    worker_logs = sources.get("worker_logs")
    if isinstance(worker_logs, Mapping):
        degraded.extend(
            f"worker_log:{name}={value}"
            for name, value in sorted(worker_logs.items())
            if value != "ok"
        )
    if degraded:
        lines.append("Telemetry: " + ", ".join(degraded))
    return "\n".join(lines)
