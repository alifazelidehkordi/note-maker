#!/usr/bin/env python3
"""Generate a bilingual, clickable Study Index from an existing source INDEX.

The existing INDEX is the primary data source. Frontmatter and note content are
used only for missing values. Links use note:// markers that are converted to
internal PDF destinations by create_combined_pdf.py.
"""
from __future__ import annotations

import argparse
import html
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote

import yaml

from pdf_common import ensure_unique, is_topic_markdown, natural_key

FRONT_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.S)
H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.M)
SESSION_RE = re.compile(r"^###\s+(\d+)\.\s+\[([^]]+)]\(([^)]+\.md)\)\s*$", re.M | re.I)
FIELD_RE = re.compile(r"^-\s+\*\*([^*]+):\*\*\s*(.*?)\s*$")
DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

SKIP_GROUPS = {"package overview", "recommended sequence", "supplementary material"}


@dataclass
class Session:
    order: int
    group_order: int
    group_title: str
    title: str
    note_path: Path
    source_pages: str = "—"
    book_pages: str = "—"
    duration: str = "—"
    focus: str = "—"
    scope: str = "—"

    @property
    def stem(self) -> str:
        return self.note_path.stem

    @property
    def destination_uri(self) -> str:
        return f"note://{quote(self.stem, safe='_-')}"


@dataclass
class SourceIndex:
    title: str
    sessions: list[Session]
    overview: dict[str, str]

    @property
    def groups(self) -> list[tuple[int, str, list[Session]]]:
        result: list[tuple[int, str, list[Session]]] = []
        for session in self.sessions:
            if not result or result[-1][0] != session.group_order:
                result.append((session.group_order, session.group_title, [session]))
            else:
                result[-1][2].append(session)
        return result


def _frontmatter(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {}
    match = FRONT_RE.match(text)
    if not match:
        return {}
    try:
        value = yaml.safe_load(match.group(1)) or {}
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _heading(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return path.stem.replace("_", " ").replace("-", " ").title()
    match = H1_RE.search(text)
    return match.group(1).strip() if match else path.stem.replace("_", " ").replace("-", " ").title()


def _excerpt(path: Path, limit: int = 220) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return "—"
    text = FRONT_RE.sub("", text, count=1)
    text = H1_RE.sub("", text, count=1)
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "|", "```", "---")):
            continue
        line = re.sub(r"\[([^]]+)]\([^)]+\)", r"\1", line)
        line = re.sub(r"[*_`>#]+", "", line)
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"
    return "—"


def _resolve_note(index_dir: Path, link: str, notes_dir: Path) -> Path:
    decoded = unquote(link).replace("\\", "/")
    candidates = [index_dir / decoded, notes_dir / decoded, notes_dir / Path(decoded).name]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    matches = list(notes_dir.rglob(Path(decoded).name))
    if len(matches) == 1:
        return matches[0].resolve()
    if len(matches) > 1:
        raise RuntimeError(f"Ambiguous note path in INDEX: {link}")
    raise FileNotFoundError(f"Session note referenced by INDEX was not found: {link}")


