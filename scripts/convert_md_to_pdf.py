#!/usr/bin/env python3
"""
Convert clean Markdown notes (from Note Maker) to high-quality study PDFs.

Uses WeasyPrint for excellent flowing layout + CSS styling.
Produces clean, readable PDFs suitable for study/review/printing
(similar style to academic/Obsidian study material exports).
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import markdown
from weasyprint import HTML, CSS

DEFAULT_CSS = """
@page {
  size: A4;
  margin: 1.6cm 1.8cm;
  @bottom-center {
    content: counter(page);
    font-size: 9pt;
    color: #718096;
  }
}

body {
  font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans", sans-serif;
  font-size: 10.2pt;
  line-height: 1.55;
  color: #1a202c;
  max-width: 100%;
}

h1 {
  font-size: 17pt;
  margin: 0 0 14pt 0;
  color: #1a365d;
  padding-bottom: 6pt;
  border-bottom: 2.5px solid #3182ce;
  page-break-after: avoid;
}

h2 {
  font-size: 12.5pt;
  margin: 16pt 0 6pt 0;
  color: #2b6cb0;
  border-left: 5px solid #63b3ed;
  padding-left: 9pt;
  page-break-after: avoid;
}

h3 {
  font-size: 10.8pt;
  margin: 11pt 0 4pt 0;
  color: #2d3748;
  page-break-after: avoid;
}

p { margin: 5pt 0; }

strong, b {
  color: #1a365d;
  font-weight: 600;
}

ul, ol {
  margin: 5pt 0 8pt 18pt;
}

li {
  margin: 3pt 0;
}

pre, code {
  background: #f0f4f8;
  padding: 2pt 5pt;
  border-radius: 3pt;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 8.8pt;
}

.key-points, .keypoints {
  background: #ebf8ff;
  border: 1.5px solid #3182ce;
  border-radius: 5pt;
  padding: 8pt 11pt;
  margin: 14pt 0;
  page-break-inside: avoid;
}

.key-points h2, .keypoints h2 {
  margin-top: 0;
  color: #2b6cb0;
  border: none;
  padding-left: 0;
  font-size: 11.5pt;
}

hr {
  border: none;
  border-top: 1px solid #e2e8f0;
  margin: 10pt 0;
}
"""

def md_to_html(md_text: str) -> str:
    """Convert the note Markdown to clean HTML."""
    # Use useful extensions
    html_body = markdown.markdown(
        md_text,
        extensions=["extra", "sane_lists", "smarty"],
    )

    # Wrap the Key Points section in a styled container
    html_body = re.sub(
        r'(<h2[^>]*>Key Points.*?</h2>)(.*?)(?=<h2|$)',
        r'<div class="key-points">\1\2</div>',
        html_body,
        flags=re.IGNORECASE | re.DOTALL,
    )

    return html_body

def make_pdf(md_path: Path, output_pdf: Path | None = None, extra_css: str | None = None) -> Path:
    """Convert one Markdown note to a beautiful PDF."""
    md_text = md_path.read_text(encoding="utf-8")
    body_html = md_to_html(md_text)

    # Try to get a nice title for the document
    title_match = re.search(r"^#\s+(.+)$", md_text, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else md_path.stem

    full_html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <style>{DEFAULT_CSS}</style>
  {f'<style>{extra_css}</style>' if extra_css else ''}
</head>
<body>
{body_html}
</body>
</html>"""

    if output_pdf is None:
        output_pdf = md_path.with_suffix(".pdf")

    output_pdf.parent.mkdir(parents=True, exist_ok=True)

    HTML(string=full_html).write_pdf(output_pdf)

    return output_pdf

def batch_convert(input_dir: Path, output_dir: Path, pattern: str = "*.md") -> list[Path]:
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results: list[Path] = []
    for md in sorted(input_dir.glob(pattern)):
        if md.is_file():
            pdf = output_dir / (md.stem + ".pdf")
            try:
                out = make_pdf(md, pdf)
                print(f"✓ {md.name} → {pdf.name}")
                results.append(out)
            except Exception as exc:
                print(f"✗ Failed {md.name}: {exc}")
    return results

def main() -> int:
    parser = argparse.ArgumentParser(description="Markdown notes → styled study PDFs (WeasyPrint)")
    parser.add_argument("input", help="Single .md file or directory")
    parser.add_argument("--output", help="Output PDF path (single) or directory (batch)")
    parser.add_argument("--batch", action="store_true", help="Process a whole directory")
    args = parser.parse_args()

    inp = Path(args.input)

    if args.batch or inp.is_dir():
        out_dir = Path(args.output) if args.output else inp / "pdfs"
        batch_convert(inp, out_dir)
    else:
        out = Path(args.output) if args.output else inp.with_suffix(".pdf")
        result = make_pdf(inp, out)
        print(f"Created PDF: {result}")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
