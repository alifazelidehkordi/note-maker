from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from . import cli as legacy_cli
from .compat import activate_legacy_imports
from .config import ConfigError


def _details_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--details", action="store_true")
    parser.add_argument("--run-dir", type=Path, default=None)
    parser.add_argument("--recent-events", type=int, default=8)
    return parser


def _parse_with_details(
    argv: Sequence[str],
) -> tuple[argparse.Namespace, argparse.Namespace, list[str]]:
    parser = legacy_cli.build_parser()
    args, unknown = parser.parse_known_args(list(argv))
    if args.command != "status":
        return args, argparse.Namespace(details=False, run_dir=None, recent_events=8), unknown
    detail_args, remaining = _details_parser().parse_known_args(unknown)
    return args, detail_args, remaining


def _status_details(args: argparse.Namespace, detail_args: argparse.Namespace) -> int:
    if args.interval <= 0:
        print("--interval must be positive.", file=sys.stderr)
        return 2
    if detail_args.recent_events < 0:
        print("--recent-events must be non-negative.", file=sys.stderr)
        return 2
    if args.summary is not None:
        print("--details cannot be combined with --summary.", file=sys.stderr)
        return 2

    snapshot_path = args.snapshot.expanduser().resolve()
    if not snapshot_path.is_file():
        print(f"No live status snapshot found at {snapshot_path}.", file=sys.stderr)
        return 1

    activate_legacy_imports()
    from parallel_runtime.observability import (  # type: ignore[import-not-found]
        build_run_observability,
        format_run_observability,
        resolve_run_dir,
    )
    from parallel_runtime.status import (  # type: ignore[import-not-found]
        is_terminal_snapshot,
        read_status_snapshot,
    )

    while True:
        try:
            snapshot = read_status_snapshot(snapshot_path)
            run_dir = resolve_run_dir(
                snapshot_path,
                snapshot,
                run_dir=detail_args.run_dir,
            )
            payload = build_run_observability(
                snapshot,
                run_dir=run_dir,
                recent_events=detail_args.recent_events,
            )
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            print(f"Could not read run observability data: {exc}", file=sys.stderr)
            return 1

        if args.json:
            if args.watch:
                print(json.dumps(payload, sort_keys=True, ensure_ascii=False), flush=True)
            else:
                print(
                    json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
                    flush=True,
                )
        else:
            if args.watch and sys.stdout.isatty():
                print("\x1b[2J\x1b[H", end="")
            print(format_run_observability(payload), flush=True)

        if not args.watch or is_terminal_snapshot(snapshot):
            return 0
        time.sleep(args.interval)


def main(argv: list[str] | None = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    if "--details" not in values:
        return legacy_cli.main(values)

    try:
        args, detail_args, remaining = _parse_with_details(values)
        if args.command != "status":
            return legacy_cli.main(values)
        if remaining:
            legacy_cli.build_parser().error("unrecognized arguments: " + " ".join(remaining))
        return _status_details(args, detail_args)
    except ConfigError as exc:
        legacy_cli.build_parser().error(str(exc))
    except KeyboardInterrupt:
        return 130
    return 1