from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from . import cli
from .config import ConfigError, ResolvedConfig, resolve_config
from .preview import build_markdown_preview, build_pdf_preview, selected_pdf_collection


def _extract_selection(values: Sequence[str]) -> tuple[list[str], tuple[str, ...], tuple[str, ...]]:
    cleaned: list[str] = []
    includes: list[str] = []
    excludes: list[str] = []
    index = 0
    while index < len(values):
        value = values[index]
        if value in {"--include", "--exclude"}:
            if index + 1 >= len(values):
                raise ConfigError(f"{value} expects a filename glob pattern.")
            pattern = values[index + 1].strip()
            if not pattern:
                raise ConfigError(f"{value} expects a non-empty filename glob pattern.")
            (includes if value == "--include" else excludes).append(pattern)
            index += 2
            continue
        if value.startswith("--include=") or value.startswith("--exclude="):
            option, _, raw_pattern = value.partition("=")
            pattern = raw_pattern.strip()
            if not pattern:
                raise ConfigError(f"{option} expects a non-empty filename glob pattern.")
            (includes if option == "--include" else excludes).append(pattern)
            index += 1
            continue
        cleaned.append(value)
        index += 1
    return cleaned, tuple(includes), tuple(excludes)


def _pdf_help_requested(values: Sequence[str]) -> bool:
    if "--help" not in values and "-h" not in values:
        return False
    try:
        run_index = values.index("run")
    except ValueError:
        return False
    return run_index + 1 < len(values) and values[run_index + 1] == "pdf"


def _print_pdf_selection_help() -> None:
    print(
        "\nPart 2B file selection:\n"
        "  --include GLOB   Include matching top-level filenames; may be repeated.\n"
        "  --exclude GLOB   Exclude matching top-level filenames; may be repeated.\n"
        "Patterns are case-sensitive on every platform. Includes are ORed, exclusions run after includes,\n"
        "and --limit is applied last. Quote shell globs such as --include '*.pdf'."
    )


def _resolved_run(args: argparse.Namespace) -> ResolvedConfig:
    overrides = cli._namespace_overrides(args, cli._RUN_KEYS)
    return resolve_config(
        args.run_command,
        config_path=args.config,
        profile=args.profile,
        cli_overrides=overrides,
    )


def _print_preview(resolved: ResolvedConfig, preview: dict[str, object]) -> int:
    payload = resolved.as_dict()
    payload["preview"] = preview
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    selection = preview.get("selection")
    if isinstance(selection, dict) and int(selection.get("selected_count", 0)) == 0:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    try:
        cleaned, includes, excludes = _extract_selection(values)
    except ConfigError as exc:
        cli.build_parser().error(str(exc))

    if _pdf_help_requested(cleaned):
        try:
            return cli.main(cleaned)
        except SystemExit as exc:
            if exc.code == 0:
                _print_pdf_selection_help()
                return 0
            raise

    parser = cli.build_parser()
    args = parser.parse_args(cleaned)
    selectors_requested = bool(includes or excludes)
    if selectors_requested and not (
        args.command == "run" and getattr(args, "run_command", None) == "pdf"
    ):
        parser.error("--include/--exclude are supported only by `note-maker run pdf`.")

    try:
        if args.command == "run" and bool(getattr(args, "dry_run", False)):
            resolved = _resolved_run(args)
            if args.run_command == "pdf":
                preview = build_pdf_preview(
                    resolved,
                    include_patterns=includes,
                    exclude_patterns=excludes,
                )
            else:
                preview = build_markdown_preview(resolved)
            return _print_preview(resolved, preview)

        if selectors_requested:
            with selected_pdf_collection(
                include_patterns=includes,
                exclude_patterns=excludes,
            ):
                return cli.main(cleaned)
        return cli.main(cleaned)
    except ConfigError as exc:
        parser.error(str(exc))
    except KeyboardInterrupt:
        return 130
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
