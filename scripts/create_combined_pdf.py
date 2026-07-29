#!/usr/bin/env python3
"""Build and verify one final A4 portrait study book from prepared Markdown notes."""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse

from pypdf import PdfReader, PdfWriter
from pypdf.constants import PageLabelStyle
from pypdf.generic import ArrayObject, NameObject

from convert_md_to_pdf import HTML, PdfStyle, make_pdf
from generate_study_index import SourceIndex, generate_index, parse_source_index
from pdf_common import (
    A4_HEIGHT_PT,
    A4_WIDTH_PT,
    CUSTOM_FONT_STACK,
    FontConfig,
    assert_portrait_a4,
    extract_font_report,
    footer_number_pages,
    page_label_sequence,
    unresolved_local_links,
)


def topic_aliases(md: Path, pdf: Path) -> set[str]:
    return {unquote(value).casefold() for value in (md.name, md.stem, pdf.name, pdf.stem)}


def aliases_from_uri(uri: str) -> set[str]:
    parsed = urlparse(uri)
    if parsed.scheme.casefold() == "note":
        raw = (parsed.netloc + parsed.path).lstrip("/")
    elif parsed.scheme.casefold() == "file":
        raw = parsed.path
    elif not parsed.scheme:
        raw = parsed.path or uri
    else:
        return set()
    raw = unquote(raw).replace("\\", "/").rstrip("/")
    if not raw:
        return set()
    name = raw.rsplit("/", 1)[-1]
    path = Path(name)
    result = {name.casefold(), path.stem.casefold()}
    if path.suffix.casefold() in {".md", ".pdf"}:
        result.add(path.with_suffix("").name.casefold())
    return result


def rewrite_index_links(writer: PdfWriter, index_page_count: int, alias_to_page: dict[str, int]) -> tuple[list[dict], list[dict]]:
    converted: list[dict] = []
    unresolved: list[dict] = []
    for page_number in range(index_page_count):
        for ref in writer.pages[page_number].get("/Annots") or []:
            annotation = ref.get_object()
            action = annotation.get("/A")
            if not action:
                continue
            action = action.get_object() if hasattr(action, "get_object") else action
            if action.get("/S") != "/URI":
                continue
            uri = str(action.get("/URI", ""))
            scheme = urlparse(uri).scheme.casefold()
            if scheme not in {"note", "file", ""}:
                continue
            candidates = aliases_from_uri(uri)
            target = next((alias_to_page[item] for item in candidates if item in alias_to_page), None)
            if target is None:
                unresolved.append({"index_page": page_number + 1, "uri": uri})
                continue
            annotation.pop(NameObject("/A"), None)
            annotation[NameObject("/Dest")] = ArrayObject([writer.pages[target].indirect_reference, NameObject("/Fit")])
            converted.append({"index_page": page_number + 1, "uri": uri, "target_page": target + 1})
    return converted, unresolved


