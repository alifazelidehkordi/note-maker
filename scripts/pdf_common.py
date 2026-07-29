#!/usr/bin/env python3
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import yaml

A4_WIDTH_PT = 595.275590551
A4_HEIGHT_PT = 841.88976378
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.S)
H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.M)
SESSION_NAME_RE = re.compile(r"^(\d{1,3})(?:_(\d{1,3}))?[_-]")
EXCLUDED_EXACT = {
    "readme.md", "index.md", "study_index.md", "study_index-rewritten.md",
    "study_index_verification.md", "qa_report.md", "boundaries.md", "structure.md",
    "combined_notes.md", "final_study_notes.pdf",
}
EXCLUDED_PARTS = (
    "verification", "quality", "diagnostic", "debug", "temporary", "intermediate",
    "cache", "manifest", "report",
)

@dataclass(frozen=True)
class Session:
    number: int
    title: str
    filename: str
    stem: str
    group: str
    pdf_pages: str
    book_pages: str
    study_focus: str
    duration: str
    note_path: Path

    @property
    def anchor(self) -> str:
        return f"session-{self.number:03d}-{quote(self.stem, safe='_-')}"


def natural_key(value: str | Path) -> tuple:
    name = Path(value).name.casefold()
    return tuple(int(x) if x.isdigit() else x for x in re.split(r"(\d+)", name))


def is_session_file(path: Path) -> bool:
    if not path.is_file() or path.suffix.casefold() != ".md":
        return False
    name = path.name.casefold()
    if name.startswith(".") or name in EXCLUDED_EXACT:
        return False
    if any(part in name for part in EXCLUDED_PARTS):
        return False
    return SESSION_NAME_RE.match(path.name) is not None


def read_frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="strict")
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}
    data = yaml.safe_load(match.group(1)) or {}
    return data if isinstance(data, dict) else {}


def strip_frontmatter(text: str) -> str:
    return FRONTMATTER_RE.sub("", text, count=1).lstrip()


def first_h1(path: Path) -> str:
    text = strip_frontmatter(path.read_text(encoding="utf-8", errors="strict"))
    match = H1_RE.search(text)
    return match.group(1).strip() if match else path.stem.replace("_", " ").replace("-", " ").title()


def locate_index(notes_dir: Path) -> Path:
    candidates = [
        notes_dir / "INDEX.md", notes_dir / "Index.md", notes_dir / "index.md",
        notes_dir / "STUDY_INDEX.md", notes_dir / "STUDY_INDEX-rewritten.md",
    ]
    for path in candidates:
        if path.is_file():
            return path
    for path in sorted(notes_dir.glob("*.md"), key=natural_key):
        if "index" in path.stem.casefold() and path.is_file():
            return path
    raise FileNotFoundError(f"No Index Markdown found in {notes_dir}")


def validate_required_paths(*paths: Path) -> None:
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(path)
        if path.is_file() and not path.stat().st_size:
            raise ValueError(f"Required file is empty: {path}")
