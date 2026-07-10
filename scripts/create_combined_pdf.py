#!/usr/bin/env python3
"""Merge split note PDFs with an auto-generated clickable study index."""
from __future__ import annotations

import argparse
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse

from pypdf import PdfReader, PdfWriter
from pypdf.constants import PageLabelStyle
from pypdf.generic import ArrayObject, NameObject

from convert_md_to_pdf import HTML, find_rich_index_md, infer_title, is_topic_note, make_pdf
from generate_study_index import collect_parts, generate_index, group_by_chapter, natural_key


def extract_title(path: Path) -> str:
    fallback = path.stem.replace("_", " ").replace("-", " ").title()
    try:
        return infer_title(path.read_text(encoding="utf-8", errors="ignore"), fallback)
    except OSError:
        return fallback


def build_simple_index_markdown(titles: list[tuple[str, str]]) -> str:
    lines = ["# فهرست مطالب / Table of Contents", "", "| # | عنوان |", "|---:|---|"]
    for number, (stem, title) in enumerate(titles, 1):
        lines.append(f"| {number} | [{title}](note://{stem}) |")
    return "\n".join(lines) + "\n"


def topic_aliases(md: Path, pdf: Path) -> set[str]:
    return {unquote(value).casefold() for value in (md.name, md.stem, pdf.name, pdf.stem)}


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
    result = {name.casefold(), path.stem.casefold()}
    if path.suffix.casefold() in {".md", ".pdf"}:
        result.add(path.with_suffix("").name.casefold())
    return result


def rewrite_index_links(writer: PdfWriter, index_page_count: int, alias_to_page: dict[str, int]) -> tuple[int, int]:
    converted = unresolved = 0
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
            target = next((alias_to_page[a] for a in candidates if a in alias_to_page), None)
            if target is None:
                if urlparse(uri).scheme.casefold() in {"note", "file", ""}:
                    unresolved += 1
                continue
            annotation.pop(NameObject("/A"), None)
            annotation[NameObject("/Dest")] = ArrayObject([writer.pages[target].indirect_reference, NameObject("/Fit")])
            converted += 1
    return converted, unresolved


def _page_size(page) -> tuple[float, float]:
    """Return a stable media-box size key in PDF points."""
    return round(float(page.mediabox.width), 3), round(float(page.mediabox.height), 3)


