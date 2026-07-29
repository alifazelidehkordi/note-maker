#!/usr/bin/env python3
"""Index-first bilingual study-index generation with legacy API compatibility."""
from __future__ import annotations

import argparse
import html
import re
from collections import OrderedDict, defaultdict
from pathlib import Path
from urllib.parse import quote

import yaml

from pdf_common import Session, first_h1, is_session_file, locate_index, natural_key, read_frontmatter

INDEX_H1_RE = re.compile(r"^#\s+(?:Index\s*[—:-]\s*)?(.+?)\s*$", re.M | re.I)
ENTRY_RE = re.compile(r"^###\s+(\d{1,3})\.\s+\[([^\]]+)\]\(([^)]+)\)\s*$(.*?)(?=^###\s+\d{1,3}\.\s+\[|^##\s+Excluded pages|\Z)", re.M | re.S)
FIELD_RE = re.compile(r"^-\s+\*\*([^*]+):\*\*\s*(.*?)\s*$", re.M)
TOTAL_RE = re.compile(r"^-\s+\*\*Numbered study parts:\*\*\s*(\d+)", re.M | re.I)
OVERALL_RE = re.compile(r"^-\s+\*\*Total PDF pages:\*\*\s*([^\n]+)", re.M | re.I)


def _field_map(block: str) -> dict[str, str]:
    return {key.strip().casefold(): value.strip() for key, value in FIELD_RE.findall(block)}


def _note_map(notes_dir: Path) -> dict[str, Path]:
    result = {}
    for path in notes_dir.glob("*.md"):
        if is_session_file(path):
            result[path.name.casefold()] = path
            result[path.stem.casefold()] = path
    return result


def parse_index(index_path: Path, notes_dir: Path) -> tuple[str, str, list[Session]]:
    """Parse the prepared Index as the primary source of ordering and metadata."""
    text = Path(index_path).read_text(encoding="utf-8", errors="strict")
    title_match = INDEX_H1_RE.search(text)
    course_title = title_match.group(1).strip() if title_match else "Study Notes"
    overall_match = OVERALL_RE.search(text)
    overall_pages = overall_match.group(1).strip() if overall_match else "—"
    note_map = _note_map(Path(notes_dir))
    sessions, missing = [], []
    for number_raw, title, target, block in ENTRY_RE.findall(text):
        number = int(number_raw)
        fields = _field_map(block)
        target_name = Path(target).name
        note = note_map.get(target_name.casefold()) or note_map.get(Path(target_name).stem.casefold())
        if note is None:
            candidates = [p for p in sorted(Path(notes_dir).glob(f"{number:02d}_*.md"), key=natural_key) if is_session_file(p)]
            note = candidates[0] if len(candidates) == 1 else None
        if note is None:
            missing.append(f"{number:02d}: {target}")
            continue
        meta = read_frontmatter(note)
        sessions.append(Session(
            number=number,
            title=title.strip() or first_h1(note),
            filename=note.name,
            stem=note.stem,
            group=(fields.get("major division") or str(meta.get("chapter_title_en") or meta.get("group") or "Study Sections")).strip(),
            pdf_pages=(fields.get("pdf pages") or str(meta.get("pdf_pages") or "—")).strip(),
            book_pages=(fields.get("book pages") or str(meta.get("book_pages") or "—")).strip(),
            study_focus=(fields.get("scope/objective") or str(meta.get("study_focus") or "—")).strip(),
            duration=(fields.get("approximate study time") or str(meta.get("duration") or "—")).strip(),
            note_path=note,
        ))
    if missing:
        raise RuntimeError("Index entries without matching note files: " + "; ".join(missing))
    sessions.sort(key=lambda item: item.number)
    expected_match = TOTAL_RE.search(text)
    expected = int(expected_match.group(1)) if expected_match else len(sessions)
    if len(sessions) != expected:
        raise RuntimeError(f"Index/session count mismatch: index={expected}, parsed={len(sessions)}")
    numbers = [item.number for item in sessions]
    if len(numbers) != len(set(numbers)):
        raise RuntimeError("Duplicate session numbers in Index")
    return course_title, overall_pages, sessions


def group_sessions(sessions: list[Session]) -> OrderedDict[str, list[Session]]:
    groups: OrderedDict[str, list[Session]] = OrderedDict()
    for session in sessions:
        groups.setdefault(session.group, []).append(session)
    return groups


