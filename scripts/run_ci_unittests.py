#!/usr/bin/env python3
"""Run unittest and expose a compact failure summary to GitHub Actions."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path


def _compact_summary(output: str, returncode: int) -> str:
    failures = re.findall(r"^(?:FAIL|ERROR):\s+(.+)$", output, flags=re.MULTILINE)
    if failures:
        summary = " | ".join(failures)
    elif returncode:
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        summary = " | ".join(lines[-3:]) if lines else f"unittest exited {returncode}"
    else:
        summary = "all tests passed"
    summary = summary.replace("\r", " ").replace("\n", " ")[:220]
    return summary.encode("ascii", errors="backslashreplace").decode("ascii")


def _write_github_outputs(summary: str, returncode: int) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    with Path(output_path).open("a", encoding="utf-8") as handle:
        handle.write(f"summary={summary}\n")
        handle.write(f"exit_code={returncode}\n")


def main() -> int:
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    output = result.stdout or ""
    summary = _compact_summary(output, result.returncode)
    _write_github_outputs(summary, result.returncode)

    log_path = Path("logs") / "unit-test-output.txt"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(output, encoding="utf-8")
    print(summary)

    # A dependent reporting job converts the captured return code back into
    # the workflow result after its display name has exposed the summary.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
