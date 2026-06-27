#!/usr/bin/env python3
"""
Generate a rich STUDY_INDEX.md (modeled after user's phisiopath style)
for a folder of topic-split study parts.

It preserves original PDF page mappings and produces nice tables
with links to the (clean) notes.

Usage examples:
  python scripts/generate_study_index.py \
    --parts-dir /path/to/parts \
    --output STUDY_INDEX-clean.md

  # If you have rewritten clean notes in another dir with same filenames:
  python scripts/generate_study_index.py \
    --parts-dir original-parts \
    --clean-dir outputs/notes \
    --output outputs/STUDY_INDEX-rewritten.md
"""

import argparse
import re
from collections import defaultdict
from pathlib import Path

import yaml


def parse_frontmatter(md_path: Path) -> dict:
    text = md_path.read_text(encoding="utf-8", errors="ignore")
    if not text.startswith("---"):
        return {}
    try:
        _, front, _ = text.split("---", 2)
        data = yaml.safe_load(front) or {}
        return data
    except Exception:
        return {}


def extract_title_from_content(md_path: Path) -> str:
    text = md_path.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"^#\s+(.+?)\s*$", text, re.MULTILINE)
    return m.group(1).strip() if m else md_path.stem


def group_by_chapter(parts: list[dict]) -> dict[int, list[dict]]:
    chapters = defaultdict(list)
    for p in parts:
        ch = p.get("chapter", 0) or 0
        chapters[ch].append(p)
    return dict(sorted(chapters.items()))


def build_index_md(parts: list[dict], clean_dir: Path | None = None, course_title: str = "Study Index") -> str:
    """Build a rich index Markdown similar to the user's format."""
    # Sort by part number if available
    parts = sorted(parts, key=lambda x: (x.get("chapter", 0), x.get("part", 0)))

    chapters = group_by_chapter(parts)

    lines = []
    lines.append(f"# فهرست مطالعه — {course_title}")
    lines.append("")
    lines.append("نسخهٔ تمیز بازنویسی‌شده. اطلاعات صفحات اصلی حفظ شده است.")
    lines.append("")

    # Overview
    total_sessions = len(parts)
    lines.append("## نمای کلی")
    lines.append("")
    lines.append(f"- تعداد جلسات: **{total_sessions}**")
    lines.append("")

    # High level chapters
    lines.append("## فهرست فصول")
    lines.append("")
    lines.append("| فصل | موضوع | جلسات | صفحات |")
    lines.append("| --: | ------ | ----: | ------ |")

    chapter_names = {
        1: "خون‌سازی و کم‌خونی‌ها",
        2: "هموستاز و انعقاد",
        # Add more as needed or derive from data
    }

    for ch_num, ch_parts in chapters.items():
        first = ch_parts[0]
        last = ch_parts[-1]
        ch_name = chapter_names.get(ch_num, f"فصل {ch_num}")
        page_range = f"{first.get('pdf_pages', '?')}–{last.get('pdf_pages', '?')}"
        lines.append(f"| {ch_num} | {ch_name} | {first.get('part','?')}–{last.get('part','?')} | {page_range} |")

    lines.append("")

    # Detailed per chapter
    for ch_num, ch_parts in chapters.items():
        ch_name_fa = chapter_names.get(ch_num, f"فصل {ch_num}")
        lines.append(f"## فصل {ch_num} — {ch_name_fa}")
        lines.append("")

        lines.append("| جلسه | موضوع | صفحات اصلی | تمرکز مطالعه |")
        lines.append("|---:|---|---|---|")

        for p in ch_parts:
            part_num = p.get("part", "?")
            title = p.get("title", extract_title_from_content(p["path"]))
            pages = p.get("pdf_pages", "—")

            # Link to clean note if provided
            if clean_dir:
                clean_path = clean_dir / p["path"].name
                link = f"[{title}]({clean_path.name})"
            else:
                link = f"[{title}]({p['path'].name})"

            focus = p.get("study_focus", "مطالعهٔ مکانیسم‌ها، ویژگی‌های بالینی و تشخیص")
            lines.append(f"| {part_num} | {link} | {pages} | {focus} |")

        lines.append("")

    # English section
    lines.append("---")
    lines.append("")
    lines.append(f"# Study Index — {course_title}")
    lines.append("")

    lines.append("| Chapter | Topic | Sessions | Pages |")
    lines.append("| --: | ------ | ----: | ------ |")

    for ch_num, ch_parts in chapters.items():
        first = ch_parts[0]
        last = ch_parts[-1]
        page_range = f"{first.get('pdf_pages', '?')}–{last.get('pdf_pages', '?')}"
        lines.append(f"| {ch_num} | Chapter {ch_num} | {first.get('part','?')}–{last.get('part','?')} | {page_range} |")

    lines.append("")

    for ch_num, ch_parts in chapters.items():
        lines.append(f"## Chapter {ch_num}")
        lines.append("")
        lines.append("| Session | Topic | Pages | Study Focus |")
        lines.append("|---:|---|---|---|")

        for p in ch_parts:
            part_num = p.get("part", "?")
            title = p.get("title", extract_title_from_content(p["path"]))
            pages = p.get("pdf_pages", "—")

            if clean_dir:
                clean_path = clean_dir / p["path"].name
                link = f"[{title}]({clean_path.name})"
            else:
                link = f"[{title}]({p['path'].name})"

            focus = p.get("study_focus", "Mechanisms, clinical features, diagnosis")
            lines.append(f"| {part_num} | {link} | {pages} | {focus} |")

        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Generate rich STUDY_INDEX.md from topic-split parts (preserving original pages)")
    parser.add_argument("--parts-dir", required=True, help="Directory containing the original or source .md parts with frontmatter (pdf_pages etc.)")
    parser.add_argument("--clean-dir", help="Directory with the rewritten clean notes (optional, for links)")
    parser.add_argument("--output", required=True, help="Output path for the generated STUDY_INDEX.md")
    parser.add_argument("--title", default="Pathophysiology", help="Course title")
    args = parser.parse_args()

    parts_dir = Path(args.parts_dir)
    clean_dir = Path(args.clean_dir) if args.clean_dir else None

    part_files = sorted([p for p in parts_dir.glob("*.md") if p.is_file()])

    parsed = []
    for pf in part_files:
        fm = parse_frontmatter(pf)
        fm["path"] = pf
        if "title" not in fm:
            fm["title"] = extract_title_from_content(pf)
        parsed.append(fm)

    index_md = build_index_md(parsed, clean_dir=clean_dir, course_title=args.title)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(index_md, encoding="utf-8")

    print(f"Generated rich index: {out_path}")
    print(f"Found {len(parsed)} parts.")


if __name__ == "__main__":
    main()
