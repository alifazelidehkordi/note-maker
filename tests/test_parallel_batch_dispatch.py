from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import batch_markdown
import batch_pdf
from parallel_runtime.coordinator import CoordinatorResult


class _InlineSuccessfulCoordinator:
    seen_configs = []

    def __init__(self, config, jobs, *, manifest):
        self.config = config
        self.jobs = list(jobs)
        self.manifest = manifest
        type(self).seen_configs.append(config)

    def run(self):
        result = CoordinatorResult(assignments={"worker-001": [], "worker-002": []})
        for index, job in enumerate(self.jobs):
            worker = f"worker-{(index % 2) + 1:03d}"
            job.output.parent.mkdir(parents=True, exist_ok=True)
            job.output.write_text(
                f"# Generated Notes\n\n## {job.title or job.key}\n\n"
                + ("Complete generated study content. " * 16),
                encoding="utf-8",
            )
            self.manifest.mark_running(
                job,
                run_id=self.config.run_id,
                attempt=1,
                worker_id=worker,
            )
            self.manifest.mark_completed(
                job,
                run_id=self.config.run_id,
                worker_id=worker,
            )
            result.succeeded.append(job.key)
            result.assignments[worker].append(job.key)
        return result


class ParallelBatchDispatchTests(unittest.TestCase):
    def setUp(self):
        _InlineSuccessfulCoordinator.seen_configs.clear()

    def test_pdf_batch_uses_coordinator_for_parallel_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs = root / "inputs"
            outputs = root / "outputs"
            logs = root / "logs"
            inputs.mkdir()
            (inputs / "a.pdf").write_bytes(b"a")
            (inputs / "b.pdf").write_bytes(b"b")
            prompt = root / "prompt.md"
            prompt.write_text("Create notes", encoding="utf-8")
            with mock.patch.object(batch_pdf, "ParallelCoordinator", _InlineSuccessfulCoordinator), mock.patch.object(
                batch_pdf.common, "LOGS_DIR", logs
            ), mock.patch.object(batch_pdf.core, "LOG_FILE", root / "run.log"), mock.patch.object(
                batch_pdf.common,
                "get_browser_provider",
                side_effect=AssertionError("parent process must not create a browser provider"),
            ):
                code = batch_pdf.run_batch(
                    inputs,
                    outputs,
                    prompt,
                    output_ext="md",
                    parallel_runs=2,
                    worker_startup_stagger=0,
                )
            self.assertEqual(code, 0)
            self.assertEqual(_InlineSuccessfulCoordinator.seen_configs[0].worker_count, 2)
            summary = json.loads((logs / "last_batch_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["parallel_runs"], 2)
            self.assertEqual(len(summary["worker_assignments"]), 2)

    def test_markdown_batch_uses_markdown_executor_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markdown = root / "lecture.md"
            markdown.write_text(
                "# Lecture\n\n## First\n\nFirst section text.\n\n## Second\n\nSecond section text.\n",
                encoding="utf-8",
            )
            outputs = root / "outputs"
            logs = root / "logs"
            prompt = root / "prompt.md"
            prompt.write_text("Create notes", encoding="utf-8")
            with mock.patch.object(batch_markdown, "ParallelCoordinator", _InlineSuccessfulCoordinator), mock.patch.object(
                batch_markdown.common, "LOGS_DIR", logs
            ), mock.patch.object(batch_markdown.core, "LOG_FILE", root / "run.log"), mock.patch.object(
                batch_markdown.common,
                "get_browser_provider",
                side_effect=AssertionError("parent process must not create a browser provider"),
            ):
                code = batch_markdown.run_batch(
                    markdown,
                    outputs,
                    prompt,
                    output_ext="md",
                    parallel_runs=2,
                    worker_startup_stagger=0,
                )
            self.assertEqual(code, 0)
            config = _InlineSuccessfulCoordinator.seen_configs[0]
            self.assertEqual(config.worker_count, 2)
            self.assertEqual(
                config.executor_path,
                "parallel_runtime.executors:MarkdownJobExecutor",
            )


if __name__ == "__main__":
    unittest.main()
