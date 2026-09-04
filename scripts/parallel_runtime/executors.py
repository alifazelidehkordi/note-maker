from __future__ import annotations

from pathlib import Path
import time
from typing import Callable

from .event_bus import EventKind
from .models import ExecutionJob, WorkerExecutionResult
from .resilience import FailureCategory, RetryBudgetPolicy, RetryTracker


class _BrowserExecutorBase:
    def __init__(self, *, config: dict[str, object], run_id: str, worker_id: str, emit: Callable) -> None:
        self.config = config
        self.run_id = run_id
        self.worker_id = worker_id
        self.emit = emit
        self.driver = None
        self.provider = None
        self._terminal_startup_error: BaseException | None = None
        self.failed = False
        self.browser_restarts = 0
        self.rate_limit_count = 0
        self.last_retry_tracker: RetryTracker | None = None

    @property
    def model(self) -> str | None:
        value = self.config.get("model")
        return None if value is None else str(value)

    @property
    def skip_warmup(self) -> bool:
        # One authenticated warm-up is enough for a coordinated run. Sending
        # one disposable "hello" per parallel browser creates an avoidable
        # request burst and can trigger ChatGPT's account-wide rate limit.
        return bool(self.config.get("skip_warmup", False)) or not self.worker_id.startswith(
            "worker-001"
        )

    def _ensure_session(self):
        import batch_common as common

        if self._terminal_startup_error is not None:
            raise self._terminal_startup_error
        if self.provider is None:
            self.provider = common.get_browser_provider(str(self.config["browser_provider"]))
        if self.driver is not None and not common.driver_is_alive(self.driver):
            common.quit_driver(self.driver)
            self.driver = None
            self.browser_restarts += 1
        if self.driver is None:
            self.driver = common.bootstrap_session(
                self.model,
                provider=self.provider,
                skip_warmup=self.skip_warmup,
                run_id=self.run_id,
                worker_id=self.worker_id,
            )
        return self.driver

    def _attempt_started(self, _driver, attempt: int, attempt_limit: int) -> None:
        self.emit(
            EventKind.ATTEMPT_STARTED,
            attempt=attempt,
            attempt_limit=attempt_limit,
        )

    def _ensure_session_resilient(
        self,
        *,
        policy: RetryBudgetPolicy,
        tracker: RetryTracker,
    ):
        while True:
            try:
                return self._ensure_session()
            except Exception as exc:
                from browser_runtime.errors import BrowserConfigurationError

                if isinstance(exc, BrowserConfigurationError):
                    self._terminal_startup_error = exc
                decision = tracker.record(exc, default_delay=policy.backoff_base)
                self._retry_event(decision, exc)
                if not decision.retry:
                    raise
                if self.driver is not None:
                    import batch_common as common

                    common.quit_driver(self.driver)
                    self.driver = None
                if decision.delay_seconds > 0:
                    time.sleep(decision.delay_seconds)

    def _discard_dead_session(self) -> None:
        """Quarantine a crashed browser before this worker accepts another job."""
        if self.driver is None:
            return
        import batch_common as common

        if common.driver_is_alive(self.driver):
            return
        common.quit_driver(self.driver)
        self.driver = None
        self.browser_restarts += 1

    def _retry_policy(self, content_attempts: int) -> RetryBudgetPolicy:
        return RetryBudgetPolicy.from_mapping(
            {
                "content_attempts": content_attempts,
                "network_retries": self.config.get("network_retries", 4),
                "browser_retries": self.config.get("browser_retries", 3),
                "download_retries": self.config.get("download_retries", 2),
                "rate_limit_retries": self.config.get("rate_limit_retries", 2),
                "backoff_base": self.config.get("retry_backoff_base", 3.0),
                "backoff_cap": self.config.get("retry_backoff_cap", 24.0),
                "jitter_ratio": self.config.get("retry_jitter_ratio", 0.20),
            },
            content_attempts=content_attempts,
        )

    def _retry_event(self, decision, error) -> None:
        self.emit(
            EventKind.RETRY_SCHEDULED,
            category=decision.category.value,
            count=decision.count,
            limit=decision.limit,
            delay_seconds=decision.delay_seconds,
            retry=decision.retry,
            error=f"{type(error).__name__}: {error}",
        )
        if decision.category == FailureCategory.RATE_LIMIT:
            self.rate_limit_count += 1
            self.emit(
                EventKind.GLOBAL_COOLDOWN_REQUESTED,
                retry_after=(decision.retry_after or decision.delay_seconds),
            )
        elif decision.category == FailureCategory.AUTH:
            self.emit(EventKind.AUTH_FAILURE, error=str(error))

    def _result(self, ok: bool, *, diagnostic_path: str | None) -> WorkerExecutionResult:
        tracker = self.last_retry_tracker
        category = tracker.last_category.value if tracker and tracker.last_category else None
        retry_counts = tracker.as_dict() if tracker else {}
        browser_restarts = max(self.browser_restarts, int(retry_counts.get("browser", 0)))
        return WorkerExecutionResult(
            success=ok,
            error=None if ok else "No valid artifact was produced after all retry budgets were exhausted.",
            diagnostics=diagnostic_path,
            browser_restarts=browser_restarts,
            rate_limit_count=self.rate_limit_count,
            failure_category=category,
            retryable=False,
            retry_after=(tracker.last_decision.retry_after if tracker and tracker.last_decision else None),
            retry_counts=retry_counts,
            metadata={
                "rate_limit_signaled": self.rate_limit_count > 0,
                "auth_signaled": category == FailureCategory.AUTH.value,
            },
        )

    def close(self) -> None:
        if self.driver is None:
            return
        import batch_common as common

        driver = self.driver
        try:
            common.quit_driver(driver)
        finally:
            try:
                outcome = driver.profile_manager.cleanup_worker(
                    driver.profile_context,
                    success=not self.failed,
                )
                common.batch_log(
                    f"Worker runtime cleanup [{outcome.status.value}]: "
                    f"{driver.profile_context.run_id}/{driver.profile_context.worker_id} — "
                    f"{outcome.reason}"
                )
            except Exception as exc:
                common.batch_log(
                    f"Worker runtime cleanup [failed]: {self.run_id}/{self.worker_id} — "
                    f"{type(exc).__name__}: {exc}"
                )
            self.driver = None


