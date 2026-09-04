from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import manifest


class ManifestLockCleanupTests(unittest.TestCase):
    @staticmethod
    def _write_manifest(path: Path) -> None:
        path.write_text(
            json.dumps(
                {
                    "schema_version": manifest.SCHEMA_VERSION,
                    "created_at": manifest.utc_now(),
                    "updated_at": manifest.utc_now(),
                    "runs": {},
                    "items": {},
                }
            ),
            encoding="utf-8",
        )

    def test_short_write_lock_retries_transient_permission_error_on_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "manifest.json"
            lock_path = manifest_path.parent / ".manifest.json.write.lock"
            original_unlink = manifest.Path.unlink
            attempts = 0

            def unlink_once_locked(path, *args, **kwargs):
                nonlocal attempts
                if path == lock_path:
                    attempts += 1
                    if attempts == 1:
                        raise PermissionError("temporary Windows file lock")
                return original_unlink(path, *args, **kwargs)

            with (
                mock.patch.object(manifest.Path, "unlink", new=unlink_once_locked),
                mock.patch.object(manifest.time, "sleep"),
            ):
                with manifest._short_write_lock(manifest_path):
                    self.assertTrue(lock_path.exists())

            self.assertEqual(attempts, 2)
            self.assertFalse(lock_path.exists())

    def test_manifest_reader_retries_transient_permission_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "manifest.json"
            self._write_manifest(manifest_path)
            original_read_text = manifest.Path.read_text
            attempts = 0

            def read_once_locked(path, *args, **kwargs):
                nonlocal attempts
                if path == manifest_path:
                    attempts += 1
                    if attempts == 1:
                        raise PermissionError("temporary Windows file lock")
                return original_read_text(path, *args, **kwargs)

            with (
                mock.patch.object(manifest.Path, "read_text", new=read_once_locked),
                mock.patch.object(manifest.time, "sleep") as sleep,
            ):
                reader = manifest.ManifestStore.reader(manifest_path)

            self.assertIsNone(reader.get("missing"))
            self.assertEqual(attempts, 2)
            sleep.assert_called_once_with(0.02)

    def test_manifest_reader_fails_after_persistent_permission_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "manifest.json"
            self._write_manifest(manifest_path)
            original_read_text = manifest.Path.read_text
            attempts = 0

            def read_always_locked(path, *args, **kwargs):
                nonlocal attempts
                if path == manifest_path:
                    attempts += 1
                    raise PermissionError("persistent Windows file lock")
                return original_read_text(path, *args, **kwargs)

            with (
                mock.patch.object(manifest.Path, "read_text", new=read_always_locked),
                mock.patch.object(manifest.time, "sleep"),
            ):
                with self.assertRaisesRegex(manifest.ManifestError, "Could not read manifest"):
                    manifest.ManifestStore.reader(manifest_path)

            self.assertEqual(attempts, 5)


if __name__ == "__main__":
    unittest.main()
