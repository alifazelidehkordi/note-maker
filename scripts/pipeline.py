from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import runtime_flags


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
DEFAULT_INPUT_DIR = ROOT / "inputs"
DEFAULT_OPML_DIR = ROOT / "outputs" / "opml"
DEFAULT_XMIND_DIR = ROOT / "outputs" / "xmind"
DEFAULT_PROMPT = ROOT / "prompts" / "prompt-mind-map.md"


def run_step(label: str, command: list[str]) -> int:
    print(f"\n=== {label} ===")
    print(" ".join(command))
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode != 0:
        print(f"{label} failed with exit code {result.returncode}", file=sys.stderr)
    return result.returncode


def build_common_args(args: argparse.Namespace) -> list[str]:
    common: list[str] = []
    if args.overwrite:
        common.append("--overwrite")
    if args.limit is not None:
        common.extend(["--limit", str(args.limit)])
    if args.model:
        common.extend(["--model", args.model])
    if args.save_diagnostics:
        common.append("--save-diagnostics")
    if getattr(args, "save_page_source", False):
        common.append("--save-page-source")
    if args.download_timeout != 90:
        common.extend(["--download-timeout", str(args.download_timeout)])
    if getattr(args, "no_warm_up", False):
        common.append("--no-warm-up")
    if getattr(args, "keep_browser", False):
        common.append("--keep-browser")
    if getattr(args, "close_delay", 20) != 20:
        common.extend(["--close-delay", str(args.close_delay)])
    if getattr(args, "output_ext", None):
        common.extend(["--output-ext", args.output_ext])
    if getattr(args, "manifest", None):
        common.extend(["--manifest", str(args.manifest)])
    if getattr(args, "no_resume", False):
        common.append("--no-resume")
    if getattr(args, "retry_failed", False):
        common.append("--retry-failed")
    if getattr(args, "adopt_existing", False):
        common.append("--adopt-existing")
    common.extend(["--browser-provider", args.browser_provider])
    common.extend(["--parallel-runs", str(args.parallel_runs)])
    common.extend(["--worker-heartbeat-interval", str(args.worker_heartbeat_interval)])
    common.extend(["--worker-timeout", str(args.worker_timeout)])
    common.extend(["--worker-ready-timeout", str(args.worker_ready_timeout)])
    common.extend(["--worker-startup-stagger", str(args.worker_startup_stagger)])
    common.extend(["--max-worker-restarts", str(args.max_worker_restarts)])
    common.extend(["--shutdown-grace-seconds", str(args.shutdown_grace_seconds)])
    common.extend(["--global-rate-limit-cooldown", str(args.global_rate_limit_cooldown)])
    common.extend(["--auth-failures-before-abort", str(args.auth_failures_before_abort)])
    common.extend(["--rate-limit-failures-before-abort", str(args.rate_limit_failures_before_abort)])
    common.extend(["--rate-limit-window-seconds", str(args.rate_limit_window_seconds)])
    if args.adaptive_concurrency:
        common.append("--adaptive-concurrency")
    common.extend(["--adaptive-scale-down-threshold", str(args.adaptive_scale_down_threshold)])
    common.extend(["--adaptive-recovery-seconds", str(args.adaptive_recovery_seconds)])
    common.extend(["--worker-max-jobs", str(args.worker_max_jobs)])
    common.extend(["--worker-memory-limit-mb", str(args.worker_memory_limit_mb)])
    common.extend(["--network-retries", str(args.network_retries)])
    common.extend(["--browser-retries", str(args.browser_retries)])
    common.extend(["--download-retries", str(args.download_retries)])
    common.extend(["--rate-limit-retries", str(args.rate_limit_retries)])
    common.extend(["--retry-backoff-base", str(args.retry_backoff_base)])
    common.extend(["--retry-backoff-cap", str(args.retry_backoff_cap)])
    common.extend(["--retry-jitter-ratio", str(args.retry_jitter_ratio)])
    if getattr(args, "runtime_dir", None):
        common.extend(["--runtime-dir", str(args.runtime_dir)])
    if getattr(args, "profile_snapshot", None):
        common.extend(["--profile-snapshot", args.profile_snapshot])
    if getattr(args, "keep_runtime", False):
        common.append("--keep-runtime")
    return common


