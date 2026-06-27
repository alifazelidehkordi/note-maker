#!/usr/bin/env python3
"""
Create a combined PDF from a folder of notes:
- First page: nice index / table of contents listing all titles
- Then all individual PDFs in order

Usage:
  python scripts/create_combined_pdf.py --notes-dir outputs/notes --pdf-dir outputs/pdfs --output outputs/combined.pdf
"""

import argparse
import re
import tempfile
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from convert_md_to_pdf import make_pdf


def extract_title(md_path: Path) -> str:
    """Extract the first # heading as title, fallback to filename."""
    try:
        text = md_path.read_text(encoding="utf-8", errors="ignore")
        match = re.search(r"^#\s+(.+?)\s*$", text, re.MULTILINE)
        if match:
            return match.group(1).strip()
    except Exception:
        pass
    return md_path.stem.replace("_", " ").title()


def build_index_markdown(titles: list[tuple[str, str]]) -> str:
    """Build a clean index Markdown."""
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
) -> Path:
    notes_dir = Path(notes_dir).resolve()
    if pdf_dir is None:
        pdf_dir = notes_dir / "pdfs"
    pdf_dir = Path(pdf_dir).resolve()

    if not notes_dir.exists():
        raise FileNotFoundError(f"Notes directory not found: {notes_dir}")

    # Collect .md files sorted by name (numeric prefix respected)
    md_files = sorted(
        [p for p in notes_dir.glob("*.md") if p.is_file()],
        key=lambda p: p.name.lower()
    )

    if not md_files:
        raise ValueError(f"No .md files found in {notes_dir}")

    # Prepare titles
    titles = []
    pdf_paths = []
    for md in md_files:
        title = extract_title(md)
        titles.append((md.stem, title))

        pdf_path = pdf_dir / f"{md.stem}.pdf"
        if not pdf_path.exists():
            # Try to generate the individual PDF on the fly if missing
            print(f"PDF missing for {md.name}, generating...")
            generated = make_pdf(md, pdf_dir / f"{md.stem}.pdf")
            pdf_path = generated
        pdf_paths.append(pdf_path)

    # Build index markdown
    index_md = build_index_markdown(titles)

    # Write temp index and convert to PDF
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        index_md_path = tmp_path / "00_INDEX.md"
        index_md_path.write_text(index_md, encoding="utf-8")

        index_pdf_path = tmp_path / "00_INDEX.pdf"
        make_pdf(index_md_path, index_pdf_path)

        # Now merge: index first + all PDFs
        writer = PdfWriter()

        # Add index
        reader = PdfReader(index_pdf_path)
        for page in reader.pages:
            writer.add_page(page)

        # Add all parts
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

        print(f"\n✅ Combined PDF created: {output_path}")
        print(f"   Total pages: {len(writer.pages)}")
        print(f"   Files included: {len(pdf_paths)} + index")

        return output_path


def main():
    parser = argparse.ArgumentParser(description="Combine all notes into one PDF with index page")
    parser.add_argument("--notes-dir", required=True, help="Directory containing the .md notes")
    parser.add_argument("--pdf-dir", help="Directory containing the .pdf files (defaults to notes-dir/pdfs)")
    parser.add_argument("--output", help="Output combined PDF path")
    args = parser.parse_args()

    create_combined(
        notes_dir=Path(args.notes_dir),
        pdf_dir=Path(args.pdf_dir) if args.pdf_dir else None,
        output_path=Path(args.output) if args.output else None,
    )


if __name__ == "__main__":
    main()
