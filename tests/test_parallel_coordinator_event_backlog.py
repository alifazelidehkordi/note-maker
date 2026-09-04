from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from manifest import JobSpec, ManifestCoordinator, hash_text
from parallel_runtime.coordinator import ParallelCoordinator
from parallel_runtime.models import ExecutionJob, RunConfig


class SlowFirstCompletionManifest(ManifestCoordinator):
    """Simulate a coordinator-side persistence stall while workers stay healthy."""

    def __init__(self, path: Path, *, delay: float) -> None:
        super().__init__(path)
        self.delay = delay
        self.delayed = False

    def mark_completed(self, job: ExecutionJob, **kwargs: object) -> None:
        if not self.delayed:
            self.delayed = True
            time.sleep(self.delay)
        super().mark_completed(job, **kwargs)


class ParallelCoordinatorEventBacklogTests(unittest.TestCase):
    def _make_jobs(
        self, root: Path, store: ManifestCoordinator, count: int
    ) -> list[ExecutionJob]:
        prompt = root / "prompt.md"
        prompt.write_text("Create complete study notes", encoding="utf-8")
        jobs: list[ExecutionJob] = []
        with store.batch_update():
            for index in range(count):
                source = root / f"source-{index}.pdf"
                source.write_bytes((f"source-{index}" * 20).encode("utf-8"))
                job = JobSpec.for_file(
                    key=f"job-{index}",
                    source=source,
                    prompt=prompt,
                    prompt_hash=hash_text("Create complete study notes"),
                    output=root / "outputs" / f"note-{index}.md",
                    expected_extensions={".md"},
                    mode="test-md",
                    title=f"Topic {index}",
                    estimated_weight=1,
                )
                jobs.append(job)
                store.mark_pending(job, reason="test fixture")
        return jobs

    def test_coordinator_stall_does_not_reexecute_healthy_worker_jobs(self) -> None:
        for repetition in range(3):
            with self.subTest(repetition=repetition), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                store = SlowFirstCompletionManifest(root / "manifest.json", delay=0.30)
                jobs = self._make_jobs(root, store, 6)
                run_id = f"event-backlog-{repetition}"
                store.register_run(
                    run_id,
                    mode="test-md",
                    planned_jobs=len(jobs),
                    parallel_runs=2,
                    browser_provider="fake",
                )
                config = RunConfig(
                    run_id=run_id,
                    manifest_path=store.path,
                    claims_dir=root / "claims",
                    worker_count=2,
                    executor_path="parallel_runtime.testing:ScriptedExecutor",
                    executor_config={
                        "execution_log": str(root / "execution.jsonl"),
                        "default_duration": 0.02,
                    },
                    heartbeat_interval=0.02,
                    worker_timeout=0.12,
                    worker_ready_timeout=3.0,
                    startup_stagger=0.0,
                    max_worker_restarts=2,
                    shutdown_grace=1.0,
                    claim_stale_after=1.0,
                    poll_interval=0.005,
                    external_claim_wait=2.0,
                )

                result = ParallelCoordinator(config, jobs, manifest=store).run()
                records = [
                    json.loads(line)
                    for line in (root / "execution.jsonl")
                    .read_text(encoding="utf-8")
                    .splitlines()
                ]

                self.assertEqual(result.failed, {})
                self.assertEqual(set(result.succeeded), {job.key for job in jobs})
                self.assertEqual(result.worker_restarts, 0)
                self.assertEqual(len(records), len(jobs))
                self.assertEqual(len({record["job"] for record in records}), len(jobs))


if __name__ == "__main__":
    unittest.main()
