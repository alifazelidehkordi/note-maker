#!/usr/bin/env python3
"""Shared helpers for the final study-notes PDF pipeline."""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from pypdf import PdfReader

A4_WIDTH = 595.275590551
A4_HEIGHT = 841.88976378
A4_TOLERANCE = 3.0
DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
SESSION_FILE_RE = re.compile(r"^(\d{1,3})(?:_(\d{1,3}))?_.+\.md$", re.I)
EXCLUDED_TOKENS = {
    "readme", "study_index", "index", "verification", "qa_report", "quality",
    "combined", "final_study_notes", "temporary", "temp", "cache", "debug",
    "log", "boundaries", "structure", "inventory", "coverage", "manifest",
}


@dataclass
class Session:
    order: int
    title: str
    filename: str
    group: str
    pdf_pages: str = "—"
    book_pages: str = "—"
    duration: str = "—"
    focus: str = "—"
    scope: str = "—"
    density: str = "—"
    source_equivalents: str = "—"
    destination: str = ""
    note_path: Path | None = None

    def __post_init__(self) -> None:
        if not self.destination:
            stem = Path(self.filename).stem
            safe = re.sub(r"[^A-Za-z0-9_-]+", "-", stem).strip("-").lower()
            self.destination = f"session-{self.order:03d}-{safe}"


@dataclass
class StudyIndex:
    title: str
    sessions: list[Session] = field(default_factory=list)
    physical_pages: str = "—"
    total_minutes: str = "—"

    @property
    def groups(self) -> list[tuple[str, list[Session]]]:
        out: list[tuple[str, list[Session]]] = []
        for item in self.sessions:
            if not out or out[-1][0] != item.group:
                out.append((item.group, [item]))
            else:
                out[-1][1].append(item)
        return out

    @property
    def coverage(self) -> str:
        bounds: list[tuple[int, int]] = []
        for item in self.sessions:
            values = [int(x) for x in re.findall(r"\d+", item.pdf_pages.translate(DIGITS))]
            if values:
                bounds.append((min(values), max(values)))
        return f"{min(x[0] for x in bounds)}-{max(x[1] for x in bounds)}" if bounds else "—"


def natural_key(value: str | Path) -> tuple:
    name = Path(value).name.casefold()
    return tuple(int(part) if part.isdigit() else part for part in re.split(r"(\d+)", name))


def is_session_note(path: Path) -> bool:
    if not path.is_file() or path.suffix.casefold() != ".md" or path.name.startswith("."):
        return False
    name = path.stem.casefold()
    exact = {"readme", "study_index", "study_index-rewritten", "index", "qa_report", "boundaries", "structure", "coverage", "manifest"}
    prefixes = ("verification", "quality_report", "combined_", "final_", "temporary_", "temp_", "cache_", "debug_", "log_")
    if name in exact or name.startswith(prefixes):
        return False
    return bool(SESSION_FILE_RE.match(path.name))


def find_index_file(notes_dir: Path, explicit: Path | None = None) -> Path:
    if explicit:
        explicit = Path(explicit).resolve()
        if not explicit.is_file():
            raise FileNotFoundError(f"Index file not found: {explicit}")
        return explicit
    candidates = []
    for folder in (notes_dir, notes_dir.parent):
        if not folder.exists():
            continue
        for path in folder.glob("*.md"):
            lowered = path.name.casefold()
            if lowered in {"index.md", "study_index.md", "study_index-rewritten.md"}:
                candidates.append(path)
    if not candidates:
        raise FileNotFoundError(f"No Index Markdown found in or near {notes_dir}")
    preferred = {"index.md": 0, "study_index.md": 1, "study_index-rewritten.md": 2}
    return sorted(candidates, key=lambda p: (preferred.get(p.name.casefold(), 9), natural_key(p)))[0].resolve()


def _field(block: str, label: str) -> str:
    match = re.search(rf"(?mi)^-\s*\*\*{re.escape(label)}:\*\*\s*(.+?)\s*$", block)
    return match.group(1).strip() if match else "—"


def _parse_pdf_pages(value: str) -> tuple[str, str]:
    match = re.search(r"(\d+)\s*[-–]\s*(\d+)(?:\s*\(printed\s*(\d+)\s*[-–]\s*(\d+)\))?", value, re.I)
    if not match:
        return value.strip() or "—", "—"
    pdf_pages = f"{int(match.group(1))}-{int(match.group(2))}"
    book_pages = f"{int(match.group(3))}-{int(match.group(4))}" if match.group(3) else "—"
    return pdf_pages, book_pages


