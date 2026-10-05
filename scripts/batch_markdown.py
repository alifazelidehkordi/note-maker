from __future__ import annotations

import argparse
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import batch_common as common
import manifest as manifest_store
import run_chatgpt_temporary_test as core
import runtime_flags
from browser_runtime import DownloadRequest, ResponseWaitRequest, UploadRequest
from parallel_runtime.job_sources import build_section_candidates
from parallel_runtime.models import PlanningOptions, RunConfig
from parallel_runtime.coordinator import ParallelCoordinator
from parallel_runtime.planner import plan_jobs


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "markdown"
DEFAULT_PROMPT = ROOT / "prompts" / "prompt-mind-map.md"


@dataclass(frozen=True)
class MarkdownSection:
    index: int
    title: str
    text: str

    @property
    def output_stem(self) -> str:
        return f"{self.index:02d}_{core.safe_filename(self.title).lower()}"


def batch_log(message: str) -> None:
    common.batch_log(message)


def parse_section_numbers(value: str | None) -> set[int] | None:
    if not value:
        return None

    selected: set[int] = set()
    for raw_part in value.split(","):
        part = raw_part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start = int(start_text.strip())
            end = int(end_text.strip())
            if start <= 0 or end <= 0 or end < start:
                raise ValueError(f"Invalid section range: {part}")
            selected.update(range(start, end + 1))
        else:
            section = int(part)
            if section <= 0:
                raise ValueError(f"Invalid section number: {part}")
            selected.add(section)
    return selected


def split_markdown_sections(markdown_path: Path) -> list[MarkdownSection]:
    text = markdown_path.read_text(encoding="utf-8")
    heading_pattern = re.compile(r"(?m)^##\s+(.+?)\s*$")
    matches = list(heading_pattern.finditer(text))
    sections: list[MarkdownSection] = []

    for zero_index, match in enumerate(matches):
        start = match.start()
        end = matches[zero_index + 1].start() if zero_index + 1 < len(matches) else len(text)
        title = match.group(1).strip()
        section_text = text[start:end].strip()
        if title and section_text:
            sections.append(MarkdownSection(index=len(sections) + 1, title=title, text=section_text))

    return sections


def select_sections(
    sections: list[MarkdownSection],
    sections_filter: set[int] | None,
    limit: int | None,
) -> list[MarkdownSection]:
    if sections_filter is not None:
        sections = [section for section in sections if section.index in sections_filter]
    if limit is not None:
        sections = sections[:limit]
    return sections


def write_markdown_section_file(section: MarkdownSection, section_dir: Path) -> Path:
    section_dir.mkdir(parents=True, exist_ok=True)
    section_path = section_dir / f"{section.output_stem}.md"
    section_path.write_text(section.text.rstrip() + "\n", encoding="utf-8")
    return section_path


def build_section_prompt(prompt: str, section: MarkdownSection) -> str:
    return (
        f"{prompt}\n\n"
        "Use the uploaded Markdown file as the complete source text. "
        f"It contains section {section.index}: {section.title}. "
        "Generate the requested downloadable file from only that uploaded section."
    )


def process_markdown_section(
    driver,
    prompt: str,
    section: MarkdownSection,
    section_file: Path,
    output_dir: Path,
    model: str | None,
    *,
    download_timeout: int,
    save_diagnostics: bool,
    output_ext: str = "opml",
) -> bool:
    session = common.as_browser_session(driver)
    ext = output_ext.lstrip(".")
    output_path = output_dir / f"{section.output_stem}.{ext}"
    batch_log(f"Processing section {section.index}: {section.title}")

    session.start_new_chat()
    session.select_model(model)

    before_downloads = session.snapshot_downloads()
    session.upload(UploadRequest(section_file, native_upload=False))

    expected_assistant_count = session.assistant_message_count() + 1
    download_started_at_ns = time.time_ns()
    session.send_message(build_section_prompt(prompt, section))
    session.wait_for_response(
        ResponseWaitRequest(min_assistant_count=expected_assistant_count)
    )

    downloaded = session.resolve_download(
        DownloadRequest(
            before=before_downloads,
            expected_extensions={f".{ext}"},
            started_at_ns=download_started_at_ns,
            timeout=download_timeout,
            job_key=section.output_stem,
        )
    )

    if downloaded is None:
        batch_log(f"FAILED: no downloadable {ext.upper()} detected for section {section.index}: {section.title}")
        return False

    common.save_artifact_download(downloaded, output_path)
    batch_log(f"Saved {ext.upper()}: {output_path}")
    return True