class PdfJobExecutor(_BrowserExecutorBase):
    def execute(self, job: ExecutionJob) -> WorkerExecutionResult:
        import batch_common as common
        import batch_pdf

        policy = self._retry_policy(int(self.config.get("max_attempts", 3)))
        self.last_retry_tracker = RetryTracker(policy, seed=f"{self.run_id}:{job.key}")
        driver = self._ensure_session_resilient(policy=policy, tracker=self.last_retry_tracker)
        diagnostic_path: str | None = None
        label = str(job.metadata.get("input_name") or job.title or job.source.name)

        def attempt(driver_obj):
            return batch_pdf.process_one(
                driver_obj,
                str(self.config["prompt"]),
                job.source,
                Path(str(self.config["output_dir"])),
                self.model,
                download_timeout=int(self.config.get("download_timeout", 90)),
                save_diagnostics=bool(self.config.get("save_diagnostics", False)),
                output_ext=str(self.config.get("output_ext", "opml")),
            )

        def capture_failure(driver_obj, attempt_number, attempt_limit, error, final):
            nonlocal diagnostic_path
            if not final and not bool(self.config.get("save_diagnostics", False)):
                return
            result = common.capture_retry_failure(
                driver=driver_obj,
                output_dir=Path(str(self.config["output_dir"])),
                run_id=self.run_id,
                job_key=label,
                attempt=attempt_number,
                max_attempts=attempt_limit,
                expected_extensions=set(job.expected_extensions),
                source=job.source,
                prompt_hash=job.prompt_hash,
                error=error,
                final=final,
                save_page_source=bool(self.config.get("save_page_source", False)),
            )
            if final:
                diagnostic_path = str(result.directory)
                self.emit(EventKind.DIAGNOSTIC_SAVED, path=diagnostic_path)

        previous = driver
        ok, self.driver = common.run_with_retries(
            label,
            driver,
            self.model,
            attempt,
            provider=self.provider,
            max_attempts=int(self.config.get("max_attempts", 3)),
            skip_warmup=self.skip_warmup,
            diagnostic_callback=capture_failure,
            save_all_diagnostics=bool(self.config.get("save_diagnostics", False)),
            attempt_callback=self._attempt_started,
            retry_policy=policy,
            retry_tracker=self.last_retry_tracker,
            retry_event_callback=self._retry_event,
        )
        if self.driver is not previous:
            self.browser_restarts += 1
        self._discard_dead_session()
        if self.driver is not None:
            common.prune_driver_cookies(self.driver)
        self.failed = self.failed or not ok
        return self._result(ok, diagnostic_path=diagnostic_path)


