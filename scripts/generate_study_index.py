#!/usr/bin/env python3
"""Generate a structured bilingual STUDY_INDEX.md for split study notes.

Links use ``note://<note-stem>`` markers. create_combined_pdf.py rewrites
those markers to internal destinations in the final merged PDF.
"""
from __future__ import annotations

import argparse
import re
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

import yaml

FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.S)
H1 = re.compile(r"^#\s+(.+?)\s*$", re.M)
NAME = re.compile(r"^(\d{1,3})(?:_(\d{1,3}))?_(.+)$")
PP = re.compile(r"(?:^|_)pp(\d{1,4})[-–](\d{1,4})(?:_|$)", re.I)
DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
META_NAMES = {"study_index.md", "study_index-rewritten.md", "study_index_verification.md", "combined_notes.md", "readme.md"}


def natural_key(path: Path) -> tuple:
    return tuple(int(x) if x.isdigit() else x for x in re.split(r"(\d+)", path.name.casefold()))


def is_note(path: Path) -> bool:
    name = path.name.casefold()
    return path.is_file() and path.suffix.casefold() == ".md" and name not in META_NAMES and not name.startswith(("study_index", "combined_notes", "."))


def frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="ignore")
    match = FRONT.match(text)
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
    raw = match.group(3) if match else path.stem
    return raw.replace("_", " ").replace("-", " ").strip().title()


def first(meta: dict, *keys: str, default=None):
    for key in keys:
        value = meta.get(key)
        if value not in (None, ""):
            return value
    return default


def integer(value, default: int) -> int:
    try:
        return int(str(value).translate(DIGITS))
    except (TypeError, ValueError):
        return default


def excerpt(path: Path, limit: int = 180) -> str:
    text = FRONT.sub("", path.read_text(encoding="utf-8", errors="ignore"), count=1)
    text = H1.sub("", text, count=1)
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("|", "---", "```", "#")):
            continue
        line = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", line)
        line = re.sub(r"[*_`>#]+", "", line)
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"
    return "مرور نکات کلیدی، سازوکارها و کاربردهای این بخش"


def collect_parts(parts_dir: Path, clean_dir: Path | None = None, focus_map: dict | None = None) -> list[dict]:
    focus_map = focus_map or {}
    source_files = sorted((p for p in Path(parts_dir).glob("*.md") if is_note(p)), key=natural_key)
    result = []
    for order, source in enumerate(source_files, 1):
        display = Path(clean_dir) / source.name if clean_dir else source
        if not display.is_file():
            display = source
        meta = frontmatter(source)
        if display != source:
            meta.update({k: v for k, v in frontmatter(display).items() if v not in (None, "")})
        match = NAME.match(source.stem)
        n1 = int(match.group(1)) if match else order
        n2 = int(match.group(2)) if match and match.group(2) else None
        chapter = integer(first(meta, "chapter", "group", default=None), n1 if n2 else 1)
        part = integer(first(meta, "part", "session", "section", default=None), n2 or n1)
        page_value = first(meta, "pdf_pages", "pages", "page_range", default=None)
        if page_value in (None, ""):
            pm = PP.search(source.stem)
            page_value = f"{int(pm.group(1))}-{int(pm.group(2))}" if pm else "—"
        title = str(first(meta, "title", default=heading(display))).strip()
        result.append({
            "path": source,
            "display_path": display,
            "stem": display.stem,
            "chapter": chapter,
            "part": part,
            "title": title,
            "title_en": str(first(meta, "title_en", "english_title", default=title)).strip(),
            "pdf_pages": str(page_value).strip(),
            "book_pages": str(first(meta, "book_pages", default="—")).strip(),
            "duration": str(first(meta, "estimated_time", "duration", "time", default="—")).strip(),
            "study_focus": str(focus_map.get(source.name, first(meta, "study_focus", "focus", default=excerpt(display)))).strip(),
            "study_focus_en": str(first(meta, "study_focus_en", "focus_en", default=focus_map.get(source.name, first(meta, "study_focus", "focus", default=excerpt(display))))).strip(),
            "source": str(first(meta, "source", "source_pdf", default="")).strip(),
            "chapter_title_fa": str(first(meta, "chapter_title_fa", "chapter_title", "group_title", default="")).strip(),
            "chapter_title_en": str(first(meta, "chapter_title_en", "group_title_en", default="")).strip(),
        })
    return sorted(result, key=lambda p: (p["chapter"], p["part"], natural_key(p["display_path"])))


