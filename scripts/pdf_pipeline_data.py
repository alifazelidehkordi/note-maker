#!/usr/bin/env python3
"""Index, metadata, session-order, and A4 constants for the PDF pipeline."""
from __future__ import annotations

import html
import re
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence
from urllib.parse import unquote

import yaml

A4_WIDTH_PT = 595.275590551
A4_HEIGHT_PT = 841.88976378
A4_SIZE = (A4_WIDTH_PT, A4_HEIGHT_PT)
assert A4_WIDTH_PT < A4_HEIGHT_PT

PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
ASCII_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.S)
H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.M)
KEY_POINTS_RE = re.compile(
    r"^##\s+(?:Key Points|نکات کلیدی|Summary|خلاصه(?:\s+کلیدی)?)\s*$([\s\S]*?)(?=^##\s+|\Z)",
    re.I | re.M,
)
INDEX_ENTRY_RE = re.compile(
    r"^\s*(?P<number>\d+)\.\s+\[(?P<title>[^]]+)\]\((?P<link>[^)]+\.md)\)\s*[—-]\s*(?P<details>.+?)\s*$",
    re.M,
)
SOURCE_PAGES_RE = re.compile(r"\bpages?\s+(\d{1,4})\s*[-–]\s*(\d{1,4})", re.I)
DURATION_RE = re.compile(r"~?\s*(\d+(?:\.\d+)?)\s*(min|minutes?|h|hr|hours?)\b", re.I)
LECTURE_RE = re.compile(r"\b(L\s*\d+[a-z]?)\b", re.I)
TOPIC_FILENAME_RE = re.compile(r"^(\d{1,4})(?:_(\d{1,4}))?_.+\.md$", re.I)

EXCLUDED_DIR_PARTS = {
    ".git", ".github", ".note-maker-claims", "diagnostics", "verification",
    "verifications", "debug", "logs", "log", "cache", "caches", "tmp",
    "temp", "temporary", "intermediate", "pdfs", "renders", "__pycache__",
}
EXCLUDED_NAME_TOKENS = {
    "readme", "study_index", "study-index", "index", "structure", "boundaries",
    "verification", "quality", "qc", "report", "manifest", "debug", "log",
    "combined", "final_study_notes", "final-study-notes", "temporary", "temp",
    "intermediate",
}


@dataclass
class FontConfig:
    regular_files: list[Path]
    bold_files: list[Path]
    regular_families: list[str]
    bold_families: list[str]
    css: str
    expected_postscript_names: set[str] = field(default_factory=set)


@dataclass
class Session:
    number: int
    title: str
    markdown_path: Path
    stem: str
    source: str = "—"
    source_pages: str = "—"
    book_pages: str = "—"
    duration: str = "—"
    study_focus: str = "—"
    group_key: str = ""
    group_title: str = ""
    destination: str = ""
    pdf_path: Path | None = None
    pdf_pages: int = 0
    start_page_index: int = -1

    @property
    def first_book_page(self) -> int | None:
        if self.start_page_index < 0:
            return None
        return self.start_page_index + 1


@dataclass
class Group:
    key: str
    title: str
    sessions: list[Session]

    @property
    def source_pages(self) -> str:
        ranges = [parse_range(s.source_pages) for s in self.sessions]
        ranges = [r for r in ranges if r]
        if not ranges:
            return "—"
        return f"{min(x[0] for x in ranges)}-{max(x[1] for x in ranges)}"

    @property
    def book_pages(self) -> str:
        values = [parse_range(s.book_pages) for s in self.sessions]
        values = [v for v in values if v]
        if not values:
            return "—"
        return f"{min(v[0] for v in values)}-{max(v[1] for v in values)}"


