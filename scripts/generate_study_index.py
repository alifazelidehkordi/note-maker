#!/usr/bin/env python3
"""Build a bilingual, data-driven Study Index from the source INDEX.md.

The source INDEX.md is authoritative. Markdown frontmatter/content are used only
for missing values. Session links intentionally use note:// markers; the final
merge step rewrites them to PDF destinations.
"""
from __future__ import annotations

import argparse
import json
import re
from html import escape as html_escape
from collections import OrderedDict
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import quote

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover
    yaml = None

DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
FRONT_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.S)
H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.M)
SESSION_RE = re.compile(
    r"^###\s+(?P<number>\d{1,3})\.\s+\[(?P<title>[^\]]+)\]\((?P<link>[^)]+\.md)\)\s*$"
    r"(?P<body>.*?)(?=^###\s+\d{1,3}\.\s+|\Z)",
    re.M | re.S,
)
FIELD_RE = re.compile(r"^-\s+\*\*(?P<key>[^*]+):\*\*\s*(?P<value>.+?)\s*$", re.M)
EXCLUDED_NAMES = {
    "readme.md", "index.md", "study_index.md", "study_index-rewritten.md",
    "study_index_verification.md", "qa_report.md", "structure.md", "boundaries.md",
    "combined_notes.md", "verification.md",
}


@dataclass(frozen=True)
class Session:
    number: int
    title: str
    title_fa: str
    note_path: str
    stem: str
    group: str
    group_fa: str
    source_pages: str
    book_pages: str
    duration: str
    focus: str
    key_concepts: str


@dataclass(frozen=True)
class StudyData:
    course_title: str
    total_sessions: int
    overall_source_pages: str
    overall_book_pages: str
    total_study_time: str
    sessions: list[Session]


def natural_key(value: str | Path) -> tuple:
    name = Path(value).name.casefold()
    return tuple(int(x) if x.isdigit() else x for x in re.split(r"(\d+)", name))


def _frontmatter(path: Path) -> dict:
    if not path.is_file() or yaml is None:
        return {}
    match = FRONT_RE.match(path.read_text(encoding="utf-8", errors="ignore"))
    if not match:
        return {}
    try:
        value = yaml.safe_load(match.group(1)) or {}
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _heading(path: Path) -> str:
    if not path.is_file():
        return path.stem.replace("_", " ").replace("-", " ").strip().title()
    match = H1_RE.search(path.read_text(encoding="utf-8", errors="ignore"))
    return match.group(1).strip() if match else path.stem.replace("_", " ").replace("-", " ").title()


def is_topic_note(path: Path) -> bool:
    name = path.name.casefold()
    if not path.is_file() or path.suffix.casefold() != ".md" or name in EXCLUDED_NAMES:
        return False
    if name.startswith(("study_index", "combined_", ".", "~")):
        return False
    return bool(re.match(r"^\d{1,3}(?:_\d{1,3})?[_-]", path.stem))


def _field_map(body: str) -> dict[str, str]:
    return {m.group("key").strip().casefold(): m.group("value").strip() for m in FIELD_RE.finditer(body)}


def _first(mapping: dict, *keys: str, default: str = "") -> str:
    for key in keys:
        value = mapping.get(key.casefold())
        if value not in (None, ""):
            return str(value).strip()
    return default


def _find_note(notes_dir: Path, link: str, number: int) -> Path:
    candidate = notes_dir / Path(link).name
    if candidate.is_file():
        return candidate
    matches = sorted(notes_dir.glob(f"{number:02d}_*.md"), key=natural_key)
    if not matches:
        matches = sorted(notes_dir.glob(f"{number}_*.md"), key=natural_key)
    if not matches:
        raise FileNotFoundError(f"Session {number} from INDEX.md has no Markdown file in {notes_dir}")
    if len(matches) > 1:
        raise ValueError(f"Session {number} maps to multiple Markdown files: {[p.name for p in matches]}")
    return matches[0]


def _range_bounds(value: str) -> tuple[int, int] | None:
    nums = [int(x) for x in re.findall(r"\d+", str(value).translate(DIGITS))]
    return (min(nums), max(nums)) if nums else None


