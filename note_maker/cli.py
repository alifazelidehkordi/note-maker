from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shutil
import sys
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
import time
from importlib import metadata
from pathlib import Path
from typing import Any

from .compat import activate_legacy_imports
from .config import ConfigError, ResolvedConfig, discover_config_path, resolve_config
from .project import (
    ProjectInitSettings,
    default_config_path,
    load_session_aliases,
    resolve_session_reference,
    set_session_alias,
    validate_session_alias,
    write_project_config,
)
from .interactive import InteractiveCancelled, build_interactive_plan


def _version() -> str:
    try:
        return metadata.version("note-maker")
    except metadata.PackageNotFoundError:
        version_file = Path(__file__).resolve().parents[1] / "VERSION"
        return version_file.read_text(encoding="utf-8").strip() if version_file.is_file() else "0"


def _json_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _set_overrides(values: list[str]) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for item in values:
        key, separator, raw = item.partition("=")
        key = key.strip().replace("-", "_")
        if not separator or not key:
            raise ConfigError(f"--set expects KEY=VALUE, received {item!r}.")
        overrides[key] = _json_value(raw.strip())
    return overrides


def _namespace_overrides(args: argparse.Namespace, names: tuple[str, ...]) -> dict[str, Any]:
    overrides = {
        name: getattr(args, name)
        for name in names
        if hasattr(args, name) and getattr(args, name) is not None
    }
    overrides.update(_set_overrides(getattr(args, "set_values", [])))
    return overrides


