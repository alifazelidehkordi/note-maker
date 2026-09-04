from __future__ import annotations

import argparse
import math
import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_BROWSER_PROVIDER = "selenium"
DEFAULT_PARALLEL_RUNS = 1
MAX_PARALLEL_RUNS = 16
DEFAULT_WORKER_HEARTBEAT_INTERVAL = 10.0
DEFAULT_WORKER_TIMEOUT = 45.0
DEFAULT_WORKER_READY_TIMEOUT = 180.0
DEFAULT_WORKER_STARTUP_STAGGER = 1.0
DEFAULT_MAX_WORKER_RESTARTS = 2
DEFAULT_SHUTDOWN_GRACE_SECONDS = 10.0
DEFAULT_GLOBAL_RATE_LIMIT_COOLDOWN = 180.0
DEFAULT_AUTH_FAILURES_BEFORE_ABORT = 2
DEFAULT_RATE_LIMIT_FAILURES_BEFORE_ABORT = 6
DEFAULT_RATE_LIMIT_WINDOW_SECONDS = 300.0
DEFAULT_ADAPTIVE_SCALE_DOWN_THRESHOLD = 2
DEFAULT_ADAPTIVE_RECOVERY_SECONDS = 900.0
DEFAULT_WORKER_MAX_JOBS = 20
DEFAULT_WORKER_MEMORY_LIMIT_MB = 0.0
DEFAULT_NETWORK_RETRIES = 4
DEFAULT_BROWSER_RETRIES = 3
DEFAULT_DOWNLOAD_RETRIES = 2
DEFAULT_RATE_LIMIT_RETRIES = 2
DEFAULT_RETRY_BACKOFF_BASE = 3.0
DEFAULT_RETRY_BACKOFF_CAP = 24.0
DEFAULT_RETRY_JITTER_RATIO = 0.20
SUPPORTED_BROWSER_PROVIDERS = (DEFAULT_BROWSER_PROVIDER, "patchright")


class RuntimeConfigurationError(ValueError):
    """Raised when a requested runtime mode is not available in the current phase."""


@dataclass(frozen=True)
class RuntimeSettings:
    browser_provider: str = DEFAULT_BROWSER_PROVIDER
    parallel_runs: int = DEFAULT_PARALLEL_RUNS
    runtime_dir: Path | None = None
    profile_snapshot: str | None = None
    keep_runtime: bool = False
    worker_heartbeat_interval: float = DEFAULT_WORKER_HEARTBEAT_INTERVAL
    worker_timeout: float = DEFAULT_WORKER_TIMEOUT
    worker_ready_timeout: float = DEFAULT_WORKER_READY_TIMEOUT
    worker_startup_stagger: float = DEFAULT_WORKER_STARTUP_STAGGER
    max_worker_restarts: int = DEFAULT_MAX_WORKER_RESTARTS
    shutdown_grace_seconds: float = DEFAULT_SHUTDOWN_GRACE_SECONDS
    global_rate_limit_cooldown: float = DEFAULT_GLOBAL_RATE_LIMIT_COOLDOWN
    auth_failures_before_abort: int = DEFAULT_AUTH_FAILURES_BEFORE_ABORT
    rate_limit_failures_before_abort: int = DEFAULT_RATE_LIMIT_FAILURES_BEFORE_ABORT
    rate_limit_window_seconds: float = DEFAULT_RATE_LIMIT_WINDOW_SECONDS
    adaptive_concurrency: bool = False
    adaptive_scale_down_threshold: int = DEFAULT_ADAPTIVE_SCALE_DOWN_THRESHOLD
    adaptive_recovery_seconds: float = DEFAULT_ADAPTIVE_RECOVERY_SECONDS
    worker_max_jobs: int = DEFAULT_WORKER_MAX_JOBS
    worker_memory_limit_mb: float = DEFAULT_WORKER_MEMORY_LIMIT_MB
    network_retries: int = DEFAULT_NETWORK_RETRIES
    browser_retries: int = DEFAULT_BROWSER_RETRIES
    download_retries: int = DEFAULT_DOWNLOAD_RETRIES
    rate_limit_retries: int = DEFAULT_RATE_LIMIT_RETRIES
    retry_backoff_base: float = DEFAULT_RETRY_BACKOFF_BASE
    retry_backoff_cap: float = DEFAULT_RETRY_BACKOFF_CAP
    retry_jitter_ratio: float = DEFAULT_RETRY_JITTER_RATIO


