from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import manifest


class ManifestV2Tests(unittest.TestCase):
    def _job(self, root: Path, key: str = "job") -> manifest.JobSpec:
        source = root / f"{key}.pdf"
        source.write_bytes(key.encode("utf-8"))
        prompt = root / "prompt.md"
        prompt.write_text("prompt", encoding="utf-8")
        return manifest.JobSpec.for_file(
            key=key,
            source=source,
            prompt=prompt,
            prompt_hash=manifest.hash_text("prompt"),
            output=root / f"{key}.md",
            expected_extensions={".md"},
            mode="pdf-md",
            metadata={"kind": "test"},
        )

    def test_schema_one_is_migrated_to_schema_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "manifest.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "created_at": "2025-01-01T00:00:00+00:00",
                        "updated_at": "2025-01-01T00:00:00+00:00",
                        "items": {
                            "legacy": {
                                "status": "failed",
                                "source_hash": "sha256:x",
                                "prompt_hash": "sha256:y",
                                "output": str(root / "legacy.md"),
                                "expected_extensions": [".md"],
                                "mode": "pdf-md",
                                "model": None,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            store = manifest.ManifestStore(path)
            self.assertTrue(store.was_migrated)
            self.assertEqual(store.data["schema_version"], 2)
            self.assertIn("runs", store.data)
            self.assertEqual(store.get("legacy")["estimated_weight"], 1)
            store.save()
            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["schema_version"], 2)
            self.assertEqual(persisted["migration"]["from_schema_version"], 1)

    def test_stale_coordinator_instances_merge_distinct_dirty_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "manifest.json"
            first = manifest.ManifestStore(path)
            second = manifest.ManifestStore(path)
            first.mark_pending(self._job(root, "a"), reason="a")
            second.mark_pending(self._job(root, "b"), reason="b")
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(set(payload["items"]), {"a", "b"})

    def test_stale_planner_cannot_downgrade_a_valid_completed_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "manifest.json"
            job = self._job(root, "shared")
            first = manifest.ManifestStore(path)
            stale = manifest.ManifestStore(path)

            first.mark_pending(job, reason="planned")
            first.mark_running(job, run_id="run-a", attempt=1, worker_id="worker-001")
            job.output.write_text(
                "# Completed Notes\n\n## Topic\n\n" + ("Valid completed content. " * 20),
            )
            first.mark_completed(job, run_id="run-a", worker_id="worker-001")

            stale.mark_pending(job, reason="stale planning snapshot")
            persisted = manifest.ManifestStore(path).get(job.key)
            self.assertEqual(persisted["status"], "completed")
            self.assertEqual(persisted["run_id"], "run-a")

    def test_writer_handle_is_process_bound_and_reader_has_no_mutation_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = manifest.ManifestStore(root / "manifest.json")
            job = self._job(root)
            reader = store.as_reader()
            self.assertFalse(hasattr(reader, "mark_running"))
            with mock.patch.object(manifest.os, "getpid", return_value=os.getpid() + 1000):
                with self.assertRaises(manifest.ManifestWriteForbiddenError):
                    store.mark_pending(job, reason="worker attempted a direct write")

    def test_execution_metadata_and_interrupted_state_are_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = manifest.ManifestStore(root / "manifest.json")
            job = self._job(root)
            store.mark_running(job, run_id="run-1", attempt=1, worker_id="worker-007")
            running = store.get(job.key)
            self.assertEqual(running["worker_id"], "worker-007")
            self.assertIsNotNone(running["claimed_at"])
            self.assertIsNotNone(running["last_heartbeat_at"])
            self.assertEqual(running["estimated_weight"], job.estimated_weight)
            self.assertEqual(running["metadata"], {"kind": "test"})

            store.mark_interrupted(job, run_id="run-1", reason="coordinator restart")
            self.assertEqual(store.get(job.key)["status"], "interrupted")
            self.assertIn("interrupted", store.inspect(job).reason)


if __name__ == "__main__":
    unittest.main()
