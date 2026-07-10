from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from uuid import uuid4


@dataclass(frozen=True)
class DiagnosticResult:
    directory: Path
    files: tuple[Path, ...]
    capture_errors: tuple[str, ...]


def create_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{timestamp}-{uuid4().hex[:8]}"


def hash_text(text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def safe_component(value: str, *, fallback: str = "job", limit: int = 120) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    cleaned = cleaned.strip("._-") or fallback
    return cleaned[:limit]


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)




def _save_screenshot(source, path: Path) -> bool:
    method = getattr(source, "save_screenshot", None)
    if method is None:
        raise RuntimeError("browser session does not support screenshots")
    try:
        return bool(method(path))
    except TypeError:
        return bool(method(str(path)))


def _page_source(source) -> str:
    method = getattr(source, "get_page_source", None)
    if method is not None:
        return str(method())
    return str(getattr(source, "page_source"))

def _error_payload(error: BaseException | None) -> tuple[str | None, str | None]:
    if error is None:
        return None, None
    return type(error).__name__, str(error)


def save_failure_diagnostics(
    *,
    driver,
    output_dir: Path,
    run_id: str,
    job_key: str,
    attempt: int,
    max_attempts: int,
    stage: str,
    expected_extensions: Iterable[str],
    source: Path | str,
    prompt_hash: str,
    error: BaseException | None,
    response_text: str = "",
    validation_errors: Iterable[str] = (),
    rejected_path: Path | None = None,
    save_page_source: bool = False,
    final: bool = True,
) -> DiagnosticResult:
    """Persist best-effort diagnostics without masking the original failure.

    Final-attempt files are written directly under the job directory. When all
    retry diagnostics are requested, intermediate attempts are placed under
    ``attempts/attempt-NN`` so the final failure remains easy to locate.
    """
    root = Path(output_dir).resolve() / "diagnostics" / safe_component(run_id, fallback="run")
    job_dir = root / safe_component(job_key)
    target_dir = job_dir if final else job_dir / "attempts" / f"attempt-{attempt:02d}"
    target_dir.mkdir(parents=True, exist_ok=True)

    files: list[Path] = []
    capture_errors: list[str] = []

    response_path = target_dir / "last_response.txt"
    try:
        _atomic_write_text(response_path, response_text or "")
        files.append(response_path)
    except Exception as exc:  # diagnostics must remain best-effort
        capture_errors.append(f"response: {type(exc).__name__}: {exc}")

    screenshot_path = target_dir / "last_state.png"
    if driver is not None and hasattr(driver, "save_screenshot"):
        try:
            saved = _save_screenshot(driver, screenshot_path)
            if saved is False:
                raise RuntimeError("driver returned False")
            if not screenshot_path.exists():
                raise RuntimeError("driver reported success but no screenshot file was created")
            files.append(screenshot_path)
        except Exception as exc:
            capture_errors.append(f"screenshot: {type(exc).__name__}: {exc}")
    else:
        capture_errors.append("screenshot: driver is unavailable")

    if save_page_source:
        page_source_path = target_dir / "page_source.html"
        try:
            page_source = _page_source(driver)
            _atomic_write_text(page_source_path, page_source)
            files.append(page_source_path)
        except Exception as exc:
            capture_errors.append(f"page_source: {type(exc).__name__}: {exc}")

    copied_candidate: Path | None = None
    if rejected_path is not None:
        rejected_path = Path(rejected_path)
        if rejected_path.exists() and rejected_path.is_file():
            suffix = rejected_path.suffix or ".bin"
            copied_candidate = target_dir / f"downloaded_candidate{suffix}"
            try:
                shutil.copy2(rejected_path, copied_candidate)
                files.append(copied_candidate)
            except Exception as exc:
                copied_candidate = None
                capture_errors.append(f"candidate: {type(exc).__name__}: {exc}")

    error_type, error_message = _error_payload(error)
    metadata = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "job_key": job_key,
        "stage": stage,
        "attempt": attempt,
        "max_attempts": max_attempts,
        "final_attempt": final,
        "expected_extensions": sorted({str(item).lower() for item in expected_extensions}),
        "source": str(source),
        "prompt_hash": prompt_hash,
        "error_type": error_type,
        "error_message": error_message,
        "validation_errors": list(validation_errors),
        "rejected_path": str(rejected_path) if rejected_path is not None else None,
        "copied_candidate": str(copied_candidate) if copied_candidate is not None else None,
        "capture_errors": capture_errors,
    }
    metadata_path = target_dir / "metadata.json"
    try:
        _atomic_write_text(
            metadata_path,
            json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        files.append(metadata_path)
    except Exception as exc:
        capture_errors.append(f"metadata: {type(exc).__name__}: {exc}")

    return DiagnosticResult(
        directory=target_dir,
        files=tuple(files),
        capture_errors=tuple(capture_errors),
    )