def _finite_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if not math.isfinite(parsed):
        raise argparse.ArgumentTypeError("must be finite")
    return parsed


def _positive_float(value: str) -> float:
    parsed = _finite_float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def _nonnegative_float(value: str) -> float:
    parsed = _finite_float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must not be negative")
    return parsed


def _nonnegative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must not be negative")
    return parsed


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def add_runtime_arguments(parser: argparse.ArgumentParser) -> None:
    """Add Level 6 browser and process-runtime flags."""
    parser.add_argument(
        "--browser-provider",
        choices=SUPPORTED_BROWSER_PROVIDERS,
        default=DEFAULT_BROWSER_PROVIDER,
        help=(
            "Browser provider. Selenium remains the default; Patchright is available as an opt-in persistent-context engine."
        ),
    )
    parser.add_argument(
        "--parallel-runs",
        type=_positive_int,
        default=DEFAULT_PARALLEL_RUNS,
        metavar="N",
        help=(
            f"Number of concurrent browser worker processes (1-{MAX_PARALLEL_RUNS}). "
            "All values, including 1, use the same dynamic coordinator runtime."
        ),
    )
    parser.add_argument(
        "--worker-heartbeat-interval",
        type=_positive_float,
        default=DEFAULT_WORKER_HEARTBEAT_INTERVAL,
        metavar="SECONDS",
        help="Seconds between worker heartbeat events (default: 10).",
    )
    parser.add_argument(
        "--worker-timeout",
        type=_positive_float,
        default=DEFAULT_WORKER_TIMEOUT,
        metavar="SECONDS",
        help="Declare a worker lost after this heartbeat silence (default: 45).",
    )
    parser.add_argument(
        "--worker-ready-timeout",
        type=_positive_float,
        default=DEFAULT_WORKER_READY_TIMEOUT,
        metavar="SECONDS",
        help="Maximum startup time before WORKER_READY is required (default: 180).",
    )
    parser.add_argument(
        "--worker-startup-stagger",
        type=_nonnegative_float,
        default=DEFAULT_WORKER_STARTUP_STAGGER,
        metavar="SECONDS",
        help="Delay between starting browser workers (default: 1).",
    )
    parser.add_argument(
        "--max-worker-restarts",
        type=_nonnegative_int,
        default=DEFAULT_MAX_WORKER_RESTARTS,
        metavar="N",
        help="Maximum restarts allowed for each logical worker (default: 2).",
    )
    parser.add_argument(
        "--shutdown-grace-seconds",
        type=_nonnegative_float,
        default=DEFAULT_SHUTDOWN_GRACE_SECONDS,
        metavar="SECONDS",
        help=(
            "Grace period for workers to stop before terminate/kill escalation "
            "during SIGINT or SIGTERM shutdown (default: 10)."
        ),
    )
    parser.add_argument(
        "--global-rate-limit-cooldown",
        type=_nonnegative_float,
        default=DEFAULT_GLOBAL_RATE_LIMIT_COOLDOWN,
        metavar="SECONDS",
        help="Pause all new job assignments after a rate limit (default: 180).",
    )
    parser.add_argument(
        "--auth-failures-before-abort",
        type=_positive_int,
        default=DEFAULT_AUTH_FAILURES_BEFORE_ABORT,
        metavar="N",
        help="Open the global authentication circuit after N failures (default: 2).",
    )
    parser.add_argument(
        "--rate-limit-failures-before-abort",
        type=_nonnegative_int,
        default=DEFAULT_RATE_LIMIT_FAILURES_BEFORE_ABORT,
        metavar="N",
        help="Open the severe rate-limit circuit after N events; 0 disables (default: 6).",
    )
    parser.add_argument(
        "--rate-limit-window-seconds",
        type=_positive_float,
        default=DEFAULT_RATE_LIMIT_WINDOW_SECONDS,
        metavar="SECONDS",
        help="Observation window used by adaptive rate-limit control (default: 300).",
    )
    parser.add_argument(
        "--adaptive-concurrency",
        action="store_true",
        help="Enable automatic active-worker scale-down and cautious recovery.",
    )
    parser.add_argument(
        "--adaptive-scale-down-threshold",
        type=_positive_int,
        default=DEFAULT_ADAPTIVE_SCALE_DOWN_THRESHOLD,
        metavar="N",
        help="Rate-limit events in the window before reducing active workers (default: 2).",
    )
    parser.add_argument(
        "--adaptive-recovery-seconds",
        type=_positive_float,
        default=DEFAULT_ADAPTIVE_RECOVERY_SECONDS,
        metavar="SECONDS",
        help="Rate-limit-free interval before increasing active workers (default: 900).",
    )
    parser.add_argument(
        "--worker-max-jobs",
        type=_nonnegative_int,
        default=DEFAULT_WORKER_MAX_JOBS,
        metavar="N",
        help="Recycle a worker after N completed jobs; 0 disables (default: 20).",
    )
    parser.add_argument(
        "--worker-memory-limit-mb",
        type=_nonnegative_float,
        default=DEFAULT_WORKER_MEMORY_LIMIT_MB,
        metavar="MB",
        help="Recycle an idle worker after exceeding this RSS; 0 disables.",
    )
    parser.add_argument("--network-retries", type=_nonnegative_int, default=DEFAULT_NETWORK_RETRIES, metavar="N")
    parser.add_argument("--browser-retries", type=_nonnegative_int, default=DEFAULT_BROWSER_RETRIES, metavar="N")
    parser.add_argument("--download-retries", type=_nonnegative_int, default=DEFAULT_DOWNLOAD_RETRIES, metavar="N")
    parser.add_argument("--rate-limit-retries", type=_nonnegative_int, default=DEFAULT_RATE_LIMIT_RETRIES, metavar="N")
    parser.add_argument("--retry-backoff-base", type=_nonnegative_float, default=DEFAULT_RETRY_BACKOFF_BASE, metavar="SECONDS")
    parser.add_argument("--retry-backoff-cap", type=_nonnegative_float, default=DEFAULT_RETRY_BACKOFF_CAP, metavar="SECONDS")
    parser.add_argument(
        "--retry-jitter-ratio",
        type=float,
        default=DEFAULT_RETRY_JITTER_RATIO,
        metavar="RATIO",
        help="Backoff jitter ratio from 0 to 1 (default: 0.20).",
    )
    parser.add_argument(
        "--runtime-dir",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "Managed runtime root for per-run and per-worker profiles, downloads, logs, and diagnostics "
            "(default: .runtime or CHATGPT_RUNTIME_DIR)."
        ),
    )
    parser.add_argument(
        "--profile-snapshot",
        default=None,
        metavar="ID_OR_PATH",
        help=(
            "Restore each managed worker profile from this authenticated session snapshot id or path "
            "(equivalent to CHATGPT_PROFILE_SNAPSHOT)."
        ),
    )
    parser.add_argument(
        "--keep-runtime",
        action="store_true",
        help=(
            "Keep managed run directories after successful completion for diagnostics. "
            "By default successful managed runtimes are deleted and failed ones are retained."
        ),
    )


