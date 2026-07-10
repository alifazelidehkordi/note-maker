from __future__ import annotations

import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

import diagnostics as diagnostic_store
import run_chatgpt_temporary_test as core
from artifact_validation import (
    ArtifactValidationError,
    ValidationResult,
    validate_artifact,
)
from browser_runtime import (
    BrowserLaunchOptions,
    BrowserProvider,
    BrowserSession,
    ManagedBrowserSession,
    ProfileManager,
    SessionBootstrapper,
    DownloadRequest,
    RateLimitError,
    ResponseWaitRequest,
    TemporaryChatError,
    create_browser_provider,
    ensure_browser_session,
)

ROOT = core.ROOT
LOGS_DIR = ROOT / "logs"
SKIP_NAME_PREFIXES = ("00_INDEX", "00_SPLIT_INDEX", "INDEX")
SKIP_NAME_STEMS = {"README", "INDEX"}


def batch_log(message: str) -> None:
    core.log(message)


def get_browser_provider(name: str = "selenium") -> BrowserProvider:
    return create_browser_provider(name)


def as_browser_session(
    value: object,
    *,
    provider: BrowserProvider | None = None,
) -> BrowserSession:
    return ensure_browser_session(value, provider=provider)


def _profile_path_for_provider(provider: BrowserProvider) -> Path:
    if provider.name == "patchright":
        return Path(
            os.environ.get("CHATGPT_PATCHRIGHT_PROFILE_DIR", ROOT / "patchright_profile")
        ).expanduser().resolve()
    return Path(
        os.environ.get("CHATGPT_CHROME_PROFILE_DIR", core.CHROME_PROFILE_DIR)
    ).expanduser().resolve()


def _download_path() -> Path:
    return Path(
        os.environ.get("CHATGPT_DOWNLOAD_DIR", getattr(core, "DOWNLOAD_DIR", ROOT / "downloads"))
    ).expanduser().resolve()


def _prepare_profile_context(
    provider: BrowserProvider,
    *,
    run_id: str,
    worker_id: str,
):
    manager = ProfileManager.from_environment(ROOT)
    snapshot = os.environ.get("CHATGPT_PROFILE_SNAPSHOT", "").strip()
    if snapshot:
        context = manager.prepare_worker(
            run_id=run_id,
            worker_id=worker_id,
            snapshot=snapshot,
        )
        batch_log(
            f"Prepared isolated worker profile from snapshot {context.snapshot_id}: "
            f"{context.profile_dir}"
        )
    else:
        context = manager.bind_existing_profile(
            run_id=run_id,
            worker_id=worker_id,
            profile_dir=_profile_path_for_provider(provider),
            download_dir=_download_path(),
        )
        batch_log(f"Using lease-protected existing profile: {context.profile_dir}")
    return manager, context


def _open_runtime_session(
    provider: BrowserProvider,
    *,
    run_id: str,
    worker_id: str,
    previous_session: object | None = None,
) -> ManagedBrowserSession:
    previous = previous_session if isinstance(previous_session, ManagedBrowserSession) else None
    if previous is not None:
        manager = previous.profile_manager
        context = previous.profile_context
    else:
        manager, context = _prepare_profile_context(
            provider,
            run_id=run_id,
            worker_id=worker_id,
        )
    bootstrapper = SessionBootstrapper(profile_manager=manager)
    return bootstrapper.open_session(
        provider=provider,
        context=context,
        options=BrowserLaunchOptions(
            browser="chrome",
            width=1400,
            height=950,
            url=core.CHATGPT_URL,
        ),
        validate_login=False,
        before_open=lambda worker_context: prune_automation_cookies(worker_context.profile_dir),
    )


def cleanup_runtime_session(driver, *, success: bool) -> None:
    if not isinstance(driver, ManagedBrowserSession):
        return
    try:
        deleted = driver.profile_manager.cleanup_run(
            driver.profile_context.run_id,
            success=success,
        )
        if deleted:
            batch_log(f"Cleaned managed runtime: {driver.profile_context.run_id}")
    except Exception as exc:
        batch_log(f"Runtime cleanup warning: {exc}")


def should_skip_input(path: Path) -> bool:
    stem_upper = path.stem.upper()
    if stem_upper in SKIP_NAME_STEMS:
        return True
    return any(stem_upper.startswith(prefix) for prefix in SKIP_NAME_PREFIXES)