def _normalise_key(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


def _parse_pdf_pages(value: str) -> tuple[str, str]:
    source = value.strip() or "—"
    source_match = re.search(r"(\d+\s*[-–]\s*\d+|\d+)", source.translate(DIGITS))
    printed_match = re.search(r"printed\s+([^)]*)", source, re.I)
    source_pages = source_match.group(1).replace(" ", "-") if source_match else "—"
    source_pages = re.sub(r"-+", "-", source_pages)
    book_pages = printed_match.group(1).strip() if printed_match else "—"
    return source_pages, book_pages


def parse_source_index(index_path: Path, notes_dir: Path | None = None) -> SourceIndex:
    index_path = Path(index_path).resolve()
    if not index_path.is_file():
        raise FileNotFoundError(index_path)
    notes_dir = Path(notes_dir).resolve() if notes_dir else index_path.parent
    text = index_path.read_text(encoding="utf-8", errors="strict")
    title_match = H1_RE.search(text)
    raw_title = title_match.group(1).strip() if title_match else index_path.stem
    title = re.sub(r"\s+Study Index\s*$", "", raw_title, flags=re.I).strip() or raw_title

    overview: dict[str, str] = {}
    current_group = "Study Sections"
    group_order = 0
    sessions: list[Session] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("## "):
            candidate = line[3:].strip()
            if candidate.casefold() not in SKIP_GROUPS:
                current_group = candidate
                group_order += 1
            i += 1
            continue
        overview_match = FIELD_RE.match(line)
        if overview_match and not sessions:
            overview[_normalise_key(overview_match.group(1))] = overview_match.group(2).strip()
        session_match = SESSION_RE.match(line)
        if not session_match:
            i += 1
            continue
        if group_order == 0:
            group_order = 1
        order = int(session_match.group(1).translate(DIGITS))
        title_value = session_match.group(2).strip()
        note = _resolve_note(index_path.parent, session_match.group(3), notes_dir)
        fields: dict[str, str] = {}
        i += 1
        while i < len(lines) and not lines[i].startswith(("### ", "## ")):
            field_match = FIELD_RE.match(lines[i].strip())
            if field_match:
                fields[_normalise_key(field_match.group(1))] = field_match.group(2).strip()
            i += 1
        source_pages, book_pages = _parse_pdf_pages(fields.get("pdf pages", ""))
        meta = _frontmatter(note)
        title_final = title_value or str(meta.get("title") or _heading(note)).strip()
        source_pages = source_pages if source_pages != "—" else str(meta.get("pdf_pages") or meta.get("pages") or "—")
        book_pages = book_pages if book_pages != "—" else str(meta.get("book_pages") or "—")
        duration = fields.get("approximate study time") or str(meta.get("estimated_time") or meta.get("duration") or "—")
        focus = fields.get("learning objective") or fields.get("scope") or str(meta.get("study_focus") or meta.get("focus") or _excerpt(note))
        scope = fields.get("scope") or title_final
        sessions.append(Session(order, group_order, current_group, title_final, note, source_pages, book_pages, duration, focus, scope))

    if not sessions:
        topic_files = sorted((p for p in notes_dir.glob("*.md") if is_topic_markdown(p)), key=natural_key)
        for order, note in enumerate(topic_files, 1):
            sessions.append(Session(order, 1, "Study Sections", _heading(note), note, focus=_excerpt(note)))

    sessions.sort(key=lambda item: item.order)
    ensure_unique((str(item.order) for item in sessions), what="session numbers")
    ensure_unique((item.stem for item in sessions), what="session files")
    return SourceIndex(title=title, sessions=sessions, overview=overview)


def _bounds(values: list[str]) -> str:
    numbers: list[int] = []
    for value in values:
        numbers.extend(int(x) for x in re.findall(r"\d+", str(value).translate(DIGITS)))
    return f"{min(numbers)}-{max(numbers)}" if numbers else "—"


def _duration_minutes(value: str) -> int | None:
    text = str(value).translate(DIGITS).casefold()
    hours = re.search(r"(\d+(?:\.\d+)?)\s*(?:h|hr|hour|ساعت)", text)
    minutes = re.search(r"(\d+)\s*(?:m|min|minute|دقیقه)", text)
    if not hours and not minutes:
        return None
    return round(float(hours.group(1)) * 60) if hours and not minutes else ((round(float(hours.group(1)) * 60) if hours else 0) + (int(minutes.group(1)) if minutes else 0))


def _total_duration(sessions: list[Session]) -> str:
    values = [_duration_minutes(item.duration) for item in sessions]
    values = [value for value in values if value is not None]
    return f"{sum(values)} minutes" if values else "—"


def _cell(value: object) -> str:
    return html.escape(str(value), quote=True).replace("\n", "<br>")


def _text_dir(value: object) -> str:
    return "rtl" if re.search(r"[\u0600-\u06FF]", str(value)) else "ltr"


def _sessions_table(sessions: list[Session], *, persian: bool) -> str:
    headings = ("جلسه", "عنوان", "صفحات منبع", "صفحات کتاب", "زمان", "تمرکز مطالعه") if persian else ("Session", "Title", "Source pages", "Book pages", "Time", "Study focus")
    rows = []
    for item in sessions:
        rows.append(
            "<tr>"
            f'<td dir="ltr">{item.order}</td>'
            f'<td dir="{_text_dir(item.title)}"><a href="{_cell(item.destination_uri)}">{_cell(item.title)}</a></td>'
            f'<td dir="ltr">{_cell(item.source_pages)}</td>'
            f'<td dir="ltr">{_cell(item.book_pages)}</td>'
            f'<td dir="{_text_dir(item.duration)}">{_cell(item.duration)}</td>'
            f'<td dir="{_text_dir(item.focus)}">{_cell(item.focus)}</td>'
            "</tr>"
        )
    return (
        '<table class="study-index-table sessions-table">'
        "<thead><tr>" + "".join(f"<th>{_cell(value)}</th>" for value in headings) + "</tr></thead>"
        "<tbody>" + "".join(rows) + "</tbody></table>"
    )


def _groups_table(source: SourceIndex, *, persian: bool) -> str:
    headings = ("فصل/گروه", "جلسات", "تعداد", "صفحات منبع", "تمرکز") if persian else ("Chapter/Group", "Sessions", "Count", "Source pages", "Focus")
    rows = []
    for group_order, title, items in source.groups:
        session_span = str(items[0].order) if len(items) == 1 else f"{items[0].order}-{items[-1].order}"
        focus = "; ".join(item.scope for item in items[:3]) + ("; …" if len(items) > 3 else "")
        rows.append(
            "<tr>"
            f'<td dir="{_text_dir(title)}"><a href="#group-{group_order}">{_cell(title)}</a></td>'
            f'<td dir="ltr">{_cell(session_span)}</td><td dir="ltr">{len(items)}</td>'
            f'<td dir="ltr">{_cell(_bounds([item.source_pages for item in items]))}</td>'
            f'<td dir="{_text_dir(focus)}">{_cell(focus)}</td>'
            "</tr>"
        )
    return (
        '<table class="study-index-table groups-table">'
        "<thead><tr>" + "".join(f"<th>{_cell(value)}</th>" for value in headings) + "</tr></thead>"
        "<tbody>" + "".join(rows) + "</tbody></table>"
    )


def build_index_md(source: SourceIndex) -> str:
    coverage = _bounds([item.source_pages for item in source.sessions])
    total_time = source.overview.get("approximate total study time") or _total_duration(source.sessions)
    lines = [
        '<div class="index-cover" dir="rtl">',
        f"# فهرست مطالعه / Study Index",
        f"## {_cell(source.title)}",
        "</div>",
        '<div class="rtl-section" dir="rtl">',
        "## نمای کلی",
        f"- **عنوان دوره:** {_cell(source.title)}",
        f"- **تعداد کل جلسات:** {len(source.sessions)}",
        f"- **محدوده کلی صفحات:** {_cell(coverage)}",
        f"- **زمان تقریبی کل:** {_cell(total_time)}",
        "- عنوان هر جلسه قابل کلیک است و مستقیماً به اولین صفحه همان جلسه در PDF نهایی می‌رود.",
        "",
        "## جدول فصل‌ها و گروه‌ها",
        _groups_table(source, persian=True),
        "",
        "## جدول کامل جلسات",
        _sessions_table(source.sessions, persian=True),
        "</div>",
        '<div class="ltr-section" dir="ltr">',
        f"# {_cell(source.title)} Study Index",
        "## Overview",
        f"- **Course:** {_cell(source.title)}",
        f"- **Total sessions:** {len(source.sessions)}",
        f"- **Overall source-page range:** {_cell(coverage)}",
        f"- **Approximate total study time:** {_cell(total_time)}",
        "- Every session title is clickable and opens the first page of that session in the final PDF.",
        "",
        "## Chapters and groups",
        _groups_table(source, persian=False),
        "",
        "## Complete session table",
        _sessions_table(source.sessions, persian=False),
        "</div>",
        "",
        "# Session groups / گروه‌های جلسات",
    ]
    for group_order, title, items in source.groups:
        lines.extend([
            f'<section id="group-{group_order}" class="index-group" dir="auto">',
            f"## {_cell(title)}",
            _sessions_table(items, persian=False),
            "</section>",
        ])
    return "\n\n".join(lines).strip() + "\n"


def generate_index(index_path: Path, output: Path, *, notes_dir: Path | None = None) -> tuple[Path, SourceIndex]:
    source = parse_source_index(index_path, notes_dir=notes_dir)
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_index_md(source), encoding="utf-8")
    return output, source


