from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import sqlite3
import stat
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping
from uuid import uuid4

from process_liveness import pid_is_alive

from .errors import (
    ActiveProfileError,
    ProfileLeaseError,
    ProfileSnapshotError,
)

SNAPSHOT_SCHEMA_VERSION = 1
PROFILE_METADATA_SCHEMA_VERSION = 1
OWNER_FILENAME = ".note-maker-profile-owner.json"
PROFILE_METADATA_FILENAME = ".note-maker-profile.json"
SNAPSHOT_METADATA_FILENAME = "snapshot.json"

AUTH_COOKIE_MARKERS = frozenset(
    {
        "__Secure-next-auth.session-token",
        "__Secure-next-auth.session-token.0",
        "__Secure-next-auth.session-token.1",
        "__Secure-oai-is",
        "oai-did",
        "cf_clearance",
    }
)

# Only session-bearing files are copied. Cache, GPU data, crash reports and browser
# binaries are intentionally excluded to keep snapshots portable and small.
SESSION_PROFILE_ITEMS = (
    Path("Local State"),
    Path("Default/Cookies"),
    Path("Default/Cookies-journal"),
    Path("Default/Cookies-wal"),
    Path("Default/Cookies-shm"),
    Path("Default/Network/Cookies"),
    Path("Default/Network/Cookies-journal"),
    Path("Default/Network/Cookies-wal"),
    Path("Default/Network/Cookies-shm"),
    Path("Default/Login Data"),
    Path("Default/Login Data-journal"),
    Path("Default/Login Data-wal"),
    Path("Default/Login Data-shm"),
    Path("Default/Web Data"),
    Path("Default/Web Data-journal"),
    Path("Default/Local Storage"),
    Path("Default/Session Storage"),
    Path("Default/IndexedDB"),
    Path("Default/Preferences"),
    Path("Default/Secure Preferences"),
)

CHROME_SINGLETON_NAMES = ("SingletonLock", "SingletonSocket", "SingletonCookie")
ABSOLUTE_PATH_KEYWORDS = (
    "directory",
    "download_path",
    "last_directory",
    "last_selected_directory",
    "savefile",
    "selectfile",
)
WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")
SAFE_COMPONENT_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_component(value: str, *, fallback: str) -> str:
    cleaned = SAFE_COMPONENT_RE.sub("-", str(value).strip()).strip(".-")
    return cleaned or fallback


def _ensure_private_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass
    return path


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    _ensure_private_directory(path.parent)
    temporary = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    data = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iter_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            yield path


def _ignore_unsafe_entries(directory: str, names: list[str]) -> set[str]:
    base = Path(directory)
    ignored: set[str] = set()
    for name in names:
        candidate = base / name
        if candidate.is_symlink() or name in CHROME_SINGLETON_NAMES or name == OWNER_FILENAME:
            ignored.add(name)
    return ignored


def _copytree_safe(source: Path, target: Path) -> None:
    shutil.copytree(
        source,
        target,
        symlinks=False,
        ignore=_ignore_unsafe_entries,
    )


