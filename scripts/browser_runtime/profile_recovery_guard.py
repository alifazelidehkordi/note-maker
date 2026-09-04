from __future__ import annotations

import hashlib
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from . import profile_manager as _profiles


_GUARD_ROOT = Path(tempfile.gettempdir()) / "note-maker-profile-guards"


def _guard_path(profile_dir: Path) -> Path:
    resolved = str(Path(profile_dir).expanduser().resolve()).encode("utf-8")
    digest = hashlib.sha256(resolved).hexdigest()
    return _GUARD_ROOT / f"{digest}.lock"


@contextmanager
def _profile_recovery_guard(profile_dir: Path) -> Iterator[None]:
    """Serialize owner-marker recovery without touching the browser profile.

    The guard is intentionally outside the profile directory. Snapshot/recovery
    code therefore never needs to add a helper file to a login profile merely
    to coordinate stale-marker recovery.
    """

    _GUARD_ROOT.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(_GUARD_ROOT, 0o700)
    except OSError:
        pass

    path = _guard_path(profile_dir)
    handle = path.open("a+b")
    try:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

        if os.name == "nt":
            import msvcrt

            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def install_profile_recovery_guard() -> None:
    """Serialize the two operations allowed to remove a proven-stale owner."""

    if getattr(_profiles, "_part1a_profile_recovery_guard_installed", False):
        return

    lease_cls = _profiles.ProfileLease
    manager_cls = _profiles.ProfileManager
    original_acquire = lease_cls.acquire
    original_clear_stale_locks = manager_cls.clear_stale_locks

    def guarded_acquire(self):
        with _profile_recovery_guard(self.profile_dir):
            return original_acquire(self)

    @classmethod
    def guarded_clear_stale_locks(cls, profile_dir):
        del cls
        with _profile_recovery_guard(Path(profile_dir)):
            # Re-inspection happens inside the original method while the guard
            # is held, so a new local owner cannot be unlinked based on a stale
            # observation made by another reclaimer.
            return original_clear_stale_locks(profile_dir)

    lease_cls.acquire = guarded_acquire
    manager_cls.clear_stale_locks = guarded_clear_stale_locks
    setattr(_profiles, "_part1a_profile_recovery_guard_installed", True)