def _page_number_overlay_html(
    page_numbers: list[int],
    width: float,
    height: float,
    extra_css: str = "",
) -> str:
    """Build transparent overlay pages with a masked, centered footer number."""
    pages = "\n".join(
        f'<div class="continuous-number-page"><div class="continuous-page-number">{number}</div></div>'
        for number in page_numbers
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <style>
{extra_css}
@page {{
  size: {width}pt {height}pt;
  margin: 0;
}}
html, body {{
  margin: 0;
  padding: 0;
  background: transparent;
}}
body {{
  font-family: Vazirmatn, "Noto Naskh Arabic", "Noto Sans Arabic", Tahoma,
    system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}}
.continuous-number-page {{
  position: relative;
  width: {width}pt;
  height: {height}pt;
  break-after: page;
  page-break-after: always;
}}
.continuous-number-page:last-child {{
  break-after: auto;
  page-break-after: auto;
}}
.continuous-page-number {{
  position: absolute;
  left: {max((width - 108.0) / 2.0, 0.0)}pt;
  bottom: 1pt;
  width: {min(108.0, width)}pt;
  height: 38pt;
  box-sizing: border-box;
  background: #ffffff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 8.5pt;
  font-weight: 400;
  line-height: 1;
  color: #64748b;
}}
  </style>
</head>
<body>
{pages}
</body>
</html>
"""


def add_continuous_page_numbers(
    writer: PdfWriter,
    *,
    start: int = 1,
    css_file: Path | None = None,
) -> int:
    """Stamp continuous visible numbers and matching PDF page labels.

    Existing component PDFs may each start at page 1. The white footer mask hides
    those old counters before the final, book-wide number is placed on top.
    Pages are grouped by media-box size so mixed-size books remain supported.
    """
    if start < 1:
        raise ValueError("Page numbering must start at 1 or greater")
    if not writer.pages:
        return 0
    if HTML is None:
        raise RuntimeError("WeasyPrint is required to add continuous page numbers")

    extra_css = ""
    base_url: str | None = None
    if css_file:
        css_path = Path(css_file).resolve()
        if not css_path.is_file():
            raise FileNotFoundError(f"CSS file not found: {css_path}")
        extra_css = css_path.read_text(encoding="utf-8")
        base_url = str(css_path.parent)

    grouped: dict[tuple[float, float], list[tuple[int, int]]] = {}
    for page_index, page in enumerate(writer.pages):
        number = start + page_index
        grouped.setdefault(_page_size(page), []).append((page_index, number))

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        for group_number, ((width, height), entries) in enumerate(grouped.items(), 1):
            overlay_path = tmp_dir / f"page-numbers-{group_number}.pdf"
            overlay_html = _page_number_overlay_html(
                [number for _, number in entries], width, height, extra_css
            )
            HTML(string=overlay_html, base_url=base_url).write_pdf(overlay_path)
            overlay_reader = PdfReader(overlay_path)
            if len(overlay_reader.pages) != len(entries):
                raise RuntimeError(
                    "Page-number overlay count mismatch: "
                    f"expected {len(entries)}, got {len(overlay_reader.pages)}"
                )
            for overlay_page, (page_index, _) in zip(overlay_reader.pages, entries):
                writer.pages[page_index].merge_page(overlay_page, over=True)

    writer.set_page_label(
        0,
        len(writer.pages) - 1,
        style=PageLabelStyle.DECIMAL,
        start=start,
    )
    return len(writer.pages)


def add_outlines(writer: PdfWriter, notes: list[Path], starts: dict[str, int], index_pages: int) -> None:
    writer.add_outline_item("فهرست مطالعه / Study Index", 0, bold=True)
    parent = writer.add_outline_item("بخش‌ها / Sections", index_pages, bold=True, is_open=True)
    items = collect_parts(notes[0].parent) if notes else []
    by_name = {item["display_path"].name: item for item in items}
    selected = [by_name[p.name] for p in notes if p.name in by_name]
    if not selected:
        for note in notes:
            writer.add_outline_item(extract_title(note), starts[note.stem.casefold()], parent=parent)
        return
    chapters = group_by_chapter(selected)
    for number, chapter_items in chapters.items():
        first_page = starts[chapter_items[0]["stem"].casefold()]
        explicit = next((x["chapter_title_fa"] for x in chapter_items if x.get("chapter_title_fa")), None)
        name = explicit or ("بخش‌های مطالعه / Study Sections" if len(chapters) == 1 else f"فصل {number} / Chapter {number}")
        chapter_parent = writer.add_outline_item(str(name), first_page, parent=parent, bold=True, is_open=False)
        for item in chapter_items:
            writer.add_outline_item(str(item["title"]), starts[item["stem"].casefold()], parent=chapter_parent)


def resolve_index(notes_dir: Path, index_md: Path | None, title: str) -> tuple[Path, bool]:
    if index_md:
        explicit = Path(index_md).resolve()
        if not explicit.is_file():
            raise FileNotFoundError(f"Index Markdown not found: {explicit}")
        return explicit, False
    existing = find_rich_index_md(notes_dir)
    if existing and existing.name.casefold() == "study_index-rewritten.md":
        return existing.resolve(), False
    generated = notes_dir.parent / "STUDY_INDEX.md"
    generate_index(notes_dir, generated, clean_dir=notes_dir, title=title)
    return generated.resolve(), True


def pdf_rebuild_reason(note: Path, pdf: Path) -> str | None:
    """Return why a topic PDF must be regenerated, or ``None`` when current."""
    if not pdf.exists():
        return "missing"
    if note.stat().st_mtime_ns > pdf.stat().st_mtime_ns:
        return "source-newer"
    return None


def pdf_needs_rebuild(note: Path, pdf: Path) -> bool:
    """Return whether a topic PDF is absent or older than its Markdown source."""
    return pdf_rebuild_reason(note, pdf) is not None


def create_combined(
    notes_dir: Path,
    pdf_dir: Path | None = None,
    output_path: Path | None = None,
    index_md: Path | None = None,
    *,
    title: str = "Study Notes",
    css_file: Path | None = None,
    continuous_page_numbers: bool = True,
    page_number_start: int = 1,
) -> Path:
    notes_dir = Path(notes_dir).resolve()
    pdf_dir = Path(pdf_dir).resolve() if pdf_dir else (notes_dir / "pdfs").resolve()
    if not notes_dir.exists():
        raise FileNotFoundError(notes_dir)
    notes = sorted([p for p in notes_dir.glob("*.md") if is_topic_note(p)], key=natural_key)
    if not notes:
        raise ValueError(f"No topic notes found in {notes_dir}")
    pdf_dir.mkdir(parents=True, exist_ok=True)
    pdfs = []
    for note in notes:
        pdf = pdf_dir / f"{note.stem}.pdf"
        rebuild_reason = pdf_rebuild_reason(note, pdf)
        if rebuild_reason:
            detail = "missing" if rebuild_reason == "missing" else "source Markdown is newer"
            print(f"PDF rebuild required for {note.name} ({detail}), generating...")
            pdf = make_pdf(note, pdf, css_file=css_file)
        pdfs.append(pdf)

    index_source, generated = resolve_index(notes_dir, index_md, title)
    print(f"Using {'generated' if generated else 'existing'} rich index: {index_source}")
    with tempfile.TemporaryDirectory() as tmp:
        index_pdf = Path(tmp) / "00_STUDY_INDEX.pdf"
        make_pdf(
            index_source,
            index_pdf,
            title=f"{title} - Study Index",
            css_file=css_file,
        )
        index_pages = len(PdfReader(index_pdf).pages)
        writer = PdfWriter()
        writer.append(index_pdf, import_outline=True)
        alias_to_page: dict[str, int] = {}
        starts: dict[str, int] = {}
        for note, pdf in zip(notes, pdfs):
            start = len(writer.pages)
            print(f"  Adding: {pdf.name} (starts at final page {start + 1})")
            writer.append(pdf, import_outline=False)
            starts[note.stem.casefold()] = start
            for alias in topic_aliases(note, pdf):
                alias_to_page[alias] = start
        converted, unresolved = rewrite_index_links(writer, index_pages, alias_to_page)
        add_outlines(writer, notes, starts, index_pages)
        for stem, page in starts.items():
            writer.add_named_destination(f"topic-{stem}", page)
        numbered_pages = 0
        if continuous_page_numbers:
            numbered_pages = add_continuous_page_numbers(
                writer, start=page_number_start, css_file=css_file
            )
        writer.add_metadata({"/Title": title, "/Subject": "Combined study notes with clickable internal index"})
        writer.page_mode = "/UseOutlines"
        output = Path(output_path).resolve() if output_path else (pdf_dir.parent / "COMBINED_NOTES.pdf").resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("wb") as stream:
            writer.write(stream)
        total_pages = len(writer.pages)
    print(f"\nCombined PDF created: {output}")
    print(f"   Total pages: {total_pages}")
    print(f"   Index pages: {index_pages}")
    print(f"   Topic notes: {len(pdfs)}")
    print(f"   Internal index links converted: {converted}")
    if continuous_page_numbers:
        print(
            f"   Continuous page numbers: {page_number_start}-"
            f"{page_number_start + numbered_pages - 1}"
        )
    if unresolved:
        print(f"   Warning: {unresolved} local index link annotation(s) could not be matched.")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Combine topic notes with an internal clickable study index")
    parser.add_argument("--notes-dir", required=True)
    parser.add_argument("--pdf-dir")
    parser.add_argument("--output")
    parser.add_argument("--index-md")
    parser.add_argument("--title", default="Study Notes")
    parser.add_argument("--css", help="Extra CSS used for the index and page-number font")
    parser.add_argument(
        "--no-continuous-page-numbers",
        action="store_true",
        help="Keep component PDF page numbering instead of stamping one continuous sequence",
    )
    parser.add_argument(
        "--page-number-start",
        type=int,
        default=1,
        help="First visible/page-label number in the combined PDF (default: 1)",
    )
    args = parser.parse_args()
    create_combined(
        Path(args.notes_dir),
        Path(args.pdf_dir) if args.pdf_dir else None,
        Path(args.output) if args.output else None,
        Path(args.index_md) if args.index_md else None,
        title=args.title,
        css_file=Path(args.css) if args.css else None,
        continuous_page_numbers=not args.no_continuous_page_numbers,
        page_number_start=args.page_number_start,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
