from __future__ import annotations

import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BrowserRuntimeArchitectureTests(unittest.TestCase):
    def test_batch_modules_do_not_use_raw_locator_apis(self):
        forbidden = {"find_element", "find_elements", "locator", "query_selector"}
        for relative in (
            "scripts/batch_common.py",
            "scripts/batch_pdf.py",
            "scripts/batch_markdown.py",
        ):
            tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"), filename=relative)
            used = {
                node.attr
                for node in ast.walk(tree)
                if isinstance(node, ast.Attribute) and node.attr in forbidden
            }
            self.assertEqual(used, set(), f"{relative} contains raw browser locator calls")

    def test_batch_jobs_use_browser_session_methods_instead_of_core_browser_calls(self):
        browser_calls = {
            "start_new_chat",
            "select_model",
            "attach_file",
            "wait_for_file_upload_complete",
            "assistant_message_count",
            "send_message",
            "wait_until_idle",
            "resolve_download",
        }
        for relative in ("scripts/batch_pdf.py", "scripts/batch_markdown.py"):
            tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"), filename=relative)
            violations = []
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                owner = node.func.value
                if isinstance(owner, ast.Name) and owner.id == "core" and node.func.attr in browser_calls:
                    violations.append(node.func.attr)
            self.assertEqual(violations, [], f"{relative} bypasses BrowserSession")

    def test_selenium_imports_are_isolated_from_facade_and_batch_modules(self):
        for relative in (
            "scripts/run_chatgpt_temporary_test.py",
            "scripts/batch_common.py",
            "scripts/batch_pdf.py",
            "scripts/batch_markdown.py",
        ):
            tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"), filename=relative)
            selenium_imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    selenium_imports.extend(alias.name for alias in node.names if alias.name.startswith("selenium"))
                elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith("selenium"):
                    selenium_imports.append(node.module or "selenium")
            self.assertEqual(selenium_imports, [], f"{relative} imports Selenium directly")
        legacy = (ROOT / "scripts/browser_runtime/selenium_legacy.py").read_text(encoding="utf-8")
        self.assertIn("from selenium", legacy)

    def test_compatibility_facade_keeps_phase0_public_function_names(self):
        import json

        baseline = json.loads(
            (ROOT / "docs/baseline/public-api-before.json").read_text(encoding="utf-8")
        )["scripts/run_chatgpt_temporary_test.py"]
        expected = {item["name"] for item in baseline["functions"]}
        tree = ast.parse(
            (ROOT / "scripts/run_chatgpt_temporary_test.py").read_text(encoding="utf-8")
        )
        current = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
        self.assertTrue(expected.issubset(current), sorted(expected - current))


if __name__ == "__main__":
    unittest.main()
