from __future__ import annotations

import hashlib
import json
import os
import socket
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from process_liveness import pid_is_alive


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_time(value: object) -> float:
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except (TypeError, ValueError):
        return 0.0


def _pid_alive(pid: int) -> bool:
    return pid_is_alive(pid)


@dataclass(frozen=True)
class JobClaim:
    job_key: str
    run_id: str
    worker_id: str
    worker_pid: int
    token: str
    path: Path
    claimed_at: str


class ClaimStore:
    """Cross-coordinator atomic job claims backed by O_EXCL files."""

    def __init__(self, root: Path, *, stale_after: float = 60.0) -> None:
        self.root = Path(root).expanduser().resolve()
        self.stale_after = max(1.0, float(stale_after))
        self.hostname = socket.gethostname()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, job_key: str) -> Path:
        digest = hashlib.sha256(job_key.encode("utf-8")).hexdigest()
        return self.root / f"{digest}.claim.json"

    def _read(self, path: Path) -> dict[str, object] | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _is_stale(self, payload: dict[str, object], path: Path) -> bool:
        heartbeat_at = _parse_time(payload.get("heartbeat_at") or payload.get("claimed_at"))
        age = max(0.0, time.time() - heartbeat_at)
        if age <= self.stale_after:
            return False
        if payload.get("hostname") == self.hostname:
            try:
                pid = int(payload.get("worker_pid") or 0)
            except (TypeError, ValueError):
                pid = 0
            if _pid_alive(pid):
                return False
        try:
            return time.time() - path.stat().st_mtime > self.stale_after
        except FileNotFoundError:
            return True

    def try_acquire(
        self,
        job_key: str,
        *,
        run_id: str,
        worker_id: str,
        worker_pid: int,
    ) -> JobClaim | None:
        path = self._path(job_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(3):
            existing = self._read(path)
            if existing is not None:
                if not self._is_stale(existing, path):
                    return None
                stale = path.with_suffix(path.suffix + f".stale-{uuid4().hex}")
                try:
                    os.replace(path, stale)
                except FileNotFoundError:
                    continue
                finally:
                    stale.unlink(missing_ok=True)
            token = uuid4().hex
            now = utc_now()
            payload = {
                "job_key": job_key,
                "run_id": run_id,
                "worker_id": worker_id,
                "worker_pid": int(worker_pid),
                "hostname": self.hostname,
                "token": token,
                "claimed_at": now,
                "heartbeat_at": now,
            }
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            return JobClaim(
                job_key=job_key,
                run_id=run_id,
                worker_id=worker_id,
                worker_pid=int(worker_pid),
                token=token,
                path=path,
                claimed_at=now,
            )
        return None

    def heartbeat(self, claim: JobClaim) -> bool:
        payload = self._read(claim.path)
        if payload is None or payload.get("token") != claim.token:
            return False
        payload["heartbeat_at"] = utc_now()
        temporary = claim.path.parent / f".{claim.path.name}.{claim.token}.tmp"
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            current = self._read(claim.path)
            if current is None or current.get("token") != claim.token:
                return False
            os.replace(temporary, claim.path)
            return True
        finally:
            temporary.unlink(missing_ok=True)


    def recover_stale(self) -> tuple[Path, ...]:
        """Remove stale claim files at coordinator startup and report recoveries."""
        recovered: list[Path] = []
        self.root.mkdir(parents=True, exist_ok=True)
        for path in sorted(self.root.glob("*.claim.json")):
            payload = self._read(path)
            if payload is None:
                try:
                    age = time.time() - path.stat().st_mtime
                except FileNotFoundError:
                    continue
                if age <= self.stale_after:
                    continue
            elif not self._is_stale(payload, path):
                continue
            quarantine = path.with_suffix(path.suffix + f".stale-{uuid4().hex}")
            try:
                os.replace(path, quarantine)
            except FileNotFoundError:
                continue
            quarantine.unlink(missing_ok=True)
            recovered.append(path)
        return tuple(recovered)

    def release_run(self, run_id: str) -> int:
        """Release only claims still owned by this run; foreign claims are untouched."""
        released = 0
        for path in sorted(self.root.glob("*.claim.json")):
            payload = self._read(path)
            if payload is None or payload.get("run_id") != run_id:
                continue
            try:
                path.unlink()
            except FileNotFoundError:
                continue
            released += 1
        return released

    def release(self, claim: JobClaim) -> bool:
        payload = self._read(claim.path)
        if payload is None:
            return True
        if payload.get("token") != claim.token:
            return False
        try:
            claim.path.unlink()
        except FileNotFoundError:
            pass
        return True
