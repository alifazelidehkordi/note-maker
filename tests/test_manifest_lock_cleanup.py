from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import manifest


class ManifestLockCleanupTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
