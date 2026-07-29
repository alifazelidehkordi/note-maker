#!/usr/bin/env python3
"""Create one final, linked, bookmarked, continuously numbered portrait PDF."""
from __future__ import annotations

import argparse
import html
import os
from pathlib import Path

import fitz
from pypdf import PdfReader

from convert_md_to_pdf import build_css, note_to_html, write_html_pdf
from generate_study_index import build_study_index_html, group_sessions, parse_index
from pdf_common import locate_index, validate_required_paths


def add_page_labels(pdf_path: Path) -> None:
    """Write an explicit decimal PageLabels tree without rebuilding through pypdf."""
    doc = fitz.open(str(pdf_path))
    doc.set_page_labels([{"startpage": 0, "prefix": "", "style": "D", "firstpagenum": 1}])
    temp = pdf_path.with_suffix(".labels.pdf")
    doc.save(str(temp), garbage=3, deflate=True)
    doc.close()
    temp.replace(pdf_path)


def create_combined(notes_dir: Path, output_path: Path, index_md: Path, font_file: Path, font_bold_file: Path) -> dict:
    validate_required_paths(notes_dir, index_md, font_file, font_bold_file)
    course_title, overall_pages, sessions = parse_index(index_md, notes_dir)
    groups = group_sessions(sessions)
    index_html = build_study_index_html(course_title, overall_pages, sessions)
    note_blocks: list[str] = []
    last_group = None
    for session in sessions:
        is_new_group = session.group != last_group
        note_blocks.append(note_to_html(session, group_start=is_new_group))
        last_group = session.group

    css = build_css(font_file, font_bold_file)
    document = f'''<!doctype html>
<html lang="en" dir="auto">
<head>
<meta charset="utf-8">
<title>{html.escape(course_title)} - Final Study Notes</title>
<style>{css}</style>
</head>
<body>
{index_html}
{''.join(note_blocks)}
</body>
</html>'''
    debug_html = output_path.with_suffix(".html")
    debug_html.write_text(document, encoding="utf-8")
    write_html_pdf(document, output_path, notes_dir)
    add_page_labels(output_path)
    reader = PdfReader(str(output_path))
    return {
        "output": str(output_path),
        "title": course_title,
        "total_pages": len(reader.pages),
        "sessions": len(sessions),
        "groups": len(groups),
        "index_html": str(debug_html),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--notes-dir", default=os.getenv("NOTES_DIR"))
    parser.add_argument("--output", default=os.getenv("COMBINED_OUTPUT"))
    parser.add_argument("--index-md")
    parser.add_argument("--font-file", default=os.getenv("FONT_FILE"))
    parser.add_argument("--font-bold-file", default=os.getenv("FONT_BOLD_FILE"))
    args = parser.parse_args()
    if not args.notes_dir or not args.output or not args.font_file or not args.font_bold_file:
        parser.error("NOTES_DIR, COMBINED_OUTPUT, FONT_FILE and FONT_BOLD_FILE are required")
    notes_dir = Path(args.notes_dir).resolve()
    index_md = Path(args.index_md).resolve() if args.index_md else locate_index(notes_dir)
    result = create_combined(
        notes_dir, Path(args.output).resolve(), index_md,
        Path(args.font_file).resolve(), Path(args.font_bold_file).resolve(),
    )
    print(f"Final PDF: {result['output']}")
    print(f"Total pages: {result['total_pages']}")
    print(f"Sessions: {result['sessions']}")
    print(f"Groups: {result['groups']}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
