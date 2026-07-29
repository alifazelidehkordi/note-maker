from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def update_readme() -> None:
    path = ROOT / "README.md"
    text = path.read_text(encoding="utf-8")
    original = text

    text, version_count = re.subn(
        r"version-0\.8\.1-2563eb",
        "version-0.8.2-2563eb",
        text,
        count=1,
    )
    text, tests_count = re.subn(
        r"tests-[0-9]+%20passing-16a34a",
        "tests-CI%20verified-16a34a",
        text,
        count=1,
    )
    old_license = (
        "No license file is currently included. Until a license is added, "
        "the repository remains **all rights reserved** by default."
    )
    new_license = (
        "This project is licensed under the [MIT License](LICENSE). See "
        "[SECURITY.md](SECURITY.md) for private vulnerability reporting guidance."
    )
    if old_license not in text:
        raise RuntimeError("README license paragraph did not match the expected text")
    text = text.replace(old_license, new_license, 1)

    if version_count != 1 or tests_count != 1:
        raise RuntimeError(
            f"README badge replacement mismatch: version={version_count}, tests={tests_count}"
        )
    if text == original:
        raise RuntimeError("README was not changed")
    path.write_text(text, encoding="utf-8")


def update_changelog() -> None:
    path = ROOT / "CHANGELOG.md"
    text = path.read_text(encoding="utf-8")
    if "## [0.8.2]" in text:
        return

    marker = "All notable changes to Note Maker are documented here.\n"
    if marker not in text:
        raise RuntimeError("CHANGELOG introduction marker was not found")

    release = """
## [0.8.2] — 2026-07-29

### Fixed

- Persistent ChatGPT rate-limit dialogs now raise a typed `RateLimitError` when acknowledgement fails, ensuring the global cooldown and retry policy activate instead of degrading into generic send or response timeouts.
- Context-free generic controls such as `Download`, `Copy`, `Share`, and `Coding Citation` are no longer accepted as artifact triggers merely because the surrounding assistant response mentions Markdown or OPML.
- Distinct rate-limit incidents from the same job now receive unique incident-scoped keys, while duplicate signaling from one failure path is suppressed.
- Patchright and the Selenium compatibility facade now share the same strict artifact-trigger policy.

### Security and release

- Added `SECURITY.md` with private reporting guidance and a sensitive-local-data handling policy.
- Replaced the version-specific release checklist with a reusable checklist covering rate-limit escalation, artifact identity, process hygiene, archive privacy, and independent review.
- Corrected the README license section to match the repository's MIT license and made version/test badges resistant to documentation drift.
- Synchronized `VERSION` and `package.json` at `0.8.2`.

### Verification

- Added regression coverage for persistent rate-limit dialogs, ambiguous download controls, and distinct rate-limit incidents within one job.
- The cross-platform Phase 1 CI matrix and browser-free release acceptance remain required before tagging `v0.8.2`.
"""
    text = text.replace(marker, marker + release, 1)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    update_readme()
    update_changelog()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
