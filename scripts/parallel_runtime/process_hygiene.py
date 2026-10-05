from __future__ import annotations

import os
import signal
import time
from collections.abc import Iterable
from pathlib import Path


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _linux_parent_map() -> dict[int, int]:
    result: dict[int, int] = {}
    proc = Path("/proc")
    if not proc.is_dir():
        return result
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            content = (entry / "stat").read_text(encoding="utf-8")
            # comm is enclosed in parentheses and may contain spaces.
            tail = content[content.rfind(")") + 2 :].split()
            parent = int(tail[1])
            result[int(entry.name)] = parent
        except (OSError, ValueError, IndexError):
            continue
    return result


def descendant_pids(root_pid: int) -> tuple[int, ...]:
    parent_map = _linux_parent_map()
    children: dict[int, list[int]] = {}
    for child, parent in parent_map.items():
        children.setdefault(parent, []).append(child)
    discovered: list[int] = []
    stack = list(children.get(int(root_pid), ()))
    while stack:
        pid = stack.pop()
        if pid in discovered:
            continue
        discovered.append(pid)
        stack.extend(children.get(pid, ()))
    # Children first makes browser cleanup more predictable.
    return tuple(reversed(discovered))


def process_rss_mb(pid: int) -> float | None:
    try:
        for line in Path(f"/proc/{int(pid)}/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024.0
    except (OSError, ValueError, IndexError):
        return None
    return None


def process_tree_rss_mb(root_pid: int) -> float | None:
    values = []
    for pid in (int(root_pid), *descendant_pids(int(root_pid))):
        rss = process_rss_mb(pid)
        if rss is not None:
            values.append(rss)
    return sum(values) if values else None


def _signal_many(pids: Iterable[int], sig: int) -> None:
    for pid in pids:
        if pid <= 1 or pid == os.getpid():
            continue
        try:
            os.kill(pid, sig)
        except (ProcessLookupError, PermissionError, OSError):
            pass


def cleanup_descendants(
    root_pid: int,
    *,
    known_descendants: Iterable[int] = (),
    grace_seconds: float = 0.5,
) -> tuple[int, ...]:
    """Terminate surviving descendants after their worker parent has exited."""
    candidates = set(int(pid) for pid in known_descendants if int(pid) > 1)
    candidates.update(descendant_pids(root_pid))
    alive = {pid for pid in candidates if pid_alive(pid)}
    if not alive:
        return ()
    if hasattr(signal, "SIGTERM"):
        _signal_many(sorted(alive, reverse=True), signal.SIGTERM)
    deadline = time.monotonic() + max(0.0, grace_seconds)
    while alive and time.monotonic() < deadline:
        time.sleep(0.02)
        alive = {pid for pid in alive if pid_alive(pid)}
    cleaned = set(alive)
    if alive and hasattr(signal, "SIGKILL"):
        _signal_many(sorted(alive, reverse=True), signal.SIGKILL)
    return tuple(sorted(cleaned))
