from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import manifest
from parallel_runtime.job_sources import build_file_candidates, build_section_candidates
from parallel_runtime.models import PlanningOptions
from parallel_runtime.planner import plan_jobs


VALID_MARKDOWN = """# Generated Note

## Explanation

This is a sufficiently complete generated note used to verify browser-free planning and resume behavior in the Level 4 tests.
"""


@dataclass(frozen=True)
class Section:
    index: int
    title: str
    text: str

    @property
    def output_stem(self) -> str:
        return f"{self.index:02d}_{self.title.lower()}"


class JobPlannerTests(unittest.TestCase):
    def test_file_planning_is_browser_free_and_commits_in_one_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "inputs"
            output_dir = root / "outputs"
            input_dir.mkdir()
            output_dir.mkdir()
            small = input_dir / "small.pdf"
            large = input_dir / "large.pdf"
            small.write_bytes(b"x")
            large.write_bytes(b"x" * (300 * 1024))
            prompt = root / "prompt.md"
            prompt.write_text("Create notes", encoding="utf-8")
            store = manifest.ManifestStore(output_dir / "manifest.json")

            candidates = build_file_candidates(
                [small, large],
                input_dir=input_dir,
                output_dir=output_dir,
                prompt_path=prompt,
                prompt_hash=manifest.hash_text("Create notes"),
                output_ext="md",
                mode="pdf-md",
                model=None,
                key_builder=lambda path, base, ext: f"{path.relative_to(base)}::{ext}",
            )
            plan = plan_jobs(candidates, store.as_reader(), run_id="run-plan")

            self.assertTrue(plan.requires_worker)
            self.assertEqual(len(plan.runnable), 2)
            self.assertGreater(plan.runnable[1].job.estimated_weight, plan.runnable[0].job.estimated_weight)
            with mock.patch.object(store, "save", wraps=store.save) as save:
                with store.batch_update():
                    store.register_run(
                        "run-plan",
                        mode="pdf-md",
                        planned_jobs=len(plan.runnable),
                        estimated_total_weight=plan.estimated_total_weight,
                    )
                    store.apply_plan(plan)
            self.assertEqual(save.call_count, 1)
            payload = json.loads(store.path.read_text(encoding="utf-8"))
            self.assertEqual(payload["runs"]["run-plan"]["planned_jobs"], 2)
            self.assertEqual(len(payload["items"]), 2)

    def test_completed_plan_has_no_runnable_worker_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "inputs"
            output_dir = root / "outputs"
            input_dir.mkdir()
            output_dir.mkdir()
            source = input_dir / "one.pdf"
            source.write_bytes(b"source")
            prompt = root / "prompt.md"
            prompt.write_text("Create notes", encoding="utf-8")
            candidates = build_file_candidates(
                [source],
                input_dir=input_dir,
                output_dir=output_dir,
                prompt_path=prompt,
                prompt_hash=manifest.hash_text("Create notes"),
                output_ext="md",
                mode="pdf-md",
                model=None,
                key_builder=lambda path, base, ext: f"{path.name}::{ext}",
            )
            store = manifest.ManifestStore(output_dir / "manifest.json")
            candidates[0].job.output.write_text(VALID_MARKDOWN, encoding="utf-8")
            store.mark_completed(candidates[0].job, run_id="first")

            plan = plan_jobs(candidates, store.as_reader(), run_id="second")
            self.assertFalse(plan.requires_worker)
            self.assertEqual(plan.initial_successes, 1)
            self.assertEqual(plan.skipped[candidates[0].label], "completed output is valid")

    def test_overwrite_invalidates_completed_job_before_coordinator_assignment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "inputs"
            output_dir = root / "outputs"
            input_dir.mkdir()
            output_dir.mkdir()
            source = input_dir / "one.pdf"
            source.write_bytes(b"source")
            prompt = root / "prompt.md"
            prompt.write_text("Create notes", encoding="utf-8")
            candidates = build_file_candidates(
                [source],
                input_dir=input_dir,
                output_dir=output_dir,
                prompt_path=prompt,
                prompt_hash=manifest.hash_text("Create notes"),
                output_ext="md",
                mode="pdf-md",
                model=None,
                key_builder=lambda path, base, ext: f"{path.name}::{ext}",
            )
            store = manifest.ManifestStore(output_dir / "manifest.json")
            candidates[0].job.output.write_text(VALID_MARKDOWN, encoding="utf-8")
            store.mark_completed(candidates[0].job, run_id="first")

            plan = plan_jobs(
                candidates,
                store.as_reader(),
                run_id="overwrite",
                options=PlanningOptions(overwrite=True),
            )
            self.assertEqual(len(plan.runnable), 1)
            self.assertEqual(plan.runnable[0].reason, "overwrite requested")
            store.apply_plan(plan)
            self.assertEqual(store.get(candidates[0].job.key)["status"], "invalidated")

    def test_section_planner_materializes_stable_input_before_worker_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markdown = root / "lecture.md"
            markdown.write_text("## Alpha\nBody", encoding="utf-8")
            prompt = root / "prompt.md"
            prompt.write_text("Prompt", encoding="utf-8")
            sections = [Section(1, "Alpha", "## Alpha\nBody")]

            candidates = build_section_candidates(
                sections,
                markdown_file=markdown,
                section_dir=root / "sections",
                output_dir=root / "outputs",
                prompt_path=prompt,
                prompt_hash=manifest.hash_text("Prompt"),
                output_ext="md",
                mode="markdown-md",
                model=None,
                key_builder=lambda source, section, ext: f"{source.name}::{section.index}::{ext}",
                section_file_writer=lambda section, directory: self._write_section(section, directory),
            )
            section, section_file = candidates[0].payload
            self.assertEqual(section.title, "Alpha")
            self.assertTrue(section_file.exists())
            self.assertEqual(candidates[0].job.metadata["section_file"], str(section_file.resolve()))
            self.assertGreaterEqual(candidates[0].job.estimated_weight, 1)

    @staticmethod
    def _write_section(section: Section, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{section.output_stem}.md"
        path.write_text(section.text, encoding="utf-8")
        return path


if __name__ == "__main__":
    unittest.main()