def validate_runtime_settings(
    browser_provider: str = DEFAULT_BROWSER_PROVIDER,
    parallel_runs: int = DEFAULT_PARALLEL_RUNS,
    *,
    runtime_dir: Path | str | None = None,
    profile_snapshot: str | Path | None = None,
    keep_runtime: bool = False,
    worker_heartbeat_interval: float = DEFAULT_WORKER_HEARTBEAT_INTERVAL,
    worker_timeout: float = DEFAULT_WORKER_TIMEOUT,
    worker_ready_timeout: float = DEFAULT_WORKER_READY_TIMEOUT,
    worker_startup_stagger: float = DEFAULT_WORKER_STARTUP_STAGGER,
    max_worker_restarts: int = DEFAULT_MAX_WORKER_RESTARTS,
    shutdown_grace_seconds: float = DEFAULT_SHUTDOWN_GRACE_SECONDS,
    global_rate_limit_cooldown: float = DEFAULT_GLOBAL_RATE_LIMIT_COOLDOWN,
    auth_failures_before_abort: int = DEFAULT_AUTH_FAILURES_BEFORE_ABORT,
    rate_limit_failures_before_abort: int = DEFAULT_RATE_LIMIT_FAILURES_BEFORE_ABORT,
    rate_limit_window_seconds: float = DEFAULT_RATE_LIMIT_WINDOW_SECONDS,
    adaptive_concurrency: bool = False,
    adaptive_scale_down_threshold: int = DEFAULT_ADAPTIVE_SCALE_DOWN_THRESHOLD,
    adaptive_recovery_seconds: float = DEFAULT_ADAPTIVE_RECOVERY_SECONDS,
    worker_max_jobs: int = DEFAULT_WORKER_MAX_JOBS,
    worker_memory_limit_mb: float = DEFAULT_WORKER_MEMORY_LIMIT_MB,
    network_retries: int = DEFAULT_NETWORK_RETRIES,
    browser_retries: int = DEFAULT_BROWSER_RETRIES,
    download_retries: int = DEFAULT_DOWNLOAD_RETRIES,
    rate_limit_retries: int = DEFAULT_RATE_LIMIT_RETRIES,
    retry_backoff_base: float = DEFAULT_RETRY_BACKOFF_BASE,
    retry_backoff_cap: float = DEFAULT_RETRY_BACKOFF_CAP,
    retry_jitter_ratio: float = DEFAULT_RETRY_JITTER_RATIO,
) -> RuntimeSettings:
    """Validate the Level 6 process runtime contract and return normalized settings."""
    if browser_provider not in SUPPORTED_BROWSER_PROVIDERS:
        supported = ", ".join(SUPPORTED_BROWSER_PROVIDERS)
        raise RuntimeConfigurationError(
            f"Unsupported browser provider '{browser_provider}'. Supported in Level 6: {supported}."
        )
    if parallel_runs < 1:
        raise RuntimeConfigurationError("parallel_runs must be at least 1.")
    if parallel_runs > MAX_PARALLEL_RUNS:
        raise RuntimeConfigurationError(
            f"parallel_runs must not exceed {MAX_PARALLEL_RUNS}."
        )
    for name, value in {
        "worker_heartbeat_interval": worker_heartbeat_interval,
        "worker_timeout": worker_timeout,
        "worker_ready_timeout": worker_ready_timeout,
        "worker_startup_stagger": worker_startup_stagger,
        "shutdown_grace_seconds": shutdown_grace_seconds,
        "global_rate_limit_cooldown": global_rate_limit_cooldown,
        "rate_limit_window_seconds": rate_limit_window_seconds,
        "adaptive_recovery_seconds": adaptive_recovery_seconds,
        "worker_memory_limit_mb": worker_memory_limit_mb,
        "retry_backoff_base": retry_backoff_base,
        "retry_backoff_cap": retry_backoff_cap,
        "retry_jitter_ratio": retry_jitter_ratio,
    }.items():
        try:
            finite = math.isfinite(value)
        except TypeError as exc:
            raise RuntimeConfigurationError(f"{name} must be a number.") from exc
        if not finite:
            raise RuntimeConfigurationError(f"{name} must be finite.")
    if worker_heartbeat_interval <= 0:
        raise RuntimeConfigurationError("worker_heartbeat_interval must be positive.")
    if worker_timeout <= worker_heartbeat_interval:
        raise RuntimeConfigurationError(
            "worker_timeout must be greater than worker_heartbeat_interval."
        )
    if worker_ready_timeout <= 0:
        raise RuntimeConfigurationError("worker_ready_timeout must be positive.")
    if worker_startup_stagger < 0:
        raise RuntimeConfigurationError("worker_startup_stagger must not be negative.")
    if max_worker_restarts < 0:
        raise RuntimeConfigurationError("max_worker_restarts must not be negative.")
    if shutdown_grace_seconds < 0:
        raise RuntimeConfigurationError("shutdown_grace_seconds must not be negative.")
    for name, value in {
        "global_rate_limit_cooldown": global_rate_limit_cooldown,
        "worker_memory_limit_mb": worker_memory_limit_mb,
        "retry_backoff_base": retry_backoff_base,
        "retry_backoff_cap": retry_backoff_cap,
    }.items():
        if value < 0:
            raise RuntimeConfigurationError(f"{name} must not be negative.")
    if auth_failures_before_abort < 1:
        raise RuntimeConfigurationError("auth_failures_before_abort must be at least 1.")
    if rate_limit_failures_before_abort < 0:
        raise RuntimeConfigurationError("rate_limit_failures_before_abort must not be negative.")
    if rate_limit_window_seconds <= 0 or adaptive_recovery_seconds <= 0:
        raise RuntimeConfigurationError("rate-limit windows and adaptive recovery must be positive.")
    if adaptive_scale_down_threshold < 1:
        raise RuntimeConfigurationError("adaptive_scale_down_threshold must be at least 1.")
    for name, value in {
        "worker_max_jobs": worker_max_jobs,
        "network_retries": network_retries,
        "browser_retries": browser_retries,
        "download_retries": download_retries,
        "rate_limit_retries": rate_limit_retries,
    }.items():
        if value < 0:
            raise RuntimeConfigurationError(f"{name} must not be negative.")
    if not 0 <= retry_jitter_ratio <= 1:
        raise RuntimeConfigurationError("retry_jitter_ratio must be between 0 and 1.")
    normalized_runtime_dir = (
        Path(runtime_dir).expanduser().resolve() if runtime_dir is not None else None
    )
    normalized_snapshot = str(profile_snapshot).strip() if profile_snapshot is not None else None
    if normalized_snapshot == "":
        normalized_snapshot = None
    return RuntimeSettings(
        browser_provider=browser_provider,
        parallel_runs=parallel_runs,
        runtime_dir=normalized_runtime_dir,
        profile_snapshot=normalized_snapshot,
        keep_runtime=bool(keep_runtime),
        worker_heartbeat_interval=float(worker_heartbeat_interval),
        worker_timeout=float(worker_timeout),
        worker_ready_timeout=float(worker_ready_timeout),
        worker_startup_stagger=float(worker_startup_stagger),
        max_worker_restarts=int(max_worker_restarts),
        shutdown_grace_seconds=float(shutdown_grace_seconds),
        global_rate_limit_cooldown=float(global_rate_limit_cooldown),
        auth_failures_before_abort=int(auth_failures_before_abort),
        rate_limit_failures_before_abort=int(rate_limit_failures_before_abort),
        rate_limit_window_seconds=float(rate_limit_window_seconds),
        adaptive_concurrency=bool(adaptive_concurrency),
        adaptive_scale_down_threshold=int(adaptive_scale_down_threshold),
        adaptive_recovery_seconds=float(adaptive_recovery_seconds),
        worker_max_jobs=int(worker_max_jobs),
        worker_memory_limit_mb=float(worker_memory_limit_mb),
        network_retries=int(network_retries),
        browser_retries=int(browser_retries),
        download_retries=int(download_retries),
        rate_limit_retries=int(rate_limit_retries),
        retry_backoff_base=float(retry_backoff_base),
        retry_backoff_cap=float(retry_backoff_cap),
        retry_jitter_ratio=float(retry_jitter_ratio),
    )


