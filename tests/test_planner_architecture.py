from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PlannerArchitectureTests(unittest.TestCase):
    def _tree(self, relative: str) -> ast.AST:
        path = ROOT / relative
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def test_batch_modules_delegate_resume_planning_to_shared_planner(self):
        for relative in ("scripts/batch_pdf.py", "scripts/batch_markdown.py"):
            tree = self._tree(relative)
            calls = [
                node.func.attr
                for node in ast.walk(tree)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            ]
            names = [
                node.func.id
                for node in ast.walk(tree)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            ]
            self.assertIn("plan_jobs", names, relative)
            self.assertNotIn("inspect", calls, relative)
            self.assertNotIn("for_file", calls, relative)
            self.assertNotIn("for_text", calls, relative)

    def test_planner_has_no_browser_runtime_dependency(self):
        for relative in (
            "scripts/parallel_runtime/models.py",
            "scripts/parallel_runtime/planner.py",
            "scripts/parallel_runtime/job_sources.py",
        ):
            tree = self._tree(relative)
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.append(node.module)
            self.assertFalse(
                any(name.startswith("browser_runtime") for name in imports),
                f"{relative} must remain browser-free: {imports}",
            )

    def test_worker_module_has_no_manifest_write_dependency(self):
        tree = self._tree("scripts/parallel_runtime/worker.py")
        imports = []
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
            elif isinstance(node, ast.Name):
                names.add(node.id)
        self.assertNotIn("manifest", imports)
        self.assertNotIn("ManifestStore", names)
        self.assertNotIn("ManifestCoordinator", names)

    def test_batches_delegate_default_execution_to_parallel_coordinator(self):
        for relative in ("scripts/batch_pdf.py", "scripts/batch_markdown.py"):
            tree = self._tree(relative)
            names = {
                node.func.id
                for node in ast.walk(tree)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            }
            self.assertIn("ParallelCoordinator", names, relative)


if __name__ == "__main__":
    unittest.main()
