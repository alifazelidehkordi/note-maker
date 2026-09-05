#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from browser_runtime.login_bootstrap import LoginBootstrapper  # noqa: E402
from browser_runtime.profile_manager import ProfileManager, RetentionPolicy  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create, inspect and restore portable ChatGPT browser-session snapshots."
    )
    parser.add_argument(
        "--runtime-dir",
        type=Path,
        default=ROOT / ".runtime",
        help="Managed run directory root.",
    )
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        default=ROOT / "profile_templates",
        help="Session snapshot directory root.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="Inspect login evidence and profile locks.")
    inspect_parser.add_argument("profile", type=Path)

    login_parser = subparsers.add_parser(
        "login",
        help="Open real Chromium with a reference profile and optionally snapshot it after close.",
    )
    login_parser.add_argument("--profile", type=Path, default=ROOT / "chrome_profile_login")
    login_parser.add_argument("--snapshot-name", default="default")
    login_parser.add_argument("--no-snapshot", action="store_true")

    snapshot_parser = subparsers.add_parser("snapshot", help="Create a portable session snapshot.")
    snapshot_parser.add_argument("profile", type=Path)
    snapshot_parser.add_argument("--name", default="default")
    snapshot_parser.add_argument("--allow-unauthenticated", action="store_true")

    prepare_parser = subparsers.add_parser("prepare-worker", help="Restore one isolated worker profile.")
    prepare_parser.add_argument("snapshot")
    prepare_parser.add_argument("--run-id", required=True)
    prepare_parser.add_argument("--worker-id", required=True)
    prepare_parser.add_argument("--recreate", action="store_true")

    cleanup_parser = subparsers.add_parser("cleanup-run", help="Apply the configured retention policy.")
    cleanup_parser.add_argument("--run-id", required=True)
    cleanup_parser.add_argument("--success", action="store_true")
    cleanup_parser.add_argument(
        "--retention",
        choices=[item.value for item in RetentionPolicy],
        default=RetentionPolicy.DELETE_SUCCESS_KEEP_FAILURE.value,
    )
    return parser


def _manager(args: argparse.Namespace) -> ProfileManager:
    retention = RetentionPolicy(getattr(args, "retention", RetentionPolicy.DELETE_SUCCESS_KEEP_FAILURE.value))
    return ProfileManager(
        runtime_root=args.runtime_dir,
        snapshot_root=args.snapshot_dir,
        retention_policy=retention,
    )


def main() -> int:
    args = build_parser().parse_args()
    manager = _manager(args)

    if args.command == "inspect":
        evidence = manager.inspect_auth_session(args.profile)
        activity = manager.inspect_activity(args.profile)
        print(
            json.dumps(
                {
                    "profile": str(args.profile.expanduser().resolve()),
                    "authenticated": evidence.authenticated,
                    "auth_markers": list(evidence.markers),
                    "auth_reason": evidence.reason,
                    "active": activity.active,
                    "ownership_state": activity.ownership_state.value,
                    "active_markers": list(activity.active_markers),
                    "stale_markers": list(activity.stale_markers),
                    "uncertain_markers": list(activity.uncertain_markers),
                },
                indent=2,
            )
        )
        return 0 if evidence.authenticated and not activity.active else 2

    if args.command == "login":
        bootstrap = LoginBootstrapper(profile_manager=manager)
        print("A real Chromium window will open. Complete ChatGPT login, then close the browser.")
        bootstrap.open_login_browser(args.profile, wait=True)
        if args.no_snapshot:
            return 0
        snapshot = bootstrap.create_snapshot(args.profile, name=args.snapshot_name)
        print(f"snapshot_id={snapshot.snapshot_id}")
        print(f"snapshot={snapshot.path}")
        return 0

    if args.command == "snapshot":
        snapshot = manager.create_snapshot(
            args.profile,
            name=args.name,
            require_auth=not args.allow_unauthenticated,
        )
        print(f"snapshot_id={snapshot.snapshot_id}")
        print(f"snapshot={snapshot.path}")
        print(f"auth_markers={','.join(snapshot.auth_markers)}")
        print(f"portable={str(snapshot.portable).lower()}")
        return 0

    if args.command == "prepare-worker":
        context = manager.prepare_worker(
            run_id=args.run_id,
            worker_id=args.worker_id,
            snapshot=args.snapshot,
            recreate=args.recreate,
        )
        print(
            json.dumps(
                {
                    "run_id": context.run_id,
                    "worker_id": context.worker_id,
                    "profile_dir": str(context.profile_dir),
                    "download_dir": str(context.download_dir),
                    "log_dir": str(context.log_dir),
                    "diagnostics_dir": str(context.diagnostics_dir),
                    "snapshot_id": context.snapshot_id,
                },
                indent=2,
            )
        )
        return 0

    if args.command == "cleanup-run":
        outcome = manager.cleanup_run(args.run_id, success=args.success)
        print(f"deleted={str(outcome).lower()}")
        print(f"status={outcome.status.value}")
        print(f"reason={outcome.reason}")
        return 0

    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