def _validated_relative(value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts or relative == Path("."):
        raise ProfileSnapshotError(f"Unsafe relative path in snapshot metadata: {value!r}")
    return relative


def _is_absolute_path_text(value: str) -> bool:
    return value.startswith("/") or value.startswith("\\\\") or bool(WINDOWS_ABSOLUTE_RE.match(value))


def _sanitize_json_paths(value: Any, *, key: str = "", changed: list[str] | None = None) -> Any:
    changed = changed if changed is not None else []
    if isinstance(value, dict):
        return {
            str(child_key): _sanitize_json_paths(
                child_value,
                key=str(child_key),
                changed=changed,
            )
            for child_key, child_value in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_json_paths(item, key=key, changed=changed) for item in value]
    if isinstance(value, str):
        lowered_key = key.lower()
        if _is_absolute_path_text(value) and any(marker in lowered_key for marker in ABSOLUTE_PATH_KEYWORDS):
            changed.append(key)
            return ""
    return value


def _sanitize_copied_json(path: Path) -> tuple[str, ...]:
    if not path.exists() or not path.is_file():
        return ()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return ()
    changed: list[str] = []
    sanitized = _sanitize_json_paths(payload, changed=changed)
    if not changed:
        return ()
    _write_json_atomic(path, sanitized)
    return tuple(sorted(set(changed)))


def _pid_alive(pid: int) -> bool:
    return pid_is_alive(pid)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _cookie_db_candidates(profile_dir: Path) -> tuple[Path, ...]:
    return (
        profile_dir / "Default" / "Network" / "Cookies",
        profile_dir / "Default" / "Cookies",
    )


def _chromium_expiry_is_valid(raw: Any, *, now: float | None = None) -> bool:
    try:
        value = int(raw or 0)
    except (TypeError, ValueError):
        return True
    if value == 0:
        return True
    # Chromium stores microseconds since 1601-01-01.
    unix_seconds = value / 1_000_000 - 11_644_473_600
    return unix_seconds > (time.time() if now is None else now)


@dataclass(frozen=True)
class AuthSessionEvidence:
    authenticated: bool
    cookie_database: Path | None = None
    markers: tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class ProfileActivity:
    active: bool
    active_markers: tuple[str, ...] = ()
    stale_markers: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProfileSnapshot:
    snapshot_id: str
    path: Path
    created_at: str
    items: tuple[str, ...]
    auth_markers: tuple[str, ...]
    portable: bool
    sanitized_path_keys: tuple[str, ...] = ()

    @property
    def metadata_path(self) -> Path:
        return self.path / SNAPSHOT_METADATA_FILENAME


@dataclass(frozen=True)
class WorkerProfileContext:
    run_id: str
    worker_id: str
    root: Path
    profile_dir: Path
    download_dir: Path
    log_dir: Path
    diagnostics_dir: Path
    snapshot_id: str | None = None
    managed: bool = True

    @property
    def metadata_path(self) -> Path:
        return self.root / PROFILE_METADATA_FILENAME


@dataclass(frozen=True)
class RunProfileContext:
    run_id: str
    root: Path
    workers_dir: Path
    created_at: str


class RetentionPolicy(str, Enum):
    DELETE_SUCCESS_KEEP_FAILURE = "delete-success-keep-failure"
    KEEP_ALL = "keep-all"
    DELETE_ALL = "delete-all"


class ProfileLease:
    """Atomic process ownership for one browser profile directory."""

    def __init__(
        self,
        profile_dir: Path,
        *,
        run_id: str,
        worker_id: str,
        stale_after_seconds: int = 24 * 60 * 60,
    ) -> None:
        if stale_after_seconds < 1:
            raise ValueError("stale_after_seconds must be at least 1")
        self.profile_dir = Path(profile_dir).expanduser().resolve()
        self.run_id = str(run_id)
        self.worker_id = str(worker_id)
        self.stale_after_seconds = stale_after_seconds
        self.token = uuid4().hex
        self.path = self.profile_dir / OWNER_FILENAME
        self._acquired = False

    @staticmethod
    def _owner_is_stale(payload: Mapping[str, Any], *, stale_after_seconds: int) -> bool:
        hostname = str(payload.get("hostname", ""))
        try:
            pid = int(payload.get("pid", 0))
        except (TypeError, ValueError):
            pid = 0
        if hostname == socket.gethostname() and pid > 0:
            return not _pid_alive(pid)
        # A lease from another host cannot be proven stale safely on a shared
        # filesystem, so fail closed instead of stealing it by age.
        return False

    def acquire(self) -> "ProfileLease":
        _ensure_private_directory(self.profile_dir)
        payload = {
            "schema_version": PROFILE_METADATA_SCHEMA_VERSION,
            "token": self.token,
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
            "run_id": self.run_id,
            "worker_id": self.worker_id,
            "acquired_at": _utc_now(),
            "acquired_epoch": time.time(),
        }
        data = json.dumps(payload, indent=2, sort_keys=True)
        for attempt in range(2):
            try:
                fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError as exc:
                existing = _read_json(self.path)
                if attempt == 0 and existing is not None and self._owner_is_stale(
                    existing,
                    stale_after_seconds=self.stale_after_seconds,
                ):
                    self.path.unlink(missing_ok=True)
                    continue
                owner = "unknown"
                if existing:
                    owner = (
                        f"pid={existing.get('pid')} host={existing.get('hostname')} "
                        f"run={existing.get('run_id')} worker={existing.get('worker_id')}"
                    )
                raise ProfileLeaseError(
                    f"Profile is already owned: {self.profile_dir} ({owner})"
                ) from exc
            else:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                self._acquired = True
                return self
        raise ProfileLeaseError(f"Could not acquire profile lease: {self.profile_dir}")

    def release(self) -> None:
        if not self._acquired:
            return
        existing = _read_json(self.path)
        if existing and existing.get("token") == self.token:
            self.path.unlink(missing_ok=True)
        self._acquired = False

    def __enter__(self) -> "ProfileLease":
        return self.acquire()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


class ProfileManager:
    def __init__(
        self,
        *,
        runtime_root: Path,
        snapshot_root: Path,
        retention_policy: RetentionPolicy = RetentionPolicy.DELETE_SUCCESS_KEEP_FAILURE,
    ) -> None:
        self.runtime_root = Path(runtime_root).expanduser().resolve()
        self.snapshot_root = Path(snapshot_root).expanduser().resolve()
        self.retention_policy = RetentionPolicy(retention_policy)
        _ensure_private_directory(self.runtime_root)
        _ensure_private_directory(self.snapshot_root)

    @classmethod
    def from_environment(cls, project_root: Path) -> "ProfileManager":
        project_root = Path(project_root).resolve()
        runtime_root = Path(os.environ.get("CHATGPT_RUNTIME_DIR", project_root / ".runtime"))
        snapshot_root = Path(
            os.environ.get("CHATGPT_PROFILE_TEMPLATE_DIR", project_root / "profile_templates")
        )
        retention = os.environ.get(
            "CHATGPT_RUNTIME_RETENTION",
            RetentionPolicy.DELETE_SUCCESS_KEEP_FAILURE.value,
        )
        return cls(
            runtime_root=runtime_root,
            snapshot_root=snapshot_root,
            retention_policy=RetentionPolicy(retention),
        )

    @staticmethod
    def inspect_auth_session(profile_dir: Path) -> AuthSessionEvidence:
        profile_dir = Path(profile_dir).expanduser().resolve()
        for database in _cookie_db_candidates(profile_dir):
            if not database.exists() or database.stat().st_size < 128:
                continue
            try:
                uri = f"file:{database.as_posix()}?mode=ro"
                connection = sqlite3.connect(uri, uri=True)
                try:
                    try:
                        rows = connection.execute(
                            "SELECT name, host_key, expires_utc FROM cookies"
                        ).fetchall()
                    except sqlite3.OperationalError:
                        rows = [
                            (name, host, 0)
                            for name, host in connection.execute(
                                "SELECT name, host_key FROM cookies"
                            ).fetchall()
                        ]
                finally:
                    connection.close()
            except (OSError, sqlite3.Error):
                continue
            markers: set[str] = set()
            for name, host, expires in rows:
                cookie_name = str(name or "")
                host_name = str(host or "").lower()
                if "chatgpt.com" not in host_name and "openai.com" not in host_name:
                    continue
                if cookie_name in AUTH_COOKIE_MARKERS or cookie_name.startswith(
                    "__Secure-next-auth.session-token"
                ):
                    if _chromium_expiry_is_valid(expires):
                        markers.add(cookie_name)
            if markers:
                return AuthSessionEvidence(
                    True,
                    database,
                    tuple(sorted(markers)),
                    "ChatGPT/OpenAI authentication cookie evidence found.",
                )
        return AuthSessionEvidence(
            False,
            None,
            (),
            "No unexpired ChatGPT/OpenAI authentication cookie marker was found.",
        )

    @staticmethod
    def inspect_activity(profile_dir: Path) -> ProfileActivity:
        profile_dir = Path(profile_dir).expanduser().resolve()
        active: list[str] = []
        stale: list[str] = []
        owner = profile_dir / OWNER_FILENAME
        if owner.exists():
            payload = _read_json(owner)
            if payload and ProfileLease._owner_is_stale(payload, stale_after_seconds=24 * 60 * 60):
                stale.append(OWNER_FILENAME)
            else:
                active.append(OWNER_FILENAME)

        hostname = socket.gethostname()
        for parent in (profile_dir, profile_dir / "Default"):
            for name in CHROME_SINGLETON_NAMES:
                marker = parent / name
                if not marker.exists() and not marker.is_symlink():
                    continue
                display = str(marker.relative_to(profile_dir))
                if marker.is_symlink():
                    try:
                        target = os.readlink(marker)
                    except OSError:
                        active.append(display)
                        continue
                    match = re.search(r"(.+)-(\d+)$", target)
                    if match and match.group(1) in {hostname, socket.getfqdn()}:
                        stale.append(display) if not _pid_alive(int(match.group(2))) else active.append(display)
                    else:
                        active.append(display)
                else:
                    # A regular SingletonSocket/Cookie cannot be proven stale safely.
                    active.append(display)
        return ProfileActivity(bool(active), tuple(sorted(active)), tuple(sorted(stale)))

    @classmethod
    def assert_profile_inactive(cls, profile_dir: Path) -> None:
        activity = cls.inspect_activity(profile_dir)
        if activity.active:
            raise ActiveProfileError(
                f"Profile appears active and cannot be copied: {Path(profile_dir).resolve()} "
                f"(markers: {', '.join(activity.active_markers)})"
            )

    @classmethod
    def clear_stale_locks(cls, profile_dir: Path) -> tuple[str, ...]:
        profile_dir = Path(profile_dir).expanduser().resolve()
        activity = cls.inspect_activity(profile_dir)
        if activity.active:
            raise ActiveProfileError(
                f"Refusing to clear locks from an active profile: {profile_dir}"
            )
        removed: list[str] = []
        for relative in activity.stale_markers:
            marker = profile_dir / relative
            marker.unlink(missing_ok=True)
            removed.append(relative)
        return tuple(sorted(removed))

    def create_snapshot(
        self,
        source_profile: Path,
        *,
        name: str | None = None,
        require_auth: bool = True,
    ) -> ProfileSnapshot:
        source_profile = Path(source_profile).expanduser().resolve()
        if not source_profile.exists() or not source_profile.is_dir():
            raise ProfileSnapshotError(f"Source profile does not exist: {source_profile}")
        self.assert_profile_inactive(source_profile)
        evidence = self.inspect_auth_session(source_profile)
        if require_auth and not evidence.authenticated:
            raise ProfileSnapshotError(evidence.reason)

        base_name = _safe_component(name or "session", fallback="session")
        snapshot_id = f"{base_name}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"
        destination = self.snapshot_root / snapshot_id
        if destination.exists():
            raise ProfileSnapshotError(f"Snapshot already exists: {destination}")
        temporary = Path(tempfile.mkdtemp(prefix=f".{snapshot_id}.", dir=self.snapshot_root))
        copied_items: list[str] = []
        sanitized: list[str] = []
        try:
            for relative in SESSION_PROFILE_ITEMS:
                source = source_profile / relative
                if not source.exists() or source.is_symlink():
                    continue
                target = temporary / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if source.is_dir():
                    _copytree_safe(source, target)
                elif source.is_file():
                    shutil.copy2(source, target)
                else:
                    continue
                copied_items.append(relative.as_posix())

            if not copied_items:
                raise ProfileSnapshotError(
                    f"No supported session data was found in profile: {source_profile}"
                )

            # Do not rewrite Secure Preferences: Chromium protects portions of
            # that file with integrity metadata and may discard it when changed.
            for relative in (Path("Local State"), Path("Default/Preferences")):
                for key in _sanitize_copied_json(temporary / relative):
                    sanitized.append(f"{relative.as_posix()}::{key}")

            copied_evidence = self.inspect_auth_session(temporary)
            if require_auth and not copied_evidence.authenticated:
                raise ProfileSnapshotError(
                    "Authentication evidence was not preserved in the session snapshot."
                )

            files = []
            for file_path in _iter_files(temporary):
                relative = file_path.relative_to(temporary).as_posix()
                files.append(
                    {
                        "path": relative,
                        "size": file_path.stat().st_size,
                        "sha256": _sha256_file(file_path),
                    }
                )
                try:
                    file_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
                except OSError:
                    pass
            for directory in sorted((path for path in temporary.rglob("*") if path.is_dir()), reverse=True):
                try:
                    directory.chmod(0o700)
                except OSError:
                    pass

            source_fingerprint = hashlib.sha256(str(source_profile).encode("utf-8")).hexdigest()
            metadata = {
                "schema_version": SNAPSHOT_SCHEMA_VERSION,
                "snapshot_id": snapshot_id,
                "created_at": _utc_now(),
                "source_profile_name": source_profile.name,
                "source_fingerprint": source_fingerprint,
                "portable": True,
                "copied_items": sorted(copied_items),
                "auth_markers": list(copied_evidence.markers),
                "sanitized_path_keys": sorted(set(sanitized)),
                "files": files,
            }
            _write_json_atomic(temporary / SNAPSHOT_METADATA_FILENAME, metadata)
            os.replace(temporary, destination)
            _ensure_private_directory(destination)
            return self.load_snapshot(destination)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    def load_snapshot(self, snapshot: str | Path) -> ProfileSnapshot:
        candidate = Path(snapshot).expanduser()
        path = candidate.resolve() if candidate.exists() else (self.snapshot_root / str(snapshot)).resolve()
        metadata_path = path / SNAPSHOT_METADATA_FILENAME
        payload = _read_json(metadata_path)
        if payload is None:
            raise ProfileSnapshotError(f"Invalid or missing snapshot metadata: {metadata_path}")
        if payload.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
            raise ProfileSnapshotError(
                f"Unsupported snapshot schema: {payload.get('schema_version')!r}"
            )
        if str(payload.get("snapshot_id", "")) != path.name:
            raise ProfileSnapshotError("Snapshot id does not match its directory name.")
        copied_items = tuple(str(item) for item in payload.get("copied_items", []))
        for item in copied_items:
            relative = _validated_relative(item)
            candidate_path = path / relative
            if not candidate_path.exists() or candidate_path.is_symlink():
                raise ProfileSnapshotError(f"Snapshot item is missing or unsafe: {item}")
        for record in payload.get("files", []):
            if not isinstance(record, dict):
                raise ProfileSnapshotError("Invalid file record in snapshot metadata.")
            relative = _validated_relative(str(record.get("path", "")))
            candidate_path = path / relative
            if not candidate_path.is_file() or candidate_path.is_symlink():
                raise ProfileSnapshotError(f"Snapshot file is missing or unsafe: {relative}")
            if candidate_path.stat().st_size != int(record.get("size", -1)):
                raise ProfileSnapshotError(f"Snapshot file size mismatch: {relative}")
            if _sha256_file(candidate_path) != str(record.get("sha256", "")):
                raise ProfileSnapshotError(f"Snapshot file checksum mismatch: {relative}")
        return ProfileSnapshot(
            snapshot_id=path.name,
            path=path,
            created_at=str(payload.get("created_at", "")),
            items=copied_items,
            auth_markers=tuple(str(item) for item in payload.get("auth_markers", [])),
            portable=bool(payload.get("portable", False)),
            sanitized_path_keys=tuple(
                str(item) for item in payload.get("sanitized_path_keys", [])
            ),
        )

    def create_run(self, run_id: str) -> RunProfileContext:
        safe_run_id = _safe_component(run_id, fallback=f"run-{uuid4().hex[:8]}")
        root = _ensure_private_directory(self.runtime_root / "runs" / safe_run_id)
        workers_dir = _ensure_private_directory(root / "workers")
        metadata_path = root / "run.json"
        if metadata_path.exists():
            payload = _read_json(metadata_path) or {}
            created_at = str(payload.get("created_at", _utc_now()))
        else:
            created_at = _utc_now()
            _write_json_atomic(
                metadata_path,
                {
                    "schema_version": PROFILE_METADATA_SCHEMA_VERSION,
                    "run_id": safe_run_id,
                    "created_at": created_at,
                    "retention_policy": self.retention_policy.value,
                },
            )
        return RunProfileContext(safe_run_id, root, workers_dir, created_at)

    def _copy_snapshot_to_profile(self, snapshot: ProfileSnapshot, profile_dir: Path) -> None:
        if profile_dir.exists() and any(profile_dir.iterdir()):
            raise ProfileSnapshotError(f"Worker profile destination is not empty: {profile_dir}")
        temporary = profile_dir.parent / f".{profile_dir.name}.{uuid4().hex}.tmp"
        temporary.mkdir(parents=True, exist_ok=False)
        try:
            for item in snapshot.items:
                relative = _validated_relative(item)
                source = snapshot.path / relative
                target = temporary / relative
                if not source.exists() or source.is_symlink():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                if source.is_dir():
                    _copytree_safe(source, target)
                else:
                    shutil.copy2(source, target)
            _write_json_atomic(
                temporary / PROFILE_METADATA_FILENAME,
                {
                    "schema_version": PROFILE_METADATA_SCHEMA_VERSION,
                    "snapshot_id": snapshot.snapshot_id,
                    "created_at": _utc_now(),
                    "portable_snapshot": snapshot.portable,
                },
            )
            if profile_dir.exists():
                profile_dir.rmdir()
            os.replace(temporary, profile_dir)
            _ensure_private_directory(profile_dir)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    def prepare_worker(
        self,
        *,
        run_id: str,
        worker_id: str,
        snapshot: ProfileSnapshot | str | Path | None = None,
        recreate: bool = False,
    ) -> WorkerProfileContext:
        run = self.create_run(run_id)
        safe_worker_id = _safe_component(worker_id, fallback="worker-001")
        worker_root = run.workers_dir / safe_worker_id
        if recreate and worker_root.exists():
            self.assert_profile_inactive(worker_root / "profile")
            shutil.rmtree(worker_root)
        _ensure_private_directory(worker_root)
        profile_dir = worker_root / "profile"
        download_dir = _ensure_private_directory(worker_root / "downloads")
        log_dir = _ensure_private_directory(worker_root / "logs")
        diagnostics_dir = _ensure_private_directory(worker_root / "diagnostics")

        loaded_snapshot: ProfileSnapshot | None = None
        if snapshot is not None:
            loaded_snapshot = snapshot if isinstance(snapshot, ProfileSnapshot) else self.load_snapshot(snapshot)
            if not profile_dir.exists() or not any(profile_dir.iterdir()):
                self._copy_snapshot_to_profile(loaded_snapshot, profile_dir)
            else:
                metadata = _read_json(profile_dir / PROFILE_METADATA_FILENAME) or {}
                if metadata.get("snapshot_id") != loaded_snapshot.snapshot_id:
                    raise ProfileSnapshotError(
                        f"Worker profile already belongs to another snapshot: {profile_dir}"
                    )
        else:
            _ensure_private_directory(profile_dir)
            if not (profile_dir / PROFILE_METADATA_FILENAME).exists():
                _write_json_atomic(
                    profile_dir / PROFILE_METADATA_FILENAME,
                    {
                        "schema_version": PROFILE_METADATA_SCHEMA_VERSION,
                        "snapshot_id": None,
                        "created_at": _utc_now(),
                        "portable_snapshot": False,
                    },
                )

        context = WorkerProfileContext(
            run_id=run.run_id,
            worker_id=safe_worker_id,
            root=worker_root,
            profile_dir=profile_dir,
            download_dir=download_dir,
            log_dir=log_dir,
            diagnostics_dir=diagnostics_dir,
            snapshot_id=loaded_snapshot.snapshot_id if loaded_snapshot else None,
            managed=True,
        )
        _write_json_atomic(
            worker_root / "worker.json",
            {
                "schema_version": PROFILE_METADATA_SCHEMA_VERSION,
                "run_id": context.run_id,
                "worker_id": context.worker_id,
                "snapshot_id": context.snapshot_id,
                "created_at": _utc_now(),
                "paths": {
                    "profile": "profile",
                    "downloads": "downloads",
                    "logs": "logs",
                    "diagnostics": "diagnostics",
                },
            },
        )
        return context

    def bind_existing_profile(
        self,
        *,
        run_id: str,
        worker_id: str,
        profile_dir: Path,
        download_dir: Path,
    ) -> WorkerProfileContext:
        profile_dir = _ensure_private_directory(Path(profile_dir).expanduser().resolve())
        download_dir = _ensure_private_directory(Path(download_dir).expanduser().resolve())
        run = self.create_run(run_id)
        safe_worker_id = _safe_component(worker_id, fallback="worker-001")
        worker_root = _ensure_private_directory(run.workers_dir / safe_worker_id)
        log_dir = _ensure_private_directory(worker_root / "logs")
        diagnostics_dir = _ensure_private_directory(worker_root / "diagnostics")
        return WorkerProfileContext(
            run_id=run.run_id,
            worker_id=safe_worker_id,
            root=worker_root,
            profile_dir=profile_dir,
            download_dir=download_dir,
            log_dir=log_dir,
            diagnostics_dir=diagnostics_dir,
            snapshot_id=None,
            managed=False,
        )

    def acquire(self, context: WorkerProfileContext) -> ProfileLease:
        activity = self.inspect_activity(context.profile_dir)
        active_without_owner = tuple(
            marker for marker in activity.active_markers if marker != OWNER_FILENAME
        )
        if active_without_owner:
            raise ActiveProfileError(
                f"Browser profile is already active: {context.profile_dir} "
                f"(markers: {', '.join(active_without_owner)})"
            )
        if activity.stale_markers:
            self.clear_stale_locks(context.profile_dir)
        return ProfileLease(
            context.profile_dir,
            run_id=context.run_id,
            worker_id=context.worker_id,
        ).acquire()

    def cleanup_worker(self, context: WorkerProfileContext) -> None:
        activity = self.inspect_activity(context.profile_dir)
        if activity.active:
            raise ActiveProfileError(
                f"Cannot delete active worker profile: {context.profile_dir}"
            )
        if context.managed and context.root.exists():
            shutil.rmtree(context.root, ignore_errors=False)

    def cleanup_run(self, run_id: str, *, success: bool) -> bool:
        should_delete = self.retention_policy is RetentionPolicy.DELETE_ALL or (
            self.retention_policy is RetentionPolicy.DELETE_SUCCESS_KEEP_FAILURE and success
        )
        if not should_delete:
            return False
        safe_run_id = _safe_component(run_id, fallback="")
        if not safe_run_id:
            return False
        run_root = self.runtime_root / "runs" / safe_run_id
        workers_dir = run_root / "workers"
        if not run_root.exists():
            return False
        for worker_dir in workers_dir.iterdir() if workers_dir.exists() else ():
            profile_dir = worker_dir / "profile"
            if profile_dir.exists() and self.inspect_activity(profile_dir).active:
                raise ActiveProfileError(f"Cannot clean active run profile: {profile_dir}")
        shutil.rmtree(run_root, ignore_errors=False)
        return True