def _page_number_overlay_html(page_numbers: list[int], font_config: FontConfig) -> str:
    pages = "\n".join(f'<div class="overlay-page"><div class="page-number">{number}</div></div>' for number in page_numbers)
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
{font_config.css()}
@page {{ size: A4 portrait; margin: 0; }}
html, body {{ margin: 0; padding: 0; background: transparent; font-family: {CUSTOM_FONT_STACK}; }}
.overlay-page {{ position: relative; width: {A4_WIDTH_PT}pt; height: {A4_HEIGHT_PT}pt; break-after: page; page-break-after: always; }}
.overlay-page:last-child {{ break-after: auto; page-break-after: auto; }}
.page-number {{ position: absolute; left: 238pt; bottom: 11pt; width: 120pt; height: 24pt; background: white; display: flex; align-items: center; justify-content: center; font-family: {CUSTOM_FONT_STACK}; font-size: 8.5pt; color: #64748b; line-height: 1; }}
</style></head><body>{pages}</body></html>"""


def add_continuous_page_numbers(writer: PdfWriter, *, start: int = 1) -> int:
    if start < 1:
        raise ValueError("Page numbering must start at 1")
    if not writer.pages:
        return 0
    if HTML is None:
        raise RuntimeError("WeasyPrint is required for page-number overlays")
    font_config = FontConfig.from_env(required=True)
    assert font_config is not None
    with tempfile.TemporaryDirectory() as tmp:
        overlay_path = Path(tmp) / "continuous-page-numbers.pdf"
        HTML(string=_page_number_overlay_html(list(range(start, start + len(writer.pages))), font_config)).write_pdf(overlay_path)
        assert_portrait_a4(overlay_path, label="page-number overlay")
        overlay = PdfReader(overlay_path)
        if len(overlay.pages) != len(writer.pages):
            raise RuntimeError(f"Page-number overlay mismatch: expected {len(writer.pages)}, got {len(overlay.pages)}")
        for page, overlay_page in zip(writer.pages, overlay.pages):
            page.merge_page(overlay_page, over=True)
    writer.set_page_label(0, len(writer.pages) - 1, style=PageLabelStyle.DECIMAL, start=start)
    return len(writer.pages)


def add_outlines(writer: PdfWriter, source: SourceIndex, starts: dict[str, int]) -> int:
    count = 1
    writer.add_outline_item("فهرست مطالعه / Study Index", 0, bold=True)
    for group_order, group_title, sessions in source.groups:
        first_page = starts[sessions[0].stem.casefold()]
        parent = writer.add_outline_item(str(group_title), first_page, bold=True, is_open=False)
        count += 1
        for session in sessions:
            writer.add_outline_item(str(session.title), starts[session.stem.casefold()], parent=parent)
            count += 1
    return count


def _flatten_outline(reader: PdfReader) -> list[tuple[str, int]]:
    result: list[tuple[str, int]] = []

    def walk(items):
        for item in items:
            if isinstance(item, list):
                walk(item)
                continue
            try:
                page = reader.get_destination_page_number(item)
            except Exception:
                page = -1
            result.append((str(getattr(item, "title", item)), page))

    walk(reader.outline)
    return result


def _qa_final_pdf(output: Path, *, source: SourceIndex, index_pages: int, converted: list[dict], expected_bookmarks: int, page_number_start: int) -> dict:
    reader = PdfReader(output)
    geometry = assert_portrait_a4(reader, label="final PDF")
    fonts = extract_font_report(reader)
    if not fonts["fonts"]:
        raise RuntimeError("No fonts were found in the final PDF")
    if fonts["unembedded"]:
        raise RuntimeError("Unembedded fonts detected: " + ", ".join(fonts["unembedded"]))
    if fonts["forbidden"]:
        raise RuntimeError("Forbidden default fonts detected: " + ", ".join(fonts["forbidden"]))
    if fonts["unexpected"]:
        raise RuntimeError("Unexpected fallback fonts detected: " + ", ".join(fonts["unexpected"]))
    unresolved = unresolved_local_links(reader)
    if unresolved:
        raise RuntimeError(f"Unresolved note:// links remain: {unresolved}")
    labels = page_label_sequence(reader)
    expected_labels = [str(value) for value in range(page_number_start, page_number_start + len(reader.pages))]
    if labels != expected_labels:
        raise RuntimeError(f"PDF page labels are not continuous: expected {expected_labels[:3]}...{expected_labels[-3:]}, got {labels[:3]}...{labels[-3:]}")
    footer_failures = footer_number_pages(reader, start=page_number_start)
    if footer_failures:
        raise RuntimeError("Visible footer page numbers missing on pages: " + ", ".join(map(str, footer_failures)))
    outline = _flatten_outline(reader)
    invalid_outline = [(title, page) for title, page in outline if page < 0 or page >= len(reader.pages)]
    if invalid_outline:
        raise RuntimeError(f"Invalid bookmark destinations: {invalid_outline}")
    if len(outline) != expected_bookmarks:
        raise RuntimeError(f"Bookmark count mismatch: expected {expected_bookmarks}, got {len(outline)}")
    expected_titles = ["فهرست مطالعه / Study Index"]
    for _, group_title, sessions in source.groups:
        expected_titles.append(group_title)
        expected_titles.extend(item.title for item in sessions)
    actual_titles = [title for title, _ in outline]
    if actual_titles != expected_titles:
        raise RuntimeError("Bookmark hierarchy/order does not match the source INDEX")
    if len(source.sessions) != len({item.stem.casefold() for item in source.sessions}):
        raise RuntimeError("Session completeness check failed: duplicate session")
    return {
        "final_pdf": str(output),
        "total_pages": len(reader.pages),
        "study_index_pages": index_pages,
        "sessions": len(source.sessions),
        "groups": len(source.groups),
        "converted_internal_links": len(converted),
        "unresolved_links": 0,
        "bookmarks": len(outline),
        "page_number_range": f"{page_number_start}-{page_number_start + len(reader.pages) - 1}",
        "embedded_fonts": fonts["embedded"],
        "page_size": "A4 (approximately 595 x 842 pt)",
        "page_orientation": "Portrait",
        "portrait_pages": geometry["portrait_pages"],
        "landscape_pages": geometry["landscape_pages"],
        "rotated_pages": geometry["rotated_pages"],
        "invalid_geometry_pages": [item["page"] for item in geometry["invalid_pages"]],
        "quality_check": "PASSED",
    }


def create_combined(notes_dir: Path, pdf_dir: Path | None = None, output_path: Path | None = None, index_md: Path | None = None, *, source_index: Path | None = None, title: str | None = None, css_file: Path | None = None, continuous_page_numbers: bool = True, page_number_start: int = 1) -> Path:
    notes_dir = Path(notes_dir).resolve()
    if not notes_dir.is_dir():
        raise FileNotFoundError(f"NOTES_DIR is missing or unreadable: {notes_dir}")
    pdf_dir = Path(pdf_dir).resolve() if pdf_dir else (notes_dir / "pdfs").resolve()
    pdf_dir.mkdir(parents=True, exist_ok=True)
    source_index = Path(source_index).resolve() if source_index else (notes_dir / "INDEX.md").resolve()
    if not source_index.is_file():
        raise FileNotFoundError(f"Primary source INDEX was not found: {source_index}")
    source = parse_source_index(source_index, notes_dir=notes_dir)
    if not source.sessions:
        raise RuntimeError("No sessions were extracted from the source INDEX")
    book_title = title or source.title

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        if index_md:
            index_source = Path(index_md).resolve()
            if not index_source.is_file():
                raise FileNotFoundError(f"Rich index Markdown not found: {index_source}")
        else:
            index_source, _ = generate_index(source_index, tmp_dir / "STUDY_INDEX-rewritten.md", notes_dir=notes_dir)

        pdfs: list[Path] = []
        component_style = PdfStyle(page_numbers=False)
        for session in source.sessions:
            note = session.note_path
            if not note.is_file():
                raise FileNotFoundError(f"Missing session Markdown: {note}")
            pdf = pdf_dir / f"{note.stem}.pdf"
            rebuild = not pdf.exists() or note.stat().st_mtime_ns > pdf.stat().st_mtime_ns
            if rebuild:
                print(f"Generating topic PDF: {note.name}")
                make_pdf(note, pdf, style=component_style, css_file=css_file)
            assert_portrait_a4(pdf, label=pdf.name)
            pdfs.append(pdf)

        index_pdf = tmp_dir / "00_STUDY_INDEX.pdf"
        make_pdf(index_source, index_pdf, style=component_style, title=f"{book_title} - Study Index", css_file=css_file, auto_rtl=False)
        index_pages = len(PdfReader(index_pdf).pages)

        writer = PdfWriter()
        writer.append(index_pdf, import_outline=False)
        alias_to_page: dict[str, int] = {}
        starts: dict[str, int] = {}
        for session, pdf in zip(source.sessions, pdfs):
            start = len(writer.pages)
            print(f"Adding session {session.order}: {pdf.name} (final page {start + 1})")
            writer.append(pdf, import_outline=False)
            starts[session.stem.casefold()] = start
            for alias in topic_aliases(session.note_path, pdf):
                alias_to_page[alias] = start

        converted, unresolved = rewrite_index_links(writer, index_pages, alias_to_page)
        if unresolved:
            detail = "; ".join(f"page={item['index_page']} uri={item['uri']}" for item in unresolved)
            raise RuntimeError(f"Unresolved internal links: {detail}")
        if not converted:
            raise RuntimeError("No session links were converted to internal destinations")
        expected_starts = set(starts.values())
        wrong_targets = [item for item in converted if item["target_page"] - 1 not in expected_starts]
        if wrong_targets:
            raise RuntimeError(f"Internal links target invalid session pages: {wrong_targets}")
        linked_starts = {item["target_page"] - 1 for item in converted}
        missing_link_targets = sorted(expected_starts - linked_starts)
        if missing_link_targets:
            raise RuntimeError("At least one session title has no resolved internal link. Missing target pages: " + ", ".join(str(page + 1) for page in missing_link_targets))

        for stem, page in starts.items():
            writer.add_named_destination(f"topic-{stem}", page)
        bookmark_count = add_outlines(writer, source, starts)
        if continuous_page_numbers:
            add_continuous_page_numbers(writer, start=page_number_start)
        writer.add_metadata({"/Title": book_title, "/Subject": "Bilingual study notes with internal links, bookmarks, and continuous numbering"})
        writer.page_mode = "/UseOutlines"

        output = Path(output_path).resolve() if output_path else (notes_dir / "FINAL_STUDY_NOTES.pdf").resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("wb") as stream:
            writer.write(stream)

    report = _qa_final_pdf(output, source=source, index_pages=index_pages, converted=converted, expected_bookmarks=bookmark_count, page_number_start=page_number_start)
    report_path = output.with_suffix(".qa.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nFinal PDF:", report["final_pdf"])
    print("Total pages:", report["total_pages"])
    print("Study Index pages:", report["study_index_pages"])
    print("Sessions:", report["sessions"])
    print("Groups:", report["groups"])
    print("Converted internal links:", report["converted_internal_links"])
    print("Unresolved links: 0")
    print("Bookmarks:", report["bookmarks"])
    print("Page number range:", report["page_number_range"])
    print("Embedded font:", ", ".join(report["embedded_fonts"]))
    print("Page size: A4")
    print("Page orientation: Portrait")
    print("Portrait pages:", report["portrait_pages"])
    print("Landscape pages: 0")
    print("Rotated pages: 0")
    print("Quality check: PASSED")
    print("QA report:", report_path)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Create and verify the final combined study PDF")
    parser.add_argument("--notes-dir", required=True)
    parser.add_argument("--pdf-dir")
    parser.add_argument("--output")
    parser.add_argument("--index-md", help="Already-generated rich bilingual index Markdown")
    parser.add_argument("--source-index", help="Primary input INDEX.md; defaults to NOTES_DIR/INDEX.md")
    parser.add_argument("--title")
    parser.add_argument("--css")
    parser.add_argument("--no-continuous-page-numbers", action="store_true")
    parser.add_argument("--page-number-start", type=int, default=1)
    args = parser.parse_args()
    create_combined(
        Path(args.notes_dir),
        Path(args.pdf_dir) if args.pdf_dir else None,
        Path(args.output) if args.output else None,
        Path(args.index_md) if args.index_md else None,
        source_index=Path(args.source_index) if args.source_index else None,
        title=args.title,
        css_file=Path(args.css) if args.css else None,
        continuous_page_numbers=not args.no_continuous_page_numbers,
        page_number_start=args.page_number_start,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
