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


VALID_MARKDOWN = """# Main Title

## Key Points

This generated note contains enough explanatory content to satisfy validation and represent a real completed artifact.
It includes a second substantial sentence so that it is not treated as a placeholder or a download-only response.
"""


class ManifestTests(unittest.TestCase):
    def make_file_job(self, root: Path, *, prompt_text: str = "prompt"):
        source = root / "source.pdf"
        source.write_bytes(b"source-v1")
        prompt = root / "prompt.md"
        prompt.write_text(prompt_text, encoding="utf-8")
        output = root / "output.md"
        return source, prompt, output, manifest.JobSpec.for_file(
            key="source.pdf::md",
            source=source,
            prompt=prompt,
            prompt_hash=manifest.hash_text(prompt_text),
            output=output,
            expected_extensions={".md"},
            mode="pdf-md",
            model="test-model",
        )

    def test_new_job_runs_and_completed_valid_job_skips(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _source, _prompt, output, job = self.make_file_job(root)
            store = manifest.ManifestStore(root / "manifest.json")
            self.assertEqual(store.inspect(job).action, manifest.DecisionAction.RUN)

            output.write_text(VALID_MARKDOWN, encoding="utf-8")
            store.mark_running(job, run_id="run-1", attempt=1)
            store.mark_completed(job, run_id="run-1")

            decision = store.inspect(job)
            self.assertEqual(decision.action, manifest.DecisionAction.SKIP)
            self.assertEqual(decision.reason, "completed output is valid")
            entry = store.get(job.key)
            self.assertEqual(entry["status"], "completed")
            self.assertEqual(entry["attempts"], 1)
            self.assertTrue(entry["output_hash"].startswith("sha256:"))

    def test_forced_reruns_invalidate_existing_completed_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _source, _prompt, output, job = self.make_file_job(root)
            output.write_text(VALID_MARKDOWN, encoding="utf-8")
            store = manifest.ManifestStore(root / "manifest.json")
            store.mark_completed(job, run_id="first")

            overwrite = store.inspect(job, overwrite=True)
            self.assertTrue(overwrite.should_run)
            self.assertTrue(overwrite.invalidate)
            self.assertEqual(overwrite.reason, "overwrite requested")

            no_resume = store.inspect(job, resume=False)
            self.assertTrue(no_resume.should_run)
            self.assertTrue(no_resume.invalidate)
            self.assertEqual(no_resume.reason, "resume disabled")

    def test_save_retries_a_transient_permission_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = manifest.ManifestStore(root / "manifest.json")
            original_replace = os.replace
            attempts = 0

            def replace_once_locked(source, destination):
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise PermissionError("temporary Windows file lock")
                return original_replace(source, destination)

            with mock.patch.object(manifest.os, "replace", side_effect=replace_once_locked):
                store.register_run("retry-test", mode="test", planned_jobs=1, parallel_runs=1)

            self.assertEqual(attempts, 2)
            self.assertEqual(manifest.ManifestStore(root / "manifest.json").get_run("retry-test")["mode"], "test")

    def test_source_content_change_invalidates_completed_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, prompt, output, job = self.make_file_job(root)
            output.write_text(VALID_MARKDOWN, encoding="utf-8")
            store = manifest.ManifestStore(root / "manifest.json")
            store.mark_completed(job, run_id="run-1")

            source.write_bytes(b"source-v2")
            changed = manifest.JobSpec.for_file(
                key=job.key,
                source=source,
                prompt=prompt,
                prompt_hash=job.prompt_hash,
                output=output,
                expected_extensions={".md"},
                mode="pdf-md",
                model="test-model",
            )
            decision = store.inspect(changed)
            self.assertTrue(decision.should_run)
            self.assertTrue(decision.invalidate)
            self.assertIn("source_hash", decision.reason)

    def test_prompt_content_change_invalidates_completed_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, prompt, output, job = self.make_file_job(root)
            output.write_text(VALID_MARKDOWN, encoding="utf-8")
            store = manifest.ManifestStore(root / "manifest.json")
            store.mark_completed(job, run_id="run-1")

            prompt.write_text("changed prompt", encoding="utf-8")
            changed = manifest.JobSpec.for_file(
                key=job.key,
                source=source,
                prompt=prompt,
                prompt_hash=manifest.hash_text("changed prompt"),
                output=output,
                expected_extensions={".md"},
                mode="pdf-md",
                model="test-model",
            )
            decision = store.inspect(changed)
            self.assertTrue(decision.should_run)
            self.assertIn("prompt_hash", decision.reason)

    def test_same_prompt_content_at_new_path_remains_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, _prompt, output, job = self.make_file_job(root)
            output.write_text(VALID_MARKDOWN, encoding="utf-8")
            store = manifest.ManifestStore(root / "manifest.json")
            store.mark_completed(job, run_id="run-1")

            moved_prompt = root / "prompts" / "same.md"
            moved_prompt.parent.mkdir()
            moved_prompt.write_text("prompt", encoding="utf-8")
            changed = manifest.JobSpec.for_file(
                key=job.key,
                source=source,
                prompt=moved_prompt,
                prompt_hash=manifest.hash_text("prompt"),
                output=output,
                expected_extensions={".md"},
                mode="pdf-md",
                model="test-model",
            )
            self.assertEqual(store.inspect(changed).action, manifest.DecisionAction.SKIP)

    def test_missing_invalid_or_changed_output_is_rerun(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _source, _prompt, output, job = self.make_file_job(root)
            output.write_text(VALID_MARKDOWN, encoding="utf-8")
            store = manifest.ManifestStore(root / "manifest.json")
            store.mark_completed(job, run_id="run-1")

            output.unlink()
            self.assertIn("missing", store.inspect(job).reason)
            output.write_text("# broken", encoding="utf-8")
            self.assertIn("failed validation", store.inspect(job).reason)
            output.write_text(VALID_MARKDOWN + "\nmanual edit", encoding="utf-8")
            self.assertIn("hash changed", store.inspect(job).reason)

    def test_running_and_failed_jobs_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _source, _prompt, _output, job = self.make_file_job(root)
            store = manifest.ManifestStore(root / "manifest.json")
            store.mark_running(job, run_id="crashed", attempt=1)
            self.assertIn("interrupted", store.inspect(job).reason)
            store.mark_failed(job, run_id="crashed", error=RuntimeError("boom"))
            self.assertIn("failed", store.inspect(job).reason)

    def test_untracked_existing_output_requires_rebuild_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _source, _prompt, output, job = self.make_file_job(root)
            output.write_text(VALID_MARKDOWN, encoding="utf-8")
            store = manifest.ManifestStore(root / "manifest.json")
            decision = store.inspect(job)
            self.assertEqual(decision.action, manifest.DecisionAction.RUN)
            self.assertIn("not tracked", decision.reason)

    def test_adopt_existing_valid_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _source, _prompt, output, job = self.make_file_job(root)
            output.write_text(VALID_MARKDOWN, encoding="utf-8")
            store = manifest.ManifestStore(root / "manifest.json")
            decision = store.inspect(job, adopt_existing=True)
            self.assertEqual(decision.action, manifest.DecisionAction.ADOPT)
            store.mark_completed(job, run_id="migration", adopted=True)
            self.assertTrue(store.get(job.key)["adopted"])

    def test_retry_failed_only_filters_new_and_completed_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _source, _prompt, output, job = self.make_file_job(root)
            store = manifest.ManifestStore(root / "manifest.json")
            self.assertEqual(
                store.inspect(job, retry_failed_only=True).action,
                manifest.DecisionAction.SKIP,
            )
            output.write_text(VALID_MARKDOWN, encoding="utf-8")
            store.mark_completed(job, run_id="run-1")
            self.assertEqual(
                store.inspect(job, retry_failed_only=True).action,
                manifest.DecisionAction.SKIP,
            )
            store.mark_failed(job, run_id="run-2", error="failed")
            self.assertEqual(
                store.inspect(job, retry_failed_only=True).action,
                manifest.DecisionAction.RUN,
            )

    def test_section_hash_is_independent_for_each_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "lecture.md"
            source.write_text("## A\nalpha\n## B\nbeta", encoding="utf-8")
            prompt = root / "prompt.md"
            prompt.write_text("prompt", encoding="utf-8")
            output_a = root / "a.md"
            output_b = root / "b.md"
            output_a.write_text(VALID_MARKDOWN, encoding="utf-8")
            output_b.write_text(VALID_MARKDOWN, encoding="utf-8")
            store = manifest.ManifestStore(root / "manifest.json")
            common = dict(
                source=source,
                prompt=prompt,
                prompt_hash=manifest.hash_text("prompt"),
                expected_extensions={".md"},
                mode="markdown-md",
            )
            job_a = manifest.JobSpec.for_text(key="lecture::1::md", source_text="## A\nalpha", output=output_a, **common)
            job_b = manifest.JobSpec.for_text(key="lecture::2::md", source_text="## B\nbeta", output=output_b, **common)
            store.mark_completed(job_a, run_id="run-1")
            store.mark_completed(job_b, run_id="run-1")

            changed_b = manifest.JobSpec.for_text(key=job_b.key, source_text="## B\nbeta changed", output=output_b, **common)
            self.assertEqual(store.inspect(job_a).action, manifest.DecisionAction.SKIP)
            self.assertEqual(store.inspect(changed_b).action, manifest.DecisionAction.RUN)

    def test_atomic_save_preserves_previous_manifest_on_replace_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _source, _prompt, _output, job = self.make_file_job(root)
            path = root / "manifest.json"
            store = manifest.ManifestStore(path)
            store.mark_pending(job, reason="initial")
            previous = path.read_text(encoding="utf-8")
            store.data["test_value"] = "new"

            with mock.patch.object(manifest.os, "replace", side_effect=OSError("replace failed")):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    store.save()

            self.assertEqual(path.read_text(encoding="utf-8"), previous)
            self.assertTrue(path.with_suffix(".json.bak").exists())
            self.assertFalse(list(root.glob(".manifest.json.*.tmp")))

    def test_manifest_json_contains_schema_and_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _source, _prompt, _output, job = self.make_file_job(root)
            path = root / "manifest.json"
            store = manifest.ManifestStore(path)
            store.mark_running(job, run_id="run-1", attempt=1)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 2)
            self.assertEqual(payload["items"][job.key]["status"], "running")
            self.assertEqual(payload["items"][job.key]["attempts"], 1)


if __name__ == "__main__":
    unittest.main()
