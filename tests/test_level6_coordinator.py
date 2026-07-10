from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from manifest import JobSpec, ManifestCoordinator, hash_text
from parallel_runtime.coordinator import ParallelCoordinator
from parallel_runtime.models import ExecutionJob, RunConfig


class Level6CoordinatorTests(unittest.TestCase):
    def _jobs(self, root: Path, count: int):
        prompt = root / "prompt.md"
        prompt.write_text("notes", encoding="utf-8")
        store = ManifestCoordinator(root / "manifest.json")
        jobs: list[ExecutionJob] = []
        with store.batch_update():
            for index in range(count):
                source = root / f"source-{index}.pdf"
                source.write_bytes((str(index) * 100).encode())
                job = JobSpec.for_file(
                    key=f"job-{index}",
                    source=source,
                    prompt=prompt,
                    prompt_hash=hash_text("notes"),
                    output=root / "outputs" / f"note-{index}.md",
                    expected_extensions={".md"},
                    mode="level6-test",
                    title=f"Job {index}",
                )
                jobs.append(job)
                store.mark_pending(job, reason="test")
        return jobs, store

    def _config(self, root: Path, store: ManifestCoordinator, jobs, **overrides):
        run_id = str(overrides.pop("run_id", "level6-run"))
        store.register_run(run_id, mode="test", planned_jobs=len(jobs), parallel_runs=2)
        values = dict(
            run_id=run_id,
            manifest_path=store.path,
            claims_dir=root / "claims",
            worker_count=2,
            executor_path="parallel_runtime.testing:ScriptedExecutor",
            executor_config={
                "execution_log": str(root / "execution.jsonl"),
                "marker_root": str(root / "markers"),
                "default_duration": 0.02,
            },
            heartbeat_interval=0.05,
            worker_timeout=2.0,
            worker_ready_timeout=5.0,
            startup_stagger=0.0,
            shutdown_grace=1.0,
            poll_interval=0.005,
            global_rate_limit_cooldown=0.2,
            rate_limit_failures_before_abort=10,
            worker_max_jobs=20,
        )
        values.update(overrides)
        return RunConfig(**values)

    def test_global_rate_limit_pauses_new_assignments(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs, store = self._jobs(root, 5)
            config = self._config(root, store, jobs)
            payload = dict(config.executor_config)
            payload["behaviors"] = {
                jobs[0].key: {"cooldown_request": 0.25, "duration": 0.03},
                jobs[1].key: {"duration": 0.08},
            }
            config = RunConfig.from_payload({**config.to_payload(), "executor_config": payload})
            result = ParallelCoordinator(config, jobs, manifest=store).run()
            self.assertEqual(result.failed, {})
            self.assertEqual(result.rate_limit_events, 1)
            records = [json.loads(line) for line in (root / "execution.jsonl").read_text().splitlines()]
            records.sort(key=lambda row: row["started_at"])
            self.assertGreaterEqual(records[2]["started_at"] - records[0]["started_at"], 0.20)

    def test_transient_network_failures_do_not_stop_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs, store = self._jobs(root, 3)
            config = self._config(root, store, jobs, network_retries=3)
            payload = dict(config.executor_config)
            payload.update({"network_retries": 3, "retry_backoff_base": 0.01, "retry_backoff_cap": 0.02})
            payload["behaviors"] = {jobs[0].key: {"network_failures": 2}}
            config = RunConfig.from_payload({**config.to_payload(), "executor_config": payload})
            result = ParallelCoordinator(config, jobs, manifest=store).run()
            self.assertEqual(result.failed, {})
            self.assertEqual(set(result.succeeded), {job.key for job in jobs})

    def test_auth_startup_circuit_starts_only_one_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs, store = self._jobs(root, 2)
            config = self._config(
                root,
                store,
                jobs,
                worker_count=4,
                auth_failures_before_abort=1,
                executor_config={"startup_failure": "auth"},
            )
            result = ParallelCoordinator(config, jobs, manifest=store).run()
            self.assertEqual(result.auth_failures, 1)
            self.assertIn("authentication circuit", result.circuit_breaker_reason or "")
            self.assertEqual(sum(len(v) for v in result.assignments.values()), 0)
            self.assertEqual(len(result.assignments), 1)

    def test_worker_recycling_preserves_all_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs, store = self._jobs(root, 5)
            config = self._config(root, store, jobs, worker_count=1, worker_max_jobs=2)
            result = ParallelCoordinator(config, jobs, manifest=store).run()
            self.assertEqual(result.failed, {})
            self.assertEqual(len(result.succeeded), 5)
            self.assertGreaterEqual(result.worker_recycles, 2)
            workers = {
                json.loads(line)["worker"]
                for line in (root / "execution.jsonl").read_text().splitlines()
            }
            self.assertGreaterEqual(len(workers), 3)


if __name__ == "__main__":
    unittest.main()