def build_study_index_html(course_title: str, overall_pages: str, sessions: list[Session]) -> str:
    groups, esc = group_sessions(sessions), html.escape
    group_rows = []
    for idx, (name, items) in enumerate(groups.items(), 1):
        session_span = str(items[0].number) if len(items) == 1 else f"{items[0].number}-{items[-1].number}"
        page_span = f"{items[0].pdf_pages.split('–')[0].split('-')[0]}-{items[-1].pdf_pages.split('–')[-1].split('-')[-1]}"
        group_rows.append(f'<tr><td>{idx}</td><td>{esc(name)}</td><td>{esc(session_span)}</td><td>{esc(page_span)}</td><td>{len(items)}</td></tr>')
    session_rows = []
    for session in sessions:
        session_rows.append(
            f'<tr><td>{session.number}</td><td class="session-link"><a href="#{esc(session.anchor)}">{esc(session.title)}</a></td>'
            f'<td>{esc(session.pdf_pages)}</td><td>{esc(session.book_pages)}</td><td>{esc(session.duration)}</td><td class="focus">{esc(session.study_focus)}</td></tr>'
        )
    return f'''
<section id="study-index" class="study-index">
<h1 class="index-bookmark">فهرست مطالعه / Study Index</h1>
<div class="cover-card"><div class="eyebrow">LABORATORY MEDICINE · STUDY BOOK</div><h2>{esc(course_title)}</h2>
<p class="lead-fa" lang="fa" dir="rtl">فهرست یکپارچه‌ی جلسات با لینک داخلی، بوک‌مارک سلسله‌مراتبی و شماره‌گذاری پیوسته</p>
<div class="metrics"><div><strong>{len(sessions)}</strong><span>جلسه / Sessions</span></div><div><strong>{len(groups)}</strong><span>فصل / Groups</span></div><div><strong>{esc(overall_pages)}</strong><span>صفحات منبع / Source pages</span></div></div></div>
<div class="index-intro" lang="fa" dir="rtl"><h2>راهنمای استفاده</h2><p>عنوان هر جلسه در جدول زیر قابل‌کلیک است و مستقیماً به نخستین صفحه‌ی همان جلسه منتقل می‌شود. بوک‌مارک‌های PDF نیز فصل‌ها و جلسات را به همان ترتیب نمایش می‌دهند.</p></div>
<h2>فصل‌ها و گروه‌ها / Chapters and Groups</h2><table class="groups-table"><thead><tr><th>#</th><th>فصل / Group</th><th>جلسات / Sessions</th><th>صفحات منبع / Source pages</th><th>تعداد / Count</th></tr></thead><tbody>{''.join(group_rows)}</tbody></table>
<h2>جدول کامل جلسات / Complete Session Table</h2><table class="sessions-table"><thead><tr><th>#</th><th>عنوان جلسه / Session title</th><th>صفحات منبع / Source</th><th>صفحات کتاب / Book</th><th>زمان / Time</th><th>تمرکز مطالعه / Study focus</th></tr></thead><tbody>{''.join(session_rows)}</tbody></table>
</section>'''


# Legacy rich-index API retained for existing callers.
FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.S)
H1 = re.compile(r"^#\s+(.+?)\s*$", re.M)
NAME = re.compile(r"^(\d{1,3})(?:_(\d{1,3}))?_(.+)$")
PP = re.compile(r"(?:^|_)pp(\d{1,4})[-–](\d{1,4})(?:_|$)", re.I)
DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
META_NAMES = {"index.md", "readme.md", "study_index.md", "study_index-rewritten.md", "study_index_verification.md", "combined_notes.md", "qa_report.md", "boundaries.md", "structure.md"}


def is_note(path: Path) -> bool:
    name = path.name.casefold()
    return path.is_file() and path.suffix.casefold() == ".md" and name not in META_NAMES and not name.startswith(("study_index", "combined_notes", "."))


def frontmatter(path: Path) -> dict:
    match = FRONT.match(path.read_text(encoding="utf-8", errors="ignore"))
    if not match:
        return {}
    try:
        data = yaml.safe_load(match.group(1)) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def heading(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="ignore")
    match = H1.search(text)
    if match:
        return match.group(1).strip()
    match = NAME.match(path.stem)
    return (match.group(3) if match else path.stem).replace("_", " ").replace("-", " ").strip().title()