def coverage(values: list[str]) -> str:
    bounds = [b for value in values if (b := _range_bounds(value))]
    return f"{min(x[0] for x in bounds)}-{max(x[1] for x in bounds)}" if bounds else "—"


def parse_source_index(index_path: Path, notes_dir: Path) -> StudyData:
    index_path = Path(index_path).resolve()
    notes_dir = Path(notes_dir).resolve()
    text = index_path.read_text(encoding="utf-8", errors="strict")
    title_match = H1_RE.search(text)
    raw_title = title_match.group(1).strip() if title_match else "Study Notes"
    course_title = re.sub(r"^Index\s*[-—–:]\s*", "", raw_title, flags=re.I).strip() or raw_title

    overview = _field_map(text.split("## Numbered study sequence", 1)[0])
    total_time = _first(overview, "Approximate total study time", default="—")
    declared_total = _first(overview, "Numbered study parts", default="0")

    sessions: list[Session] = []
    for match in SESSION_RE.finditer(text):
        number = int(match.group("number"))
        fields = _field_map(match.group("body"))
        note = _find_note(notes_dir, match.group("link"), number)
        meta = {str(k).casefold(): v for k, v in _frontmatter(note).items()}
        title = match.group("title").strip() or _first(meta, "title", default=_heading(note))
        title_fa = _first(meta, "title_fa", "persian_title", default=title)
        group = _first(fields, "Major division", default=_first(meta, "chapter_title_en", "group", default="Study Sections"))
        group_fa = _first(meta, "chapter_title_fa", "group_title_fa", default=group)
        source_pages = _first(fields, "PDF pages", default=_first(meta, "pdf_pages", "pages", default="—"))
        book_pages = _first(fields, "Book pages", default=_first(meta, "book_pages", default="—"))
        duration = _first(fields, "Approximate study time", default=_first(meta, "estimated_time", "duration", default="—"))
        focus = _first(fields, "Scope/objective", default=_first(meta, "study_focus", "focus", default="—"))
        key_concepts = _first(fields, "Key concepts and skills", default=_first(meta, "key_concepts", default="—"))
        sessions.append(Session(number, title, title_fa, str(note), note.stem, group, group_fa, source_pages, book_pages, duration, focus, key_concepts))

    if not sessions:
        raise ValueError(f"No numbered sessions found in source Index: {index_path}")
    sessions.sort(key=lambda s: s.number)
    numbers = [s.number for s in sessions]
    if len(numbers) != len(set(numbers)):
        raise ValueError("Duplicate session numbers found in source Index")
    expected = list(range(min(numbers), max(numbers) + 1))
    if numbers != expected:
        raise ValueError(f"Non-contiguous session numbering in source Index: {numbers}")
    if declared_total.isdigit() and int(declared_total) != len(sessions):
        raise ValueError(f"Index declares {declared_total} sessions but {len(sessions)} were parsed")

    return StudyData(
        course_title=course_title,
        total_sessions=len(sessions),
        overall_source_pages=coverage([s.source_pages for s in sessions]),
        overall_book_pages=coverage([s.book_pages for s in sessions]),
        total_study_time=total_time,
        sessions=sessions,
    )


def group_sessions(sessions: list[Session]) -> OrderedDict[str, list[Session]]:
    groups: OrderedDict[str, list[Session]] = OrderedDict()
    for session in sessions:
        groups.setdefault(session.group, []).append(session)
    return groups