def _add_runtime_shortcuts(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--browser-provider", choices=("selenium", "patchright"), default=None)
    parser.add_argument("--parallel-runs", type=int, default=None)
    parser.add_argument("--runtime-dir", type=Path, default=None)
    parser.add_argument(
        "--profile-snapshot",
        default=None,
        help="Immutable snapshot ID/path or a browser session alias from [sessions].",
    )
    parser.add_argument("--keep-runtime", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument(
        "--adaptive-concurrency", action=argparse.BooleanOptionalAction, default=None
    )
    parser.add_argument("--global-rate-limit-cooldown", type=float, default=None)
    parser.add_argument("--network-retries", type=int, default=None)
    parser.add_argument("--browser-retries", type=int, default=None)
    parser.add_argument("--download-retries", type=int, default=None)
    parser.add_argument("--rate-limit-retries", type=int, default=None)
    parser.add_argument(
        "--set",
        dest="set_values",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Override any supported configuration key; may be repeated.",
    )


def _add_shared_run_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--prompt", type=Path, default=None)
    parser.add_argument("--output-ext", choices=("opml", "md", "markdown"), default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--download-timeout", type=int, default=None)
    parser.add_argument("--close-delay", type=int, default=None)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--overwrite", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--retry-failed", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--adopt-existing", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--save-diagnostics", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--save-page-source", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--keep-browser", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--no-warm-up", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--dry-run", action="store_true")
    _add_runtime_shortcuts(parser)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="note-maker",
        description="Unified configuration, validation, diagnostics, and batch execution.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {_version()}")
    parser.add_argument("--config", type=Path, default=None, help="Path to note-maker.toml.")
    parser.add_argument(
        "--profile",
        default=None,
        help="Named configuration preset from [profiles.*], not a browser session.",
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON where supported."
    )

    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="Create reusable project settings in note-maker.toml.")
    init.add_argument("--input-dir", type=Path, default=Path("inputs"))
    init.add_argument("--output-dir", type=Path, default=Path("outputs/notes"))
    init.add_argument("--prompt", type=Path, default=Path("prompts/prompt-mind-map.md"))
    init.add_argument(
        "--format",
        "--output-ext",
        dest="output_ext",
        choices=("opml", "md", "markdown"),
        default="md",
    )
    init.add_argument("--browser-provider", choices=("selenium", "patchright"), default="selenium")
    init.add_argument("--workers", type=int, default=1, help="Saved worker count for this project.")
    init.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing project configuration instead of refusing to overwrite it.",
    )

    login = commands.add_parser(
        "login",
        help="Open dedicated Chromium and save a reusable browser session alias.",
    )
    login.add_argument("--name", default="default", help="Stable human name for the new session.")

    profiles = commands.add_parser(
        "profiles",
        help="List or inspect reusable browser sessions; configuration presets use --profile.",
    )
    profile_commands = profiles.add_subparsers(dest="profiles_command", required=True)
    profile_commands.add_parser("list", help="List session aliases and immutable snapshots.")
    profile_inspect = profile_commands.add_parser(
        "inspect", help="Inspect a session alias or immutable snapshot without opening a browser."
    )
    profile_inspect.add_argument("reference")

    doctor = commands.add_parser(
        "doctor", help="Check the resolved workflow, paths, selected provider, and session availability."
    )
    doctor.add_argument(
        "--strict", action="store_true", help="Treat missing optional system browsers as errors."
    )
    doctor.add_argument(
        "--target",
        choices=("pdf", "markdown"),
        default="pdf",
        help="Workflow configuration to diagnose (default: pdf).",
    )

    status = commands.add_parser("status", help="Show or watch live batch status.")
    status.add_argument(
        "--summary",
        type=Path,
        default=None,
        help="Read a completed batch summary instead of the live status snapshot.",
    )
    status.add_argument(
        "--snapshot",
        type=Path,
        default=Path("logs/last_status.json"),
        help="Live status snapshot path (default: logs/last_status.json).",
    )
    status.add_argument("--watch", action="store_true", help="Refresh until the run is terminal.")
    status.add_argument(
        "--interval",
        type=float,
        default=1.0,
        metavar="SECONDS",
        help="Polling interval for --watch (default: 1.0).",
    )

    validate = commands.add_parser(
        "validate", help="Validate generated Markdown or OPML artifacts."
    )
    validate.add_argument("paths", nargs="+", type=Path)
    validate.add_argument("--extension", choices=("md", "markdown", "opml"), default=None)

    config = commands.add_parser(
        "config", help="Display the resolved configuration and source precedence."
    )
    config.add_argument("target", choices=("pdf", "markdown"), default="pdf", nargs="?")
    config.add_argument("--markdown-file", type=Path, default=None)
    _add_runtime_shortcuts(config)

    interactive = commands.add_parser(
        "interactive",
        help="Guide input, workflow, prompt, output, and runtime selection interactively.",
    )
    interactive.add_argument(
        "--dry-run",
        action="store_true",
        help="Review the interactive configuration without running the browser pipeline.",
    )

    run = commands.add_parser("run", help="Run a configured batch.")
    run_commands = run.add_subparsers(dest="run_command", required=True)

    pdf = run_commands.add_parser(
        "pdf", help="Process PDF, DOCX, or Markdown files from a directory."
    )
    pdf.add_argument("--input-dir", type=Path, default=None)
    pdf.add_argument("--max-attempts", type=int, default=None)
    _add_shared_run_arguments(pdf)

    markdown = run_commands.add_parser(
        "markdown", help="Process each level-2 section in one Markdown file."
    )
    markdown.add_argument("--markdown-file", type=Path, default=None)
    markdown.add_argument("--sections", default=None)
    markdown.add_argument("--max-section-attempts", type=int, default=None)
    markdown.add_argument("--chrome-profile-dir", type=Path, default=None)
    _add_shared_run_arguments(markdown)

    return parser