def parse_index(index_path: Path, notes_dir: Path) -> StudyIndex:
    text = index_path.read_text(encoding="utf-8", errors="strict")
    h1 = re.search(r"(?m)^#\s+(.+?)\s*$", text)
    title = h1.group(1).strip() if h1 else notes_dir.name.replace("_", " ").title()
    cleaned_title = re.sub(r"\s*(?:Study\s+Index|فهرست\s+مطالعه)\s*$", "", title, flags=re.I).strip()
    title = cleaned_title or title
    physical = _field(text, "Physical PDF pages")
    minutes = _field(text, "Approximate total study time")

    group = "Study Sections"
    sessions: list[Session] = []
    lines = text.splitlines()
    i = 0
    ignored_groups = {"package overview", "recommended sequence", "supplementary files", "notes"}
    while i < len(lines):
        line = lines[i]
        group_match = re.match(r"^##\s+(.+?)\s*$", line)
        if group_match:
            candidate = group_match.group(1).strip()
            if candidate.casefold() not in ignored_groups:
                group = candidate
            i += 1
            continue
        session_match = re.match(r"^###\s+(\d{1,3})\.\s+\[([^]]+)\]\(([^)]+\.md)\)\s*$", line)
        if not session_match:
            i += 1
            continue
        start = i + 1
        end = start
        while end < len(lines) and not re.match(r"^#{2,3}\s+", lines[end]):
            end += 1
        block = "\n".join(lines[start:end])
        order = int(session_match.group(1).translate(DIGITS))
        title_value = session_match.group(2).strip()
        filename = Path(session_match.group(3)).name
        raw_pages = _field(block, "PDF pages")
        pdf_pages, book_pages = _parse_pdf_pages(raw_pages)
        focus = _field(block, "Learning objective")
        if focus == "—":
            focus = _field(block, "Scope")
        session = Session(
            order=order,
            title=title_value,
            filename=filename,
            group=group,
            pdf_pages=pdf_pages,
            book_pages=book_pages,
            duration=_field(block, "Approximate study time"),
            focus=focus,
            scope=_field(block, "Scope"),
            density=_field(block, "Density"),
            source_equivalents=_field(block, "Substantive page-equivalents"),
        )
        sessions.append(session)
        i = end

    if not sessions:
        raise ValueError(f"No numbered study sessions could be parsed from {index_path}")

    note_files = [p for p in notes_dir.glob("*.md") if is_session_note(p)]
    by_name = {p.name.casefold(): p for p in note_files}
    by_number: dict[int, list[Path]] = {}
    for p in note_files:
        match = SESSION_FILE_RE.match(p.name)
        if match:
            by_number.setdefault(int(match.group(1)), []).append(p)

    missing = []
    used: set[Path] = set()
    for session in sessions:
        direct = by_name.get(session.filename.casefold())
        if direct is None:
            candidates = [p for p in by_number.get(session.order, []) if p not in used]
            direct = sorted(candidates, key=natural_key)[0] if candidates else None
        if direct is None:
            missing.append(f"{session.order}: {session.title} ({session.filename})")
        else:
            session.note_path = direct.resolve()
            used.add(direct)
    if missing:
        raise FileNotFoundError("Index sessions missing Markdown files:\n- " + "\n- ".join(missing))

    duplicates = [p for p in used if sum(1 for s in sessions if s.note_path == p) > 1]
    if duplicates:
        raise RuntimeError("Duplicate note assignment: " + ", ".join(str(p) for p in duplicates))

    extra = sorted(set(note_files) - used, key=natural_key)
    if extra:
        raise RuntimeError("Session Markdown files absent from Index: " + ", ".join(p.name for p in extra))

    sessions.sort(key=lambda s: s.order)
    expected = list(range(sessions[0].order, sessions[0].order + len(sessions)))
    actual = [s.order for s in sessions]
    if actual != expected:
        raise RuntimeError(f"Non-contiguous or duplicated session order: {actual}")
    return StudyIndex(title=title, sessions=sessions, physical_pages=physical, total_minutes=minutes)


def require_readable_file(path: Path, label: str) -> Path:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path}")
    try:
        with path.open("rb") as stream:
            stream.read(1)
    except OSError as exc:
        raise PermissionError(f"{label} is not readable: {path}: {exc}") from exc
    return path


def require_directory(path: Path, label: str) -> Path:
    path = Path(path).resolve()
    if not path.is_dir():
        raise NotADirectoryError(f"{label} not found: {path}")
    return path


def font_face_css(font_file: Path, font_bold_file: Path) -> str:
    regular = require_readable_file(font_file, "FONT_FILE").as_uri()
    bold = require_readable_file(font_bold_file, "FONT_BOLD_FILE").as_uri()
    return f"""
@font-face {{ font-family: StudyArabic; src: url('{regular}'); font-style: normal; font-weight: 400; }}
@font-face {{ font-family: StudyArabic; src: url('{regular}'); font-style: normal; font-weight: 700; }}
@font-face {{ font-family: StudyLatin; src: url('{bold if 'Bold' not in Path(bold).name else regular}'); font-style: normal; font-weight: 400; }}
@font-face {{ font-family: StudyLatin; src: url('{bold}'); font-style: normal; font-weight: 700; }}
"""


def escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def normalize_visual_glyphs(text: str) -> str:
    """Normalize two decorative arrows unsupported by the supplied fonts."""
    return text.replace("⮚", "→").replace("🡪", "→")


def page_index_from_destination(reader: PdfReader, destination) -> int:
    return reader.get_destination_page_number(destination)


def iter_outline_items(items: Iterable, level: int = 0):
    for item in items:
        if isinstance(item, list):
            yield from iter_outline_items(item, level + 1)
        else:
            yield level, item