def group_by_chapter(parts: list[dict]) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = defaultdict(list)
    for part in parts:
        out[int(part["chapter"])].append(part)
    return dict(sorted(out.items()))


def bounds(value: str) -> tuple[int, int] | None:
    nums = [int(x) for x in re.findall(r"\d+", str(value).translate(DIGITS))]
    return (min(nums), max(nums)) if nums else None


def coverage(parts: list[dict]) -> str:
    values = [bounds(p["pdf_pages"]) for p in parts]
    values = [v for v in values if v]
    return f"{min(v[0] for v in values)}-{max(v[1] for v in values)}" if values else "—"


def duration_minutes(value: str) -> int | None:
    text = str(value).translate(DIGITS).casefold()
    if text.strip() in {"", "—", "-"}:
        return None
    h = re.search(r"(\d+(?:\.\d+)?)\s*(?:h|hr|hour|ساعت)", text)
    m = re.search(r"(\d+)\s*(?:m|min|minute|دقیقه)", text)
    if not h and not m:
        plain = re.fullmatch(r"\s*(\d+)\s*", text)
        return int(plain.group(1)) if plain else None
    return round(float(h.group(1)) * 60) if h and not m else ((round(float(h.group(1)) * 60) if h else 0) + (int(m.group(1)) if m else 0))


def format_duration(minutes: int | None, english: bool = False) -> str:
    if minutes is None:
        return "—"
    h, m = divmod(minutes, 60)
    if english:
        return f"{h} h {m} min" if h and m else (f"{h} h" if h else f"{m} min")
    return f"{h} ساعت و {m} دقیقه" if h and m else (f"{h} ساعت" if h else f"{m} دقیقه")


def chapter_name(number: int, items: list[dict], count: int, english: bool = False) -> str:
    key = "chapter_title_en" if english else "chapter_title_fa"
    explicit = next((x[key] for x in items if x.get(key)), None)
    if explicit:
        return explicit
    if count == 1:
        return "Study Sections" if english else "بخش‌های مطالعه"
    return f"Chapter {number}" if english else f"فصل {number}"


def topic_summary(items: list[dict], english: bool = False) -> str:
    key = "title_en" if english else "title"
    titles = [x[key] for x in items]
    return "، ".join(titles[:3]) + ("، …" if len(titles) > 3 else "")


def span(items: list[dict]) -> str:
    a, b = items[0]["part"], items[-1]["part"]
    return str(a) if a == b else f"{a}-{b}"


def total_time(items: list[dict]) -> int | None:
    values = [duration_minutes(x["duration"]) for x in items]
    return sum(v for v in values if v is not None) if any(v is not None for v in values) else None


def link(part: dict) -> str:
    return f"note://{quote(part['stem'], safe='_-')}"