def _print(payload: Any, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
        return
    if isinstance(payload, dict):
        for key, value in payload.items():
            print(f"{key}: {value}")
    else:
        print(payload)


def _project_config_path(args: argparse.Namespace, *, require_existing: bool) -> Path:
    selected = discover_config_path(args.config)
    path = selected if selected is not None else default_config_path()
    if require_existing and not path.is_file():
        raise ConfigError(f"Configuration file does not exist: {path}. Run `note-maker init` first.")
    return path


def _profile_services(project_root: Path) -> tuple[Any, type[Any], type[Exception]]:
    activate_legacy_imports()
    from browser_runtime.errors import ProfileSnapshotError  # type: ignore[import-not-found]
    from browser_runtime.login_bootstrap import LoginBootstrapper  # type: ignore[import-not-found]
    from browser_runtime.profile_manager import ProfileManager  # type: ignore[import-not-found]

    return ProfileManager.from_environment(project_root), LoginBootstrapper, ProfileSnapshotError


def _init(args: argparse.Namespace) -> int:
    config_path = _project_config_path(args, require_existing=False)
    settings = ProjectInitSettings(
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        prompt=args.prompt,
        output_ext=args.output_ext,
        browser_provider=args.browser_provider,
        parallel_runs=args.workers,
    )
    write_project_config(config_path, settings, force=args.force)
    resolved = resolve_config("pdf", config_path=config_path, environ={})
    payload = {
        "config_path": str(config_path),
        "input_dir": str(resolved.values["input_dir"]),
        "output_dir": str(resolved.values["output_dir"]),
        "prompt": str(resolved.values["prompt"]),
        "output_ext": resolved.values["output_ext"],
        "browser_provider": resolved.runtime.browser_provider,
        "parallel_runs": resolved.runtime.parallel_runs,
    }
    _print(payload, as_json=args.json)
    return 0


def _login(args: argparse.Namespace) -> int:
    config_path = _project_config_path(args, require_existing=True)
    name = validate_session_alias(args.name)
    project_root = config_path.parent
    manager, bootstrap_type, _ = _profile_services(project_root)
    profile_dir = (project_root / "chrome_profile_login" / name).resolve()

    print(
        "A dedicated Chromium window will open. Complete ChatGPT login, then close that browser. "
        "The saved cookie markers are local evidence only; server-session validity is not assumed.",
        file=sys.stderr,
    )
    bootstrap = bootstrap_type(profile_manager=manager)
    bootstrap.open_login_browser(profile_dir, wait=True)
    snapshot = bootstrap.create_snapshot(profile_dir, name=name)
    set_session_alias(config_path, name, snapshot.snapshot_id)
    payload = {
        "name": name,
        "snapshot_id": snapshot.snapshot_id,
        "snapshot": str(snapshot.path),
        "config_path": str(config_path),
        "authentication_evidence": bool(snapshot.auth_markers),
        "server_session_verified": False,
    }
    _print(payload, as_json=args.json)
    return 0


def _snapshot_payload(snapshot: Any, *, aliases: list[str]) -> dict[str, Any]:
    return {
        "snapshot_id": snapshot.snapshot_id,
        "aliases": aliases,
        "path": str(snapshot.path),
        "created_at": snapshot.created_at,
        "portable": bool(snapshot.portable),
        "authentication": {
            "cookie_markers_present": bool(snapshot.auth_markers),
            "cookie_markers": list(snapshot.auth_markers),
            "server_session_verified": False,
            "detail": "Cookie markers are local authentication evidence, not proof of a currently valid server session.",
        },
    }


def _profiles(args: argparse.Namespace) -> int:
    config_path = _project_config_path(args, require_existing=True)
    aliases = load_session_aliases(config_path)
    manager, _, snapshot_error = _profile_services(config_path.parent)

    if args.profiles_command == "list":
        snapshots: list[dict[str, Any]] = []
        alias_by_snapshot: dict[str, list[str]] = {}
        for alias, snapshot_id in aliases.items():
            alias_by_snapshot.setdefault(snapshot_id, []).append(alias)
        if manager.snapshot_root.is_dir():
            for path in sorted(manager.snapshot_root.iterdir(), key=lambda item: item.name):
                if not path.is_dir():
                    continue
                try:
                    snapshot = manager.load_snapshot(path.name)
                except snapshot_error as exc:
                    snapshots.append(
                        {
                            "snapshot_id": path.name,
                            "aliases": sorted(alias_by_snapshot.get(path.name, [])),
                            "valid": False,
                            "error": str(exc),
                        }
                    )
                    continue
                entry = _snapshot_payload(
                    snapshot,
                    aliases=sorted(alias_by_snapshot.get(snapshot.snapshot_id, [])),
                )
                entry["valid"] = True
                snapshots.append(entry)
        sessions = [
            {
                "name": alias,
                "snapshot_id": snapshot_id,
                "available": any(
                    item.get("snapshot_id") == snapshot_id and item.get("valid") is True
                    for item in snapshots
                ),
            }
            for alias, snapshot_id in sorted(aliases.items())
        ]
        payload = {
            "config_path": str(config_path),
            "sessions": sessions,
            "snapshots": snapshots,
            "configuration_presets_are_separate": True,
        }
        if args.json:
            _print(payload, as_json=True)
        else:
            print("Browser sessions (aliases -> immutable snapshots):")
            if not sessions:
                print("  none")
            for session in sessions:
                availability = "available" if session["available"] else "missing"
                print(f"  {session['name']} -> {session['snapshot_id']} ({availability})")
            print("Configuration presets are separate and are selected with global --profile.")
        return 0

    alias, snapshot_reference = resolve_session_reference(config_path, args.reference)
    try:
        snapshot = manager.load_snapshot(snapshot_reference)
    except snapshot_error as exc:
        raise ConfigError(str(exc)) from exc
    payload = _snapshot_payload(snapshot, aliases=[alias] if alias is not None else [])
    payload["requested_reference"] = args.reference
    payload["resolved_from_alias"] = alias
    _print(payload, as_json=args.json)
    return 0


def _existing_writable_directory(path: Path) -> tuple[bool, str]:
    path = path.expanduser().resolve()
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    if not candidate.exists():
        return False, f"no existing parent for {path}"
    if not candidate.is_dir():
        return False, f"nearest existing path is not a directory: {candidate}"
    writable = os.access(candidate, os.W_OK)
    return writable, f"{path} (nearest existing parent: {candidate})"


def _doctor(args: argparse.Namespace) -> int:
    checks: list[dict[str, Any]] = [
        {
            "name": "python",
            "ok": sys.version_info >= (3, 10),
            "detail": platform.python_version(),
        }
    ]
    resolved: ResolvedConfig | None = None
    try:
        resolved = resolve_config(
            args.target,
            config_path=args.config,
            profile=args.profile,
        )
        checks.append(
            {
                "name": "configuration",
                "ok": True,
                "detail": str(resolved.config_path or "built-in defaults"),
            }
        )
    except ConfigError as exc:
        checks.append({"name": "configuration", "ok": False, "detail": str(exc)})

    provider = resolved.runtime.browser_provider if resolved is not None else None
    required_modules = {
        "selenium": ("selenium", "pyautogui", "pyperclip"),
        "patchright": ("patchright",),
    }.get(provider, ())
    for module in required_modules:
        present = importlib.util.find_spec(module) is not None
        checks.append(
            {
                "name": f"dependency:{module}",
                "ok": present,
                "detail": "installed" if present else f"missing for selected provider {provider}",
            }
        )

    browsers = {
        "chrome": shutil.which("google-chrome") or shutil.which("google-chrome-stable"),
        "chromium": shutil.which("chromium") or shutil.which("chromium-browser"),
        "edge": shutil.which("microsoft-edge") or shutil.which("microsoft-edge-stable"),
    }
    system_browser = next((path for path in browsers.values() if path), None)
    if provider == "selenium":
        checks.append(
            {
                "name": "browser:selenium",
                "ok": system_browser is not None or not args.strict,
                "detail": system_browser
                or "no system Chromium found; Selenium runtime startup was not launched by doctor",
            }
        )
    elif provider == "patchright":
        patchright_present = importlib.util.find_spec("patchright") is not None
        checks.append(
            {
                "name": "browser:patchright",
                "ok": patchright_present,
                "detail": (
                    "provider package available; browser startup was not launched by doctor"
                    if patchright_present
                    else "provider package missing"
                ),
            }
        )

    if resolved is not None:
        values = resolved.values
        if args.target == "pdf":
            source = values.get("input_dir")
            source_ok = isinstance(source, Path) and source.is_dir()
            checks.append(
                {
                    "name": "input",
                    "ok": source_ok,
                    "detail": str(source) if source_ok else f"input directory unavailable: {source}",
                }
            )
        else:
            source = values.get("markdown_file")
            source_ok = isinstance(source, Path) and source.is_file()
            checks.append(
                {
                    "name": "input",
                    "ok": source_ok,
                    "detail": str(source) if source_ok else f"Markdown input unavailable: {source}",
                }
            )

        prompt = values.get("prompt")
        prompt_ok = isinstance(prompt, Path) and prompt.is_file()
        checks.append(
            {
                "name": "prompt",
                "ok": prompt_ok,
                "detail": str(prompt) if prompt_ok else f"prompt file unavailable: {prompt}",
            }
        )

        output = values.get("output_dir")
        if isinstance(output, Path):
            output_ok, output_detail = _existing_writable_directory(output)
        else:
            output_ok, output_detail = False, f"invalid output directory: {output}"
        checks.append({"name": "output", "ok": output_ok, "detail": output_detail})

        snapshot_reference = resolved.runtime.profile_snapshot
        if snapshot_reference:
            project_root = resolved.config_path.parent if resolved.config_path else Path.cwd()
            manager, _, snapshot_error = _profile_services(project_root)
            try:
                snapshot = manager.load_snapshot(snapshot_reference)
            except snapshot_error as exc:
                checks.append(
                    {
                        "name": "session",
                        "ok": False,
                        "detail": f"configured snapshot unavailable: {exc}",
                    }
                )
            else:
                marker_detail = (
                    f"{len(snapshot.auth_markers)} local cookie marker(s) present"
                    if snapshot.auth_markers
                    else "no local authentication cookie markers recorded"
                )
                checks.append(
                    {
                        "name": "session",
                        "ok": True,
                        "detail": (
                            f"snapshot {snapshot.snapshot_id} available; {marker_detail}; "
                            "live server session not verified"
                        ),
                    }
                )
        else:
            checks.append(
                {
                    "name": "session",
                    "ok": True,
                    "detail": "no reusable snapshot configured; live authentication was not checked",
                }
            )

    payload = {"ok": all(item["ok"] for item in checks), "checks": checks}
    if args.json:
        _print(payload, as_json=True)
    else:
        for item in checks:
            marker = "OK" if item["ok"] else "FAIL"
            print(f"[{marker}] {item['name']}: {item['detail']}")
    return 0 if payload["ok"] else 1


def _read_summary(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Batch summary must contain a JSON object: {path}")
    return payload


def _status(args: argparse.Namespace) -> int:
    if args.interval <= 0:
        print("--interval must be positive.", file=sys.stderr)
        return 2

    if args.summary is not None:
        path = args.summary.expanduser().resolve()
        if not path.is_file():
            print(f"No batch summary found at {path}.", file=sys.stderr)
            return 1
        try:
            payload = _read_summary(path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            print(f"Could not read batch summary {path}: {exc}", file=sys.stderr)
            return 1
        if args.json:
            _print(payload, as_json=True)
        else:
            fields = (
                "mode",
                "run_id",
                "successes",
                "failures",
                "output_dir",
                "browser_provider",
                "parallel_runs",
                "interrupted",
            )
            _print({key: payload.get(key) for key in fields if key in payload}, as_json=False)
        return 0

    snapshot_path = args.snapshot.expanduser().resolve()
    if not snapshot_path.is_file():
        fallback = Path("logs/last_batch_summary.json").expanduser().resolve()
        if not args.watch and fallback.is_file():
            try:
                payload = _read_summary(fallback)
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                print(f"Could not read batch summary {fallback}: {exc}", file=sys.stderr)
                return 1
            if args.json:
                _print(payload, as_json=True)
            else:
                fields = (
                    "mode",
                    "run_id",
                    "successes",
                    "failures",
                    "output_dir",
                    "browser_provider",
                    "parallel_runs",
                    "interrupted",
                )
                _print({key: payload.get(key) for key in fields if key in payload}, as_json=False)
            return 0
        print(f"No live status snapshot found at {snapshot_path}.", file=sys.stderr)
        return 1

    activate_legacy_imports()
    from parallel_runtime.status import (  # type: ignore[import-not-found]
        format_status_snapshot,
        is_terminal_snapshot,
        read_status_snapshot,
    )

    while True:
        try:
            payload = read_status_snapshot(snapshot_path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            print(f"Could not read live status {snapshot_path}: {exc}", file=sys.stderr)
            return 1
        if args.json:
            if args.watch:
                print(json.dumps(payload, sort_keys=True, ensure_ascii=False), flush=True)
            else:
                _print(payload, as_json=True)
        else:
            if args.watch and sys.stdout.isatty():
                print("\x1b[2J\x1b[H", end="")
            print(format_status_snapshot(payload), flush=True)
        if not args.watch or is_terminal_snapshot(payload):
            return 0
        time.sleep(args.interval)


def _validate(args: argparse.Namespace) -> int:
    activate_legacy_imports()
    from artifact_validation import validate_artifact  # type: ignore[import-not-found]

    results: list[dict[str, Any]] = []
    failed = False
    forced = f".{args.extension}" if args.extension else None
    for raw_path in args.paths:
        path = raw_path.expanduser().resolve()
        expected = {forced or path.suffix.lower()}
        result = validate_artifact(path, expected)
        entry = {
            "path": str(path),
            "valid": result.valid,
            "errors": list(result.errors),
        }
        results.append(entry)
        failed = failed or not result.valid
    if args.json:
        _print({"valid": not failed, "artifacts": results}, as_json=True)
    else:
        for item in results:
            marker = "VALID" if item["valid"] else "INVALID"
            print(f"[{marker}] {item['path']}")
            for error in item["errors"]:
                print(f"  - {error}")
    return 2 if failed else 0


def _resolved_for_config(args: argparse.Namespace) -> ResolvedConfig:
    overrides = _namespace_overrides(
        args,
        (
            "markdown_file",
            "browser_provider",
            "parallel_runs",
            "runtime_dir",
            "profile_snapshot",
            "keep_runtime",
            "adaptive_concurrency",
            "global_rate_limit_cooldown",
            "network_retries",
            "browser_retries",
            "download_retries",
            "rate_limit_retries",
        ),
    )
    return resolve_config(
        args.target,
        config_path=args.config,
        profile=args.profile,
        cli_overrides=overrides,
    )


def _config(args: argparse.Namespace) -> int:
    resolved = _resolved_for_config(args)
    _print(resolved.as_dict(), as_json=args.json)
    return 0


_RUN_KEYS = (
    "input_dir",
    "markdown_file",
    "output_dir",
    "prompt",
    "output_ext",
    "sections",
    "model",
    "limit",
    "max_attempts",
    "max_section_attempts",
    "download_timeout",
    "close_delay",
    "manifest",
    "overwrite",
    "resume",
    "retry_failed",
    "adopt_existing",
    "save_diagnostics",
    "save_page_source",
    "keep_browser",
    "no_warm_up",
    "chrome_profile_dir",
    "browser_provider",
    "parallel_runs",
    "runtime_dir",
    "profile_snapshot",
    "keep_runtime",
    "adaptive_concurrency",
    "global_rate_limit_cooldown",
    "network_retries",
    "browser_retries",
    "download_retries",
    "rate_limit_retries",
)


def _validate_output_target(path: Path) -> None:
    if path.exists() and not path.is_dir():
        raise ConfigError(f"output_dir exists and is not a directory: {path}")
    ancestor = path
    while not ancestor.exists() and ancestor != ancestor.parent:
        ancestor = ancestor.parent
    if ancestor.exists() and not ancestor.is_dir():
        raise ConfigError(f"output_dir parent is not a directory: {ancestor}")


def _validate_resolved_run(
    resolved: ResolvedConfig,
    *,
    input_files: Sequence[Path] | None = None,
) -> None:
    values = resolved.values
    prompt = values.get("prompt")
    output_dir = values.get("output_dir")
    if not isinstance(prompt, Path) or not prompt.is_file():
        raise ConfigError(f"Prompt file does not exist: {prompt}")
    try:
        if not prompt.read_text(encoding="utf-8").strip():
            raise ConfigError(f"Prompt file is empty: {prompt}")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"Could not read UTF-8 prompt {prompt}: {exc}") from exc
    if not isinstance(output_dir, Path):
        raise ConfigError("output_dir must resolve to a filesystem path.")
    _validate_output_target(output_dir)
    if values.get("keep_browser") and resolved.runtime.parallel_runs > 1:
        raise ConfigError("--keep-browser is only compatible with --parallel-runs 1.")

    if resolved.command == "pdf":
        input_dir = values.get("input_dir")
        if not isinstance(input_dir, Path) or not input_dir.is_dir():
            raise ConfigError(f"Input directory does not exist: {input_dir}")
        activate_legacy_imports()
        import batch_common  # type: ignore[import-not-found]

        discovered = batch_common.collect_input_files(input_dir)
        files = list(input_files) if input_files is not None else discovered
        if input_files is not None:
            allowed = set(discovered)
            for path in files:
                if path.resolve() not in allowed:
                    raise ConfigError(
                        f"Input file is missing, unsupported, or excluded by batch rules: {path}"
                    )
        if not files:
            raise ConfigError(f"No supported PDF, DOCX, or MD files found in {input_dir}.")
        return

    markdown_file = values.get("markdown_file")
    if not isinstance(markdown_file, Path) or not markdown_file.is_file():
        raise ConfigError(f"Markdown file does not exist: {markdown_file}")


@contextmanager
def _selected_input_directory(
    input_dir: Path, input_files: Sequence[Path] | None
) -> Iterator[Path]:
    if input_files is None:
        yield input_dir
        return

    activate_legacy_imports()
    import batch_common

    selected = [path.resolve() for path in input_files]
    if selected == batch_common.collect_input_files(input_dir):
        yield input_dir
        return

    try:
        temporary = tempfile.TemporaryDirectory(prefix=".note-maker-selection-", dir=input_dir)
    except OSError:
        temporary = tempfile.TemporaryDirectory(prefix=".note-maker-selection-")
    with temporary as stage_name:
        stage = Path(stage_name)
        for source in selected:
            target = stage / source.name
            try:
                os.link(source, target)
            except OSError:
                shutil.copy2(source, target)
        yield stage


def _execute_resolved(
    resolved: ResolvedConfig,
    *,
    input_files: Sequence[Path] | None = None,
) -> int:
    _validate_resolved_run(resolved, input_files=input_files)
    activate_legacy_imports()
    values = resolved.values
    if resolved.command == "pdf":
        import batch_pdf  # type: ignore[import-not-found]

        input_dir = values["input_dir"]
        assert isinstance(input_dir, Path)
        with _selected_input_directory(input_dir, input_files) as execution_input_dir:
            return batch_pdf.run_batch(  # type: ignore[no-any-return]
                input_dir=execution_input_dir,
                output_dir=values["output_dir"],
                prompt_path=values["prompt"],
                overwrite=bool(values["overwrite"]),
                limit=values["limit"],
                model=values["model"],
                save_diagnostics=bool(values["save_diagnostics"]),
                save_page_source=bool(values["save_page_source"]),
                max_attempts=int(values["max_attempts"]),
                download_timeout=int(values["download_timeout"]),
                close_delay=int(values["close_delay"]),
                skip_warmup=bool(values["no_warm_up"]),
                keep_browser=bool(values["keep_browser"]),
                output_ext=str(values["output_ext"]),
                manifest_path=values["manifest"],
                resume=bool(values["resume"]),
                retry_failed=bool(values["retry_failed"]),
                adopt_existing=bool(values["adopt_existing"]),
                runtime_settings=resolved.runtime,
            )

    import batch_markdown  # type: ignore[import-not-found]

    try:
        sections_filter = batch_markdown.parse_section_numbers(values["sections"])
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc
    return batch_markdown.run_batch(  # type: ignore[no-any-return]
        markdown_file=values["markdown_file"],
        output_dir=values["output_dir"],
        prompt_path=values["prompt"],
        sections_filter=sections_filter,
        overwrite=bool(values["overwrite"]),
        limit=values["limit"],
        model=values["model"],
        save_diagnostics=bool(values["save_diagnostics"]),
        save_page_source=bool(values["save_page_source"]),
        max_section_attempts=int(values["max_section_attempts"]),
        download_timeout=int(values["download_timeout"]),
        close_delay=int(values["close_delay"]),
        chrome_profile_dir=values["chrome_profile_dir"],
        skip_warmup=bool(values["no_warm_up"]),
        keep_browser=bool(values["keep_browser"]),
        output_ext=str(values["output_ext"]),
        manifest_path=values["manifest"],
        resume=bool(values["resume"]),
        retry_failed=bool(values["retry_failed"]),
        adopt_existing=bool(values["adopt_existing"]),
        runtime_settings=resolved.runtime,
    )


def _run(args: argparse.Namespace) -> int:
    overrides = _namespace_overrides(args, _RUN_KEYS)
    resolved = resolve_config(
        args.run_command,
        config_path=args.config,
        profile=args.profile,
        cli_overrides=overrides,
    )
    if args.dry_run:
        _print(resolved.as_dict(), as_json=True)
        return 0
    return _execute_resolved(resolved)


def _interactive(args: argparse.Namespace) -> int:
    try:
        plan = build_interactive_plan(config_path=args.config, profile=args.profile)
    except InteractiveCancelled:
        print("Cancelled.")
        return 130

    if args.dry_run:
        return 0
    print("Starting Note Maker...")
    code = _execute_resolved(plan.resolved, input_files=plan.input_files)
    output_dir = plan.resolved.values.get("output_dir")
    if code == 0:
        print(f"Completed successfully. Outputs: {output_dir}")
    else:
        print(f"Run finished with exit code {code}. Outputs: {output_dir}", file=sys.stderr)
    return code


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            return _init(args)
        if args.command == "login":
            return _login(args)
        if args.command == "profiles":
            return _profiles(args)
        if args.command == "doctor":
            return _doctor(args)
        if args.command == "status":
            return _status(args)
        if args.command == "validate":
            return _validate(args)
        if args.command == "config":
            return _config(args)
        if args.command == "interactive":
            return _interactive(args)
        if args.command == "run":
            return _run(args)
    except ConfigError as exc:
        parser.error(str(exc))
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        return 130
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
