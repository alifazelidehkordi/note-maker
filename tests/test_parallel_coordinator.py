from __future__ import annotations

import json
import multiprocessing as mp
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from manifest import JobSpec, ManifestCoordinator, hash_text
from parallel_runtime.claims import ClaimStore
from parallel_runtime.coordinator import ParallelCoordinator
from parallel_runtime.event_bus import EventKind, WorkerEvent
from parallel_runtime.models import ExecutionJob, RunConfig


def _coordinator_child(
    root_text: str,
    run_id: str,
    job_payloads: list[dict[str, object]],
    *,
    worker_count: int,
    duration: float,
    result_name: str,
    crash_key: str | None = None,
) -> None:
    root = Path(root_text)
    jobs = [ExecutionJob.from_payload(payload) for payload in job_payloads]
    manifest_path = root / "manifest.json"
    store = ManifestCoordinator(manifest_path)
    store.register_run(
        run_id,
        mode="test-md",
        planned_jobs=len(jobs),
        parallel_runs=worker_count,
        browser_provider="fake",
    )
    behaviors: dict[str, dict[str, object]] = {}
    if crash_key is not None:
        behaviors[crash_key] = {"crash_count": 1}
    config = RunConfig(
        run_id=run_id,
        manifest_path=manifest_path,
        claims_dir=root / "claims",
        worker_count=worker_count,
        executor_path="parallel_runtime.testing:ScriptedExecutor",
        executor_config={
            "execution_log": str(root / "execution.jsonl"),
            "marker_root": str(root / "markers"),
            "default_duration": duration,
            "behaviors": behaviors,
        },
        heartbeat_interval=0.05,
        worker_timeout=2.0,
        startup_stagger=0.0,
        max_worker_restarts=2,
        shutdown_grace=1.0,
        claim_stale_after=1.0,
        poll_interval=0.01,
        external_claim_wait=10.0,
    )
    result = ParallelCoordinator(config, jobs, manifest=store).run()
    (root / result_name).write_text(
        json.dumps(result.__dict__, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


class ParallelCoordinatorTests(unittest.TestCase):
    def _make_jobs(self, root: Path, count: int) -> tuple[list[ExecutionJob], ManifestCoordinator]:
        prompt = root / "prompt.md"
        prompt.write_text("Create complete study notes", encoding="utf-8")
        manifest = ManifestCoordinator(root / "manifest.json")
        jobs: list[ExecutionJob] = []
        with manifest.batch_update():
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
                    estimated_weight=(index % 4) + 1,
                )
                jobs.append(job)
                manifest.mark_pending(job, reason="test fixture")
        return jobs, manifest

    def _run(self, root: Path, jobs: list[ExecutionJob], store: ManifestCoordinator, workers: int):
        run_id = f"run-{workers}"
        store.register_run(
            run_id,
            mode="test-md",
            planned_jobs=len(jobs),
            parallel_runs=workers,
            browser_provider="fake",
        )
        config = RunConfig(
            run_id=run_id,
            manifest_path=store.path,
            claims_dir=root / "claims",
            worker_count=workers,
            executor_path="parallel_runtime.testing:ScriptedExecutor",
            executor_config={
                "execution_log": str(root / "execution.jsonl"),
                "marker_root": str(root / "markers"),
                "default_duration": 0.02,
            },
            heartbeat_interval=0.05,
            worker_timeout=2.0,
            startup_stagger=0.0,
            max_worker_restarts=2,
            shutdown_grace=1.0,
            claim_stale_after=1.0,
            poll_interval=0.01,
            external_claim_wait=5.0,
        )
        return ParallelCoordinator(config, jobs, manifest=store).run(), run_id

    def test_one_to_four_workers_execute_every_job_exactly_once(self):
        for workers in (1, 2, 3, 4):
            with self.subTest(workers=workers), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                jobs, store = self._make_jobs(root, 9)
                result, run_id = self._run(root, jobs, store, workers)
                self.assertEqual(result.failed, {})
                self.assertEqual(set(result.succeeded), {job.key for job in jobs})
                records = [
                    json.loads(line)
                    for line in (root / "execution.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()
                ]
                self.assertEqual(len(records), len(jobs))
                self.assertEqual(len({record["job"] for record in records}), len(jobs))
                self.assertLessEqual(len({record["worker"] for record in records}), workers)
                self.assertTrue(all(store.get(job.key)["status"] == "completed" for job in jobs))
                run = store.get_run(run_id)
                self.assertEqual(len(run["workers"]), workers)


    def test_external_claim_timeout_does_not_overwrite_owner_manifest_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs, store = self._make_jobs(root, 1)
            job = jobs[0]
            store.register_run(
                "owner-run", mode="test", planned_jobs=1, parallel_runs=1
            )
            store.mark_running(
                job, run_id="owner-run", attempt=1, worker_id="owner-worker"
            )
            claim_store = ClaimStore(root / "claims", stale_after=5.0)
            owner_claim = claim_store.try_acquire(
                job.key,
                run_id="owner-run",
                worker_id="owner-worker",
                worker_pid=os.getpid(),
            )
            self.assertIsNotNone(owner_claim)

            store.register_run(
                "waiting-run", mode="test", planned_jobs=1, parallel_runs=1
            )
            config = RunConfig(
                run_id="waiting-run",
                manifest_path=store.path,
                claims_dir=root / "claims",
                worker_count=1,
                executor_path="parallel_runtime.testing:ScriptedExecutor",
                heartbeat_interval=0.05,
                worker_timeout=2.0,
                startup_stagger=0.0,
                poll_interval=0.01,
                external_claim_wait=0.05,
            )
            result = ParallelCoordinator(config, jobs, manifest=store).run()
            self.assertIn(job.key, result.failed)
            persisted = ManifestCoordinator(store.path).get(job.key)
            self.assertEqual(persisted["status"], "running")
            self.assertEqual(persisted["run_id"], "owner-run")
            claim_store.release(owner_claim)

    def test_dynamic_pull_queue_redistributes_uneven_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs, store = self._make_jobs(root, 10)
            run_id = "dynamic"
            store.register_run(run_id, mode="test", planned_jobs=len(jobs), parallel_runs=3)
            behaviors = {
                jobs[0].key: {"duration": 0.25},
                jobs[1].key: {"duration": 0.20},
                jobs[2].key: {"duration": 0.15},
            }
            config = RunConfig(
                run_id=run_id,
                manifest_path=store.path,
                claims_dir=root / "claims",
                worker_count=3,
                executor_path="parallel_runtime.testing:ScriptedExecutor",
                executor_config={
                    "execution_log": str(root / "execution.jsonl"),
                    "default_duration": 0.01,
                    "behaviors": behaviors,
                },
                heartbeat_interval=0.05,
                worker_timeout=2.0,
                startup_stagger=0.0,
                poll_interval=0.01,
            )
            result = ParallelCoordinator(config, jobs, manifest=store).run()
            assigned = [key for values in result.assignments.values() for key in values]
            self.assertCountEqual(assigned, [job.key for job in jobs])
            self.assertGreaterEqual(sum(bool(values) for values in result.assignments.values()), 2)
            self.assertGreater(max(map(len, result.assignments.values())), 1)


    def test_late_event_from_old_worker_generation_is_ignored(self):
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = RunConfig(
                run_id="generation-filter",
                manifest_path=root / "manifest.json",
                claims_dir=root / "claims",
                worker_count=1,
                executor_path="parallel_runtime.testing:ScriptedExecutor",
            )
            coordinator = ParallelCoordinator(config, [])
            slot = SimpleNamespace(
                worker_id="worker-001",
                generation=2,
                last_heartbeat=123.0,
            )
            coordinator.slots["worker-001"] = slot

            coordinator._handle_event(
                WorkerEvent(
                    EventKind.WORKER_FATAL,
                    "worker-001",
                    runtime_worker_id="worker-001",
                )
            )
            self.assertEqual(slot.last_heartbeat, 123.0)

            coordinator._handle_event(
                WorkerEvent(
                    EventKind.WORKER_FATAL,
                    "worker-001",
                    runtime_worker_id="worker-001-g002",
                )
            )
            self.assertEqual(slot.last_heartbeat, 0.0)
            coordinator._close_queue(coordinator.event_queue)

    def test_worker_crash_requeues_job_and_restarts_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs, store = self._make_jobs(root, 3)
            run_id = "crash-recovery"
            store.register_run(run_id, mode="test", planned_jobs=3, parallel_runs=1)
            config = RunConfig(
                run_id=run_id,
                manifest_path=store.path,
                claims_dir=root / "claims",
                worker_count=1,
                executor_path="parallel_runtime.testing:ScriptedExecutor",
                executor_config={
                    "execution_log": str(root / "execution.jsonl"),
                    "marker_root": str(root / "markers"),
                    "behaviors": {jobs[0].key: {"crash_count": 1}},
                },
                heartbeat_interval=0.05,
                worker_timeout=2.0,
                startup_stagger=0.0,
                max_worker_restarts=2,
                poll_interval=0.01,
            )
            result = ParallelCoordinator(config, jobs, manifest=store).run()
            self.assertEqual(result.failed, {})
            self.assertEqual(result.worker_restarts, 1)
            self.assertEqual(set(result.succeeded), {job.key for job in jobs})
            self.assertGreaterEqual(result.assignments["worker-001"].count(jobs[0].key), 2)
            self.assertEqual(store.get(jobs[0].key)["status"], "completed")
            worker = store.get_run(run_id)["workers"]["worker-001"]
            self.assertEqual(worker["generation"], 2)
            self.assertEqual(worker["runtime_worker_id"], "worker-001-g002")

    @unittest.skipUnless(os.name == "posix", "heartbeat freeze test requires SIGSTOP")
    def test_heartbeat_timeout_kills_and_replaces_frozen_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs, store = self._make_jobs(root, 1)
            run_id = "heartbeat-recovery"
            store.register_run(run_id, mode="test", planned_jobs=1, parallel_runs=1)
            config = RunConfig(
                run_id=run_id,
                manifest_path=store.path,
                claims_dir=root / "claims",
                worker_count=1,
                executor_path="parallel_runtime.testing:ScriptedExecutor",
                executor_config={
                    "marker_root": str(root / "markers"),
                    "behaviors": {jobs[0].key: {"freeze_count": 1}},
                },
                heartbeat_interval=0.05,
                worker_timeout=0.25,
                worker_ready_timeout=3.0,
                startup_stagger=0.0,
                max_worker_restarts=2,
                shutdown_grace=0.5,
                claim_stale_after=1.0,
                poll_interval=0.01,
            )
            result = ParallelCoordinator(config, jobs, manifest=store).run()
            self.assertEqual(result.failed, {})
            self.assertEqual(result.worker_restarts, 1)
            self.assertEqual(result.succeeded, [jobs[0].key])
            self.assertEqual(store.get(jobs[0].key)["status"], "completed")

    def test_two_independent_runs_on_shared_output_do_not_duplicate_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs, _store = self._make_jobs(root, 8)
            payloads = [job.to_payload() for job in jobs]
            ctx = mp.get_context("spawn")
            processes = [
                ctx.Process(
                    target=_coordinator_child,
                    kwargs={
                        "root_text": str(root),
                        "run_id": f"shared-{index}",
                        "job_payloads": payloads,
                        "worker_count": 2,
                        "duration": 0.08,
                        "result_name": f"result-{index}.json",
                    },
                )
                for index in (1, 2)
            ]
            for process in processes:
                process.start()
            for process in processes:
                process.join(timeout=20)
                self.assertEqual(process.exitcode, 0)

            records = [
                json.loads(line)
                for line in (root / "execution.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()
            ]
            self.assertEqual(len(records), len(jobs))
            self.assertEqual(len({record["job"] for record in records}), len(jobs))
            results = [
                json.loads((root / f"result-{index}.json").read_text(encoding="utf-8"))
                for index in (1, 2)
            ]
            observed = set()
            for result in results:
                observed.update(result["succeeded"])
                observed.update(result["externally_completed"])
            self.assertEqual(observed, {job.key for job in jobs})

    @unittest.skipUnless(os.name == "posix", "graceful SIGTERM test requires POSIX signals")
    def test_sigterm_triggers_graceful_interrupted_shutdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs, _store = self._make_jobs(root, 1)
            (root / "jobs.json").write_text(
                json.dumps([jobs[0].to_payload()]), encoding="utf-8"
            )
            runner = root / "run_graceful.py"
            runner_lines = [
                "import json, sys",
                "from pathlib import Path",
                f"sys.path.insert(0, {str(SCRIPTS)!r})",
                "from manifest import ManifestCoordinator",
                "from parallel_runtime.coordinator import ParallelCoordinator",
                "from parallel_runtime.models import ExecutionJob, RunConfig",
                "def main():",
                f"    root = Path({str(root)!r})",
                "    jobs = [ExecutionJob.from_payload(v) for v in json.loads((root / 'jobs.json').read_text())]",
                "    store = ManifestCoordinator(root / 'manifest.json')",
                "    store.register_run('graceful-run', mode='test', planned_jobs=1, parallel_runs=1)",
                "    config = RunConfig(run_id='graceful-run', manifest_path=store.path, claims_dir=root / 'claims', worker_count=1, executor_path='parallel_runtime.testing:ScriptedExecutor', executor_config={'default_duration': 5.0, 'behaviors': {jobs[0].key: {'ignore_sigterm': True}}}, heartbeat_interval=0.05, worker_timeout=2.0, startup_stagger=0.0, max_worker_restarts=1, shutdown_grace=1.0, claim_stale_after=1.0, poll_interval=0.01)",
                "    result = ParallelCoordinator(config, jobs, manifest=store).run()",
                "    (root / 'graceful-result.json').write_text(json.dumps(result.__dict__))",
                "if __name__ == '__main__':",
                "    main()",
            ]
            runner.write_text("\n".join(runner_lines) + "\n", encoding="utf-8")
            environment = dict(os.environ)
            environment["PYTHONPATH"] = str(SCRIPTS)
            process = subprocess.Popen(
                [sys.executable, str(runner)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
                env=environment,
            )
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                item = ManifestCoordinator(root / "manifest.json").get(jobs[0].key)
                if item and item.get("status") == "running":
                    break
                if process.poll() is not None:
                    break
                time.sleep(0.05)
            self.assertIsNone(process.poll(), "coordinator exited before SIGTERM")
            os.kill(process.pid, signal.SIGTERM)
            time.sleep(0.1)
            self.assertTrue(
                any((root / "claims").glob("*.claim.json")),
                "claim was released while the interrupted worker was still alive",
            )
            stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, f"stdout={stdout}; stderr={stderr}")
            result = json.loads((root / "graceful-result.json").read_text(encoding="utf-8"))
            self.assertTrue(result["interrupted"])
            item = ManifestCoordinator(root / "manifest.json").get(jobs[0].key)
            self.assertEqual(item["status"], "interrupted")
            self.assertFalse(any((root / "claims").glob("*.claim.json")))

    @unittest.skipUnless(os.name == "posix", "forced process termination test requires POSIX signals")
    def test_resume_after_forced_coordinator_and_worker_kill(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs, _store = self._make_jobs(root, 1)
            (root / "jobs.json").write_text(
                json.dumps([jobs[0].to_payload()]), encoding="utf-8"
            )
            runner = root / "run_killable.py"
            runner_lines = [
                "import json, sys",
                "from pathlib import Path",
                f"sys.path.insert(0, {str(SCRIPTS)!r})",
                "from manifest import ManifestCoordinator",
                "from parallel_runtime.coordinator import ParallelCoordinator",
                "from parallel_runtime.models import ExecutionJob, RunConfig",
                "def main():",
                f"    root = Path({str(root)!r})",
                "    jobs = [ExecutionJob.from_payload(v) for v in json.loads((root / 'jobs.json').read_text())]",
                "    store = ManifestCoordinator(root / 'manifest.json')",
                "    store.register_run('killed-run', mode='test', planned_jobs=1, parallel_runs=1)",
                "    config = RunConfig(run_id='killed-run', manifest_path=store.path, claims_dir=root / 'claims', worker_count=1, executor_path='parallel_runtime.testing:ScriptedExecutor', executor_config={'default_duration': 5.0}, heartbeat_interval=0.05, worker_timeout=2.0, startup_stagger=0.0, max_worker_restarts=1, claim_stale_after=1.0, poll_interval=0.01)",
                "    ParallelCoordinator(config, jobs, manifest=store).run()",
                "if __name__ == '__main__':",
                "    main()",
            ]
            runner.write_text("\n".join(runner_lines) + "\n", encoding="utf-8")
            environment = dict(os.environ)
            environment["PYTHONPATH"] = str(SCRIPTS)
            process = subprocess.Popen(
                [sys.executable, str(runner)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
                env=environment,
            )

            deadline = time.monotonic() + 10
            running_seen = False
            process_error = ""
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    _stdout, process_error = process.communicate(timeout=2)
                    break
                fresh = ManifestCoordinator(root / "manifest.json")
                item = fresh.get(jobs[0].key)
                if item and item.get("status") == "running":
                    running_seen = True
                    break
                time.sleep(0.05)
            self.assertTrue(
                running_seen,
                f"job did not enter running state before timeout; stderr={process_error}",
            )

            os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=5)
            time.sleep(1.2)

            resumed_store = ManifestCoordinator(root / "manifest.json")
            resumed_store.register_run(
                "resume-run", mode="test", planned_jobs=1, parallel_runs=1
            )
            config = RunConfig(
                run_id="resume-run",
                manifest_path=resumed_store.path,
                claims_dir=root / "claims",
                worker_count=1,
                executor_path="parallel_runtime.testing:ScriptedExecutor",
                executor_config={"default_duration": 0.01},
                heartbeat_interval=0.05,
                worker_timeout=2.0,
                startup_stagger=0.0,
                max_worker_restarts=1,
                claim_stale_after=1.0,
                poll_interval=0.01,
            )
            result = ParallelCoordinator(config, jobs, manifest=resumed_store).run()
            self.assertEqual(result.succeeded, [jobs[0].key])
            self.assertEqual(resumed_store.get(jobs[0].key)["status"], "completed")



if __name__ == "__main__":
    unittest.main()