def first(meta: dict, *keys: str, default=None):
    for key in keys:
        if meta.get(key) not in (None, ""):
            return meta[key]
    return default


def integer(value, default: int) -> int:
    try:
        return int(str(value).translate(DIGITS))
    except (TypeError, ValueError):
        return default


def excerpt(path: Path, limit: int = 180) -> str:
    text = H1.sub("", FRONT.sub("", path.read_text(encoding="utf-8", errors="ignore"), count=1), count=1)
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("|", "---", "```", "#")):
            continue
        line = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", line)
        line = re.sub(r"[*_`>#]+", "", line)
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            return line if len(line) <= limit else line[:limit - 1].rstrip() + "…"
    return "مرور نکات کلیدی، سازوکارها و کاربردهای این بخش"


def collect_parts(parts_dir: Path, clean_dir: Path | None = None, focus_map: dict | None = None) -> list[dict]:
    focus_map = focus_map or {}
    result = []
    for order, source in enumerate(sorted((p for p in Path(parts_dir).glob("*.md") if is_note(p)), key=natural_key), 1):
        display = Path(clean_dir) / source.name if clean_dir else source
        if not display.is_file():
            display = source
        meta = frontmatter(source)
        if display != source:
            meta.update({k: v for k, v in frontmatter(display).items() if v not in (None, "")})
        match = NAME.match(source.stem)
        n1 = int(match.group(1)) if match else order
        n2 = int(match.group(2)) if match and match.group(2) else None
        page_value = first(meta, "pdf_pages", "pages", "page_range")
        if page_value in (None, ""):
            page_match = PP.search(source.stem)
            page_value = f"{page_match.group(1)}-{page_match.group(2)}" if page_match else "—"
        title = str(first(meta, "title", default=heading(display))).strip()
        result.append({
            "path": source, "display_path": display, "stem": display.stem,
            "chapter": integer(first(meta, "chapter", "group"), n1 if n2 else 1),
            "part": integer(first(meta, "part", "session", "section"), n2 or n1),
            "title": title, "title_en": str(first(meta, "title_en", "english_title", default=title)).strip(),
            "pdf_pages": str(page_value).strip(), "book_pages": str(first(meta, "book_pages", default="—")).strip(),
            "duration": str(first(meta, "estimated_time", "duration", "time", default="—")).strip(),
            "study_focus": str(focus_map.get(source.name, first(meta, "study_focus", "focus", default=excerpt(display)))).strip(),
            "study_focus_en": str(first(meta, "study_focus_en", "focus_en", default=focus_map.get(source.name, first(meta, "study_focus", "focus", default=excerpt(display))))).strip(),
            "source": str(first(meta, "source", "source_pdf", default="")).strip(),
            "chapter_title_fa": str(first(meta, "chapter_title_fa", "chapter_title", "group_title", default="")).strip(),
            "chapter_title_en": str(first(meta, "chapter_title_en", "group_title_en", default="")).strip(),
        })
    return sorted(result, key=lambda item: (item["chapter"], item["part"], natural_key(item["display_path"])))


def group_by_chapter(parts: list[dict]) -> dict[int, list[dict]]:
    result: dict[int, list[dict]] = defaultdict(list)
    for part in parts:
        result[int(part["chapter"])].append(part)
    return dict(sorted(result.items()))


def bounds(value: str) -> tuple[int, int] | None:
    nums = [int(item) for item in re.findall(r"\d+", str(value).translate(DIGITS))]
    return (min(nums), max(nums)) if nums else None


def coverage(parts: list[dict]) -> str:
    values = [value for value in (bounds(part["pdf_pages"]) for part in parts) if value]
    return f"{min(v[0] for v in values)}-{max(v[1] for v in values)}" if values else "—"


def duration_minutes(value: str) -> int | None:
    text = str(value).translate(DIGITS).casefold()
    hours = re.search(r"(\d+(?:\.\d+)?)\s*(?:h|hr|hour|ساعت)", text)
    minutes = re.search(r"(\d+)\s*(?:m|min|minute|دقیقه)", text)
    if not hours and not minutes:
        plain = re.fullmatch(r"\s*(\d+)\s*", text)
        return int(plain.group(1)) if plain else None
    return (round(float(hours.group(1)) * 60) if hours else 0) + (int(minutes.group(1)) if minutes else 0)