def collect_parts(parts_dir: Path, clean_dir: Path | None = None, focus_map: dict | None = None) -> list[dict]:
    """Compatibility wrapper used by existing callers and tests."""
    del focus_map
    root = Path(clean_dir or parts_dir)
    index = next((p for p in (Path(parts_dir) / "INDEX.md", root / "INDEX.md") if p.is_file()), None)
    if index:
        source = parse_source_index(index, notes_dir=root)
        return [
            {
                "path": item.note_path,
                "display_path": item.note_path,
                "stem": item.stem,
                "chapter": item.group_order,
                "part": item.order,
                "title": item.title,
                "title_en": item.title,
                "pdf_pages": item.source_pages,
                "book_pages": item.book_pages,
                "duration": item.duration,
                "study_focus": item.focus,
                "study_focus_en": item.focus,
                "source": "",
                "chapter_title_fa": item.group_title,
                "chapter_title_en": item.group_title,
            }
            for item in source.sessions
        ]
    files = sorted((p for p in root.glob("*.md") if is_topic_markdown(p)), key=natural_key)
    return [
        {
            "path": path,
            "display_path": path,
            "stem": path.stem,
            "chapter": 1,
            "part": order,
            "title": _heading(path),
            "title_en": _heading(path),
            "pdf_pages": "—",
            "book_pages": "—",
            "duration": "—",
            "study_focus": _excerpt(path),
            "study_focus_en": _excerpt(path),
            "source": "",
            "chapter_title_fa": "Study Sections",
            "chapter_title_en": "Study Sections",
        }
        for order, path in enumerate(files, 1)
    ]


def group_by_chapter(parts: list[dict]) -> dict[int, list[dict]]:
    result: dict[int, list[dict]] = {}
    for part in parts:
        result.setdefault(int(part["chapter"]), []).append(part)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a bilingual clickable Study Index from an existing INDEX.md")
    parser.add_argument("--index", "--original-index", dest="index", required=True, help="Primary source INDEX.md")
    parser.add_argument("--notes-dir", "--clean-dir", dest="notes_dir")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output, source = generate_index(Path(args.index), Path(args.output), notes_dir=Path(args.notes_dir) if args.notes_dir else None)
    print(f"Generated rich index: {output}")
    print(f"Sessions: {len(source.sessions)}")
    print(f"Groups: {len(source.groups)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
