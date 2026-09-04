from __future__ import annotations

import json
import os
import re
import shutil
import socket
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from process_liveness import pid_is_alive as _pid_alive
from process_liveness import process_start_identity as _process_start_identity

from . import profile_manager as _legacy
from .errors import ActiveProfileError, ProfileLeaseError, ProfileSnapshotError

_BaseProfileLease = _legacy.ProfileLease
_BaseProfileManager = _legacy.ProfileManager


class OwnershipState(str, Enum):
    INACTIVE = "inactive"
    ACTIVE = "active"
    STALE = "stale"
    UNCERTAIN = "uncertain"


class CleanupStatus(str, Enum):
    DELETED = "deleted"
    RETAINED_BY_POLICY = "retained-by-policy"
    STILL_ACTIVE = "still-active"
    FAILED = "failed"


@dataclass(frozen=True)
class ProfileActivity:
    ownership_state: OwnershipState
    active_markers: tuple[str, ...] = ()
    stale_markers: tuple[str, ...] = ()
    uncertain_markers: tuple[str, ...] = ()

    @property
    def active(self) -> bool:
        """Compatibility flag: true whenever destructive action must be blocked."""
        return self.ownership_state in {OwnershipState.ACTIVE, OwnershipState.UNCERTAIN}

    @property
    def confirmed_active(self) -> bool:
        return self.ownership_state is OwnershipState.ACTIVE

    @property
    def uncertain(self) -> bool:
        return self.ownership_state is OwnershipState.UNCERTAIN

    @property
    def blocking_markers(self) -> tuple[str, ...]:
        return tuple(sorted((*self.active_markers, *self.uncertain_markers)))


@dataclass(frozen=True)
class CleanupOutcome:
    status: CleanupStatus
    scope: str
    path: Path
    reason: str
    ownership_state: OwnershipState | None = None

    @property
    def deleted(self) -> bool:
        return self.status is CleanupStatus.DELETED

    def __bool__(self) -> bool:
        # Preserve callers that historically treated cleanup_run() as a bool.
        return self.deleted

    def __str__(self) -> str:
        # Preserve scripts/profile_bootstrap.py's legacy deleted=true/false line.
        return str(self.deleted)

    def to_dict(self) -> dict[str, str | bool | None]:
        return {
            "status": self.status.value,
            "scope": self.scope,
            "path": str(self.path),
            "reason": self.reason,
            "ownership_state": (
                self.ownership_state.value if self.ownership_state is not None else None
            ),
            "deleted": self.deleted,
        }


def _local_hostnames() -> frozenset[str]:
    values = {socket.gethostname(), socket.getfqdn()}
    return frozenset(value.casefold().rstrip(".") for value in values if value)


def _is_local_hostname(value: object) -> bool:
    hostname = str(value or "").strip().casefold().rstrip(".")
    return bool(hostname) and hostname in _local_hostnames()


def _pid_from_payload(payload: Mapping[str, Any]) -> int:
    try:
        return int(payload.get("pid", 0))
    except (TypeError, ValueError):
        return 0


def _owner_state(payload: Mapping[str, Any] | None) -> OwnershipState:
    if payload is None or not _is_local_hostname(payload.get("hostname")):
        return OwnershipState.UNCERTAIN
    pid = _pid_from_payload(payload)
    if pid <= 0:
        return OwnershipState.UNCERTAIN
    if not _pid_alive(pid):
        return OwnershipState.STALE

    recorded_identity = str(payload.get("process_start_identity") or "").strip()
    current_identity = _process_start_identity(pid)
    if not recorded_identity or current_identity is None:
        return OwnershipState.UNCERTAIN
    if recorded_identity != current_identity:
        return OwnershipState.STALE
    return OwnershipState.ACTIVE


def _path_is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _activity_state(
    active: list[str], stale: list[str], uncertain: list[str]
) -> OwnershipState:
    if active:
        return OwnershipState.ACTIVE
    if uncertain:
        return OwnershipState.UNCERTAIN
    if stale:
        return OwnershipState.STALE
    return OwnershipState.INACTIVE