class MarkdownJobExecutor(_BrowserExecutorBase):
    def execute(self, job: ExecutionJob) -> WorkerExecutionResult:
        import batch_common as common
        import batch_markdown

        policy = self._retry_policy(int(self.config.get("max_attempts", 3)))
        self.last_retry_tracker = RetryTracker(policy, seed=f"{self.run_id}:{job.key}")
        driver = self._ensure_session_resilient(policy=policy, tracker=self.last_retry_tracker)
        section_file = Path(str(job.metadata["section_file"]))
        section = batch_markdown.MarkdownSection(
            index=int(job.metadata["section_index"]),
            title=str(job.metadata["section_title"]),
            text=section_file.read_text(encoding="utf-8").strip(),
        )
        diagnostic_path: str | None = None
        label = job.title or f"section {section.index:02d} {section.title}"

        def attempt(driver_obj):
            return batch_markdown.process_markdown_section(
                driver=driver_obj,
                prompt=str(self.config["prompt"]),
                section=section,
                section_file=section_file,
                output_dir=Path(str(self.config["output_dir"])),
                model=self.model,
                download_timeout=int(self.config.get("download_timeout", 90)),
                save_diagnostics=bool(self.config.get("save_diagnostics", False)),
                output_ext=str(self.config.get("output_ext", "opml")),
            )

        def capture_failure(driver_obj, attempt_number, attempt_limit, error, final):
            nonlocal diagnostic_path
            if not final and not bool(self.config.get("save_diagnostics", False)):
                return
            result = common.capture_retry_failure(
                driver=driver_obj,
                output_dir=Path(str(self.config["output_dir"])),
                run_id=self.run_id,
                job_key=label,
                attempt=attempt_number,
                max_attempts=attempt_limit,
                expected_extensions=set(job.expected_extensions),
                source=section_file,
                prompt_hash=job.prompt_hash,
                error=error,
                final=final,
                save_page_source=bool(self.config.get("save_page_source", False)),
            )
            if final:
                diagnostic_path = str(result.directory)
                self.emit(EventKind.DIAGNOSTIC_SAVED, path=diagnostic_path)

        previous = driver
        ok, self.driver = common.run_with_retries(
            str(label),
            driver,
            self.model,
            attempt,
            provider=self.provider,
            max_attempts=int(self.config.get("max_attempts", 3)),
            skip_warmup=self.skip_warmup,
            diagnostic_callback=capture_failure,
            save_all_diagnostics=bool(self.config.get("save_diagnostics", False)),
            attempt_callback=self._attempt_started,
            retry_policy=policy,
            retry_tracker=self.last_retry_tracker,
            retry_event_callback=self._retry_event,
        )
        if self.driver is not previous:
            self.browser_restarts += 1
        self._discard_dead_session()
        if self.driver is not None:
            common.prune_driver_cookies(self.driver)
        self.failed = self.failed or not ok
        return self._result(ok, diagnostic_path=diagnostic_path)