def collect_input_files(input_dir: Path) -> list[Path]:
    patterns = ("*.pdf", "*.docx", "*.md")
    files: list[Path] = []
    for pattern in patterns:
        files.extend(path.resolve() for path in input_dir.glob(pattern) if path.is_file())
    unique = sorted({path for path in files if not should_skip_input(path)}, key=lambda p: p.name.lower())
    return unique


def wait_for_download(
    before,
    *,
    expected_extensions: set[str],
    started_at_ns: int,
    timeout: int = 90,
    browser_session: BrowserSession | object | None = None,
) -> Path | None:
    """Compatibility helper backed by the provider download contract."""
    if browser_session is None:
        # Filesystem-only salvage remains available through the compatibility
        # facade when no active session exists.
        return core.resolve_download(
            None,
            before,
            expected_extensions=expected_extensions,
            started_at_ns=started_at_ns,
            timeout=timeout,
            click=False,
        )
    session = as_browser_session(browser_session)
    return session.resolve_download(
        DownloadRequest(
            before=before,
            expected_extensions=expected_extensions,
            started_at_ns=started_at_ns,
            timeout=timeout,
            click=False,
        )
    )


def driver_is_alive(driver) -> bool:
    if driver is None:
        return False
    try:
        return as_browser_session(driver).is_alive()
    except Exception:
        return False


def quit_driver(driver) -> None:
    if driver is None:
        return
    try:
        as_browser_session(driver).close()
    except Exception:
        pass


def reset_chat(driver, model: str | None) -> None:
    session = as_browser_session(driver)
    session.start_new_chat()
    session.select_model(model)


def is_temporary_chat_error(exc: Exception) -> bool:
    if isinstance(exc, TemporaryChatError):
        return True
    message = str(exc).lower()
    return "temporary chat" in message or "prompt editor" in message


def recover_from_chat_error(
    driver,
    model: str | None,
    *,
    provider: BrowserProvider | None = None,
    skip_warmup: bool = False,
):
    batch_log("Recovering from temporary-chat load failure...")
    if driver_is_alive(driver):
        removed = prune_driver_cookies(driver)
        if removed:
            try:
                reset_chat(driver, model)
                return as_browser_session(driver, provider=provider)
            except Exception as exc:
                batch_log(f"Live cookie prune retry failed: {exc}")
    quit_driver(driver)
    previous_session = driver if isinstance(driver, ManagedBrowserSession) else None
    return recreate_driver(
        model,
        provider=provider,
        skip_warmup=skip_warmup,
        previous_session=previous_session,
    )


def recreate_driver(
    model: str | None,
    *,
    provider: BrowserProvider | None = None,
    skip_warmup: bool = False,
    previous_session: object | None = None,
    run_id: str | None = None,
    worker_id: str = "worker-001",
):
    batch_log("Detected dead or disconnected browser session. Recreating browser session...")
    selected = provider or get_browser_provider("selenium")
    previous = previous_session if isinstance(previous_session, ManagedBrowserSession) else None
    if previous is not None:
        effective_run_id = previous.profile_context.run_id
        effective_worker_id = previous.profile_context.worker_id
    else:
        effective_run_id = run_id or diagnostic_store.create_run_id()
        effective_worker_id = worker_id
    session = _open_runtime_session(
        selected,
        run_id=effective_run_id,
        worker_id=effective_worker_id,
        previous_session=previous,
    )
    batch_log("Checking login state...")
    session.wait_until_logged_in()
    batch_log("Logged-in chat box is visible.")
    if not skip_warmup:
        warm_up(session, model)
    else:
        reset_chat(session, model)
    return session


def warm_up(driver, model: str | None) -> None:
    session = as_browser_session(driver)
    batch_log("Warm-up: opening temporary chat and sending hello.")
    reset_chat(session, model)
    expected_assistant_count = session.assistant_message_count() + 1
    session.send_message("hello")
    session.wait_for_response(
        ResponseWaitRequest(min_assistant_count=expected_assistant_count)
    )
    batch_log("Warm-up complete.")


DELETE_COOKIE_PREFIXES = ("conv_key_",)
DELETE_COOKIE_EXACT = {"_dd_s"}


def should_delete_cookie(name: str) -> bool:
    if name in DELETE_COOKIE_EXACT:
        return True
    return any(name.startswith(prefix) for prefix in DELETE_COOKIE_PREFIXES)