def build_index_md(parts: list[dict], clean_dir: Path | None = None, course_title: str = "Study Notes") -> str:
    del clean_dir
    if not parts:
        raise ValueError("No Markdown topic notes were found for the study index.")
    chapters = group_by_chapter(parts)
    count = len(chapters)
    sources = sorted({p["source"] for p in parts if p["source"]})
    lines = [f"# فهرست مطالعه {course_title}", "", "## نمای کلی", ""]
    if sources:
        lines.append(f"- منبع: {', '.join(sources)}")
    lines += [
        f"- تعداد جلسات مطالعه: {len(parts)}",
        f"- پوشش کلی جلسات: صفحات {coverage(parts)}",
        f"- زمان کل تخمینی: {format_duration(total_time(parts))}",
        "- هر عنوان جلسه مستقیماً به محل شروع همان بخش در PDF نهایی لینک می‌شود.",
        "", "## فهرست فصل‌ها و گروه‌ها", "",
        "| فصل/بخش | موضوع | جلسات | صفحات PDF | صفحات کتاب | زمان تقریبی |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for number, items in chapters.items():
        name = chapter_name(number, items, count)
        lines.append(f"| [{name}](#chapter-{number}-fa) | {topic_summary(items)} | {span(items)} | {coverage(items)} | — | {format_duration(total_time(items))} |")
    lines += ["", "## روش پیشنهادی مطالعه", "", "1. ابتدا تیترها، شکل‌ها و جدول‌های هر بخش را سریع مرور کنید.", "2. مسیر اصلی مطلب، الگوریتم، سازوکار یا زنجیره تصمیم‌گیری را مشخص کنید.", "3. نکات کلیدی، محدودیت‌ها و موارد مقایسه‌ای را جدا یادداشت کنید.", "4. در پایان هر بخش، نکات اصلی را بدون نگاه‌کردن بازسازی کنید.", ""]
    for number, items in chapters.items():
        name = chapter_name(number, items, count)
        lines += [f'## {name} <a id="chapter-{number}-fa"></a>', "", f"{len(items)} جلسه · صفحات PDF {coverage(items)} · زمان تقریبی: {format_duration(total_time(items))}", "", "| جلسه | موضوع | صفحات PDF | صفحات کتاب | زمان | تمرکز مطالعه |", "|---:|---|---:|---:|---:|---|"]
        for p in items:
            lines.append(f"| {p['part']} | [{p['title']}]({link(p)}) | {p['pdf_pages']} | {p['book_pages']} | {p['duration']} | {p['study_focus']} |")
        lines.append("")
    lines += ["---", "", f"# {course_title} Study Index", "", "## Overview", ""]
    if sources:
        lines.append(f"- Source: {', '.join(sources)}")
    lines += [f"- Total study sessions: {len(parts)}", f"- Overall coverage: PDF pages {coverage(parts)}", f"- Total estimated time: {format_duration(total_time(parts), True)}", "- Every session title links to the beginning of that section inside the final combined PDF.", "", "## Table of Contents", "", "| Chapter/Group | Topic | Sessions | PDF pages | Book pages | Estimated time |", "|---|---|---:|---:|---:|---:|"]
    for number, items in chapters.items():
        name = chapter_name(number, items, count, True)
        lines.append(f"| [{name}](#chapter-{number}-en) | {topic_summary(items, True)} | {span(items)} | {coverage(items)} | — | {format_duration(total_time(items), True)} |")
    lines.append("")
    for number, items in chapters.items():
        name = chapter_name(number, items, count, True)
        lines += [f'## {name} <a id="chapter-{number}-en"></a>', "", f"{len(items)} sessions · PDF pages {coverage(items)} · Estimated time: {format_duration(total_time(items), True)}", "", "| Session | Topic | PDF pages | Book pages | Time | Study focus |", "|---:|---|---:|---:|---:|---|"]
        for p in items:
            lines.append(f"| {p['part']} | [{p['title_en']}]({link(p)}) | {p['pdf_pages']} | {p['book_pages']} | {p['duration']} | {p['study_focus_en']} |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def load_original_index(path: Path) -> dict:
    if not path.exists():
        return {}
    result = {}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = re.search(r"\[[^]]+\]\(([^)]+\.md)\)", line, re.I)
        cells = [x.strip() for x in line.strip().strip("|").split("|")]
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
    parser = argparse.ArgumentParser(description="Generate a rich STUDY_INDEX.md from split topic notes")
    parser.add_argument("--parts-dir", required=True)
    parser.add_argument("--clean-dir")
    parser.add_argument("--original-index")
    parser.add_argument("--output", required=True)
    parser.add_argument("--title", default="Study Notes")
    args = parser.parse_args()
    output = generate_index(Path(args.parts_dir), Path(args.output), clean_dir=Path(args.clean_dir) if args.clean_dir else None, original_index=Path(args.original_index) if args.original_index else None, title=args.title)
    print(f"Generated rich index: {output}")
    print(f"Found {len(collect_parts(Path(args.parts_dir), Path(args.clean_dir) if args.clean_dir else None))} parts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
