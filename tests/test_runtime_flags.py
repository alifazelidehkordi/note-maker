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

import batch_markdown
import batch_pdf
import pipeline
import runtime_flags


class RuntimeFlagsTests(unittest.TestCase):
    def test_batch_parsers_preserve_runtime_defaults(self):
        pdf_args = batch_pdf.build_parser().parse_args([])
        self.assertEqual(pdf_args.browser_provider, "selenium")
        self.assertEqual(pdf_args.parallel_runs, 1)
        self.assertIsNone(pdf_args.runtime_dir)
        self.assertIsNone(pdf_args.profile_snapshot)
        self.assertFalse(pdf_args.keep_runtime)

        md_args = batch_markdown.build_parser().parse_args(
            ["--markdown-file", "lecture.md"]
        )
        self.assertEqual(md_args.browser_provider, "selenium")
        self.assertEqual(md_args.parallel_runs, 1)
        self.assertIsNone(md_args.runtime_dir)
        self.assertIsNone(md_args.profile_snapshot)
        self.assertFalse(md_args.keep_runtime)

    def test_explicit_level5_flags_are_accepted(self):
        args = batch_pdf.build_parser().parse_args(
            ["--browser-provider", "selenium", "--parallel-runs", "1"]
        )
        settings = runtime_flags.settings_from_namespace(args)
        self.assertEqual(
            settings,
            runtime_flags.RuntimeSettings(
                browser_provider="selenium",
                parallel_runs=1,
            ),
        )

    def test_non_positive_parallel_runs_is_rejected_by_argparse(self):
        with self.assertRaises(SystemExit):
            batch_pdf.build_parser().parse_args(["--parallel-runs", "0"])

    def test_parallel_execution_is_enabled_with_a_safety_cap(self):
        settings = runtime_flags.validate_runtime_settings("selenium", 4)
        self.assertEqual(settings.parallel_runs, 4)
        with self.assertRaisesRegex(
            runtime_flags.RuntimeConfigurationError,
            "must not exceed",
        ):
            runtime_flags.validate_runtime_settings(
                "selenium", runtime_flags.MAX_PARALLEL_RUNS + 1
            )

    def test_worker_timeout_must_exceed_heartbeat_interval(self):
        with self.assertRaisesRegex(
            runtime_flags.RuntimeConfigurationError,
            "must be greater",
        ):
            runtime_flags.validate_runtime_settings(
                worker_heartbeat_interval=10, worker_timeout=10
            )



    def test_worker_ready_timeout_must_be_positive(self):
        with self.assertRaisesRegex(
            runtime_flags.RuntimeConfigurationError,
            "worker_ready_timeout",
        ):
            runtime_flags.validate_runtime_settings(worker_ready_timeout=0)

    def test_shutdown_grace_is_configurable_and_nonnegative(self):
        settings = runtime_flags.validate_runtime_settings(
            shutdown_grace_seconds=3.5
        )
        self.assertEqual(settings.shutdown_grace_seconds, 3.5)
        with self.assertRaisesRegex(
            runtime_flags.RuntimeConfigurationError,
            "shutdown_grace_seconds",
        ):
            runtime_flags.validate_runtime_settings(
                shutdown_grace_seconds=-0.1
            )

    def test_patchright_provider_is_opt_in_and_unknown_provider_is_rejected(self):
        settings = runtime_flags.validate_runtime_settings("patchright", 1)
        self.assertEqual(settings.browser_provider, "patchright")
        with self.assertRaisesRegex(
            runtime_flags.RuntimeConfigurationError,
            "Unsupported browser provider",
        ):
            runtime_flags.validate_runtime_settings("unknown", 1)

    def test_batch_summary_records_runtime_settings(self):
        valid_markdown = (
            "# Existing Note\n\n## Explanation\n\n"
            "This existing note is long enough to pass validation and be adopted "
            "without opening a browser session during the Level 3 runtime test.\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "inputs"
            output_dir = root / "outputs"
            logs_dir = root / "logs"
            input_dir.mkdir()
            output_dir.mkdir()
            (input_dir / "source.pdf").write_bytes(b"pdf")
            (output_dir / "source.md").write_text(valid_markdown, encoding="utf-8")
            prompt = root / "prompt.md"
            prompt.write_text("Create notes", encoding="utf-8")

            with mock.patch.object(batch_pdf.common, "LOGS_DIR", logs_dir), mock.patch.object(
                batch_pdf.core, "LOG_FILE", root / "run.log"
            ), mock.patch.object(
                batch_pdf.common,
                "get_browser_provider",
                side_effect=AssertionError("zero runnable jobs must not construct a provider"),
            ), mock.patch.object(
                batch_pdf.common,
                "bootstrap_session",
                side_effect=AssertionError("adoption must not open the browser"),
            ):
                code = batch_pdf.run_batch(
                    input_dir=input_dir,
                    output_dir=output_dir,
                    prompt_path=prompt,
                    output_ext="md",
                    adopt_existing=True,
                    browser_provider="selenium",
                    parallel_runs=1,
                )

            self.assertEqual(code, 0)
            summary = json.loads(
                (logs_dir / "last_batch_summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(summary["browser_provider"], "selenium")
            self.assertEqual(summary["parallel_runs"], 1)
            self.assertEqual(summary["worker_heartbeat_interval"], 10.0)
            self.assertEqual(summary["worker_timeout"], 45.0)
            self.assertEqual(summary["worker_ready_timeout"], 180.0)
            self.assertEqual(summary["worker_startup_stagger"], 1.0)
            self.assertEqual(summary["max_worker_restarts"], 2)
            self.assertEqual(summary["shutdown_grace_seconds"], 10.0)
            self.assertEqual(summary["global_rate_limit_cooldown"], 180.0)
            self.assertEqual(summary["auth_failures_before_abort"], 2)
            self.assertFalse(summary["adaptive_concurrency"])
            self.assertEqual(summary["worker_max_jobs"], 20)
            self.assertEqual(summary["network_retries"], 4)

    def test_pipeline_forwards_parallel_runtime_settings(self):
        args = pipeline.build_parser().parse_args(
            [
                "pdf",
                "--browser-provider",
                "selenium",
                "--parallel-runs",
                "1",
            ]
        )
        common = pipeline.build_common_args(args)
        self.assertIn("--browser-provider", common)
        self.assertEqual(common[common.index("--browser-provider") + 1], "selenium")
        self.assertIn("--parallel-runs", common)
        self.assertEqual(common[common.index("--parallel-runs") + 1], "1")
        self.assertIn("--worker-heartbeat-interval", common)
        self.assertIn("--worker-timeout", common)
        self.assertIn("--worker-ready-timeout", common)
        self.assertIn("--worker-startup-stagger", common)
        self.assertIn("--max-worker-restarts", common)
        self.assertIn("--shutdown-grace-seconds", common)
        self.assertIn("--global-rate-limit-cooldown", common)
        self.assertIn("--auth-failures-before-abort", common)
        self.assertIn("--worker-max-jobs", common)
        self.assertIn("--network-retries", common)
        self.assertIn("--retry-jitter-ratio", common)


    def test_level6_resilience_flags_are_validated(self):
        args = batch_pdf.build_parser().parse_args(
            [
                "--global-rate-limit-cooldown", "12",
                "--auth-failures-before-abort", "1",
                "--rate-limit-failures-before-abort", "4",
                "--adaptive-concurrency",
                "--adaptive-recovery-seconds", "30",
                "--worker-max-jobs", "5",
                "--worker-memory-limit-mb", "512",
                "--network-retries", "2",
                "--browser-retries", "1",
                "--download-retries", "1",
                "--rate-limit-retries", "1",
                "--retry-backoff-base", "0.5",
                "--retry-backoff-cap", "5",
                "--retry-jitter-ratio", "0.1",
            ]
        )
        settings = runtime_flags.settings_from_namespace(args)
        self.assertEqual(settings.global_rate_limit_cooldown, 12)
        self.assertTrue(settings.adaptive_concurrency)
        self.assertEqual(settings.worker_max_jobs, 5)
        self.assertEqual(settings.worker_memory_limit_mb, 512)
        self.assertEqual(settings.network_retries, 2)
        self.assertEqual(settings.retry_jitter_ratio, 0.1)
        with self.assertRaisesRegex(runtime_flags.RuntimeConfigurationError, "retry_jitter_ratio"):
            runtime_flags.validate_runtime_settings(retry_jitter_ratio=1.1)

    def test_profile_runtime_flags_are_normalized_and_forwarded(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp) / "managed-runtime"
            args = pipeline.build_parser().parse_args(
                [
                    "pdf",
                    "--runtime-dir",
                    str(runtime_dir),
                    "--profile-snapshot",
                    "signed-in-session",
                    "--keep-runtime",
                ]
            )
            settings = runtime_flags.settings_from_namespace(args)
            self.assertEqual(settings.runtime_dir, runtime_dir.resolve())
            self.assertEqual(settings.profile_snapshot, "signed-in-session")
            self.assertTrue(settings.keep_runtime)

            common = pipeline.build_common_args(args)
            self.assertEqual(
                common[common.index("--runtime-dir") + 1],
                str(runtime_dir),
            )
            self.assertEqual(
                common[common.index("--profile-snapshot") + 1],
                "signed-in-session",
            )
            self.assertIn("--keep-runtime", common)

    def test_explicit_runtime_settings_are_applied_to_environment(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {}, clear=True):
            settings = runtime_flags.validate_runtime_settings(
                runtime_dir=Path(tmp) / "runtime",
                profile_snapshot="snapshot-001",
                keep_runtime=True,
            )
            runtime_flags.apply_runtime_environment(settings)
            self.assertEqual(os.environ["CHATGPT_RUNTIME_DIR"], str((Path(tmp) / "runtime").resolve()))
            self.assertEqual(os.environ["CHATGPT_PROFILE_SNAPSHOT"], "snapshot-001")
            self.assertEqual(os.environ["CHATGPT_RUNTIME_RETENTION"], "keep-all")

    def test_batch_main_accepts_parallel_mode_and_forwards_it(self):
        with mock.patch.object(
            sys,
            "argv",
            [
                "batch_pdf.py",
                "--parallel-runs",
                "2",
                "--rate-limit-failures-before-abort",
                "1000",
                "--worker-max-jobs",
                "0",
            ],
        ), mock.patch.object(batch_pdf, "run_batch", return_value=0) as run_batch:
            code = batch_pdf.main()
        self.assertEqual(code, 0)
        self.assertEqual(run_batch.call_args.kwargs["parallel_runs"], 2)
        settings = run_batch.call_args.kwargs["runtime_settings"]
        self.assertEqual(settings.rate_limit_failures_before_abort, 1000)
        self.assertEqual(settings.worker_max_jobs, 0)

    def test_markdown_main_forwards_complete_runtime_settings(self):
        with mock.patch.object(
            sys,
            "argv",
            [
                "batch_markdown.py",
                "--markdown-file",
                "lecture.md",
                "--rate-limit-failures-before-abort",
                "777",
                "--worker-max-jobs",
                "0",
            ],
        ), mock.patch.object(batch_markdown, "run_batch", return_value=0) as run_batch:
            code = batch_markdown.main()
        self.assertEqual(code, 0)
        settings = run_batch.call_args.kwargs["runtime_settings"]
        self.assertEqual(settings.rate_limit_failures_before_abort, 777)
        self.assertEqual(settings.worker_max_jobs, 0)


if __name__ == "__main__":
    unittest.main()
