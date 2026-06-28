#!/usr/bin/env python3
"""
Create a combined PDF from a folder of notes:
- First pages: rich STUDY_INDEX when available, else a simple TOC
- Then all individual topic-note PDFs in order

Usage:
  python scripts/create_combined_pdf.py --notes-dir outputs/notes --pdf-dir outputs/pdfs --output outputs/combined.pdf
  python scripts/create_combined_pdf.py --notes-dir outputs/phisiopath-full --index-md outputs/phisiopath-full/STUDY_INDEX-rewritten.md
"""

import argparse
import tempfile
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from convert_md_to_pdf import find_rich_index_md, infer_title, is_topic_note, make_pdf


def extract_title(md_path: Path) -> str:
    """Extract the first # heading as title, fallback to filename."""
    fallback = md_path.stem.replace("_", " ").title()
    try:
        text = md_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return fallback
    return infer_title(text, fallback)


def build_simple_index_markdown(titles: list[tuple[str, str]]) -> str:
    """Fallback TOC when no rich STUDY_INDEX exists."""
    lines = [
        "# فهرست مطالب / Table of Contents",
        "",
        "این فایل شامل تمام بخش‌های تولید شده است.",
        "",
        "| # | عنوان | فایل |",
        "|---|-------|------|",
    ]
    for i, (stem, title) in enumerate(titles, 1):
        lines.append(f"| {i} | {title} | `{stem}.md` |")
    lines.extend([
        "",
        "## یادداشت",
        "- همه بخش‌ها به ترتیب شماره فایل مرتب شده‌اند.",
        "- برای مطالعه سریع از فهرست بالا استفاده کنید.",
    ])
    return "\n".join(lines)


def create_combined(
    notes_dir: Path,
    pdf_dir: Path | None = None,
    output_path: Path | None = None,
    index_md: Path | None = None,
) -> Path:
    notes_dir = Path(notes_dir).resolve()
    if pdf_dir is None:
        pdf_dir = notes_dir / "pdfs"
    pdf_dir = Path(pdf_dir).resolve()

    if not notes_dir.exists():
        raise FileNotFoundError(f"Notes directory not found: {notes_dir}")

    md_files = sorted(
        [p for p in notes_dir.glob("*.md") if p.is_file() and is_topic_note(p)],
        key=lambda p: p.name.lower(),
    )

    if not md_files:
        raise ValueError(f"No topic notes found in {notes_dir}")

    titles: list[tuple[str, str]] = []
    pdf_paths: list[Path] = []
    for md in md_files:
        title = extract_title(md)
        titles.append((md.stem, title))

        pdf_path = pdf_dir / f"{md.stem}.pdf"
        if not pdf_path.exists():
            print(f"PDF missing for {md.name}, generating...")
            pdf_path = make_pdf(md, pdf_path)
        pdf_paths.append(pdf_path)

    rich_index = Path(index_md).resolve() if index_md else find_rich_index_md(notes_dir)
    if rich_index and rich_index.is_file():
        print(f"Using rich index: {rich_index.name}")
        index_source = rich_index
    else:
        print("No rich STUDY_INDEX found — using simple table of contents.")
        index_source = None

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        if index_source is not None:
            index_md_path = index_source
        else:
            index_md_path = tmp_path / "00_INDEX.md"
            index_md_path.write_text(build_simple_index_markdown(titles), encoding="utf-8")

        index_pdf_path = tmp_path / "00_INDEX.pdf"
        make_pdf(index_md_path, index_pdf_path)

        writer = PdfWriter()
        reader = PdfReader(index_pdf_path)
        for page in reader.pages:
            writer.add_page(page)

        for pdf_path in pdf_paths:
            print(f"  Adding: {pdf_path.name}")
            reader = PdfReader(pdf_path)
            for page in reader.pages:
                writer.add_page(page)

        if output_path is None:
            output_path = pdf_dir.parent / "COMBINED_NOTES.pdf"

        output_path = Path(output_path).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "wb") as f:
            writer.write(f)

        index_label = rich_index.name if rich_index else "simple TOC"
        print(f"\n✅ Combined PDF created: {output_path}")
        print(f"   Total pages: {len(writer.pages)}")
        print(f"   Index: {index_label}")
        print(f"   Topic notes: {len(pdf_paths)}")

        return output_path


def main():
    parser = argparse.ArgumentParser(description="Combine topic notes into one PDF with index front matter")
    parser.add_argument("--notes-dir", required=True, help="Directory containing the .md topic notes")
    parser.add_argument("--pdf-dir", help="Directory containing the .pdf files (defaults to notes-dir/pdfs)")
    parser.add_argument("--output", help="Output combined PDF path")
    parser.add_argument(
        "--index-md",
        help="Rich STUDY_INDEX markdown for the opening pages (auto-detects STUDY_INDEX-rewritten.md)",
    )
    args = parser.parse_args()

    create_combined(
        notes_dir=Path(args.notes_dir),
        pdf_dir=Path(args.pdf_dir) if args.pdf_dir else None,
        output_path=Path(args.output) if args.output else None,
        index_md=Path(args.index_md) if args.index_md else None,
    )


if __name__ == "__main__":
    main()