def natural_key(value: str | Path) -> tuple:
    text = value.name if isinstance(value, Path) else str(value)
    return tuple(int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", text))


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def strip_markdown(value: str) -> str:
    value = re.sub(r"!\[([^]]*)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"[*_`>#|]+", " ", value)
    return normalize_space(html.unescape(value))


def parse_frontmatter(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8", errors="strict")
    except OSError:
        return {}
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}
    try:
        data = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def markdown_title(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    match = H1_RE.search(text)
    if match:
        return strip_markdown(match.group(1))
    raw = re.sub(r"^\d+(?:_\d+)?_", "", path.stem)
    return normalize_space(raw.replace("_", " ").replace("-", " ")).title()


def extract_study_focus(path: Path, limit: int = 230) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    key_match = KEY_POINTS_RE.search(text)
    if key_match:
        bullets: list[str] = []
        for raw in key_match.group(1).splitlines():
            line = raw.strip()
            if re.match(r"^[-*+]\s+", line):
                bullets.append(strip_markdown(re.sub(r"^[-*+]\s+", "", line)))
            if len(bullets) >= 2:
                break
        focus = "; ".join(x for x in bullets if x)
        if focus:
            return focus if len(focus) <= limit else focus[: limit - 1].rstrip() + "…"
    body = FRONTMATTER_RE.sub("", text, count=1)
    body = H1_RE.sub("", body, count=1)
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "|", "```", "---", "<!--")):
            continue
        line = strip_markdown(line)
        if line:
            return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"
    return "مرور نکات کلیدی این جلسه / Review the key concepts in this session"


def is_excluded_path(path: Path) -> bool:
    if path.name.startswith("."):
        return True
    if any(part.casefold() in EXCLUDED_DIR_PARTS for part in path.parts):
        return True
    stem = path.stem.casefold()
    normalized = re.sub(r"[^a-z0-9]+", "_", stem).strip("_")
    words = set(normalized.split("_"))
    if normalized in EXCLUDED_NAME_TOKENS:
        return True
    if any(normalized.startswith(token + "_") or normalized.endswith("_" + token) for token in EXCLUDED_NAME_TOKENS):
        return True
    if words.intersection({"readme", "verification", "debug", "temporary", "intermediate"}):
        return True
    if path.suffix.casefold() not in {".md", ".pdf"}:
        return True
    return False


def is_session_markdown(path: Path) -> bool:
    return path.is_file() and not is_excluded_path(path) and bool(TOPIC_FILENAME_RE.match(path.name))


def locate_index_file(notes_dir: Path, original_parts_dir: Path | None = None, explicit: Path | None = None) -> Path:
    if explicit:
        path = explicit.resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Index file not found: {path}")
        return path
    roots = [Path(notes_dir)]
    if original_parts_dir:
        roots.append(Path(original_parts_dir))
    candidates: list[tuple[int, Path]] = []
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob("*.md"):
            if any(part.casefold() in EXCLUDED_DIR_PARTS for part in p.parts):
                continue
            name = p.name.casefold()
            priority = 100
            if name == "index.md":
                priority = 0
            elif name in {"study_index.md", "study-index.md"}:
                priority = 1
            elif "index" in name:
                priority = 5
            try:
                sample = p.read_text(encoding="utf-8", errors="ignore")[:20000]
            except OSError:
                continue
            if len(INDEX_ENTRY_RE.findall(sample)) >= 2:
                candidates.append((priority, p.resolve()))
    if not candidates:
        raise FileNotFoundError(f"No usable Markdown Index was found under: {', '.join(str(r) for r in roots)}")
    candidates.sort(key=lambda item: (item[0], natural_key(item[1])))
    return candidates[0][1]


def _resolve_session_path(index_path: Path, notes_dir: Path, link: str) -> Path:
    clean = unquote(link.split("#", 1)[0]).replace("\\", "/")
    basename = Path(clean).name
    direct_candidates = [
        index_path.parent / clean,
        notes_dir / clean,
        notes_dir / basename,
        index_path.parent / basename,
    ]
    for candidate in direct_candidates:
        if candidate.is_file():
            return candidate.resolve()
    matches = [p for p in notes_dir.rglob(basename) if p.is_file()]
    if len(matches) == 1:
        return matches[0].resolve()
    stem_matches = [p for p in notes_dir.rglob("*.md") if p.stem.casefold() == Path(basename).stem.casefold()]
    if len(stem_matches) == 1:
        return stem_matches[0].resolve()
    raise FileNotFoundError(f"Index session target could not be resolved: {link}")


def _parse_details(details: str) -> tuple[str, str, str]:
    page_match = SOURCE_PAGES_RE.search(details)
    source_pages = f"{int(page_match.group(1))}-{int(page_match.group(2))}" if page_match else "—"
    source = details[: page_match.start()].rstrip(" ,;-") if page_match else details.split(";", 1)[0].strip()
    duration_match = DURATION_RE.search(details)
    duration = "—"
    if duration_match:
        amount = duration_match.group(1)
        unit = duration_match.group(2).casefold()
        duration = f"{amount} min" if unit.startswith("m") else f"{amount} h"
    return normalize_space(source) or "—", source_pages, duration


def _first_metadata(meta: dict, keys: Sequence[str], default: str = "") -> str:
    for key in keys:
        value = meta.get(key)
        if value not in (None, ""):
            return normalize_space(str(value))
    return default


def _group_identity(source: str, meta: dict, session_number: int) -> tuple[str, str]:
    explicit_key = _first_metadata(meta, ("chapter", "group", "chapter_number", "group_number"))
    explicit_title = _first_metadata(meta, ("chapter_title", "chapter_title_en", "group_title", "group_title_en"))
    if explicit_key:
        key = f"meta-{explicit_key.casefold()}"
        title = explicit_title or f"Group {explicit_key}"
        return key, title
    normalized_source = normalize_space(source)
    if normalized_source and normalized_source != "—":
        key = unicodedata.normalize("NFKC", normalized_source).casefold()
        title = re.sub(r"(?:\.(?:pdf|pptx))+$", "", normalized_source, flags=re.I)
        return f"source-{key}", title
    lecture = LECTURE_RE.search(str(meta))
    if lecture:
        value = lecture.group(1).replace(" ", "")
        return f"lecture-{value.casefold()}", value.upper()
    return "ungrouped", "Study Sessions"


def destination_name(number: int, stem: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", stem).strip("-")[:90]
    return f"session-{number:03d}-{safe}"


def parse_index_sessions(index_path: Path, notes_dir: Path) -> list[Session]:
    text = index_path.read_text(encoding="utf-8", errors="strict")
    sessions: list[Session] = []
    seen_numbers: set[int] = set()
    seen_paths: set[Path] = set()
    for match in INDEX_ENTRY_RE.finditer(text):
        number = int(match.group("number").translate(ASCII_DIGITS))
        if number in seen_numbers:
            raise ValueError(f"Duplicate session number in Index: {number}")
        md_path = _resolve_session_path(index_path, notes_dir, match.group("link"))
        if md_path in seen_paths:
            raise ValueError(f"Duplicate session file in Index: {md_path.name}")
        if is_excluded_path(md_path):
            raise ValueError(f"Index points to a non-session file: {md_path.name}")
        meta = parse_frontmatter(md_path)
        source, source_pages, duration = _parse_details(match.group("details"))
        source = _first_metadata(meta, ("source", "source_pdf"), source)
        source_pages = _first_metadata(meta, ("source_pages", "pdf_pages", "pages", "page_range"), source_pages)
        duration = _first_metadata(meta, ("duration", "estimated_time", "time"), duration)
        title = normalize_space(match.group("title")) or _first_metadata(meta, ("title",), markdown_title(md_path))
        group_key, group_title = _group_identity(source, meta, number)
        focus = _first_metadata(meta, ("study_focus", "focus", "summary"), extract_study_focus(md_path))
        session = Session(
            number=number,
            title=title,
            markdown_path=md_path,
            stem=md_path.stem,
            source=source,
            source_pages=source_pages,
            duration=duration,
            study_focus=focus,
            group_key=group_key,
            group_title=group_title,
            destination=destination_name(number, md_path.stem),
        )
        sessions.append(session)
        seen_numbers.add(number)
        seen_paths.add(md_path)
    if not sessions:
        raise ValueError(f"No numbered session entries were found in Index: {index_path}")
    sessions.sort(key=lambda s: s.number)
    expected = list(range(sessions[0].number, sessions[0].number + len(sessions)))
    actual = [s.number for s in sessions]
    if actual != expected:
        raise ValueError(f"Session numbering in Index is not contiguous: {actual}")
    return sessions


def fallback_sessions(notes_dir: Path) -> list[Session]:
    paths = sorted((p for p in Path(notes_dir).glob("*.md") if is_session_markdown(p)), key=natural_key)
    sessions: list[Session] = []
    for idx, path in enumerate(paths, 1):
        meta = parse_frontmatter(path)
        number_match = TOPIC_FILENAME_RE.match(path.name)
        number = int(number_match.group(1)) if number_match else idx
        title = _first_metadata(meta, ("title",), markdown_title(path))
        source = _first_metadata(meta, ("source", "source_pdf"), "—")
        pages = _first_metadata(meta, ("source_pages", "pdf_pages", "pages", "page_range"), "—")
        group_key, group_title = _group_identity(source, meta, number)
        sessions.append(Session(number, title, path.resolve(), path.stem, source, pages, "—", "—", extract_study_focus(path), group_key, group_title, destination_name(number, path.stem)))
    return sessions


def group_sessions(sessions: Sequence[Session]) -> list[Group]:
    grouped: OrderedDict[str, Group] = OrderedDict()
    for session in sessions:
        if session.group_key not in grouped:
            grouped[session.group_key] = Group(session.group_key, session.group_title, [])
        grouped[session.group_key].sessions.append(session)
    return list(grouped.values())


def parse_range(value: str) -> tuple[int, int] | None:
    nums = [int(x) for x in re.findall(r"\d+", str(value).translate(ASCII_DIGITS))]
    if not nums:
        return None
    return min(nums), max(nums)


def pages_coverage(sessions: Sequence[Session], field_name: str) -> str:
    ranges = [parse_range(getattr(s, field_name)) for s in sessions]
    ranges = [r for r in ranges if r]
    if not ranges:
        return "—"
    return f"{min(r[0] for r in ranges)}-{max(r[1] for r in ranges)}"


def infer_course_title(index_path: Path, notes_dir: Path, explicit: str | None = None) -> str:
    if explicit and normalize_space(explicit) and normalize_space(explicit).casefold() != "study notes":
        return normalize_space(explicit)
    text = index_path.read_text(encoding="utf-8", errors="replace")
    match = H1_RE.search(text)
    if match:
        candidate = strip_markdown(match.group(1))
        if candidate.casefold() not in {"study index", "index", "فهرست مطالعه"}:
            return candidate
    name = normalize_space(notes_dir.name.replace("_", " ").replace("-", " "))
    return name.title() if name else "Study Notes"


