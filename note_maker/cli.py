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
from importlib import metadata
from pathlib import Path
from typing import Any

from .compat import activate_legacy_imports
from .config import ConfigError, ResolvedConfig, resolve_config
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
    parser.add_argument("--profile-snapshot", default=None)
    parser.add_argument("--keep-runtime", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--adaptive-concurrency", action=argparse.BooleanOptionalAction, default=None)
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
    parser.add_argument("--profile", default=None, help="Named profile from the configuration file.")
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


def _doctor(args: argparse.Namespace) -> int:
    checks: list[dict[str, Any]] = [
        {
            "name": "python",
            "ok": sys.version_info >= (3, 10),
            "detail": platform.python_version(),
        }
    ]
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
        installed = importlib.util.find_spec(module) is not None
        checks.append(
            {
                "name": f"dependency:{module}",
                "ok": installed,
                "detail": "installed" if installed else "missing",
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
        resolved = resolve_config("pdf", config_path=args.config, profile=args.profile)
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
    import batch_common  # type: ignore[import-not-found]

    selected = [path.resolve() for path in input_files]
    if selected == batch_common.collect_input_files(input_dir):
        yield input_dir
        return

    try:
        temporary = tempfile.TemporaryDirectory(
            prefix=".note-maker-selection-", dir=input_dir
        )
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