def run_pdf_pipeline(args: argparse.Namespace) -> int:
    python = sys.executable
    common = build_common_args(args)
    out_ext = getattr(args, "output_ext", None) or "opml"
    is_markdown_output = out_ext.lower() in ("md", "markdown")

    pdf_args = [
        python,
        str(SCRIPTS / "batch_pdf.py"),
        "--input-dir",
        str(args.input_dir),
        "--output-dir",
        str(args.opml_dir),
        "--prompt",
        str(args.prompt),
        *common,
    ]
    if args.max_attempts != 3:
        pdf_args.extend(["--max-attempts", str(args.max_attempts)])

    step1_label = "Step 1/2: Generate Markdown from PDF/DOCX" if is_markdown_output else "Step 1/2: Generate OPML from PDF/DOCX/MD"
    code = run_step(step1_label, pdf_args)

    if is_markdown_output:
        print("\nMarkdown mode: skipping XMind conversion. Artifacts are ready in the output directory.")
        return code

    convert_args = [
        python,
        str(SCRIPTS / "convert_opml_batch.py"),
        "--opml-dir",
        str(args.opml_dir),
        "--xmind-dir",
        str(args.xmind_dir),
    ]
    if args.overwrite:
        convert_args.append("--overwrite")
    if args.limit is not None:
        convert_args.extend(["--limit", str(args.limit)])

    convert_code = run_step("Step 2/2: Convert OPML to XMind", convert_args)
    if code != 0:
        return code
    return convert_code


def run_markdown_pipeline(args: argparse.Namespace) -> int:
    if not args.markdown_file:
        print("ERROR: --markdown-file is required for markdown mode.", file=sys.stderr)
        return 1

    python = sys.executable
    common = build_common_args(args)
    out_ext = getattr(args, "output_ext", None) or "opml"
    is_markdown_output = out_ext.lower() in ("md", "markdown")

    md_args = [
        python,
        str(SCRIPTS / "batch_markdown.py"),
        "--markdown-file",
        str(args.markdown_file),
        "--output-dir",
        str(args.opml_dir),
        "--prompt",
        str(args.prompt),
        *common,
    ]
    if args.sections:
        md_args.extend(["--sections", args.sections])
    if args.max_section_attempts != 3:
        md_args.extend(["--max-section-attempts", str(args.max_section_attempts)])

    step1_label = "Step 1/2: Generate Markdown from Markdown sections" if is_markdown_output else "Step 1/2: Generate OPML from Markdown sections"
    code = run_step(step1_label, md_args)

    if is_markdown_output:
        print("\nMarkdown mode: skipping XMind conversion. Clean .md files are ready.")
        return code

    convert_args = [
        python,
        str(SCRIPTS / "convert_opml_batch.py"),
        "--opml-dir",
        str(args.opml_dir),
        "--xmind-dir",
        str(args.xmind_dir),
    ]
    if args.overwrite:
        convert_args.append("--overwrite")
    if args.limit is not None:
        convert_args.extend(["--limit", str(args.limit)])

    convert_code = run_step("Step 2/2: Convert OPML to XMind", convert_args)
    if code != 0:
        return code
    return convert_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Full pipeline: source file(s) -> OPML -> XMind (.xmind)"
    )
    parser.add_argument(
        "mode",
        choices=["pdf", "markdown"],
        help="pdf: batch PDF/DOCX files; markdown: split a .md file by ## headings",
    )
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--markdown-file", type=Path)
    parser.add_argument("--opml-dir", type=Path, default=DEFAULT_OPML_DIR)
    parser.add_argument("--xmind-dir", type=Path, default=DEFAULT_XMIND_DIR)
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT)
    parser.add_argument("--sections")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--model")
    parser.add_argument(
        "--save-diagnostics",
        action="store_true",
        help="Save diagnostics for every failed retry; final failures are always saved.",
    )
    parser.add_argument(
        "--save-page-source",
        action="store_true",
        help="Include potentially sensitive page_source.html in failure diagnostics.",
    )
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--max-section-attempts", type=int, default=3)
    parser.add_argument("--download-timeout", type=int, default=90)
    parser.add_argument("--close-delay", type=int, default=20)
    parser.add_argument(
        "--no-warm-up",
        action="store_true",
        help="Skip the initial hello warm-up in ChatGPT.",
    )
    parser.add_argument(
        "--keep-browser",
        action="store_true",
        help="Leave the browser open after the batch finishes.",
    )
    parser.add_argument("--output-ext", default=None, help="Output extension for generated artifact (opml or md)")
    parser.add_argument("--manifest", type=Path, default=None, help="Manifest path passed to the batch generator")
    parser.add_argument("--no-resume", action="store_true", help="Ignore resume decisions while still recording results")
    parser.add_argument("--retry-failed", action="store_true", help="Only run failed or interrupted manifest jobs")
    parser.add_argument("--adopt-existing", action="store_true", help="Validate and register untracked existing outputs")
    runtime_flags.add_runtime_arguments(parser)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        runtime_flags.settings_from_namespace(args)
    except runtime_flags.RuntimeConfigurationError as exc:
        parser.error(str(exc))

    if args.mode == "pdf":
        return run_pdf_pipeline(args)
    return run_markdown_pipeline(args)


if __name__ == "__main__":
    raise SystemExit(main())
