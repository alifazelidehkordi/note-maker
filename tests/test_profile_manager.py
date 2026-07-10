from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from browser_runtime import (  # noqa: E402
    ActiveProfileError,
    ProfileLease,
    ProfileLeaseError,
    ProfileManager,
    ProfileSnapshotError,
    RetentionPolicy,
)


def create_cookie_database(profile: Path, *, valid: bool = True, modern: bool = True) -> Path:
    database = (
        profile / "Default" / "Network" / "Cookies"
        if modern
        else profile / "Default" / "Cookies"
    )
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "CREATE TABLE cookies (name TEXT, host_key TEXT, expires_utc INTEGER)"
        )
        expiry = 0 if valid else 1
        connection.execute(
            "INSERT INTO cookies VALUES (?, ?, ?)",
            ("__Secure-next-auth.session-token.0", ".chatgpt.com", expiry),
        )
        connection.commit()
    finally:
        connection.close()
    return database


def create_reference_profile(root: Path) -> Path:
    profile = root / "reference"
    create_cookie_database(profile)
    default = profile / "Default"
    (default / "Local Storage" / "leveldb").mkdir(parents=True)
    (default / "Local Storage" / "leveldb" / "000001.ldb").write_bytes(b"session")
    (default / "Session Storage").mkdir()
    (default / "Session Storage" / "CURRENT").write_text("MANIFEST-000001\n")
    (default / "IndexedDB" / "https_chatgpt.com_0.indexeddb.leveldb").mkdir(parents=True)
    (default / "IndexedDB" / "https_chatgpt.com_0.indexeddb.leveldb" / "CURRENT").write_text(
        "MANIFEST-000001\n"
    )
    (default / "Preferences").write_text(
        json.dumps(
            {
                "download": {"default_directory": "/home/private/downloads"},
                "profile": {"name": "Default"},
            }
        ),
        encoding="utf-8",
    )
    (profile / "Local State").write_text(
        json.dumps({"selectfile": {"last_directory": "C:\\private\\files"}}),
        encoding="utf-8",
    )
    return profile