def _section_job_key(markdown_file: Path, section: MarkdownSection, ext: str) -> str:
    return f"{markdown_file.name}::section-{section.index:04d}::{ext}"


def run_batch(
    markdown_file: Path,
    output_dir: Path,
    prompt_path: Path,
    sections_filter: set[int] | None = None,
    overwrite: bool = False,
    limit: int | None = None,
    model: str | None = None,
    save_diagnostics: bool = False,
    save_page_source: bool = False,
    max_section_attempts: int = 3,
    download_timeout: int = 90,
    close_delay: int = 20,
    chrome_profile_dir: Path | None = None,
    skip_warmup: bool = False,
    keep_browser: bool = False,
    output_ext: str = "opml",
    manifest_path: Path | None = None,
    resume: bool = True,
    retry_failed: bool = False,
    adopt_existing: bool = False,
    browser_provider: str = runtime_flags.DEFAULT_BROWSER_PROVIDER,
    parallel_runs: int = runtime_flags.DEFAULT_PARALLEL_RUNS,
    runtime_dir: Path | None = None,
    profile_snapshot: str | None = None,
    keep_runtime: bool = False,
    worker_heartbeat_interval: float = runtime_flags.DEFAULT_WORKER_HEARTBEAT_INTERVAL,
    worker_timeout: float = runtime_flags.DEFAULT_WORKER_TIMEOUT,
    worker_ready_timeout: float = runtime_flags.DEFAULT_WORKER_READY_TIMEOUT,
    worker_startup_stagger: float = runtime_flags.DEFAULT_WORKER_STARTUP_STAGGER,
    max_worker_restarts: int = runtime_flags.DEFAULT_MAX_WORKER_RESTARTS,
    shutdown_grace_seconds: float = runtime_flags.DEFAULT_SHUTDOWN_GRACE_SECONDS,
    runtime_settings: runtime_flags.RuntimeSettings | None = None,
) -> int:
    runtime = runtime_settings or runtime_flags.validate_runtime_settings(
        browser_provider,
        parallel_runs,
        runtime_dir=runtime_dir,
        profile_snapshot=profile_snapshot,
        keep_runtime=keep_runtime,
        worker_heartbeat_interval=worker_heartbeat_interval,
        worker_timeout=worker_timeout,
        worker_ready_timeout=worker_ready_timeout,
        worker_startup_stagger=worker_startup_stagger,
        max_worker_restarts=max_worker_restarts,
        shutdown_grace_seconds=shutdown_grace_seconds,
    )
    runtime_flags.apply_runtime_environment(runtime)
    if keep_browser and runtime.parallel_runs > 1:
        raise ValueError("--keep-browser is only compatible with --parallel-runs 1.")
    provider = None
    core.LOG_FILE.write_text("", encoding="utf-8")
    output_dir.mkdir(parents=True, exist_ok=True)

    if chrome_profile_dir is not None:
        resolved_profile = str(chrome_profile_dir.expanduser().resolve())
        os.environ["CHATGPT_CHROME_PROFILE_DIR"] = resolved_profile
        os.environ["CHATGPT_PATCHRIGHT_PROFILE_DIR"] = resolved_profile

    if not markdown_file.exists():
        raise FileNotFoundError(markdown_file)
    if not prompt_path.exists():
        raise FileNotFoundError(prompt_path)

    prompt = prompt_path.read_text(encoding="utf-8").strip()
    if not prompt:
        raise ValueError("Prompt file is empty.")

    all_sections = split_markdown_sections(markdown_file)
    sections = select_sections(all_sections, sections_filter, limit)
    if not sections:
        batch_log(f"No matching level-2 Markdown sections found in {markdown_file}")
        return 1

    section_dir = output_dir / "_md_sections"
    ext = output_ext.lstrip(".").lower()
    run_id = common.diagnostic_store.create_run_id()
    prompt_hash = manifest_store.hash_text(prompt)
    manifest_file = (manifest_path or (output_dir / "manifest.json")).resolve()
    store = manifest_store.ManifestCoordinator(manifest_file)
    diagnostics_by_job: dict[str, str] = {}
    skipped: dict[str, str] = {}
    adopted: list[str] = []
    batch_log(f"Run ID: {run_id}")
    batch_log(f"Markdown file: {markdown_file}")
    batch_log(f"Output folder: {output_dir}")
    batch_log(f"Output extension: .{ext}")
    batch_log(f"Manifest: {manifest_file}")
    batch_log(f"Resume: {'enabled' if resume else 'disabled'}")
    batch_log(f"Detected sections: {len(all_sections)}")
    batch_log(f"Sections selected: {len(sections)}")
    batch_log(f"Browser provider: {runtime.browser_provider}")
    batch_log(f"Parallel runs: {runtime.parallel_runs}")
    if runtime.runtime_dir is not None:
        batch_log(f"Managed runtime root: {runtime.runtime_dir}")
    if runtime.profile_snapshot is not None:
        batch_log(f"Profile snapshot: {runtime.profile_snapshot}")
    batch_log(f"Keep managed runtime: {'yes' if runtime.keep_runtime else 'policy default'}")

    candidates = build_section_candidates(
        sections,
        markdown_file=markdown_file,
        section_dir=section_dir,
        output_dir=output_dir,
        prompt_path=prompt_path,
        prompt_hash=prompt_hash,
        output_ext=ext,
        mode=f"markdown-{ext}",
        model=model,
        key_builder=_section_job_key,
        section_file_writer=write_markdown_section_file,
    )
    plan = plan_jobs(
        candidates,
        store.as_reader(),
        run_id=run_id,
        options=PlanningOptions(
            overwrite=overwrite,
            resume=resume,
            adopt_existing=adopt_existing,
            retry_failed_only=retry_failed,
        ),
    )
    with store.batch_update():
        store.register_run(
            run_id,
            mode=f"markdown-{ext}",
            planned_jobs=len(plan.runnable),
            estimated_total_weight=plan.estimated_total_weight,
            parallel_runs=runtime.parallel_runs,
            browser_provider=runtime.browser_provider,
        )
        store.apply_plan(plan)

    for item in plan.runnable:
        batch_log(
            f"Resume decision for {item.label}: run — {item.reason} "
            f"(weight={item.job.estimated_weight})"
        )
    for label, reason in plan.skipped.items():
        batch_log(f"Resume decision for {label}: skip — {reason}")
    for label in plan.adopted:
        batch_log(f"Resume decision for {label}: adopt — valid existing output")

    planned = plan.runnable
    skipped = dict(plan.skipped)
    adopted = list(plan.adopted)
    successes = plan.initial_successes
    batch_log(
        f"Planning complete: runnable={len(planned)}, skipped={len(skipped)}, "
        f"adopted={len(adopted)}, estimated_weight={plan.estimated_total_weight}."
    )

    failures: list[str] = []

    if planned and not keep_browser:
        label_by_key = {item.job.key: item.label for item in planned}
        config = RunConfig(
            run_id=run_id,
            manifest_path=manifest_file,
            claims_dir=manifest_file.parent / ".note-maker-claims",
            worker_count=runtime.parallel_runs,
            executor_path="parallel_runtime.executors:MarkdownJobExecutor",
            executor_config={
                "prompt": prompt,
                "output_dir": str(output_dir),
                "model": model,
                "browser_provider": runtime.browser_provider,
                "max_attempts": max_section_attempts,
                "download_timeout": download_timeout,
                "skip_warmup": skip_warmup,
                "save_diagnostics": save_diagnostics,
                "save_page_source": save_page_source,
                "output_ext": ext,
                "network_retries": runtime.network_retries,
                "browser_retries": runtime.browser_retries,
                "download_retries": runtime.download_retries,
                "rate_limit_retries": runtime.rate_limit_retries,
                "retry_backoff_base": runtime.retry_backoff_base,
                "retry_backoff_cap": runtime.retry_backoff_cap,
                "retry_jitter_ratio": runtime.retry_jitter_ratio,
            },
            heartbeat_interval=runtime.worker_heartbeat_interval,
            worker_timeout=runtime.worker_timeout,
            worker_ready_timeout=runtime.worker_ready_timeout,
            startup_stagger=runtime.worker_startup_stagger,
            max_worker_restarts=runtime.max_worker_restarts,
            shutdown_grace=runtime.shutdown_grace_seconds,
            claim_stale_after=max(runtime.worker_timeout * 2.0, 60.0),
            global_rate_limit_cooldown=runtime.global_rate_limit_cooldown,
            auth_failures_before_abort=runtime.auth_failures_before_abort,
            rate_limit_failures_before_abort=runtime.rate_limit_failures_before_abort,
            rate_limit_window_seconds=runtime.rate_limit_window_seconds,
            adaptive_concurrency=runtime.adaptive_concurrency,
            adaptive_scale_down_threshold=runtime.adaptive_scale_down_threshold,
            adaptive_recovery_seconds=runtime.adaptive_recovery_seconds,
            worker_max_jobs=runtime.worker_max_jobs,
            rest_every=runtime.rest_every,
            rest_seconds=runtime.rest_seconds,
            rest_state=runtime.rest_state,
            worker_memory_limit_mb=runtime.worker_memory_limit_mb,
            content_attempts=max_section_attempts,
            network_retries=runtime.network_retries,
            browser_retries=runtime.browser_retries,
            download_retries=runtime.download_retries,
            rate_limit_retries=runtime.rate_limit_retries,
            retry_backoff_base=runtime.retry_backoff_base,
            retry_backoff_cap=runtime.retry_backoff_cap,
            retry_jitter_ratio=runtime.retry_jitter_ratio,
        )
        result = ParallelCoordinator(
            config,
            (item.job for item in planned),
            manifest=store,
            event_logger=batch_log,
        ).run()
        successes += len(result.succeeded) + len(result.externally_completed)
        failures = [label_by_key.get(key, key) for key in result.failed]
        diagnostics_by_job.update(
            {label_by_key.get(key, key): path for key, path in result.diagnostics.items()}
        )
        batch_log(
            f"Parallel Markdown batch complete. Successes: {successes}. "
            f"Failures: {len(failures)}. Workers: {runtime.parallel_runs}. "
            f"Restarts: {result.worker_restarts}."
        )
        if failures:
            batch_log("Failed sections:")
            for name in failures:
                batch_log(f"- {name}")
        summary_path = common.write_batch_summary(
            mode=f"markdown-{ext}",
            successes=successes,
            failures=failures,
            output_dir=output_dir,
            extra={
                "markdown_file": str(markdown_file),
                "max_section_attempts": max_section_attempts,
                "download_timeout": download_timeout,
                "output_ext": ext,
                "run_id": run_id,
                "manifest": str(manifest_file),
                "resume_enabled": resume,
                "retry_failed_only": retry_failed,
                "skipped": skipped,
                "adopted": adopted,
                "diagnostics": diagnostics_by_job,
                "browser_provider": runtime.browser_provider,
                "parallel_runs": runtime.parallel_runs,
                "worker_heartbeat_interval": runtime.worker_heartbeat_interval,
                "worker_timeout": runtime.worker_timeout,
                "worker_ready_timeout": runtime.worker_ready_timeout,
                "worker_startup_stagger": runtime.worker_startup_stagger,
                "max_worker_restarts": runtime.max_worker_restarts,
                "shutdown_grace_seconds": runtime.shutdown_grace_seconds,
                "global_rate_limit_cooldown": runtime.global_rate_limit_cooldown,
                "auth_failures_before_abort": runtime.auth_failures_before_abort,
                "rate_limit_failures_before_abort": runtime.rate_limit_failures_before_abort,
                "adaptive_concurrency": runtime.adaptive_concurrency,
                "adaptive_scale_down_threshold": runtime.adaptive_scale_down_threshold,
                "adaptive_recovery_seconds": runtime.adaptive_recovery_seconds,
                "worker_max_jobs": runtime.worker_max_jobs,
                "worker_memory_limit_mb": runtime.worker_memory_limit_mb,
                "network_retries": runtime.network_retries,
                "browser_retries": runtime.browser_retries,
                "download_retries": runtime.download_retries,
                "rate_limit_retries": runtime.rate_limit_retries,
                "retry_backoff_base": runtime.retry_backoff_base,
                "retry_backoff_cap": runtime.retry_backoff_cap,
                "retry_jitter_ratio": runtime.retry_jitter_ratio,
                "runtime_dir": str(runtime.runtime_dir) if runtime.runtime_dir else None,
                "profile_snapshot": runtime.profile_snapshot,
                "keep_runtime": runtime.keep_runtime,
                "worker_restarts": result.worker_restarts,
                "worker_recycles": result.worker_recycles,
                "zombie_processes_cleaned": result.zombie_processes_cleaned,
                "stale_claims_recovered": result.stale_claims_recovered,
                "retry_counts": result.retry_counts,
                "rate_limit_events": result.rate_limit_events,
                "auth_failures": result.auth_failures,
                "global_cooldown_seconds": result.global_cooldown_seconds,
                "minimum_active_workers": result.minimum_active_workers,
                "final_active_workers": result.final_active_workers,
                "adaptive_scale_downs": result.adaptive_scale_downs,
                "adaptive_scale_ups": result.adaptive_scale_ups,
                "circuit_breaker_reason": result.circuit_breaker_reason,
                "worker_assignments": result.assignments,
                "externally_completed": result.externally_completed,
                "coordinator_duration_seconds": result.duration_seconds,
                "interrupted": result.interrupted,
            },
        )
        store.finish_run(
            run_id,
            status=(
                "interrupted"
                if result.interrupted
                else ("completed" if not failures else "completed_with_failures")
            ),
            summary_path=summary_path,
        )
        return 130 if result.interrupted else (0 if not failures else 2)

    driver = None
    try:
        if planned:
            provider = common.get_browser_provider(runtime.browser_provider)
            driver = common.bootstrap_session(
                model,
                provider=provider,
                skip_warmup=skip_warmup,
                run_id=run_id,
                worker_id="worker-001",
            )

        for position, planned_job in enumerate(planned, start=1):
            section, section_file = planned_job.payload
            job = planned_job.job
            label = planned_job.label
            batch_log(f"Starting runnable section {position}/{len(planned)}: {label}")

            def attempt(driver_obj):
                return process_markdown_section(
                    driver=driver_obj,
                    prompt=prompt,
                    section=section,
                    section_file=section_file,
                    output_dir=output_dir,
                    model=model,
                    download_timeout=download_timeout,
                    save_diagnostics=save_diagnostics,
                    output_ext=output_ext,
                )

            def on_attempt(_driver_obj, attempt_number, _attempt_limit):
                store.mark_running(
                    job, run_id=run_id, attempt=attempt_number, worker_id="worker-001"
                )

            def capture_failure(driver_obj, attempt_number, attempt_limit, error, final):
                result = None
                try:
                    result = common.capture_retry_failure(
                        driver=driver_obj,
                        output_dir=output_dir,
                        run_id=run_id,
                        job_key=label,
                        attempt=attempt_number,
                        max_attempts=attempt_limit,
                        expected_extensions={f".{ext}"},
                        source=section_file,
                        prompt_hash=prompt_hash,
                        error=error,
                        final=final,
                        save_page_source=save_page_source,
                    )
                    if final:
                        diagnostics_by_job[label] = str(result.directory)
                finally:
                    if final:
                        store.mark_failed(
                            job,
                            run_id=run_id,
                            error=error,
                            diagnostics=result.directory if result is not None else None,
                        )

            ok, driver = common.run_with_retries(
                label,
                driver,
                model,
                attempt,
                provider=provider,
                max_attempts=max_section_attempts,
                skip_warmup=skip_warmup,
                diagnostic_callback=capture_failure,
                save_all_diagnostics=save_diagnostics,
                attempt_callback=on_attempt,
            )
            if ok:
                try:
                    store.mark_completed(job, run_id=run_id)
                    successes += 1
                except Exception as exc:
                    batch_log(f"ERROR: output was produced but manifest completion failed: {exc}")
                    store.mark_failed(job, run_id=run_id, error=exc)
                    failures.append(f"{section.index:02d} {section.title}")
            else:
                failures.append(f"{section.index:02d} {section.title}")
                entry = store.get(job.key)
                if not entry or entry.get("status") != "failed":
                    store.mark_failed(
                        job,
                        run_id=run_id,
                        error="No valid artifact was produced after all retries.",
                    )
            common.prune_driver_cookies(driver)

        batch_log(
            f"Markdown batch complete. Successes: {successes}. Failures: {len(failures)}. "
            f"Skipped: {len(skipped)}. Adopted: {len(adopted)}."
        )
        if failures:
            batch_log("Failed sections:")
            for name in failures:
                batch_log(f"- {name}")

        summary_path = common.write_batch_summary(
            mode=f"markdown-{ext}",
            successes=successes,
            failures=failures,
            output_dir=output_dir,
            extra={
                "markdown_file": str(markdown_file),
                "max_section_attempts": max_section_attempts,
                "download_timeout": download_timeout,
                "output_ext": ext,
                "run_id": run_id,
                "manifest": str(manifest_file),
                "resume_enabled": resume,
                "retry_failed_only": retry_failed,
                "skipped": skipped,
                "adopted": adopted,
                "diagnostics": diagnostics_by_job,
                "browser_provider": runtime.browser_provider,
                "parallel_runs": runtime.parallel_runs,
                "worker_heartbeat_interval": runtime.worker_heartbeat_interval,
                "worker_timeout": runtime.worker_timeout,
                "worker_ready_timeout": runtime.worker_ready_timeout,
                "worker_startup_stagger": runtime.worker_startup_stagger,
                "max_worker_restarts": runtime.max_worker_restarts,
                "shutdown_grace_seconds": runtime.shutdown_grace_seconds,
                "global_rate_limit_cooldown": runtime.global_rate_limit_cooldown,
                "auth_failures_before_abort": runtime.auth_failures_before_abort,
                "rate_limit_failures_before_abort": runtime.rate_limit_failures_before_abort,
                "adaptive_concurrency": runtime.adaptive_concurrency,
                "adaptive_scale_down_threshold": runtime.adaptive_scale_down_threshold,
                "adaptive_recovery_seconds": runtime.adaptive_recovery_seconds,
                "worker_max_jobs": runtime.worker_max_jobs,
                "worker_memory_limit_mb": runtime.worker_memory_limit_mb,
                "network_retries": runtime.network_retries,
                "browser_retries": runtime.browser_retries,
                "download_retries": runtime.download_retries,
                "rate_limit_retries": runtime.rate_limit_retries,
                "retry_backoff_base": runtime.retry_backoff_base,
                "retry_backoff_cap": runtime.retry_backoff_cap,
                "retry_jitter_ratio": runtime.retry_jitter_ratio,
                "runtime_dir": str(runtime.runtime_dir) if runtime.runtime_dir else None,
                "profile_snapshot": runtime.profile_snapshot,
                "keep_runtime": runtime.keep_runtime,
            },
        )
        store.finish_run(
            run_id,
            status="completed" if not failures else "completed_with_failures",
            summary_path=summary_path,
        )
        return 0 if not failures else 2
    finally:
        if driver is None:
            batch_log("No browser session was required.")
        elif keep_browser:
            batch_log("Keeping browser open (--keep-browser).")
        else:
            batch_log(f"Closing browser in {close_delay} seconds...")
            time.sleep(close_delay)
            common.quit_driver(driver)
            common.cleanup_runtime_session(driver, success=not failures)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Process each ## section in a Markdown file with a prompt and download the generated artifact.")
    parser.add_argument("--markdown-file", type=Path, required=True, help="Markdown file with ## section headings")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT)
    parser.add_argument("--sections", default=None, help="Comma-separated section numbers or ranges, e.g. 20,21,22 or 20-22.")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--model", default=None)
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
    parser.add_argument("--max-section-attempts", type=int, default=3)
    parser.add_argument("--download-timeout", type=int, default=90)
    parser.add_argument("--close-delay", type=int, default=20)
    parser.add_argument("--chrome-profile-dir", type=Path, default=None)
    parser.add_argument("--output-ext", default="opml", help="Output file extension (opml or md)")
    parser.add_argument(
        "--no-warm-up",
        action="store_true",
        help="Skip the initial hello warm-up message when opening ChatGPT.",
    )
    parser.add_argument(
        "--keep-browser",
        action="store_true",
        help="Do not close the browser when the batch finishes.",
    )
    parser.add_argument("--manifest", type=Path, default=None, help="Manifest path (default: <output-dir>/manifest.json)")
    parser.add_argument("--no-resume", action="store_true", help="Ignore resume decisions and run selected jobs again; results are still recorded.")
    parser.add_argument("--retry-failed", action="store_true", help="Only run sections previously failed, interrupted, pending, or invalidated in the manifest.")
    parser.add_argument("--adopt-existing", action="store_true", help="Validate and register untracked existing outputs instead of rebuilding them.")
    runtime_flags.add_runtime_arguments(parser)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        runtime = runtime_flags.settings_from_namespace(args)
    except runtime_flags.RuntimeConfigurationError as exc:
        parser.error(str(exc))

    try:
        return run_batch(
            markdown_file=args.markdown_file,
            output_dir=args.output_dir,
            prompt_path=args.prompt,
            sections_filter=parse_section_numbers(args.sections),
            overwrite=args.overwrite,
            limit=args.limit,
            model=args.model,
            save_diagnostics=args.save_diagnostics,
            save_page_source=args.save_page_source,
            output_ext=getattr(args, "output_ext", "opml"),
            max_section_attempts=args.max_section_attempts,
            download_timeout=args.download_timeout,
            close_delay=args.close_delay,
            chrome_profile_dir=args.chrome_profile_dir,
            skip_warmup=args.no_warm_up,
            keep_browser=args.keep_browser,
            manifest_path=args.manifest,
            resume=not args.no_resume,
            retry_failed=args.retry_failed,
            adopt_existing=args.adopt_existing,
            browser_provider=args.browser_provider,
            parallel_runs=args.parallel_runs,
            runtime_dir=args.runtime_dir,
            profile_snapshot=args.profile_snapshot,
            keep_runtime=args.keep_runtime,
            worker_heartbeat_interval=args.worker_heartbeat_interval,
            worker_timeout=args.worker_timeout,
            worker_ready_timeout=args.worker_ready_timeout,
            worker_startup_stagger=args.worker_startup_stagger,
            max_worker_restarts=args.max_worker_restarts,
            shutdown_grace_seconds=args.shutdown_grace_seconds,
            runtime_settings=runtime,
        )
    except Exception as exc:
        core.log(f"ERROR: {exc}")
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