def format_duration(minutes: int | None, english: bool = False) -> str:
    if minutes is None:
        return "—"
    hours, mins = divmod(minutes, 60)
    if english:
        return f"{hours} h {mins} min" if hours and mins else (f"{hours} h" if hours else f"{mins} min")
    return f"{hours} ساعت و {mins} دقیقه" if hours and mins else (f"{hours} ساعت" if hours else f"{mins} دقیقه")


def chapter_name(number: int, items: list[dict], count: int, english: bool = False) -> str:
    key = "chapter_title_en" if english else "chapter_title_fa"
    explicit = next((item[key] for item in items if item.get(key)), None)
    return explicit or (("Study Sections" if english else "بخش‌های مطالعه") if count == 1 else (f"Chapter {number}" if english else f"فصل {number}"))


def topic_summary(items: list[dict], english: bool = False) -> str:
    titles = [item["title_en" if english else "title"] for item in items]
    return "، ".join(titles[:3]) + ("، …" if len(titles) > 3 else "")


def span(items: list[dict]) -> str:
    return str(items[0]["part"]) if items[0]["part"] == items[-1]["part"] else f"{items[0]['part']}-{items[-1]['part']}"


def total_time(items: list[dict]) -> int | None:
    values = [duration_minutes(item["duration"]) for item in items]
    return sum(value for value in values if value is not None) if any(value is not None for value in values) else None


def link(part: dict) -> str:
    return f"note://{quote(part['stem'], safe='_-')}"


def build_index_md(parts: list[dict], clean_dir: Path | None = None, course_title: str = "Study Notes") -> str:
    del clean_dir
    if not parts:
        raise ValueError("No Markdown topic notes were found for the study index.")
    chapters = group_by_chapter(parts)
    lines = [f"# فهرست مطالعه {course_title}", "", f"- تعداد جلسات مطالعه: {len(parts)}", f"- پوشش کلی جلسات: صفحات {coverage(parts)}", "", "## فهرست فصل‌ها و گروه‌ها", ""]
    for number, items in chapters.items():
        lines += [f"## {chapter_name(number, items, len(chapters))}", "", "| جلسه | موضوع | صفحات PDF | صفحات کتاب | زمان | تمرکز مطالعه |", "|---:|---|---:|---:|---:|---|"]
        for part in items:
            lines.append(f"| {part['part']} | [{part['title']}]({link(part)}) | {part['pdf_pages']} | {part['book_pages']} | {part['duration']} | {part['study_focus']} |")
        lines.append("")
    lines += ["---", "", f"# {course_title} Study Index", "", f"- Total study sessions: {len(parts)}", f"- Overall coverage: PDF pages {coverage(parts)}", ""]
    return "\n".join(lines).rstrip() + "\n"


def load_original_index(path: Path) -> dict:
    if not path.exists():
        return {}
    result = {}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = re.search(r"\[[^]]+\]\(([^)]+\.md)\)", line, re.I)
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if match and len(cells) >= 4:
            result[Path(match.group(1)).name] = cells[-1]
    return result


def generate_index(parts_dir: Path, output: Path, *, clean_dir: Path | None = None, original_index: Path | None = None, title: str = "Study Notes") -> Path:
    parts = collect_parts(parts_dir, clean_dir, load_original_index(original_index) if original_index else None)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_index_md(parts, course_title=title), encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a rich study index")
    parser.add_argument("--parts-dir"); parser.add_argument("--notes-dir"); parser.add_argument("--clean-dir"); parser.add_argument("--original-index"); parser.add_argument("--index"); parser.add_argument("--output", required=True); parser.add_argument("--title", default="Study Notes")
    args = parser.parse_args()
    if args.notes_dir:
        notes_dir = Path(args.notes_dir); index_path = Path(args.index) if args.index else locate_index(notes_dir)
        title, pages, sessions = parse_index(index_path, notes_dir)
        Path(args.output).write_text(build_study_index_html(title, pages, sessions), encoding="utf-8")
        return 0
    if not args.parts_dir:
        parser.error("--parts-dir or --notes-dir is required")
    generate_index(Path(args.parts_dir), Path(args.output), clean_dir=Path(args.clean_dir) if args.clean_dir else None, original_index=Path(args.original_index) if args.original_index else None, title=args.title)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
