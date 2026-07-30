#!/usr/bin/env python3
"""Generate a bilingual Study Index from the prepared Index and Markdown files."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pdf_pipeline_common import (
    build_index_markdown,
    group_sessions,
    infer_course_title,
    locate_index_file,
    parse_index_sessions,
)


def generate_index(
    notes_dir: Path,
    output: Path,
    *,
    original_parts_dir: Path | None = None,
    index_path: Path | None = None,
    title: str | None = None,
    book_pages_json: Path | None = None,
    total_pages: int | None = None,
) -> tuple[Path, list]:
    notes_dir = Path(notes_dir).resolve()
    source_index = locate_index_file(notes_dir, original_parts_dir, index_path)
    sessions = parse_index_sessions(source_index, notes_dir)
    if book_pages_json:
        data = json.loads(Path(book_pages_json).read_text(encoding="utf-8"))
        for session in sessions:
            value = data.get(session.stem) or data.get(str(session.number))
            if value:
                session.book_pages = str(value)
    course_title = infer_course_title(source_index, notes_dir, title)
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_index_markdown(sessions, course_title, total_pages=total_pages), encoding="utf-8")
    return output, sessions


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a bilingual, clickable Study Index")
    parser.add_argument("--notes-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--original-parts-dir")
    parser.add_argument("--index")
    parser.add_argument("--title")
    parser.add_argument("--book-pages-json")
    parser.add_argument("--total-pages", type=int)
    args = parser.parse_args()
    output, sessions = generate_index(
        Path(args.notes_dir),
        Path(args.output),
        original_parts_dir=Path(args.original_parts_dir) if args.original_parts_dir else None,
        index_path=Path(args.index) if args.index else None,
        title=args.title,
        book_pages_json=Path(args.book_pages_json) if args.book_pages_json else None,
        total_pages=args.total_pages,
    )
    print(f"Generated Study Index: {output}")
    print(f"Sessions: {len(sessions)}")
    print(f"Groups: {len(group_sessions(sessions))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