class SafeProfileLease(_BaseProfileLease):
    """Profile lease that records PID start identity to survive PID reuse safely."""

    @staticmethod
    def _owner_is_stale(payload: Mapping[str, Any], *, stale_after_seconds: int) -> bool:
        del stale_after_seconds
        return _owner_state(payload) is OwnershipState.STALE

    def acquire(self) -> "SafeProfileLease":
        _legacy._ensure_private_directory(self.profile_dir)
        payload = {
            "schema_version": _legacy.PROFILE_METADATA_SCHEMA_VERSION,
            "token": self.token,
            "pid": os.getpid(),
            "process_start_identity": _process_start_identity(os.getpid()),
            "hostname": socket.gethostname(),
            "run_id": self.run_id,
            "worker_id": self.worker_id,
            "acquired_at": _legacy._utc_now(),
            "acquired_epoch": time.time(),
        }
        data = json.dumps(payload, indent=2, sort_keys=True)
        for attempt in range(2):
            try:
                fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError as exc:
                existing = _legacy._read_json(self.path)
                if attempt == 0 and _owner_state(existing) is OwnershipState.STALE:
                    self.path.unlink(missing_ok=True)
                    continue
                owner = "unknown"
                state = OwnershipState.UNCERTAIN
                if existing:
                    state = _owner_state(existing)
                    owner = (
                        f"pid={existing.get('pid')} host={existing.get('hostname')} "
                        f"run={existing.get('run_id')} worker={existing.get('worker_id')} "
                        f"state={state.value}"
                    )
                raise ProfileLeaseError(
                    f"Profile is already owned or ownership is uncertain: "
                    f"{self.profile_dir} ({owner})"
                ) from exc
            else:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                self._acquired = True
                return self
        raise ProfileLeaseError(f"Could not acquire profile lease: {self.profile_dir}")


