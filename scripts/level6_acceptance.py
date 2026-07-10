#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
SCRIPTS = ROOT / "scripts"
for path in (str(ROOT), str(TESTS), str(SCRIPTS)):
    if path not in sys.path:
        sys.path.insert(0, path)


MODULES = (
    "test_resilience_control",
    "test_level6_coordinator",
    "test_process_hygiene",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic Level 6 resilience acceptance checks.")
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "logs" / "level6-acceptance.json",
    )
    args = parser.parse_args()
    suite = unittest.TestSuite()
    loader = unittest.defaultTestLoader
    for module in MODULES:
        suite.addTests(loader.loadTestsFromName(module))
    started = time.monotonic()
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = {
        "schema_version": 1,
        "phase": 6,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "successful": result.wasSuccessful(),
        "duration_seconds": round(time.monotonic() - started, 3),
        "modules": list(MODULES),
        "acceptance_contracts": [
            "global rate-limit events pause new assignments",
            "transient network failures remain within bounded retry budgets",
            "authentication circuit uses a one-worker startup barrier",
            "adaptive concurrency scales down and recovers",
            "worker recycling preserves outputs and resume state",
            "stale claims and surviving child processes are cleaned safely",
        ],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Level 6 acceptance report: {args.report}")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
