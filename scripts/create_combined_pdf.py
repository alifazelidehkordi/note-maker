#!/usr/bin/env python3
"""Create one validated PDF with a bilingual index, links, outlines, and labels."""
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

from pypdf import PdfReader, PdfWriter
from pypdf.constants import PageLabelStyle
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, NameObject

from convert_md_to_pdf import FontConfig, HTML, infer_title, make_pdf
from generate_study_index import Session, StudyData, generate_index, group_sessions, parse_source_index


@dataclass(frozen=True)
class BuildReport:
    final_pdf: str
    total_pages: int
    index_pages: int
    sessions: int
    internal_links_converted: int
    unresolved_links: int
    page_number_range: str
    font_name: str
    embedded_fonts: list[str]
    bookmarks: int
    groups: int


def topic_aliases(note: Path, pdf: Path) -> set[str]:
    values = (note.name, note.stem, pdf.name, pdf.stem)
    return {unquote(value).casefold() for value in values}


def aliases_from_uri(uri: str) -> set[str]:
    parsed = urlparse(uri)
    scheme = parsed.scheme.casefold()
    if scheme == "note":
        raw = (parsed.netloc + parsed.path).lstrip("/")
    elif scheme == "file":
        raw = parsed.path
    elif scheme == "":
        raw = parsed.path or uri
    else:
        return set()
    raw = unquote(raw).replace("\\", "/").rstrip("/")
    if not raw:
        return set()
    name = raw.rsplit("/", 1)[-1]
    path = Path(name)
    aliases = {name.casefold(), path.stem.casefold()}
    if path.suffix.casefold() in {".md", ".pdf"}:
        aliases.add(path.with_suffix("").name.casefold())
    return aliases


def rewrite_index_links(writer: PdfWriter, index_page_count: int, alias_to_page: dict[str, int]) -> tuple[int, int, list[int]]:
    converted = 0
    unresolved = 0
    target_pages: list[int] = []
    for page_number in range(index_page_count):
        annotations = writer.pages[page_number].get("/Annots") or []
        for ref in annotations:
            annotation = ref.get_object()
            action = annotation.get("/A")
            if not action:
                continue
            action = action.get_object() if hasattr(action, "get_object") else action
            if action.get("/S") != "/URI":
                continue
            uri = str(action.get("/URI", ""))
            candidates = aliases_from_uri(uri)
            if not candidates:
                continue
            target = next((alias_to_page[a] for a in candidates if a in alias_to_page), None)
            if target is None:
                if urlparse(uri).scheme.casefold() in {"note", "file", ""}:
                    unresolved += 1
                continue
            annotation.pop(NameObject("/A"), None)
            annotation[NameObject("/Dest")] = ArrayObject([
                writer.pages[target].indirect_reference,
                NameObject("/Fit"),
            ])
            converted += 1
            target_pages.append(target)
    return converted, unresolved, target_pages


def _page_size(page) -> tuple[float, float]:
    return round(float(page.mediabox.width), 3), round(float(page.mediabox.height), 3)


def _font_face_css(fonts: FontConfig) -> str:
    arabic_bold = fonts.arabic_bold or fonts.arabic_regular
    return f"""
@font-face {{ font-family: 'StudyArabic'; src: url('{fonts.arabic_regular.resolve().as_uri()}'); font-weight: 400; }}
@font-face {{ font-family: 'StudyArabic'; src: url('{Path(arabic_bold).resolve().as_uri()}'); font-weight: 700; }}
@font-face {{ font-family: 'StudyLatin'; src: url('{fonts.latin_regular.resolve().as_uri()}'); font-weight: 400; }}
@font-face {{ font-family: 'StudyLatin'; src: url('{fonts.latin_bold.resolve().as_uri()}'); font-weight: 700; }}
"""