class SafeProfileManager(_BaseProfileManager):
    PROFILE_RELEASE_ATTEMPTS = 6
    PROFILE_RELEASE_DELAY_SECONDS = 0.1

    @staticmethod
    def inspect_activity(profile_dir: Path) -> ProfileActivity:
        profile_dir = Path(profile_dir).expanduser().resolve()
        active: list[str] = []
        stale: list[str] = []
        uncertain: list[str] = []

        owner = profile_dir / _legacy.OWNER_FILENAME
        if owner.exists():
            owner_state = _owner_state(_legacy._read_json(owner))
            if owner_state is OwnershipState.ACTIVE:
                active.append(_legacy.OWNER_FILENAME)
            elif owner_state is OwnershipState.STALE:
                stale.append(_legacy.OWNER_FILENAME)
            else:
                uncertain.append(_legacy.OWNER_FILENAME)

        for parent in (profile_dir, profile_dir / "Default"):
            for name in _legacy.CHROME_SINGLETON_NAMES:
                marker = parent / name
                if not marker.exists() and not marker.is_symlink():
                    continue
                display = str(marker.relative_to(profile_dir))
                if not marker.is_symlink():
                    uncertain.append(display)
                    continue
                try:
                    target = os.readlink(marker)
                except OSError:
                    uncertain.append(display)
                    continue
                match = re.search(r"(.+)-(\d+)$", target)
                if match is None or not _is_local_hostname(match.group(1)):
                    uncertain.append(display)
                    continue
                pid = int(match.group(2))
                if _pid_alive(pid):
                    # Chromium does not record process-start identity in its
                    # singleton symlink. A live matching PID is therefore not
                    # enough evidence to distinguish activity from PID reuse.
                    uncertain.append(display)
                else:
                    stale.append(display)

        state = _activity_state(active, stale, uncertain)
        return ProfileActivity(
            ownership_state=state,
            active_markers=tuple(sorted(active)),
            stale_markers=tuple(sorted(stale)),
            uncertain_markers=tuple(sorted(uncertain)),
        )

    @classmethod
    def assert_profile_inactive(cls, profile_dir: Path) -> None:
        activity = cls.inspect_activity(profile_dir)
        if not activity.active:
            return
        profile = Path(profile_dir).expanduser().resolve()
        if activity.uncertain:
            raise ActiveProfileError(
                f"Profile ownership is uncertain and destructive/copy operations are refused: "
                f"{profile} (markers: {', '.join(activity.blocking_markers)})"
            )
        raise ActiveProfileError(
            f"Profile appears active and cannot be copied or removed: {profile} "
            f"(markers: {', '.join(activity.active_markers)})"
        )

    @classmethod
    def clear_stale_locks(cls, profile_dir: Path) -> tuple[str, ...]:
        profile_dir = Path(profile_dir).expanduser().resolve()
        activity = cls.inspect_activity(profile_dir)
        if activity.active:
            raise ActiveProfileError(
                f"Refusing stale-lock recovery because profile ownership is "
                f"{activity.ownership_state.value}: {profile_dir}"
            )
        removed: list[str] = []
        for relative in activity.stale_markers:
            marker = profile_dir / relative
            marker.unlink(missing_ok=True)
            removed.append(relative)
        return tuple(sorted(removed))

    @classmethod
    def wait_for_profile_release(
        cls,
        profile_dir: Path,
        *,
        attempts: int | None = None,
        delay_seconds: float | None = None,
    ) -> ProfileActivity:
        max_attempts = max(1, attempts or cls.PROFILE_RELEASE_ATTEMPTS)
        delay = cls.PROFILE_RELEASE_DELAY_SECONDS if delay_seconds is None else max(0.0, delay_seconds)
        last = cls.inspect_activity(profile_dir)
        for attempt in range(max_attempts):
            if last.ownership_state is OwnershipState.STALE:
                cls.clear_stale_locks(profile_dir)
                last = cls.inspect_activity(profile_dir)
            if last.ownership_state is OwnershipState.INACTIVE:
                return last
            if attempt + 1 < max_attempts and delay > 0:
                time.sleep(delay)
            last = cls.inspect_activity(profile_dir)
        return last

    def create_snapshot(
        self,
        source_profile: Path,
        *,
        name: str | None = None,
        require_auth: bool = True,
    ):
        activity = self.wait_for_profile_release(source_profile)
        if activity.active:
            self.assert_profile_inactive(source_profile)
        if activity.ownership_state is OwnershipState.STALE:
            raise ProfileSnapshotError(
                f"Could not recover proven-stale profile locks safely: "
                f"{Path(source_profile).expanduser().resolve()}"
            )
        return super().create_snapshot(source_profile, name=name, require_auth=require_auth)

    def acquire(self, context):
        activity = self.inspect_activity(context.profile_dir)
        blocking_without_owner = tuple(
            marker
            for marker in activity.blocking_markers
            if marker != _legacy.OWNER_FILENAME
        )
        if blocking_without_owner:
            raise ActiveProfileError(
                f"Browser profile is active or ownership is uncertain: {context.profile_dir} "
                f"(markers: {', '.join(blocking_without_owner)})"
            )
        if activity.stale_markers:
            self.clear_stale_locks(context.profile_dir)
        return SafeProfileLease(
            context.profile_dir,
            run_id=context.run_id,
            worker_id=context.worker_id,
        ).acquire()

    def _should_delete(self, *, success: bool) -> bool:
        return self.retention_policy is _legacy.RetentionPolicy.DELETE_ALL or (
            self.retention_policy is _legacy.RetentionPolicy.DELETE_SUCCESS_KEEP_FAILURE and success
        )

    def _worker_root_is_owned(self, context) -> bool:
        run_id = _legacy._safe_component(context.run_id, fallback="")
        worker_id = _legacy._safe_component(context.worker_id, fallback="")
        expected = self.runtime_root / "runs" / run_id / "workers" / worker_id
        return bool(run_id and worker_id) and context.root.resolve() == expected.resolve()

    def cleanup_worker(self, context, *, success: bool | None = None) -> CleanupOutcome:
        path = context.root.resolve()
        if not self._worker_root_is_owned(context):
            return CleanupOutcome(
                CleanupStatus.FAILED,
                "worker",
                path,
                "Worker runtime path is outside the manager-owned run directory.",
            )
        if success is not None and not self._should_delete(success=success):
            return CleanupOutcome(
                CleanupStatus.RETAINED_BY_POLICY,
                "worker",
                path,
                f"Retention policy {self.retention_policy.value} keeps this worker runtime.",
            )
        if not path.exists():
            return CleanupOutcome(
                CleanupStatus.DELETED,
                "worker",
                path,
                "Worker runtime was already absent.",
            )
        if _path_is_within(self.snapshot_root, path):
            return CleanupOutcome(
                CleanupStatus.RETAINED_BY_POLICY,
                "worker",
                path,
                "Reusable snapshot storage overlaps this worker runtime; retained for safety.",
            )

        try:
            if context.managed and context.profile_dir.exists():
                activity = self.wait_for_profile_release(
                    context.profile_dir,
                    attempts=4,
                    delay_seconds=0.05,
                )
                if activity.confirmed_active:
                    return CleanupOutcome(
                        CleanupStatus.STILL_ACTIVE,
                        "worker",
                        path,
                        "Confirmed profile owner is still active.",
                        activity.ownership_state,
                    )
                if activity.uncertain:
                    return CleanupOutcome(
                        CleanupStatus.RETAINED_BY_POLICY,
                        "worker",
                        path,
                        "Profile ownership is uncertain; runtime retained for safety.",
                        activity.ownership_state,
                    )
                if activity.ownership_state is OwnershipState.STALE:
                    return CleanupOutcome(
                        CleanupStatus.FAILED,
                        "worker",
                        path,
                        "Proven-stale locks could not be recovered within the retry budget.",
                        activity.ownership_state,
                    )
            elif not context.managed and _path_is_within(context.profile_dir, path):
                return CleanupOutcome(
                    CleanupStatus.RETAINED_BY_POLICY,
                    "worker",
                    path,
                    "Unmanaged browser profile overlaps the worker runtime; retained for safety.",
                    OwnershipState.UNCERTAIN,
                )
            shutil.rmtree(path, ignore_errors=False)
        except Exception as exc:
            return CleanupOutcome(
                CleanupStatus.FAILED,
                "worker",
                path,
                f"Worker runtime cleanup failed: {type(exc).__name__}: {exc}",
            )
        return CleanupOutcome(
            CleanupStatus.DELETED,
            "worker",
            path,
            "Worker-owned runtime resources were deleted.",
        )

    def cleanup_run(self, run_id: str, *, success: bool) -> CleanupOutcome:
        safe_run_id = _legacy._safe_component(run_id, fallback="")
        run_root = (self.runtime_root / "runs" / safe_run_id).resolve()
        if not safe_run_id:
            return CleanupOutcome(
                CleanupStatus.RETAINED_BY_POLICY,
                "run",
                run_root,
                "Empty/unsafe run id was not eligible for cleanup.",
            )
        if not self._should_delete(success=success):
            return CleanupOutcome(
                CleanupStatus.RETAINED_BY_POLICY,
                "run",
                run_root,
                f"Retention policy {self.retention_policy.value} keeps this run runtime.",
            )
        if not run_root.exists():
            return CleanupOutcome(
                CleanupStatus.RETAINED_BY_POLICY,
                "run",
                run_root,
                "Run runtime does not exist; nothing was deleted.",
            )

        workers_dir = run_root / "workers"
        if self.snapshot_root.resolve() == run_root or _path_is_within(
            self.snapshot_root, workers_dir
        ):
            return CleanupOutcome(
                CleanupStatus.RETAINED_BY_POLICY,
                "run",
                run_root,
                "Reusable snapshot storage overlaps worker runtime; whole run retained for safety.",
            )

        try:
            if workers_dir.exists():
                for worker_dir in sorted(workers_dir.iterdir()):
                    if not worker_dir.is_dir():
                        continue
                    profile_dir = worker_dir / "profile"
                    if not profile_dir.exists():
                        continue
                    activity = self.wait_for_profile_release(
                        profile_dir,
                        attempts=4,
                        delay_seconds=0.05,
                    )
                    if activity.confirmed_active:
                        return CleanupOutcome(
                            CleanupStatus.STILL_ACTIVE,
                            "run",
                            run_root,
                            f"Worker profile is still active: {profile_dir}",
                            activity.ownership_state,
                        )
                    if activity.uncertain:
                        return CleanupOutcome(
                            CleanupStatus.RETAINED_BY_POLICY,
                            "run",
                            run_root,
                            f"Worker profile ownership is uncertain: {profile_dir}",
                            activity.ownership_state,
                        )
                    if activity.ownership_state is OwnershipState.STALE:
                        return CleanupOutcome(
                            CleanupStatus.FAILED,
                            "run",
                            run_root,
                            f"Could not recover proven-stale locks: {profile_dir}",
                            activity.ownership_state,
                        )

            if _path_is_within(self.snapshot_root, run_root):
                # Snapshot storage is intentionally independent of disposable
                # worker state even if a custom layout places it under run_root.
                if workers_dir.exists():
                    shutil.rmtree(workers_dir, ignore_errors=False)
                (run_root / "run.json").unlink(missing_ok=True)
                try:
                    run_root.rmdir()
                except OSError:
                    pass
                return CleanupOutcome(
                    CleanupStatus.DELETED,
                    "run",
                    run_root,
                    "Disposable run resources were deleted; reusable snapshots were preserved.",
                )

            shutil.rmtree(run_root, ignore_errors=False)
        except Exception as exc:
            return CleanupOutcome(
                CleanupStatus.FAILED,
                "run",
                run_root,
                f"Run runtime cleanup failed: {type(exc).__name__}: {exc}",
            )
        return CleanupOutcome(
            CleanupStatus.DELETED,
            "run",
            run_root,
            "Run-owned runtime resources were deleted after workers stopped.",
        )


def install_profile_safety() -> None:
    """Install Part 1A profile ownership/cleanup behavior in the existing service."""
    if getattr(_legacy, "_part1a_profile_safety_installed", False):
        return
    _legacy.OwnershipState = OwnershipState
    _legacy.CleanupStatus = CleanupStatus
    _legacy.CleanupOutcome = CleanupOutcome
    _legacy.ProfileActivity = ProfileActivity
    _legacy.ProfileLease = SafeProfileLease
    _legacy.ProfileManager = SafeProfileManager
    setattr(_legacy, "_part1a_profile_safety_installed", True)
