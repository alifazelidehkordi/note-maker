#!/usr/bin/env python3
"""Run the unittest suite while preserving complete CI output as an artifact."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    output = result.stdout or b""
    log_path = Path("logs") / "unit-test-output.txt"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_bytes(output)

    try:
        sys.stdout.buffer.write(output)
        sys.stdout.buffer.flush()
    except BrokenPipeError:
        pass

    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
