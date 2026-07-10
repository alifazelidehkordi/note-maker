#!/usr/bin/env python3
from __future__ import annotations

import argparse
import multiprocessing as mp
import queue
import shutil
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from browser_runtime import (  # noqa: E402
    BrowserLaunchOptions,
    PatchrightProvider,
    ProfileManager,
    RetentionPolicy,
    SessionBootstrapper,
    WorkerProfileContext,
)


def _browser_worker(
    context: WorkerProfileContext,
    runtime_root: Path,
    snapshot_root: Path,
    ready_queue,
    command_queue,
    result_queue,
) -> None:
    manager = ProfileManager(
        runtime_root=runtime_root,
        snapshot_root=snapshot_root,
        retention_policy=RetentionPolicy.KEEP_ALL,
    )
    session = None
    try:
        session = SessionBootstrapper(profile_manager=manager).open_session(
            provider=PatchrightProvider(),
            context=context,
            options=BrowserLaunchOptions(
                headless=True,
                url="about:blank",
                navigation_timeout=30,
                action_timeout=15,
                use_stealth=False,
            ),
            validate_login=False,
        )
        title = context.worker_id
        session.raw_handle.set_content(f"<!doctype html><title>{title}</title><h1>{title}</h1>")
        ready_queue.put((context.worker_id, "ready", session.raw_handle.title()))
        while True:
            command = command_queue.get(timeout=60)
            if command == "health":
                result_queue.put(
                    (
                        context.worker_id,
                        "health",
                        session.is_alive(),
                        session.raw_handle.title(),
                    )
                )
            elif command == "stop":
                break
            else:
                result_queue.put((context.worker_id, "unknown", command))
    except Exception as exc:
        ready_queue.put((context.worker_id, "error", f"{type(exc).__name__}: {exc}"))
        raise
    finally:
        if session is not None:
            session.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Open two simultaneous Patchright worker processes with isolated profiles."
    )
    parser.add_argument("--runtime-dir", type=Path, default=ROOT / ".runtime-smoke")
    parser.add_argument("--snapshot-dir", type=Path, default=ROOT / ".profile-snapshots-smoke")
    parser.add_argument("--keep", action="store_true")
    return parser


def _receive(target_queue, *, timeout: int = 60):
    try:
        return target_queue.get(timeout=timeout)
    except queue.Empty as exc:
        raise RuntimeError("Timed out waiting for browser worker.") from exc


def main() -> int:
    args = build_parser().parse_args()
    run_id = f"profile-smoke-{uuid4().hex[:8]}"
    manager = ProfileManager(
        runtime_root=args.runtime_dir,
        snapshot_root=args.snapshot_dir,
        retention_policy=RetentionPolicy.KEEP_ALL,
    )
    seed_context = manager.prepare_worker(run_id=run_id, worker_id="snapshot-seed")
    seed_session = SessionBootstrapper(profile_manager=manager).open_session(
        provider=PatchrightProvider(),
        context=seed_context,
        options=BrowserLaunchOptions(
            headless=True,
            url="about:blank",
            navigation_timeout=30,
            action_timeout=15,
            use_stealth=False,
        ),
        validate_login=False,
    )
    seed_session.raw_handle.set_content("<!doctype html><title>snapshot-seed</title>")
    seed_session.close()
    snapshot = manager.create_snapshot(
        seed_context.profile_dir,
        name="profile-isolation-smoke",
        require_auth=False,
    )
    manager.cleanup_worker(seed_context)
    contexts = [
        manager.prepare_worker(
            run_id=run_id,
            worker_id="worker-001",
            snapshot=snapshot,
        ),
        manager.prepare_worker(
            run_id=run_id,
            worker_id="worker-002",
            snapshot=snapshot,
        ),
    ]

    mp_context = mp.get_context("spawn")
    ready_queue = mp_context.Queue()
    result_queue = mp_context.Queue()
    command_queues = [mp_context.Queue(), mp_context.Queue()]
    processes = [
        mp_context.Process(
            target=_browser_worker,
            args=(
                contexts[index],
                args.runtime_dir.resolve(),
                args.snapshot_dir.resolve(),
                ready_queue,
                command_queues[index],
                result_queue,
            ),
            name=contexts[index].worker_id,
        )
        for index in range(2)
    ]

    try:
        for process in processes:
            process.start()
        ready = [_receive(ready_queue), _receive(ready_queue)]
        if any(item[1] != "ready" for item in ready):
            raise RuntimeError(f"A worker failed to start: {ready}")
        if {item[0] for item in ready} != {"worker-001", "worker-002"}:
            raise RuntimeError(f"Unexpected workers became ready: {ready}")

        command_queues[0].put("stop")
        processes[0].join(timeout=30)
        if processes[0].is_alive() or processes[0].exitcode != 0:
            raise RuntimeError(f"Worker one did not stop cleanly: exit={processes[0].exitcode}")

        command_queues[1].put("health")
        health = _receive(result_queue)
        if health[:2] != ("worker-002", "health") or not health[2] or health[3] != "worker-002":
            raise RuntimeError(f"Worker two was affected by worker one shutdown: {health}")

        manager.cleanup_worker(contexts[0])
        if not contexts[1].profile_dir.exists():
            raise RuntimeError("Cleaning worker one removed worker two data.")

        command_queues[1].put("stop")
        processes[1].join(timeout=30)
        if processes[1].is_alive() or processes[1].exitcode != 0:
            raise RuntimeError(f"Worker two did not stop cleanly: exit={processes[1].exitcode}")

        print(f"run_id={run_id}")
        print(f"snapshot_id={snapshot.snapshot_id}")
        print(f"worker_1_profile={contexts[0].profile_dir}")
        print(f"worker_2_profile={contexts[1].profile_dir}")
        print("snapshot_clone=passed")
        print("simultaneous_processes=2")
        print("profile_isolation=passed")
        return 0
    finally:
        for index, process in enumerate(processes):
            if process.is_alive():
                command_queues[index].put("stop")
                process.join(timeout=10)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        if not args.keep:
            shutil.rmtree(args.runtime_dir, ignore_errors=True)
            shutil.rmtree(args.snapshot_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