def settings_from_namespace(args: argparse.Namespace) -> RuntimeSettings:
    return validate_runtime_settings(
        browser_provider=getattr(args, "browser_provider", DEFAULT_BROWSER_PROVIDER),
        parallel_runs=getattr(args, "parallel_runs", DEFAULT_PARALLEL_RUNS),
        runtime_dir=getattr(args, "runtime_dir", None),
        profile_snapshot=getattr(args, "profile_snapshot", None),
        keep_runtime=getattr(args, "keep_runtime", False),
        worker_heartbeat_interval=getattr(
            args, "worker_heartbeat_interval", DEFAULT_WORKER_HEARTBEAT_INTERVAL
        ),
        worker_timeout=getattr(args, "worker_timeout", DEFAULT_WORKER_TIMEOUT),
        worker_ready_timeout=getattr(
            args, "worker_ready_timeout", DEFAULT_WORKER_READY_TIMEOUT
        ),
        worker_startup_stagger=getattr(
            args, "worker_startup_stagger", DEFAULT_WORKER_STARTUP_STAGGER
        ),
        max_worker_restarts=getattr(
            args, "max_worker_restarts", DEFAULT_MAX_WORKER_RESTARTS
        ),
        shutdown_grace_seconds=getattr(
            args, "shutdown_grace_seconds", DEFAULT_SHUTDOWN_GRACE_SECONDS
        ),
        global_rate_limit_cooldown=getattr(args, "global_rate_limit_cooldown", DEFAULT_GLOBAL_RATE_LIMIT_COOLDOWN),
        auth_failures_before_abort=getattr(args, "auth_failures_before_abort", DEFAULT_AUTH_FAILURES_BEFORE_ABORT),
        rate_limit_failures_before_abort=getattr(args, "rate_limit_failures_before_abort", DEFAULT_RATE_LIMIT_FAILURES_BEFORE_ABORT),
        rate_limit_window_seconds=getattr(args, "rate_limit_window_seconds", DEFAULT_RATE_LIMIT_WINDOW_SECONDS),
        adaptive_concurrency=getattr(args, "adaptive_concurrency", False),
        adaptive_scale_down_threshold=getattr(args, "adaptive_scale_down_threshold", DEFAULT_ADAPTIVE_SCALE_DOWN_THRESHOLD),
        adaptive_recovery_seconds=getattr(args, "adaptive_recovery_seconds", DEFAULT_ADAPTIVE_RECOVERY_SECONDS),
        worker_max_jobs=getattr(args, "worker_max_jobs", DEFAULT_WORKER_MAX_JOBS),
        worker_memory_limit_mb=getattr(args, "worker_memory_limit_mb", DEFAULT_WORKER_MEMORY_LIMIT_MB),
        network_retries=getattr(args, "network_retries", DEFAULT_NETWORK_RETRIES),
        browser_retries=getattr(args, "browser_retries", DEFAULT_BROWSER_RETRIES),
        download_retries=getattr(args, "download_retries", DEFAULT_DOWNLOAD_RETRIES),
        rate_limit_retries=getattr(args, "rate_limit_retries", DEFAULT_RATE_LIMIT_RETRIES),
        retry_backoff_base=getattr(args, "retry_backoff_base", DEFAULT_RETRY_BACKOFF_BASE),
        retry_backoff_cap=getattr(args, "retry_backoff_cap", DEFAULT_RETRY_BACKOFF_CAP),
        retry_jitter_ratio=getattr(args, "retry_jitter_ratio", DEFAULT_RETRY_JITTER_RATIO),
    )


def apply_runtime_environment(settings: RuntimeSettings) -> None:
    """Apply explicit Level 6 CLI settings to the profile runtime environment.

    Unspecified values deliberately leave existing environment configuration
    untouched so shell-level deployments remain backward compatible.
    """
    if settings.runtime_dir is not None:
        os.environ["CHATGPT_RUNTIME_DIR"] = str(settings.runtime_dir)
    if settings.profile_snapshot is not None:
        os.environ["CHATGPT_PROFILE_SNAPSHOT"] = settings.profile_snapshot
    if settings.keep_runtime:
        os.environ["CHATGPT_RUNTIME_RETENTION"] = "keep-all"