def _page_number_overlay_html(numbers: list[int], width: float, height: float, fonts: FontConfig) -> str:
    pages = "\n".join(
        f'<div class="page"><div class="number">{number}</div></div>' for number in numbers
    )
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
{_font_face_css(fonts)}
@page {{ size: {width}pt {height}pt; margin: 0; }}
html, body {{ margin: 0; padding: 0; background: transparent; }}
body {{ font-family: 'StudyArabic', 'StudyLatin'; }}
.page {{ position: relative; width: {width}pt; height: {height}pt; break-after: page; }}
.page:last-child {{ break-after: auto; }}
.number {{ position: absolute; left: 0; right: 0; bottom: 13pt; text-align: center; font-size: 8.5pt; line-height: 1; color: #64748b; }}
</style></head><body>{pages}</body></html>"""


def add_continuous_page_numbers(writer: PdfWriter, fonts: FontConfig, start: int = 1) -> int:
    if start < 1:
        raise ValueError("Page numbering must start at 1")
    if HTML is None:
        raise RuntimeError("WeasyPrint is required for continuous page numbering")
    grouped: dict[tuple[float, float], list[tuple[int, int]]] = {}
    for page_index, page in enumerate(writer.pages):
        grouped.setdefault(_page_size(page), []).append((page_index, start + page_index))
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        for group_no, ((width, height), entries) in enumerate(grouped.items(), 1):
            overlay_path = tmp_dir / f"page-number-{group_no}.pdf"
            HTML(string=_page_number_overlay_html([n for _, n in entries], width, height, fonts), base_url=str(fonts.arabic_regular.parent)).write_pdf(overlay_path)
            overlay = PdfReader(overlay_path)
            if len(overlay.pages) != len(entries):
                raise RuntimeError("Page-number overlay page count mismatch")
            for overlay_page, (target_index, _) in zip(overlay.pages, entries):
                writer.pages[target_index].merge_page(overlay_page, over=True)
    writer.set_page_label(0, len(writer.pages) - 1, style=PageLabelStyle.DECIMAL, start=start)
    return len(writer.pages)


def add_outlines(writer: PdfWriter, data: StudyData, starts: dict[str, int]) -> int:
    count = 0
    writer.add_outline_item("فهرست مطالعه / Study Index", 0, bold=True)
    count += 1
    for group_no, (group, sessions) in enumerate(group_sessions(data.sessions).items(), 1):
        first_page = starts[sessions[0].stem.casefold()]
        group_fa = sessions[0].group_fa
        label = group if group_fa == group else f"{group_fa} / {group}"
        parent = writer.add_outline_item(f"{group_no}. {label}", first_page, bold=True, is_open=False)
        count += 1
        for session in sessions:
            title = session.title if session.title_fa == session.title else f"{session.title_fa} / {session.title}"
            writer.add_outline_item(f"{session.number}. {title}", starts[session.stem.casefold()], parent=parent)
            count += 1
    return count


def _resolve(obj):
    return obj.get_object() if isinstance(obj, IndirectObject) else obj


def _font_descriptor(font: DictionaryObject) -> DictionaryObject | None:
    font = _resolve(font)
    descriptor = font.get("/FontDescriptor")
    if descriptor:
        return _resolve(descriptor)
    descendants = font.get("/DescendantFonts")
    if descendants:
        first = _resolve(descendants[0])
        descriptor = first.get("/FontDescriptor")
        if descriptor:
            return _resolve(descriptor)
    return None


def inspect_fonts(reader: PdfReader) -> tuple[list[str], list[str]]:
    names: set[str] = set()
    non_embedded: set[str] = set()
    for page in reader.pages:
        resources = _resolve(page.get("/Resources") or {})
        fonts = _resolve(resources.get("/Font") or {})
        for font_ref in fonts.values():
            font = _resolve(font_ref)
            raw_name = str(font.get("/BaseFont", "Unknown")).lstrip("/")
            clean_name = re.sub(r"^[A-Z]{6}\+", "", raw_name)
            names.add(clean_name)
            descriptor = _font_descriptor(font)
            embedded = bool(descriptor and any(key in descriptor for key in ("/FontFile", "/FontFile2", "/FontFile3")))
            if not embedded:
                non_embedded.add(clean_name)
    return sorted(names), sorted(non_embedded)


def _dest_page_number(reader: PdfReader, dest) -> int | None:
    dest = _resolve(dest)
    if isinstance(dest, (list, ArrayObject)) and dest:
        target = dest[0]
        target = _resolve(target)
        for index, page in enumerate(reader.pages):
            if page.indirect_reference and hasattr(dest[0], "idnum") and page.indirect_reference.idnum == dest[0].idnum:
                return index
            if target is page:
                return index
    return None


def verify_output(path: Path, *, index_pages: int, sessions: int, converted: int, expected_targets: list[int], page_start: int, expected_bookmarks: int) -> tuple[list[str], int]:
    reader = PdfReader(path)
    if len(reader.pages) < index_pages + sessions:
        raise RuntimeError("Final PDF has fewer pages than the index plus one page per session")
    labels = reader.page_labels
    expected_labels = [str(page_start + i) for i in range(len(reader.pages))]
    if labels != expected_labels:
        raise RuntimeError(f"PDF page labels are not continuous: first={labels[:3]} last={labels[-3:]}")

    unresolved = 0
    linked_targets: list[int] = []
    for page_no in range(index_pages):
        for ref in reader.pages[page_no].get("/Annots") or []:
            annot = _resolve(ref)
            action = annot.get("/A")
            if action:
                action = _resolve(action)
                uri = str(action.get("/URI", "")) if action.get("/S") == "/URI" else ""
                if aliases_from_uri(uri):
                    unresolved += 1
            dest = annot.get("/Dest")
            if dest:
                target = _dest_page_number(reader, dest)
                if target is not None and target >= index_pages:
                    linked_targets.append(target)
    if unresolved:
        raise RuntimeError(f"{unresolved} unresolved local link(s) remain in final PDF")
    if len(linked_targets) != converted:
        raise RuntimeError(f"Internal link verification mismatch: expected {converted}, found {len(linked_targets)}")
    if sorted(linked_targets) != sorted(expected_targets):
        raise RuntimeError("One or more session links point to the wrong page")

    fonts, non_embedded = inspect_fonts(reader)
    if non_embedded:
        raise RuntimeError(f"Non-embedded fonts detected: {', '.join(non_embedded)}")
    if not fonts:
        raise RuntimeError("No embedded fonts were detected")
    unexpected_fonts = [name for name in fonts if not name.startswith(("StudyArabic", "StudyLatin"))]
    if unexpected_fonts:
        raise RuntimeError(
            "Fonts outside the supplied Study font family were used: "
            + ", ".join(unexpected_fonts)
        )

    def outline_count(items) -> int:
        total = 0
        for item in items:
            if isinstance(item, list):
                total += outline_count(item)
            else:
                total += 1
        return total
    found_bookmarks = outline_count(reader.outline)
    if found_bookmarks != expected_bookmarks:
        raise RuntimeError(f"Bookmark count mismatch: expected {expected_bookmarks}, found {found_bookmarks}")
    return fonts, found_bookmarks


def create_combined(
    notes_dir: Path,
    source_index: Path,
    pdf_dir: Path,
    output_path: Path,
    *,
    font_config: FontConfig,
    title: str | None = None,
    generated_index: Path | None = None,
    css_file: Path | None = None,
    page_number_start: int = 1,
    report_json: Path | None = None,
) -> tuple[Path, BuildReport]:
    notes_dir = Path(notes_dir).resolve()
    source_index = Path(source_index).resolve()
    pdf_dir = Path(pdf_dir).resolve()
    output_path = Path(output_path).resolve()
    font_config.validate()
    data = parse_source_index(source_index, notes_dir)
    book_title = title or data.course_title
    generated_index = Path(generated_index).resolve() if generated_index else (pdf_dir.parent / "STUDY_INDEX.md").resolve()
    generate_index(source_index, notes_dir, generated_index, generated_index.with_suffix(".metadata.json"))
    pdf_dir.mkdir(parents=True, exist_ok=True)

    session_pdfs: list[tuple[Session, Path, Path]] = []
    for session in data.sessions:
        note = Path(session.note_path)
        pdf = pdf_dir / f"{session.stem}.pdf"
        print(f"Converting session {session.number:02d}: {note.name}")
        make_pdf(note, pdf, css_file=css_file, font_config=font_config, page_numbers=False)
        session_pdfs.append((session, note, pdf))

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        index_pdf = tmp_dir / "00_STUDY_INDEX.pdf"
        make_pdf(generated_index, index_pdf, title=f"{book_title} - Study Index", css_file=css_file, font_config=font_config, page_numbers=False, force_index=True)
        index_pages = len(PdfReader(index_pdf).pages)
        writer = PdfWriter()
        writer.append(index_pdf, import_outline=False)
        starts: dict[str, int] = {}
        alias_to_page: dict[str, int] = {}
        seen: set[str] = set()
        for session, note, pdf in session_pdfs:
            key = session.stem.casefold()
            if key in seen:
                raise RuntimeError(f"Duplicate session detected: {session.stem}")
            seen.add(key)
            start = len(writer.pages)
            writer.append(pdf, import_outline=False)
            starts[key] = start
            for alias in topic_aliases(note, pdf):
                alias_to_page[alias] = start
            print(f"  Added {pdf.name} at final page {start + page_number_start}")
        if len(starts) != data.total_sessions:
            raise RuntimeError("A session was omitted or added more than once")

        converted, unresolved, expected_targets = rewrite_index_links(writer, index_pages, alias_to_page)
        if unresolved:
            raise RuntimeError(f"Build aborted: {unresolved} unresolved local index link(s)")
        missing_link_targets = sorted(set(starts.values()) - set(expected_targets))
        if missing_link_targets:
            raise RuntimeError(
                f"Index does not contain a working link for {len(missing_link_targets)} session(s): "
                f"{missing_link_targets}"
            )
        bookmarks = add_outlines(writer, data, starts)
        for stem, page in starts.items():
            writer.add_named_destination(f"session-{stem}", page)
        numbered = add_continuous_page_numbers(writer, font_config, start=page_number_start)
        writer.add_metadata({
            "/Title": book_title,
            "/Subject": "Combined study notes with bilingual clickable Study Index",
            "/Creator": "note-maker",
        })
        writer.page_mode = "/UseOutlines"

        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_output = output_path.with_suffix(output_path.suffix + ".tmp")
        if temp_output.exists():
            temp_output.unlink()
        with temp_output.open("wb") as stream:
            writer.write(stream)

        fonts, verified_bookmarks = verify_output(
            temp_output,
            index_pages=index_pages,
            sessions=data.total_sessions,
            converted=converted,
            expected_targets=expected_targets,
            page_start=page_number_start,
            expected_bookmarks=bookmarks,
        )
        os.replace(temp_output, output_path)

    report = BuildReport(
        final_pdf=str(output_path),
        total_pages=numbered,
        index_pages=index_pages,
        sessions=data.total_sessions,
        internal_links_converted=converted,
        unresolved_links=0,
        page_number_range=f"{page_number_start}-{page_number_start + numbered - 1}",
        font_name=", ".join(fonts),
        embedded_fonts=fonts,
        bookmarks=verified_bookmarks,
        groups=len(group_sessions(data.sessions)),
    )
    if report_json:
        report_json = Path(report_json).resolve()
        report_json.parent.mkdir(parents=True, exist_ok=True)
        report_json.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nFinal PDF created")
    print(f"  Path: {report.final_pdf}")
    print(f"  Total pages: {report.total_pages}")
    print(f"  Index pages: {report.index_pages}")
    print(f"  Sessions: {report.sessions}")
    print(f"  Internal links converted: {report.internal_links_converted}")
    print(f"  Unresolved links: {report.unresolved_links}")
    print(f"  Page number range: {report.page_number_range}")
    print(f"  Embedded font(s): {report.font_name}")
    return output_path, report


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and validate the final combined study-notes PDF")
    parser.add_argument("--notes-dir", required=True)
    parser.add_argument("--source-index", required=True, help="Authoritative input INDEX.md")
    parser.add_argument("--pdf-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--generated-index")
    parser.add_argument("--title")
    parser.add_argument("--css")
    parser.add_argument("--font-file", required=True, help="Arabic/Persian regular font")
    parser.add_argument("--font-bold-file", required=True, help="Latin bold font")
    parser.add_argument("--latin-font-file", required=True, help="Latin regular font")
    parser.add_argument("--arabic-font-bold-file")
    parser.add_argument("--page-number-start", type=int, default=1)
    parser.add_argument("--report-json")
    args = parser.parse_args()
    fonts = FontConfig(Path(args.font_file), Path(args.latin_font_file), Path(args.font_bold_file), Path(args.arabic_font_bold_file) if args.arabic_font_bold_file else None)
    create_combined(
        Path(args.notes_dir), Path(args.source_index), Path(args.pdf_dir), Path(args.output),
        font_config=fonts,
        title=args.title,
        generated_index=Path(args.generated_index) if args.generated_index else None,
        css_file=Path(args.css) if args.css else None,
        page_number_start=args.page_number_start,
        report_json=Path(args.report_json) if args.report_json else None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