class ProfileManagerTests(unittest.TestCase):
    def build_manager(self, root: Path, *, retention=RetentionPolicy.KEEP_ALL) -> ProfileManager:
        return ProfileManager(
            runtime_root=root / "runtime",
            snapshot_root=root / "snapshots",
            retention_policy=retention,
        )

    def test_auth_detection_supports_modern_cookie_database_and_expiry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            valid = root / "valid"
            expired = root / "expired"
            create_cookie_database(valid, valid=True, modern=True)
            create_cookie_database(expired, valid=False, modern=False)

            valid_evidence = ProfileManager.inspect_auth_session(valid)
            expired_evidence = ProfileManager.inspect_auth_session(expired)

            self.assertTrue(valid_evidence.authenticated)
            self.assertIn("__Secure-next-auth.session-token.0", valid_evidence.markers)
            self.assertFalse(expired_evidence.authenticated)

    def test_snapshot_is_selective_portable_and_sanitizes_absolute_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager = self.build_manager(root)
            reference = create_reference_profile(root)
            (reference / "Default" / "Cache").mkdir()
            (reference / "Default" / "Cache" / "secret.bin").write_bytes(b"cache")

            snapshot = manager.create_snapshot(reference, name="golden")
            metadata_text = snapshot.metadata_path.read_text(encoding="utf-8")
            metadata = json.loads(metadata_text)

            self.assertTrue(snapshot.portable)
            self.assertNotIn(str(reference.resolve()), metadata_text)
            self.assertFalse((snapshot.path / "Default" / "Cache").exists())
            self.assertTrue((snapshot.path / "Default" / "Network" / "Cookies").exists())
            preferences = json.loads(
                (snapshot.path / "Default" / "Preferences").read_text(encoding="utf-8")
            )
            local_state = json.loads((snapshot.path / "Local State").read_text(encoding="utf-8"))
            self.assertEqual(preferences["download"]["default_directory"], "")
            self.assertEqual(local_state["selectfile"]["last_directory"], "")
            self.assertTrue(metadata["sanitized_path_keys"])

    def test_secure_preferences_is_copied_without_rewriting_protected_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager = self.build_manager(root)
            reference = create_reference_profile(root)
            secure_preferences = reference / "Default" / "Secure Preferences"
            original = json.dumps(
                {
                    "protected": {"integrity": "signed-value"},
                    "download": {"default_directory": "/private/protected/path"},
                },
                separators=(",", ":"),
            )
            secure_preferences.write_text(original, encoding="utf-8")

            snapshot = manager.create_snapshot(reference, name="golden")

            copied = snapshot.path / "Default" / "Secure Preferences"
            self.assertEqual(copied.read_text(encoding="utf-8"), original)
            self.assertFalse(
                any(item.startswith("Default/Secure Preferences::") for item in snapshot.sanitized_path_keys)
            )

    def test_snapshot_rejects_active_reference_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager = self.build_manager(root)
            reference = create_reference_profile(root)
            lease = ProfileLease(reference, run_id="login", worker_id="reference").acquire()
            try:
                with self.assertRaises(ActiveProfileError):
                    manager.create_snapshot(reference)
            finally:
                lease.release()

    def test_profile_lease_is_exclusive_and_reclaims_dead_local_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "profile"
            first = ProfileLease(profile, run_id="run-a", worker_id="worker-1").acquire()
            try:
                with self.assertRaises(ProfileLeaseError):
                    ProfileLease(profile, run_id="run-b", worker_id="worker-2").acquire()
            finally:
                first.release()

            owner = profile / ".note-maker-profile-owner.json"
            owner.write_text(
                json.dumps(
                    {
                        "pid": 999_999_999,
                        "hostname": socket.gethostname(),
                        "acquired_epoch": 0,
                    }
                ),
                encoding="utf-8",
            )
            reclaimed = ProfileLease(profile, run_id="run-c", worker_id="worker-3").acquire()
            self.assertTrue(owner.exists())
            reclaimed.release()
            self.assertFalse(owner.exists())

    def test_two_worker_profiles_are_independent_and_cleanup_is_scoped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager = self.build_manager(root)
            snapshot = manager.create_snapshot(create_reference_profile(root), name="golden")
            first = manager.prepare_worker(run_id="run-1", worker_id="worker-001", snapshot=snapshot)
            second = manager.prepare_worker(run_id="run-1", worker_id="worker-002", snapshot=snapshot)

            self.assertNotEqual(first.profile_dir, second.profile_dir)
            self.assertNotEqual(first.download_dir, second.download_dir)
            self.assertFalse(any((first.profile_dir / name).exists() for name in ("SingletonLock", "SingletonSocket", "SingletonCookie")))
            self.assertFalse(any((second.profile_dir / name).exists() for name in ("SingletonLock", "SingletonSocket", "SingletonCookie")))

            first_cookie = first.profile_dir / "Default" / "Network" / "Cookies"
            second_cookie = second.profile_dir / "Default" / "Network" / "Cookies"
            first_cookie.write_bytes(b"worker-one")
            self.assertNotEqual(first_cookie.read_bytes(), second_cookie.read_bytes())

            manager.cleanup_worker(first)
            self.assertFalse(first.root.exists())
            self.assertTrue(second.root.exists())
            self.assertTrue(second_cookie.exists())

    def test_retention_policy_keeps_failure_and_deletes_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager = self.build_manager(
                root,
                retention=RetentionPolicy.DELETE_SUCCESS_KEEP_FAILURE,
            )
            snapshot = manager.create_snapshot(create_reference_profile(root), name="golden")
            failed = manager.prepare_worker(run_id="failed-run", worker_id="worker-1", snapshot=snapshot)
            successful = manager.prepare_worker(run_id="successful-run", worker_id="worker-1", snapshot=snapshot)

            self.assertFalse(manager.cleanup_run("failed-run", success=False))
            self.assertTrue(failed.root.exists())
            self.assertTrue(manager.cleanup_run("successful-run", success=True))
            self.assertFalse(successful.root.parent.parent.exists())

    def test_cleanup_of_unknown_run_is_a_noop_and_does_not_create_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager = self.build_manager(
                root,
                retention=RetentionPolicy.DELETE_ALL,
            )
            unknown = manager.runtime_root / "runs" / "unknown-run"

            self.assertFalse(manager.cleanup_run("unknown-run", success=True))
            self.assertFalse(unknown.exists())


    def test_snapshot_integrity_detects_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager = self.build_manager(root)
            snapshot = manager.create_snapshot(create_reference_profile(root), name="golden")
            cookie = snapshot.path / "Default" / "Network" / "Cookies"
            cookie.write_bytes(cookie.read_bytes() + b"tampered")
            with self.assertRaisesRegex(ProfileSnapshotError, "size mismatch|checksum mismatch"):
                manager.load_snapshot(snapshot.path)

    def test_nested_symlinks_are_not_copied_into_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager = self.build_manager(root)
            reference = create_reference_profile(root)
            outside = root / "outside.txt"
            outside.write_text("private", encoding="utf-8")
            link = reference / "Default" / "Local Storage" / "leveldb" / "outside-link"
            try:
                link.symlink_to(outside)
            except OSError:
                self.skipTest("Symlinks are unavailable in this environment")
            snapshot = manager.create_snapshot(reference, name="golden")
            self.assertFalse(
                (snapshot.path / "Default" / "Local Storage" / "leveldb" / "outside-link").exists()
            )

    def test_live_chromium_singleton_marker_blocks_profile_use(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "profile"
            profile.mkdir()
            marker = profile / "SingletonLock"
            try:
                marker.symlink_to(f"{socket.gethostname()}-{os.getpid()}")
            except OSError:
                self.skipTest("Symlinks are unavailable in this environment")
            manager = self.build_manager(Path(tmp) / "manager")
            context = manager.bind_existing_profile(
                run_id="run",
                worker_id="worker",
                profile_dir=profile,
                download_dir=Path(tmp) / "downloads",
            )
            with self.assertRaises(ActiveProfileError):
                manager.acquire(context)

    def test_unauthenticated_snapshot_is_fail_closed_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager = self.build_manager(root)
            profile = root / "anonymous"
            (profile / "Default" / "Local Storage").mkdir(parents=True)
            with self.assertRaises(ProfileSnapshotError):
                manager.create_snapshot(profile)


if __name__ == "__main__":
    unittest.main()
