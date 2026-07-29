from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import shutil
import sys
from importlib import metadata
from pathlib import Path
from typing import Any

from .compat import activate_legacy_imports
from .config import ConfigError, ResolvedConfig, resolve_config


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
    parser.add_argument("--profile-snapshot", default=None)
    parser.add_argument(
        "--keep-runtime",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    parser.add_argument(
        "--adaptive-concurrency",
        action=argparse.BooleanOptionalAction,
        default=None,
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
        "--profile", default=None, help="Named profile from the configuration file."
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON where supported."
    )

    commands = parser.add_subparsers(dest="command", required=True)

    doctor = commands.add_parser(
        "doctor", help="Check dependencies, configuration, and browser availability."
    )
    doctor.add_argument(
        "--strict", action="store_true", help="Treat missing optional browsers as errors."
    )

    status = commands.add_parser("status", help="Show the latest batch summary.")
    status.add_argument("--summary", type=Path, default=Path("logs/last_batch_summary.json"))

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


def _doctor(args: argparse.Namespace) -> int:
    checks: list[dict[str, Any]] = []
    checks.append(
        {
            "name": "python",
            "ok": sys.version_info >= (3, 10),
            "detail": platform.python_version(),
        }
    )
    for module in (
        "selenium",
        "pyautogui",
        "pyperclip",
        "markdown",
        "weasyprint",
        "pypdf",
        "yaml",
        "patchright",
    ):
        checks.append(
            {
                "name": f"dependency:{module}",
                "ok": importlib.util.find_spec(module) is not None,
                "detail": "installed"
                if importlib.util.find_spec(module) is not None
                else "missing",
            }
        )

    browsers = {
        "chrome": shutil.which("google-chrome") or shutil.which("google-chrome-stable"),
        "chromium": shutil.which("chromium") or shutil.which("chromium-browser"),
        "edge": shutil.which("microsoft-edge") or shutil.which("microsoft-edge-stable"),
    }
    browser_ok = any(browsers.values())
    checks.append(
        {
            "name": "system-browser",
            "ok": browser_ok or not args.strict,
            "detail": next(
                (path for path in browsers.values() if path), "bundled browser may be used"
            ),
        }
    )

    try:
        resolved = resolve_config(
            "pdf",
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

    payload = {"ok": all(item["ok"] for item in checks), "checks": checks}
    if args.json:
        _print(payload, as_json=True)
    else:
        for item in checks:
            marker = "OK" if item["ok"] else "FAIL"
            print(f"[{marker}] {item['name']}: {item['detail']}")
    return 0 if payload["ok"] else 1


def _status(args: argparse.Namespace) -> int:
    path = args.summary.expanduser().resolve()
    if not path.is_file():
        print(f"No batch summary found at {path}.", file=sys.stderr)
        return 1
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
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


def _validate(args: argparse.Namespace) -> int:
    activate_legacy_imports()
    from artifact_validation import validate_artifact

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

    activate_legacy_imports()
    values = resolved.values
    if args.run_command == "pdf":
        import batch_pdf

        return batch_pdf.run_batch(
            input_dir=values["input_dir"],
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

    import batch_markdown

    return batch_markdown.run_batch(
        markdown_file=values["markdown_file"],
        output_dir=values["output_dir"],
        prompt_path=values["prompt"],
        sections_filter=batch_markdown.parse_section_numbers(values["sections"]),
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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            return _doctor(args)
        if args.command == "status":
            return _status(args)
        if args.command == "validate":
            return _validate(args)
        if args.command == "config":
            return _config(args)
        if args.command == "run":
            return _run(args)
    except ConfigError as exc:
        parser.error(str(exc))
    except KeyboardInterrupt:
        return 130
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
