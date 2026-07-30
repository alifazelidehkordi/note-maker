#!/usr/bin/env python3
"""Build and validate the final combined Study Notes PDF.

The input Index controls ordering. Every page is rebuilt as A4 portrait, links
are converted to stable named destinations, bookmarks are hierarchical, and
all critical QA failures terminate with a non-zero exit code.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from pathlib import Path

import fitz
from pypdf import PdfReader, PdfWriter
from pypdf.constants import PageLabelStyle
from pypdf.generic import NameObject, TextStringObject
from weasyprint import HTML

from convert_md_to_pdf import PdfStyle, make_pdf
from pdf_pipeline_common import (
    A4_HEIGHT_PT,
    A4_WIDTH_PT,
    aliases_from_uri,
    build_index_markdown,
    check_a4_portrait,
    collect_embedded_fonts,
    font_config,
    font_stack,
    group_sessions,
    infer_course_title,
    locate_index_file,
    parse_index_sessions,
    session_aliases,
    validate_component_pdf,
    validate_font_coverage,
    write_json,
)


def _rewrite_index_links(writer: PdfWriter, index_pages: int, alias_to_session: dict[str, object]) -> tuple[int, list[dict]]:
    converted = 0
    unresolved: list[dict] = []
    for page_index in range(index_pages):
        annotations = writer.pages[page_index].get("/Annots") or []
        for ref in annotations:
            annotation = ref.get_object()
            action = annotation.get("/A")
            if not action:
                continue
            action = action.get_object() if hasattr(action, "get_object") else action
            if str(action.get("/S")) != "/URI":
                continue
            uri = str(action.get("/URI", ""))
            if not uri.casefold().startswith("note:"):
                continue
            session = next((alias_to_session[a] for a in aliases_from_uri(uri) if a in alias_to_session), None)
            if session is None:
                unresolved.append({"page": page_index + 1, "uri": uri})
                continue
            annotation.pop(NameObject("/A"), None)
            annotation[NameObject("/Dest")] = TextStringObject(session.destination)
            converted += 1
    return converted, unresolved


def _add_bookmarks(writer: PdfWriter, sessions, index_pages: int) -> int:
    count = 0
    writer.add_outline_item("فهرست مطالعه / Study Index", 0, bold=True, is_open=True)
    count += 1
    for group_number, group in enumerate(group_sessions(sessions), 1):
        first = group.sessions[0].start_page_index
        group_title = f"گروه {group_number} / Group {group_number} - {group.title}"
        parent = writer.add_outline_item(group_title, first, bold=True, is_open=False)
        count += 1
        for session in group.sessions:
            writer.add_outline_item(f"{session.number}. {session.title}", session.start_page_index, parent=parent)
            count += 1
    return count


def _footer_overlay_pdf(path: Path, total_pages: int, fonts) -> None:
    regular = font_stack(fonts.regular_families)
    pages = "\n".join(f'<section class="p"><span>{i}</span></section>' for i in range(1, total_pages + 1))
    css = f"""
{fonts.css}
@page {{ size:A4 portrait; margin:0; }}
html, body {{ margin:0; padding:0; background:transparent; }}
body {{ font-family:{regular}; }}
.p {{ position:relative; width:{A4_WIDTH_PT}pt; height:{A4_HEIGHT_PT}pt; break-after:page; page-break-after:always; }}
.p:last-child {{ break-after:auto; page-break-after:auto; }}
.p span {{ position:absolute; left:0; right:0; bottom:12pt; text-align:center; font-size:8.4pt; color:#64748b; line-height:1; }}
"""
    html_doc = f"<!doctype html><html><head><meta charset='utf-8'><style>{css}</style></head><body>{pages}</body></html>"
    HTML(string=html_doc).write_pdf(path)
    validate_component_pdf(path)


def _add_page_numbers(writer: PdfWriter, fonts) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        overlay_path = Path(tmp) / "footer-overlay.pdf"
        _footer_overlay_pdf(overlay_path, len(writer.pages), fonts)
        overlay = PdfReader(overlay_path)
        if len(overlay.pages) != len(writer.pages):
            raise RuntimeError("Footer overlay page count mismatch")
        for page, footer in zip(writer.pages, overlay.pages):
            page.merge_page(footer, over=True)
    writer.set_page_label(0, len(writer.pages) - 1, style=PageLabelStyle.DECIMAL, start=1)


def _render_sessions(sessions, pdf_dir: Path, fonts, extra_css: str, course_title: str) -> None:
    pdf_dir.mkdir(parents=True, exist_ok=True)
    force = os.environ.get("FORCE_REBUILD_PDFS", "0") == "1"
    renderer_inputs = {
        Path(__file__).resolve(),
        Path(make_pdf.__code__.co_filename).resolve(),
        Path(validate_component_pdf.__code__.co_filename).resolve(),
        *fonts.regular_files,
        *fonts.bold_files,
    }
    renderer_mtime = max(path.stat().st_mtime_ns for path in renderer_inputs if path.is_file())
    for session in sessions:
        pdf = pdf_dir / f"{session.stem}.pdf"
        newest_input = max(session.markdown_path.stat().st_mtime_ns, renderer_mtime)
        needs_build = force or not pdf.is_file() or newest_input > pdf.stat().st_mtime_ns
        if needs_build:
            print(f"Rendering session {session.number:02d}: {session.title}", flush=True)
            make_pdf(
                session.markdown_path,
                pdf,
                fonts=fonts,
                style=PdfStyle(page_numbers=False),
                extra_css=extra_css,
                session_meta={
                    "number": session.number,
                    "group": session.group_title,
                    "source_pages": session.source_pages,
                    "duration": session.duration,
                },
                running_book_title=course_title,
            )
        else:
            print(f"Reusing validated session {session.number:02d}: {pdf.name}", flush=True)
        session.pdf_path = pdf
        session.pdf_pages = validate_component_pdf(pdf)


def _layout_index_until_stable(sessions, title: str, work_dir: Path, fonts, extra_css: str) -> tuple[Path, int, int]:
    previous_pages = None
    index_md = work_dir / "STUDY_INDEX.generated.md"
    index_pdf = work_dir / "STUDY_INDEX.generated.pdf"
    total_session_pages = sum(s.pdf_pages for s in sessions)
    for iteration in range(1, 7):
        assumed_index_pages = previous_pages or 1
        cursor = assumed_index_pages
        for session in sessions:
            start = cursor + 1
            end = cursor + session.pdf_pages
            session.book_pages = str(start) if start == end else f"{start}-{end}"
            cursor = end
        total_pages = assumed_index_pages + total_session_pages
        index_md.write_text(build_index_markdown(sessions, title, total_pages=total_pages), encoding="utf-8")
        make_pdf(
            index_md,
            index_pdf,
            title=f"{title} - Study Index",
            fonts=fonts,
            style=PdfStyle(page_numbers=False, is_index=True),
            extra_css=extra_css,
            running_book_title=title,
        )
        index_pages = validate_component_pdf(index_pdf)
        print(f"Study Index layout pass {iteration}: {index_pages} page(s)")
        if previous_pages == index_pages:
            final_total = index_pages + total_session_pages
            # Recompute exact book-page ranges using the stable index page count.
            cursor = index_pages
            for session in sessions:
                session.start_page_index = cursor
                start = cursor + 1
                cursor += session.pdf_pages
                end = cursor
                session.book_pages = str(start) if start == end else f"{start}-{end}"
            index_md.write_text(build_index_markdown(sessions, title, total_pages=final_total), encoding="utf-8")
            make_pdf(
                index_md,
                index_pdf,
                title=f"{title} - Study Index",
                fonts=fonts,
                style=PdfStyle(page_numbers=False, is_index=True),
                extra_css=extra_css,
                running_book_title=title,
            )
            final_index_pages = validate_component_pdf(index_pdf)
            if final_index_pages != index_pages:
                previous_pages = final_index_pages
                continue
            return index_pdf, final_index_pages, final_total
        previous_pages = index_pages
    raise RuntimeError("Study Index page count did not stabilize after 6 layout passes")


def _annotation_target_name(annotation) -> str | None:
    dest = annotation.get("/Dest")
    if isinstance(dest, str):
        return str(dest)
    return None


def _flatten_outlines(reader: PdfReader):
    flat = []
    def walk(items, level=0):
        parent = None
        for item in items:
            if isinstance(item, list):
                walk(item, level + 1)
            else:
                flat.append((level, str(getattr(item, "title", item)), item))
    walk(reader.outline)
    return flat


def _qc_final(output: Path, sessions, index_pages: int, converted: int, unresolved: list[dict], bookmark_count: int, expected_title: str) -> dict:
    reader = PdfReader(output)
    geometry = check_a4_portrait(reader)
    failures: list[str] = []
    if geometry["landscape"]:
        failures.append(f"Landscape pages: {geometry['landscape']}")
    if geometry["rotated"]:
        failures.append(f"Rotated pages: {geometry['rotated']}")
    if geometry["wrong_size"]:
        failures.append(f"Non-A4 pages: {geometry['wrong_size']}")

    fonts, unembedded, undesired = collect_embedded_fonts(reader)
    if unembedded:
        failures.append(f"Unembedded fonts: {unembedded}")
    if undesired:
        failures.append(f"Unexpected fallback fonts: {undesired}")

    named = reader.named_destinations
    for session in sessions:
        if session.destination not in named:
            failures.append(f"Missing named destination: {session.destination} ({session.title})")
            continue
        page_num = reader.get_destination_page_number(named[session.destination])
        if page_num != session.start_page_index:
            failures.append(f"Destination mismatch for session {session.number}: expected page index {session.start_page_index}, got {page_num}")

    remaining_note_uris: list[dict] = []
    linked_destinations: list[str] = []
    for page_number, page in enumerate(reader.pages[:index_pages], 1):
        for ref in page.get("/Annots") or []:
            annotation = ref.get_object()
            action = annotation.get("/A")
            if action:
                action = action.get_object() if hasattr(action, "get_object") else action
                uri = str(action.get("/URI", ""))
                if uri.casefold().startswith("note:"):
                    remaining_note_uris.append({"page": page_number, "uri": uri})
            target = _annotation_target_name(annotation)
            if target:
                linked_destinations.append(target)
    if remaining_note_uris:
        failures.append(f"Unresolved note:// annotations remain: {remaining_note_uris}")
    minimum_links = len(sessions) * 2
    if converted < minimum_links:
        failures.append(f"Too few internal link annotations: converted={converted}, minimum={minimum_links}")
    if unresolved:
        failures.append(f"Unresolved internal links: {unresolved}")
    for session in sessions:
        if linked_destinations.count(session.destination) < 2:
            failures.append(f"Session {session.number} does not have links in both bilingual session tables")

    flat_outlines = _flatten_outlines(reader)
    outline = reader.outline
    bookmark_hierarchy_ok = True
    if not outline or isinstance(outline[0], list) or "Study Index" not in str(getattr(outline[0], "title", "")):
        failures.append("Study Index bookmark is missing or not first")
        bookmark_hierarchy_ok = False
    elif reader.get_destination_page_number(outline[0]) != 0:
        failures.append("Study Index bookmark does not point to page 1")
        bookmark_hierarchy_ok = False
    groups = group_sessions(sessions)
    cursor = 1
    for group_number, group in enumerate(groups, 1):
        if cursor + 1 >= len(outline) or isinstance(outline[cursor], list) or not isinstance(outline[cursor + 1], list):
            failures.append(f"Malformed bookmark hierarchy at group {group_number}")
            bookmark_hierarchy_ok = False
            break
        group_item = outline[cursor]
        children = outline[cursor + 1]
        group_page = reader.get_destination_page_number(group_item)
        if group_page != group.sessions[0].start_page_index:
            failures.append(f"Group {group_number} bookmark destination mismatch")
            bookmark_hierarchy_ok = False
        if len(children) != len(group.sessions):
            failures.append(f"Group {group_number} bookmark child count mismatch")
            bookmark_hierarchy_ok = False
        else:
            for child, session in zip(children, group.sessions):
                title = str(getattr(child, "title", ""))
                if not title.startswith(f"{session.number}."):
                    failures.append(f"Bookmark order/title mismatch for session {session.number}")
                    bookmark_hierarchy_ok = False
                if reader.get_destination_page_number(child) != session.start_page_index:
                    failures.append(f"Bookmark destination mismatch for session {session.number}")
                    bookmark_hierarchy_ok = False
        cursor += 2
    if cursor != len(outline):
        failures.append("Unexpected extra top-level bookmark entries")
        bookmark_hierarchy_ok = False
    if len(flat_outlines) != bookmark_count:
        failures.append(f"Bookmark count mismatch: expected {bookmark_count}, got {len(flat_outlines)}")
        bookmark_hierarchy_ok = False

    expected_order = [s.number for s in sessions]
    if len(set(expected_order)) != len(expected_order):
        failures.append("Duplicate sessions detected")
    if expected_order != sorted(expected_order):
        failures.append("Session order differs from Index")

    page_labels = reader.page_labels
    expected_labels = [str(i) for i in range(1, len(reader.pages) + 1)]
    if page_labels != expected_labels:
        failures.append("PDF Page Labels are not the continuous 1..N sequence")

    footer_errors: list[int] = []
    doc = fitz.open(output)
    for page_index, page in enumerate(doc):
        words = page.get_text("words")
        expected = str(page_index + 1)
        candidates = [w for w in words if w[4] == expected and w[1] >= page.rect.height - 45]
        if not candidates:
            footer_errors.append(page_index + 1)
        for block in page.get_text("blocks"):
            x0, y0, x1, y1 = block[:4]
            if x0 < -1 or y0 < -1 or x1 > page.rect.width + 1 or y1 > page.rect.height + 1:
                failures.append(f"Text block outside page bounds on page {page_index + 1}: {(x0, y0, x1, y1)}")
                break
    doc.close()
    if footer_errors:
        failures.append(f"Missing/mismatched visible footer numbers on pages: {footer_errors}")

    report = {
        "final_pdf": str(output),
        "total_pages": len(reader.pages),
        "study_index_pages": index_pages,
        "sessions": len(sessions),
        "groups": len(group_sessions(sessions)),
        "converted_internal_links": converted,
        "unresolved_links": len(unresolved) + len(remaining_note_uris),
        "bookmarks": len(flat_outlines),
        "bookmark_hierarchy_verified": bookmark_hierarchy_ok,
        "page_number_range": f"1-{len(reader.pages)}",
        "embedded_fonts": sorted(fonts),
        "unembedded_fonts": unembedded,
        "unexpected_fallback_fonts": undesired,
        "page_size": "A4 (595.276 x 841.890 pt)",
        "page_orientation": "Portrait",
        "portrait_pages": len(reader.pages) - len(geometry["landscape"]),
        "landscape_pages": len(geometry["landscape"]),
        "landscape_page_numbers": geometry["landscape"],
        "rotated_pages": len(geometry["rotated"]),
        "rotated_page_numbers": geometry["rotated"],
        "wrong_size_pages": geometry["wrong_size"],
        "footer_errors": footer_errors,
        "session_order": expected_order,
        "quality_check": "PASSED" if not failures else "FAILED",
        "failures": failures,
    }
    if failures:
        raise RuntimeError("Final PDF quality check failed:\n- " + "\n- ".join(failures))
    return report


def create_combined(
    notes_dir: Path,
    pdf_dir: Path,
    output_path: Path,
    *,
    original_parts_dir: Path | None = None,
    index_md: Path | None = None,
    title: str | None = None,
    css_file: Path | None = None,
    report_path: Path | None = None,
) -> tuple[Path, dict]:
    notes_dir = Path(notes_dir).resolve()
    pdf_dir = Path(pdf_dir).resolve()
    output = Path(output_path).resolve()
    if not notes_dir.is_dir() or not os.access(notes_dir, os.R_OK):
        raise FileNotFoundError(f"NOTES_DIR is missing or unreadable: {notes_dir}")
    source_index = locate_index_file(notes_dir, original_parts_dir, index_md)
    sessions = parse_index_sessions(source_index, notes_dir)
    fonts = font_config()
    extra_css = ""
    if css_file:
        css_file = Path(css_file).resolve()
        if not css_file.is_file():
            raise FileNotFoundError(f"CSS file not found: {css_file}")
        extra_css = css_file.read_text(encoding="utf-8")
    course_title = infer_course_title(source_index, notes_dir, title)
    validate_font_coverage(
        fonts,
        [source_index, *[s.markdown_path for s in sessions]],
        extra_text="فهرست مطالعه جدول فصل‌ها و گروه‌ها جدول کامل جلسات صفحات منبع صفحات کتاب تمرکز مطالعه قابل کلیک Study Index Chapters Groups Sessions Source pages Book pages Study focus",
    )

    _render_sessions(sessions, pdf_dir, fonts, extra_css, course_title)
    with tempfile.TemporaryDirectory(prefix="note-maker-final-") as tmp:
        work_dir = Path(tmp)
        index_pdf, index_pages, total_pages = _layout_index_until_stable(sessions, course_title, work_dir, fonts, extra_css)
        writer = PdfWriter()
        writer.append(index_pdf, import_outline=False)
        alias_to_session = {}
        for session in sessions:
            if len(writer.pages) != session.start_page_index:
                raise RuntimeError(f"Computed start page mismatch before adding session {session.number}")
            writer.append(session.pdf_path, import_outline=False)
            for alias in session_aliases(session):
                alias_to_session[alias] = session
        if len(writer.pages) != total_pages:
            raise RuntimeError(f"Final page count mismatch: expected {total_pages}, got {len(writer.pages)}")
        for session in sessions:
            writer.add_named_destination(session.destination, session.start_page_index)
        converted, unresolved = _rewrite_index_links(writer, index_pages, alias_to_session)
        if unresolved:
            raise RuntimeError(f"Unresolved internal links: {unresolved}")
        bookmark_count = _add_bookmarks(writer, sessions, index_pages)
        _add_page_numbers(writer, fonts)
        writer.add_metadata({
            "/Title": course_title,
            "/Subject": "Combined bilingual study notes with clickable internal index",
            "/Creator": "note-maker final PDF pipeline",
        })
        writer.page_mode = "/UseOutlines"
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("wb") as stream:
            writer.write(stream)

    report = _qc_final(output, sessions, index_pages, converted, unresolved, bookmark_count, course_title)
    report_path = Path(report_path).resolve() if report_path else output.with_suffix(".quality-report.json")
    write_json(report_path, report)
    return output, report


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the final A4 portrait Study Notes PDF")
    parser.add_argument("--notes-dir", required=True)
    parser.add_argument("--pdf-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--original-parts-dir")
    parser.add_argument("--index-md")
    parser.add_argument("--title")
    parser.add_argument("--css")
    parser.add_argument("--report")
    args = parser.parse_args()
    output, report = create_combined(
        Path(args.notes_dir),
        Path(args.pdf_dir),
        Path(args.output),
        original_parts_dir=Path(args.original_parts_dir) if args.original_parts_dir else None,
        index_md=Path(args.index_md) if args.index_md else None,
        title=args.title,
        css_file=Path(args.css) if args.css else None,
        report_path=Path(args.report) if args.report else None,
    )
    print(f"Final PDF: {output}")
    print(f"Total pages: {report['total_pages']}")
    print(f"Study Index pages: {report['study_index_pages']}")
    print(f"Sessions: {report['sessions']}")
    print(f"Groups: {report['groups']}")
    print(f"Converted internal links: {report['converted_internal_links']}")
    print(f"Unresolved links: {report['unresolved_links']}")
    print(f"Bookmarks: {report['bookmarks']}")
    print(f"Page number range: {report['page_number_range']}")
    print(f"Embedded font: {', '.join(report['embedded_fonts'])}")
    print(f"Page size: A4")
    print(f"Page orientation: Portrait")
    print(f"Portrait pages: {report['portrait_pages']}")
    print(f"Landscape pages: {report['landscape_pages']}")
    print(f"Rotated pages: {report['rotated_pages']}")
    print(f"Quality check: {report['quality_check']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
