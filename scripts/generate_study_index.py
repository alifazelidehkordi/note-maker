#!/usr/bin/env python3
"""Generate a bilingual rich Markdown index from the existing Index data."""
from __future__ import annotations

import argparse
from collections import OrderedDict
from pathlib import Path
from urllib.parse import quote

from pdf_utils import (
    PipelineError,
    StudyIndexData,
    find_index_file,
    is_topic_note,
    natural_key,
    parse_study_index,
    range_span,
)


def collect_parts(
    parts_dir: Path,
    clean_dir: Path | None = None,
    focus_map: dict | None = None,
    index_md: Path | None = None,
) -> list[dict]:
    """Compatibility wrapper returning session dictionaries in Index order."""
    del focus_map
    notes_dir = Path(clean_dir or parts_dir).resolve()
    index_path = find_index_file(Path(parts_dir).resolve(), index_md)
    data = parse_study_index(index_path, notes_dir)
    return [
        {
            "path": session.note_path,
            "display_path": session.note_path,
            "stem": session.note_path.stem,
            "chapter": session.group_number,
            "part": session.number,
            "title": session.title,
            "title_en": session.title,
            "pdf_pages": session.source_pages,
            "book_pages": session.book_pages,
            "duration": session.duration,
            "study_focus": session.study_focus,
            "study_focus_en": session.study_focus,
            "source": "",
            "chapter_title_fa": session.group,
            "chapter_title_en": session.group,
        }
        for session in data.sessions
    ]


def group_by_chapter(parts: list[dict]) -> dict[int, list[dict]]:
    grouped: OrderedDict[int, list[dict]] = OrderedDict()
    for part in parts:
        grouped.setdefault(int(part["chapter"]), []).append(part)
    return dict(grouped)


def _link(stem: str) -> str:
    return f"note://{quote(stem, safe='_-')}"


def build_index_md(data: StudyIndexData, course_title: str | None = None) -> str:
    title = course_title or data.course_title
    lines = [
        f"# فهرست مطالعه / {title} Study Index",
        "",
        "## نمای کلی / Overview",
        "",
        f"- تعداد جلسات / Sessions: **{len(data.sessions)}**",
        f"- تعداد فصل‌ها و گروه‌ها / Groups: **{len(data.groups)}**",
        f"- صفحات منبع / Source pages: **{data.source_coverage}**",
        f"- صفحات کتاب / Book pages: **{data.book_coverage}**",
        f"- زمان کل تخمینی / Estimated total time: **{data.total_study_time}**",
        "- عنوان هر جلسه در PDF نهایی قابل کلیک است. / Every session title is clickable in the final PDF.",
        "",
        "## فصل‌ها و گروه‌ها / Chapters and Groups",
        "",
        "| # | فصل / Group | جلسات / Sessions | صفحات منبع / Source | صفحات کتاب / Book | تعداد / Count |",
        "|---:|---|---:|---:|---:|---:|",
    ]
    for number, group in enumerate(data.groups, 1):
        lines.append(
            f"| {number} | {group.title} | {group.number_span} | {group.source_span} | "
            f"{group.book_span} | {len(group.sessions)} |"
        )
    lines.extend(
        [
            "",
            "## جدول کامل جلسات / Complete Session Table",
            "",
            "| # | عنوان جلسه / Session title | صفحات منبع / Source | صفحات کتاب / Book | زمان / Time | تمرکز مطالعه / Study focus |",
            "|---:|---|---:|---:|---:|---|",
        ]
    )
    for session in data.sessions:
        lines.append(
            f"| {session.number} | [{session.title}]({_link(session.note_path.stem)}) | "
            f"{session.source_pages} | {session.book_pages} | {session.duration} | {session.study_focus} |"
        )
    lines.append("")
    return "\n".join(lines)


def generate_index(
    parts_dir: Path,
    output: Path,
    *,
    clean_dir: Path | None = None,
    title: str | None = None,
    index_md: Path | None = None,
) -> Path:
    notes_dir = Path(clean_dir or parts_dir).resolve()
    index_path = find_index_file(Path(parts_dir).resolve(), index_md)
    data = parse_study_index(index_path, notes_dir)
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_index_md(data, title), encoding="utf-8")
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a bilingual rich study index")
    parser.add_argument("--parts-dir", required=True)
    parser.add_argument("--clean-dir")
    parser.add_argument("--index-md", help="Existing Index source; auto-detected when omitted")
    parser.add_argument("--output", required=True)
    parser.add_argument("--title")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        output = generate_index(
            Path(args.parts_dir),
            Path(args.output),
            clean_dir=Path(args.clean_dir) if args.clean_dir else None,
            title=args.title,
            index_md=Path(args.index_md) if args.index_md else None,
        )
        print(f"Study Index created: {output}")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
