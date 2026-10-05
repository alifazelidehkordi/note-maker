from __future__ import annotations

import re
import time
from collections.abc import Iterable
from pathlib import Path

from .models import DownloadSnapshot, normalize_extensions
from .selectors import NON_FILE_DOWNLOAD_PHRASES

PARTIAL_SUFFIXES = (".crdownload", ".tmp", ".part", ".download")
MARKDOWN_EXTENSIONS = frozenset({".md", ".markdown"})
DOWNLOAD_TIME_TOLERANCE_NS = 2_000_000_000


def safe_path_component(value: str, fallback: str = "download") -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    return normalized[:120] or fallback


def is_partial_download(path: Path) -> bool:
    lowered = path.name.lower()
    return any(lowered.endswith(suffix) for suffix in PARTIAL_SUFFIXES)


def _file_state(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def snapshot_directory(directory: Path) -> DownloadSnapshot:
    snapshot: DownloadSnapshot = {}
    if not directory.exists():
        return snapshot
    for path in directory.rglob("*"):
        if not path.is_file():
            continue
        resolved = path.resolve()
        state = _file_state(resolved)
        if state is not None:
            snapshot[resolved] = state
    return snapshot


def _normalize_snapshot(value: object) -> DownloadSnapshot:
    if isinstance(value, dict):
        normalized: DownloadSnapshot = {}
        for path, state in value.items():
            try:
                normalized[Path(path).resolve()] = state
            except TypeError:
                continue
        return normalized
    if isinstance(value, (set, frozenset, list, tuple)):
        return {Path(path).resolve(): None for path in value}
    return {}


def is_fresh(path: Path, before: object, *, started_at_ns: int) -> bool:
    resolved = path.resolve()
    current = _file_state(resolved)
    if current is None:
        return False
    snapshot = _normalize_snapshot(before)
    if resolved in snapshot and snapshot[resolved] == current:
        return False
    if resolved in snapshot and snapshot[resolved] is None:
        return False
    if started_at_ns and current[0] + DOWNLOAD_TIME_TOLERANCE_NS < started_at_ns:
        return False
    return True


def content_matches(path: Path, expected_extensions: Iterable[str]) -> bool:
    expected = normalize_extensions(set(expected_extensions))
    try:
        if path.stat().st_size <= 0 or path.stat().st_size > 10_000_000:
            return False
        sample = path.read_text(encoding="utf-8", errors="ignore")[:8192]
    except OSError:
        return False
    lower = sample.lower()
    if ".opml" in expected and "<opml" in lower:
        return True
    if expected & MARKDOWN_EXTENSIONS:
        stripped = sample.lstrip()
        return stripped.startswith("#") or "\n## " in sample or "\n### " in sample
    return False


def is_expected_artifact(path: Path, expected_extensions: Iterable[str]) -> bool:
    if not path.is_file() or is_partial_download(path):
        return False
    expected = normalize_extensions(set(expected_extensions))
    accepted = set(expected)
    if expected & MARKDOWN_EXTENSIONS:
        accepted.update(MARKDOWN_EXTENSIONS)
    suffix = path.suffix.lower()
    if suffix in accepted:
        return True
    if suffix in {".opml", ".md", ".markdown"}:
        return False
    return content_matches(path, expected)


def score_download_trigger(
    *,
    text: str = "",
    href: str = "",
    title: str = "",
    aria: str = "",
    context: str = "",
    expected_extensions: Iterable[str],
) -> int:
    expected = normalize_extensions(set(expected_extensions))
    direct = " ".join(part for part in (text, title, aria) if part).strip()
    candidate_haystack = " ".join(part for part in (direct, href) if part).lower()
    context_haystack = context.lower()
    full_haystack = f"{candidate_haystack} {context_haystack}".strip()
    if any(phrase in full_haystack for phrase in NON_FILE_DOWNLOAD_PHRASES):
        return 0

    def expected_reference(value: str) -> int:
        reference_score = 0
        for extension in expected:
            if extension in value:
                reference_score = max(reference_score, 90)
        if ".opml" in expected and re.search(r"\bopml\b", value):
            reference_score = max(reference_score, 75)
        if expected & MARKDOWN_EXTENSIONS and re.search(r"\bmarkdown\b", value):
            reference_score = max(reference_score, 75)
        return reference_score

    # A candidate must carry its own artifact evidence. Surrounding assistant
    # text alone is not enough because one response can contain multiple generic
    # controls. Plain "Download" buttons are handled only after an artifact card
    # opens a dedicated preview, where the provider has already selected a
    # format-specific card or link.
    score = expected_reference(candidate_haystack)
    direct_lower = direct.lower()
    explicit_download = "download" in direct_lower or "دانلود" in direct
    href_lower = href.lower()
    artifact_href = any(
        marker in href_lower
        for marker in ("sandbox:", "/download", "/file-", "blob:", "data:")
    )
    if (
        score == 0
        and explicit_download
        and artifact_href
        and expected_reference(context_haystack)
    ):
        score = 60
    if score == 0:
        return 0
    if "sandbox:" in href_lower:
        score += 20
    if "/download" in href_lower or "/file-" in href_lower:
        score += 15
    if explicit_download:
        score += 25
    return min(score, 100)


def find_fresh_candidates(
    directory: Path,
    before: object,
    *,
    expected_extensions: Iterable[str],
    started_at_ns: int,
) -> list[Path]:
    if not directory.exists():
        return []
    candidates = [
        path.resolve()
        for path in directory.rglob("*")
        if path.is_file()
        and is_fresh(path, before, started_at_ns=started_at_ns)
        and is_expected_artifact(path, expected_extensions)
    ]
    return sorted(candidates, key=lambda path: path.stat().st_mtime_ns, reverse=True)


def salvage_download(
    directory: Path,
    before: object,
    *,
    expected_extensions: Iterable[str],
    started_at_ns: int,
    timeout: int,
    sleep_interval: float = 0.5,
) -> Path | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        candidates = find_fresh_candidates(
            directory,
            before,
            expected_extensions=expected_extensions,
            started_at_ns=started_at_ns,
        )
        if candidates:
            return candidates[0]
        time.sleep(sleep_interval)
    candidates = find_fresh_candidates(
        directory,
        before,
        expected_extensions=expected_extensions,
        started_at_ns=started_at_ns,
    )
    return candidates[0] if candidates else None