def _escape_cell(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip() or "—"


def _bi(fa: str, en: str) -> str:
    return (
        f'<span dir="rtl">{html_escape(fa)}</span> / '
        f'<span dir="ltr">{html_escape(en)}</span>'
    )


def build_index_markdown(data: StudyData) -> str:
    groups = group_sessions(data.sessions)
    lines = [
        "---",
        "document_type: study_index",
        f"course_title: {json.dumps(data.course_title, ensure_ascii=False)}",
        f"total_sessions: {data.total_sessions}",
        "---",
        "",
        f"# {_bi('فهرست مطالعه', f'Study Index — {data.course_title}')}",
        "",
        '> <span dir="rtl"><strong>راهنما:</strong> عنوان هر جلسه قابل کلیک است و مستقیماً به نخستین صفحه همان جلسه در PDF نهایی می‌رود.</span>',
        ">",
        '> <span dir="ltr"><strong>Guide:</strong> Every session title is clickable and opens the first page of that session in the final PDF.</span>',
        "",
        f"## {_bi('نمای کلی', 'Overview')}",
        "",
        f"| {_bi('شاخص', 'Metric')} | {_bi('مقدار', 'Value')} |",
        "|---|---:|",
        f"| {_bi('عنوان دوره', 'Course')} | {_escape_cell(data.course_title)} |",
        f"| {_bi('تعداد کل جلسات', 'Total sessions')} | {data.total_sessions} |",
        f"| {_bi('محدوده صفحات منبع', 'Source PDF pages')} | {_escape_cell(data.overall_source_pages)} |",
        f"| {_bi('محدوده صفحات کتاب', 'Book pages')} | {_escape_cell(data.overall_book_pages)} |",
        f"| {_bi('زمان تقریبی کل', 'Estimated total study time')} | {_escape_cell(data.total_study_time)} |",
        "",
        f"## {_bi('فصل‌ها و گروه‌ها', 'Chapters and Groups')}",
        "",
        f"| # | {_bi('فصل یا گروه', 'Chapter or group')} | {_bi('جلسات', 'Sessions')} | {_bi('صفحات منبع', 'Source pages')} | {_bi('صفحات کتاب', 'Book pages')} |",
        "|---:|---|---:|---:|---:|",
    ]
    for index, (group, items) in enumerate(groups.items(), 1):
        first, last = items[0].number, items[-1].number
        span = str(first) if first == last else f"{first}-{last}"
        group_fa = items[0].group_fa
        group_display = _escape_cell(group) if group_fa == group else _bi(group_fa, group)
        lines.append(
            f"| {index} | [{group_display}](#chapter-{index:03d}) | {span} | "
            f"{coverage([x.source_pages for x in items])} | {coverage([x.book_pages for x in items])} |"
        )

    lines += ["", f"## {_bi('جدول کامل جلسات', 'Complete Session Table')}", ""]
    for index, (group, items) in enumerate(groups.items(), 1):
        group_fa = items[0].group_fa
        bilingual = _escape_cell(group) if group_fa == group else _bi(group_fa, group)
        lines += [
            f'<a id="chapter-{index:03d}"></a>',
            f"### {index}. {bilingual}",
            "",
            f"| {_bi('جلسه', 'Session')} | {_bi('عنوان', 'Title')} | {_bi('صفحات منبع', 'Source pages')} | {_bi('صفحات کتاب', 'Book pages')} | {_bi('زمان', 'Time')} | {_bi('تمرکز مطالعه', 'Study focus')} |",
            "|---:|---|---:|---:|---:|---|",
        ]
        for session in items:
            uri = f"note://{quote(session.stem, safe='_-')}"
            title = _escape_cell(session.title) if session.title_fa == session.title else _bi(session.title_fa, session.title)
            lines.append(
                f"| {session.number} | [{title}]({uri}) | {_escape_cell(session.source_pages)} | "
                f"{_escape_cell(session.book_pages)} | {_escape_cell(session.duration)} | {_escape_cell(session.focus)} |"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def generate_index(source_index: Path, notes_dir: Path, output: Path, metadata_output: Path | None = None) -> tuple[Path, StudyData]:
    data = parse_source_index(source_index, notes_dir)
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_index_markdown(data), encoding="utf-8")
    if metadata_output:
        meta_path = Path(metadata_output).resolve()
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps(asdict(data), ensure_ascii=False, indent=2), encoding="utf-8")
    return output, data


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a bilingual Study Index from the authoritative INDEX.md")
    parser.add_argument("--source-index", "--original-index", dest="source_index", required=True)
    parser.add_argument("--notes-dir", "--clean-dir", dest="notes_dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--metadata-output")
    args = parser.parse_args()
    output, data = generate_index(Path(args.source_index), Path(args.notes_dir), Path(args.output), Path(args.metadata_output) if args.metadata_output else None)
    print(f"Generated Study Index: {output}")
    print(f"Sessions: {data.total_sessions}")
    print(f"Source page range: {data.overall_source_pages}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