def prune_driver_cookies(driver) -> int:
    """Remove temporary-chat cookies through the provider-neutral session API."""
    if not driver_is_alive(driver):
        return 0
    session = as_browser_session(driver)
    removed = 0
    for cookie in session.get_cookies():
        name = str(cookie.get("name", ""))
        if not should_delete_cookie(name):
            continue
        try:
            session.delete_cookie(name)
            removed += 1
        except Exception:
            pass
    if removed:
        batch_log(f"Pruned {removed} automation cookie(s) from live session.")
    return removed


def prune_automation_cookies(profile_dir: Path | None = None) -> None:
    script = ROOT / "scripts" / "prune_chatgpt_cookies.py"
    if not script.exists():
        return
    import subprocess
    import sys

    batch_log("Pruning automation cookies (keeping login session)...")
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--profile-dir",
            str((profile_dir or core.CHROME_PROFILE_DIR) / "Default"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    for line in (result.stdout or "").strip().splitlines():
        batch_log(line)
    if result.returncode != 0:
        batch_log(f"Cookie prune warning: {result.stderr.strip() or result.returncode}")


def bootstrap_session(
    model: str | None,
    *,
    provider: BrowserProvider | None = None,
    skip_warmup: bool = False,
    run_id: str | None = None,
    worker_id: str = "worker-001",
):
    selected = provider or get_browser_provider("selenium")
    effective_run_id = run_id or diagnostic_store.create_run_id()
    manager, context = _prepare_profile_context(
        selected,
        run_id=effective_run_id,
        worker_id=worker_id,
    )
    bootstrapper = SessionBootstrapper(profile_manager=manager)
    session = bootstrapper.open_session(
        provider=selected,
        context=context,
        options=BrowserLaunchOptions(
            browser="chrome",
            width=1400,
            height=950,
            url=core.CHATGPT_URL,
        ),
        validate_login=False,
        before_open=lambda worker_context: prune_automation_cookies(worker_context.profile_dir),
    )
    batch_log("ChatGPT opened.")
    batch_log("Checking login state...")
    session.wait_until_logged_in()
    batch_log("Logged-in chat box is visible.")
    if skip_warmup:
        reset_chat(session, model)
        batch_log("Skipped warm-up hello message.")
    else:
        warm_up(session, model)
    return session


def _fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _preserve_rejected_artifact(temporary: Path, output_path: Path) -> Path | None:
    if not temporary.exists():
        return None
    rejected_dir = output_path.parent / "_rejected"
    rejected_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    rejected_path = rejected_dir / f"{output_path.stem}-{timestamp}{output_path.suffix}"
    os.replace(temporary, rejected_path)
    return rejected_path


def save_artifact_download(
    downloaded: Path,
    output_path: Path,
    *,
    validate: bool = True,
    min_markdown_bytes: int = 100,
) -> ValidationResult:
    """Validate a downloaded artifact and replace the destination atomically.

    The existing output remains untouched until the new candidate has passed
    validation and the final ``os.replace`` succeeds. Invalid candidates are
    preserved under ``<output-dir>/_rejected`` for troubleshooting.
    """
    downloaded = downloaded.resolve()
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if downloaded == output_path:
        result = (
            validate_artifact(
                output_path,
                {output_path.suffix},
                min_markdown_bytes=min_markdown_bytes,
            )
            if validate
            else ValidationResult(True, (), output_path.suffix.lstrip(".") or None)
        )
        if not result.valid:
            raise ArtifactValidationError(output_path, result)
        return result

    temporary = output_path.parent / f".{output_path.name}.{uuid4().hex}.incoming.tmp"
    result = ValidationResult(True, (), output_path.suffix.lstrip(".") or None)
    try:
        shutil.move(str(downloaded), str(temporary))
        if validate:
            result = validate_artifact(
                temporary,
                {output_path.suffix},
                min_markdown_bytes=min_markdown_bytes,
            )
            if not result.valid:
                rejected_path = _preserve_rejected_artifact(temporary, output_path)
                raise ArtifactValidationError(
                    output_path,
                    result,
                    rejected_path=rejected_path,
                )

        _fsync_file(temporary)
        os.replace(temporary, output_path)
        return result
    except ArtifactValidationError:
        raise
    except Exception:
        if temporary.exists():
            temporary.unlink(missing_ok=True)
        raise


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_batch_summary(
    *,
    mode: str,
    successes: int,
    failures: list[str],
    output_dir: Path,
    extra: dict | None = None,
) -> Path:
    """Write an immutable run summary plus the compatibility latest copy."""
    payload = {
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "successes": successes,
        "failure_count": len(failures),
        "failures": failures,
        "output_dir": str(output_dir),
    }
    if extra:
        payload.update(extra)

    run_id = str(payload.get("run_id") or diagnostic_store.create_run_id())
    payload["run_id"] = run_id
    safe_run_id = diagnostic_store.safe_component(run_id, fallback="run")
    run_summary = LOGS_DIR / "runs" / safe_run_id / "summary.json"
    latest_summary = LOGS_DIR / "last_batch_summary.json"
    latest_pointer = LOGS_DIR / "last_batch_summary.pointer.json"

    _atomic_write_json(run_summary, payload)
    _atomic_write_json(latest_summary, payload)
    _atomic_write_json(
        latest_pointer,
        {
            "run_id": run_id,
            "summary": str(run_summary.resolve()),
            "updated_at": payload["finished_at"],
        },
    )
    batch_log(f"Batch summary saved: {run_summary}")
    batch_log(f"Latest batch summary updated: {latest_summary}")
    return run_summary


class NoValidArtifactError(RuntimeError):
    """A retry attempt completed without producing a usable artifact."""


DiagnosticCallback = Callable[[object, int, int, BaseException, bool], None]
AttemptCallback = Callable[[object, int, int], None]


def capture_retry_failure(
    *,
    driver,
    output_dir: Path,
    run_id: str,
    job_key: str,
    attempt: int,
    max_attempts: int,
    expected_extensions: set[str],
    source: Path | str,
    prompt_hash: str,
    error: BaseException,
    final: bool,
    save_page_source: bool = False,
) -> diagnostic_store.DiagnosticResult:
    """Capture one failed retry attempt without raising a secondary error."""
    validation_errors: tuple[str, ...] = ()
    rejected_path: Path | None = None
    if isinstance(error, ArtifactValidationError):
        stage = "validation"
        validation_errors = error.result.errors
        rejected_path = error.rejected_path
    elif isinstance(error, NoValidArtifactError):
        stage = "download"
    else:
        stage = "automation"

    session = as_browser_session(driver) if driver is not None else None
    try:
        response_text = session.latest_assistant_text() if session is not None else ""
    except Exception as exc:
        response_text = f"[Could not read latest assistant response: {type(exc).__name__}: {exc}]"

    result = diagnostic_store.save_failure_diagnostics(
        driver=session,
        output_dir=output_dir,
        run_id=run_id,
        job_key=job_key,
        attempt=attempt,
        max_attempts=max_attempts,
        stage=stage,
        expected_extensions=expected_extensions,
        source=source,
        prompt_hash=prompt_hash,
        error=error,
        response_text=response_text,
        validation_errors=validation_errors,
        rejected_path=rejected_path,
        save_page_source=save_page_source,
        final=final,
    )
    batch_log(f"Diagnostics saved: {result.directory}")
    for capture_error in result.capture_errors:
        batch_log(f"Diagnostics warning: {capture_error}")
    return result


def _emit_retry_diagnostic(
    callback: DiagnosticCallback | None,
    driver,
    attempt: int,
    max_attempts: int,
    error: BaseException,
    *,
    final: bool,
    save_all: bool,
) -> None:
    if callback is None or (not final and not save_all):
        return
    try:
        callback(driver, attempt, max_attempts, error, final)
    except Exception as exc:
        batch_log(f"WARNING: could not save diagnostics: {exc}")


def run_with_retries(
    label: str,
    driver,
    model: str | None,
    process_once: Callable[[object], bool],
    *,
    provider: BrowserProvider | None = None,
    max_attempts: int = 3,
    retry_delay: int = 5,
    skip_warmup: bool = False,
    diagnostic_callback: DiagnosticCallback | None = None,
    save_all_diagnostics: bool = False,
    attempt_callback: AttemptCallback | None = None,
    retry_policy=None,
    retry_tracker=None,
    retry_event_callback=None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> tuple[bool, object]:
    selected = provider or get_browser_provider("selenium")
    if retry_policy is not None:
        from parallel_runtime.resilience import RetryTracker

        tracker = retry_tracker or RetryTracker(retry_policy, seed=label)
        session = as_browser_session(driver, provider=selected)
        attempt = 0
        attempt_limit = retry_policy.maximum_total_attempts
        while attempt < attempt_limit:
            attempt += 1
            error: BaseException | None = None
            try:
                if not driver_is_alive(session):
                    previous_session = session
                    quit_driver(session)
                    session = recreate_driver(
                        model,
                        provider=selected,
                        skip_warmup=skip_warmup,
                        previous_session=previous_session,
                    )
                if attempt > 1:
                    batch_log(f"Retrying {label} (attempt {attempt}/{attempt_limit})...")
                if attempt_callback is not None:
                    attempt_callback(session, attempt, attempt_limit)
                if process_once(session):
                    return True, session
                error = NoValidArtifactError("No valid artifact was produced by this attempt.")
            except Exception as exc:
                error = exc

            decision = tracker.record(error, default_delay=retry_delay)
            final = not decision.retry or attempt >= attempt_limit
            if retry_event_callback is not None:
                retry_event_callback(decision, error)
            batch_log(
                f"Retry category={decision.category.value} count={decision.count}/"
                f"{decision.limit} retry={'yes' if decision.retry and not final else 'no'} "
                f"for {label}: {error}"
            )
            _emit_retry_diagnostic(
                diagnostic_callback,
                session,
                attempt,
                attempt_limit,
                error,
                final=final,
                save_all=save_all_diagnostics,
            )
            if final:
                return False, session
            if is_temporary_chat_error(error):
                session = recover_from_chat_error(
                    session,
                    model,
                    provider=selected,
                    skip_warmup=skip_warmup,
                )
            elif driver_is_alive(session):
                reset_chat(session, model)
            else:
                previous_session = session
                quit_driver(session)
                session = recreate_driver(
                    model,
                    provider=selected,
                    skip_warmup=skip_warmup,
                    previous_session=previous_session,
                )
            if decision.delay_seconds > 0:
                sleep_fn(decision.delay_seconds)
        return False, session

    session = as_browser_session(driver, provider=selected)
    for attempt in range(1, max_attempts + 1):
        retry_wait = retry_delay
        try:
            if not driver_is_alive(session):
                previous_session = session
                quit_driver(session)
                session = recreate_driver(
                    model,
                    provider=selected,
                    skip_warmup=skip_warmup,
                    previous_session=previous_session,
                )

            if attempt > 1:
                batch_log(f"Retrying {label} (attempt {attempt}/{max_attempts})...")

            if attempt_callback is not None:
                attempt_callback(session, attempt, max_attempts)

            if process_once(session):
                return True, session

            error = NoValidArtifactError("No valid artifact was produced by this attempt.")
            final = attempt == max_attempts
            _emit_retry_diagnostic(
                diagnostic_callback,
                session,
                attempt,
                max_attempts,
                error,
                final=final,
                save_all=save_all_diagnostics,
            )
            if final:
                batch_log("No valid artifact obtained after the final attempt.")
            else:
                batch_log("No valid artifact obtained. Opening a fresh chat for next attempt.")
                if driver_is_alive(session):
                    reset_chat(session, model)
                else:
                    previous_session = session
                    quit_driver(session)
                    session = recreate_driver(
                        model,
                        provider=selected,
                        skip_warmup=skip_warmup,
                        previous_session=previous_session,
                    )
        except Exception as exc:
            final = attempt == max_attempts
            if isinstance(exc, RateLimitError) and exc.retry_after:
                retry_wait = max(retry_delay, exc.retry_after)
                batch_log(f"Rate limit cooldown requested: {retry_wait}s")
            batch_log(f"ERROR on attempt {attempt}/{max_attempts} for {label}: {exc}")
            _emit_retry_diagnostic(
                diagnostic_callback,
                session,
                attempt,
                max_attempts,
                exc,
                final=final,
                save_all=save_all_diagnostics,
            )
            if not final:
                if is_temporary_chat_error(exc):
                    session = recover_from_chat_error(
                        session,
                        model,
                        provider=selected,
                        skip_warmup=skip_warmup,
                    )
                elif driver_is_alive(session):
                    reset_chat(session, model)
                else:
                    previous_session = session
                    quit_driver(session)
                    session = recreate_driver(
                        model,
                        provider=selected,
                        skip_warmup=skip_warmup,
                        previous_session=previous_session,
                    )
        if attempt < max_attempts:
            time.sleep(retry_wait)
    return False, session
