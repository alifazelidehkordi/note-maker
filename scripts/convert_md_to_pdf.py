#!/usr/bin/env python3
"""
Convert clean Markdown study notes to high-quality PDFs with WeasyPrint.

Optimized for medical/study notes, Persian/English mixed text, printing, and
Obsidian-like exports. The visual style is controlled through CLI settings
instead of editing the Python source every time.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

try:
    import markdown
except ModuleNotFoundError:  # pragma: no cover - runtime dependency check
    markdown = None

try:
    from weasyprint import HTML
except ModuleNotFoundError:  # pragma: no cover - runtime dependency check
    HTML = None


@dataclass(frozen=True)
class PdfStyle:
    page_size: str = "A4"
    margin: str = "1.45cm 1.55cm"
    font_size: str = "10.4pt"
    line_height: str = "1.48"
    font_family: str = (
        'Vazirmatn, "Noto Naskh Arabic", "Noto Sans Arabic", Tahoma, '
        'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
    )
    theme: str = "medical-blue"
    preset: str = "study"
    rtl: bool = False
    page_numbers: bool = True


THEMES: dict[str, dict[str, str]] = {
    "medical-blue": {
        "text": "#172033",
        "muted": "#64748b",
        "heading": "#0f3a66",
        "accent": "#2563eb",
        "accent_soft": "#dbeafe",
        "accent_border": "#60a5fa",
        "surface": "#f8fafc",
        "surface_strong": "#eff6ff",
        "border": "#dbe4ee",
        "code_bg": "#eef2f7",
        "danger": "#b91c1c",
    },
    "ink": {
        "text": "#111827",
        "muted": "#6b7280",
        "heading": "#111827",
        "accent": "#374151",
        "accent_soft": "#f3f4f6",
        "accent_border": "#9ca3af",
        "surface": "#fafafa",
        "surface_strong": "#f4f4f5",
        "border": "#d4d4d8",
        "code_bg": "#f4f4f5",
        "danger": "#991b1b",
    },
    "emerald": {
        "text": "#17231d",
        "muted": "#64746c",
        "heading": "#064e3b",
        "accent": "#059669",
        "accent_soft": "#d1fae5",
        "accent_border": "#6ee7b7",
        "surface": "#f8faf9",
        "surface_strong": "#ecfdf5",
        "border": "#d1e7dd",
        "code_bg": "#eef7f2",
        "danger": "#b91c1c",
    },
}


PRESETS: dict[str, dict[str, str]] = {
    # Balanced: readable but not wasteful.
    "study": {"font_size": "10.4pt", "line_height": "1.48", "margin": "1.45cm 1.55cm"},
    # Fits more notes per page while staying legible.
    "compact": {"font_size": "9.6pt", "line_height": "1.34", "margin": "1.15cm 1.25cm"},
    # Better for long review sessions and tablet reading.
    "comfortable": {"font_size": "11pt", "line_height": "1.6", "margin": "1.7cm 1.8cm"},
    # More conservative ink/print layout.
    "print": {"font_size": "10pt", "line_height": "1.42", "margin": "1.35cm 1.45cm"},
}


FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL | re.MULTILINE)
METADATA_LINE_RE = re.compile(
    r"(?m)^\s*(?:"
    r"\*\*منبع اصلی:\*\*.*|"
    r"منبع اصلی:.*|"
    r"book_pages:.*|"
    r"chapter:.*|"
    r"part:.*|"
    r"pdf_pages:.*|"
    r"source:.*"
    r")$"
)


KEY_SECTION_RE = re.compile(
    r"(<h2[^>]*>\s*(?:Key Points|نکات کلیدی|خلاصه(?:\s+کلیدی)?)\s*</h2>)(.*?)(?=<h2|$)",
    re.IGNORECASE | re.DOTALL,
)


WARNING_SECTION_RE = re.compile(
    r"(<h2[^>]*>\s*(?:Warnings?|هشدارها?|Pitfalls?|اشتباهات رایج)\s*</h2>)(.*?)(?=<h2|$)",
    re.IGNORECASE | re.DOTALL,
)

RTL_SCRIPT_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]")
TOPIC_NOTE_RE = re.compile(r"^\d{2}_\d{2}_", re.IGNORECASE)
RICH_INDEX_NAMES = ("STUDY_INDEX-rewritten.md", "STUDY_INDEX.md")

MARKDOWN_EXTENSIONS = [
    "extra",
    "sane_lists",
    "smarty",
    "tables",
    "fenced_code",
    "footnotes",
    "toc",
]
MARKDOWN_EXTENSION_CONFIGS: dict[str, dict[str, Any]] = {
    "toc": {"permalink": False},
}


def apply_preset(style: PdfStyle) -> PdfStyle:
    """Return a PdfStyle with preset defaults applied before explicit CLI values."""
    values = PRESETS.get(style.preset, PRESETS["study"]).copy()
    defaults = PdfStyle()
    return PdfStyle(
        page_size=style.page_size,
        margin=style.margin if style.margin != defaults.margin else values["margin"],
        font_size=style.font_size if style.font_size != defaults.font_size else values["font_size"],
        line_height=(
            style.line_height
            if style.line_height != defaults.line_height
            else values["line_height"]
        ),
        font_family=style.font_family,
        theme=style.theme,
        preset=style.preset,
        rtl=style.rtl,
        page_numbers=style.page_numbers,
    )


def build_css(style: PdfStyle, extra_css: str | None = None, css_file: Path | None = None) -> str:
    """Build the final CSS used by WeasyPrint."""
    palette = THEMES.get(style.theme, THEMES["medical-blue"])
    direction = "rtl" if style.rtl else "ltr"
    text_align = "right" if style.rtl else "left"
    border_side = "right" if style.rtl else "left"
    padding_side = "padding-right" if style.rtl else "padding-left"
    code_direction = "ltr"
    page_counter = "content: counter(page);" if style.page_numbers else "content: '';"

    css = f"""
@page {{
  size: {style.page_size};
  margin: {style.margin};
  @bottom-center {{
    {page_counter}
    font-size: 8.5pt;
    color: {palette['muted']};
  }}
}}

html {{
  font-variant-ligatures: common-ligatures;
}}

body {{
  direction: {direction};
  text-align: {text_align};
  font-family: {style.font_family};
  font-size: {style.font_size};
  line-height: {style.line_height};
  color: {palette['text']};
  max-width: 100%;
  counter-reset: figures tables;
}}

body, p, li, blockquote, td, th, h1, h2, h3, h4 {{
  unicode-bidi: plaintext;
}}

h1, h2, h3, h4 {{
  color: {palette['heading']};
  line-height: 1.25;
  page-break-after: avoid;
  break-after: avoid;
  orphans: 3;
  widows: 3;
}}

h1 {{
  font-size: 18pt;
  margin: 0 0 14pt 0;
  padding-bottom: 7pt;
  border-bottom: 2.5px solid {palette['accent']};
}}

h2 {{
  font-size: 14pt;
  margin: 17pt 0 7pt 0;
  border-{border_side}: 5px solid {palette['accent_border']};
  {padding_side}: 9pt;
}}

h3 {{
  font-size: 12.1pt;
  font-weight: 700;
  margin: 11pt 0 4pt 0;
}}

h4 {{
  font-size: 10.9pt;
  font-weight: 700;
  margin: 9pt 0 3pt 0;
}}

p {{
  margin: 3.5pt 0;
}}

strong, b {{
  color: {palette['heading']};
  font-weight: 700;
}}

em {{
  color: {palette['text']};
}}

ul, ol {{
  margin-top: 5pt;
  margin-bottom: 8pt;
  padding-inline-start: 18pt;
}}

li {{
  margin: 3.3pt 0;
}}

li > p {{
  margin: 2pt 0;
}}

blockquote {{
  margin: 10pt 0;
  padding: 7pt 10pt;
  background: {palette['surface']};
  border-{border_side}: 4px solid {palette['border']};
  color: {palette['text']};
  page-break-inside: avoid;
  break-inside: avoid;
}}

hr {{
  border: none;
  border-top: 1px solid {palette['border']};
  margin: 11pt 0;
}}

a {{
  color: {palette['accent']};
  text-decoration: none;
}}

code {{
  direction: {code_direction};
  unicode-bidi: isolate;
  background: {palette['code_bg']};
  padding: 1.6pt 4pt;
  border-radius: 3pt;
  font-family: "JetBrains Mono", "Fira Code", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 8.7pt;
}}

pre {{
  direction: {code_direction};
  unicode-bidi: isolate;
  background: {palette['code_bg']};
  padding: 7pt 9pt;
  border-radius: 5pt;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  page-break-inside: avoid;
  break-inside: avoid;
}}

pre code {{
  background: transparent;
  padding: 0;
  border-radius: 0;
}}

table {{
  width: 100%;
  border-collapse: collapse;
  margin: 10pt 0 12pt 0;
  font-size: 9.5pt;
  page-break-inside: auto;
}}

th, td {{
  border: 1px solid {palette['border']};
  padding: 5pt 6pt;
  vertical-align: top;
}}

th {{
  background: {palette['surface_strong']};
  color: {palette['heading']};
  font-weight: 700;
}}

tr {{
  page-break-inside: avoid;
  break-inside: avoid;
}}

img, svg {{
  max-width: 100%;
  height: auto;
  page-break-inside: avoid;
  break-inside: avoid;
}}

sup, sub {{
  line-height: 0;
}}

.key-points, .keypoints, .summary-box {{
  background: {palette['accent_soft']};
  border: 1.4px solid {palette['accent_border']};
  border-radius: 7pt;
  padding: 8.5pt 11pt;
  margin: 13pt 0;
  page-break-inside: avoid;
  break-inside: avoid;
}}

.key-points h2, .keypoints h2, .summary-box h2 {{
  margin-top: 0;
  border: none;
  padding: 0;
  color: {palette['heading']};
  font-size: 13.2pt;
}}

.warning-box {{
  background: #fff7ed;
  border: 1.4px solid #fb923c;
  border-radius: 7pt;
  padding: 8.5pt 11pt;
  margin: 13pt 0;
  page-break-inside: avoid;
  break-inside: avoid;
}}

.warning-box h2 {{
  margin-top: 0;
  border: none;
  padding: 0;
  color: {palette['danger']};
  font-size: 13.2pt;
}}

.footnote, .footnote-ref {{
  font-size: 8.5pt;
}}

/* Force page breaks between major sections in combined documents. */
.page-break, div[style*="page-break-before"] {{
  page-break-before: always;
  break-before: page;
  display: block;
  height: 0;
  margin: 0;
  padding: 0;
}}

/* Use this class when each major note should start on a fresh page. */
.note-heading {{
  page-break-before: always;
  break-before: page;
}}
"""

    if css_file and css_file.exists():
        css += "\n" + css_file.read_text(encoding="utf-8")
    if extra_css:
        css += "\n" + extra_css
    return css


def clean_markdown(md_text: str) -> str:
    """Remove note-maker metadata that should not appear in the PDF."""
    if md_text.lstrip().startswith("---"):
        md_text = FRONTMATTER_RE.sub("", md_text, count=1).lstrip()

    md_text = METADATA_LINE_RE.sub("", md_text)
    return md_text.strip()


def is_topic_note(path: Path) -> bool:
    """True for numbered study notes (01_01_...), not index/meta files."""
    return bool(TOPIC_NOTE_RE.match(path.name))


def find_rich_index_md(notes_dir: Path) -> Path | None:
    """Locate a rich STUDY_INDEX next to or inside the notes folder."""
    notes_dir = Path(notes_dir)
    for name in RICH_INDEX_NAMES:
        for candidate in (notes_dir / name, notes_dir.parent / name):
            if candidate.is_file():
                return candidate
    return None


def contains_rtl_script(text: str) -> bool:
    """Return True when Persian/Arabic script is present."""
    return bool(RTL_SCRIPT_RE.search(text))


def resolve_style(style: PdfStyle, md_text: str, *, auto_rtl: bool) -> PdfStyle:
    """Apply preset defaults and optional RTL auto-detection."""
    style = apply_preset(style)
    if auto_rtl and not style.rtl and contains_rtl_script(md_text):
        return replace(style, rtl=True)
    return style


def require_dependencies() -> None:
    """Fail with a helpful message if runtime PDF dependencies are missing."""
    missing: list[str] = []
    if markdown is None:
        missing.append("markdown")
    if HTML is None:
        missing.append("weasyprint")
    if missing:
        packages = " ".join(missing)
        print(
            "Missing required Python package(s): " + ", ".join(missing) + "\n"
            f"Install them with: python -m pip install {packages}",
            file=sys.stderr,
        )
        raise SystemExit(2)


def md_to_html(md_text: str, *, cleaned: bool = False) -> str:
    """Convert Markdown to clean HTML and wrap useful study sections."""
    require_dependencies()
    if not cleaned:
        md_text = clean_markdown(md_text)

    converter = markdown.Markdown(
        extensions=MARKDOWN_EXTENSIONS,
        extension_configs=MARKDOWN_EXTENSION_CONFIGS,
        output_format="html5",
    )
    try:
        html_body = converter.convert(md_text)
    finally:
        converter.reset()

    html_body = KEY_SECTION_RE.sub(r'<div class="key-points">\1\2</div>', html_body)
    html_body = WARNING_SECTION_RE.sub(r'<div class="warning-box">\1\2</div>', html_body)
    return html_body


def infer_title(md_text: str, fallback: str, *, cleaned: bool = False) -> str:
    """Extract the first H1 as the document title."""
    text = md_text if cleaned else clean_markdown(md_text)
    title_match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    return title_match.group(1).strip() if title_match else fallback


def make_pdf(
    md_path: Path,
    output_pdf: Path | None = None,
    *,
    style: PdfStyle | None = None,
    title: str | None = None,
    extra_css: str | None = None,
    css_file: Path | None = None,
    prebuilt_css: str | None = None,
    auto_rtl: bool = True,
) -> Path:
    """Convert one Markdown note to a styled PDF."""
    require_dependencies()
    md_text = md_path.read_text(encoding="utf-8")
    cleaned = clean_markdown(md_text)
    style = resolve_style(style or PdfStyle(), cleaned, auto_rtl=auto_rtl)
    body_html = md_to_html(cleaned, cleaned=True)
    document_title = title or infer_title(cleaned, md_path.stem, cleaned=True)
    css = prebuilt_css if prebuilt_css is not None else build_css(
        style, extra_css=extra_css, css_file=css_file
    )
    dir_attr = "rtl" if style.rtl else "auto"
    lang_attr = "fa" if style.rtl else "en"

    full_html = f"""<!DOCTYPE html>
<html lang="{lang_attr}" dir="{dir_attr}">
<head>
  <meta charset="utf-8">
  <title>{html.escape(document_title)}</title>
  <style>{css}</style>
</head>
<body>
{body_html}
</body>
</html>"""

    if output_pdf is None:
        output_pdf = md_path.with_suffix(".pdf")

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=full_html, base_url=str(md_path.parent)).write_pdf(output_pdf)
    return output_pdf


def batch_convert(
    input_dir: Path,
    output_dir: Path,
    *,
    pattern: str = "*.md",
    style: PdfStyle | None = None,
    css_file: Path | None = None,
    auto_rtl: bool = True,
) -> list[Path]:
    """Convert all matching Markdown files in a directory."""
    require_dependencies()
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    base_style = apply_preset(style or PdfStyle())
    extra_css = css_file.read_text(encoding="utf-8") if css_file and css_file.exists() else None
    # Shared CSS is safe only when direction is fixed for every file.
    shared_css: str | None = None
    if not auto_rtl or base_style.rtl:
        shared_css = build_css(base_style, extra_css=extra_css)

    results: list[Path] = []
    for md in sorted(input_dir.glob(pattern)):
        if not md.is_file() or not is_topic_note(md):
            continue
        pdf = output_dir / (md.stem + ".pdf")
        try:
            out = make_pdf(
                md,
                pdf,
                style=base_style,
                extra_css=None if shared_css else extra_css,
                prebuilt_css=shared_css,
                auto_rtl=auto_rtl,
            )
            print(f"✓ {md.name} -> {pdf.name}")
            results.append(out)
        except Exception as exc:  # noqa: BLE001 - user-facing batch converter
            print(f"✗ Failed {md.name}: {exc}")
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Markdown notes -> styled study PDFs with WeasyPrint"
    )
    parser.add_argument("input", help="Single .md file or directory")
    parser.add_argument("--output", help="Output PDF path for single mode, or output directory for batch mode")
    parser.add_argument("--batch", action="store_true", help="Process a whole directory")
    parser.add_argument("--pattern", default="*.md", help="Glob pattern for batch mode, default: *.md")
    parser.add_argument("--css", help="Path to an extra CSS file appended after the built-in style")

    parser.add_argument(
        "--preset",
        choices=sorted(PRESETS),
        default="study",
        help="Layout density preset: study, compact, comfortable, or print",
    )
    parser.add_argument(
        "--theme",
        choices=sorted(THEMES),
        default="medical-blue",
        help="Color theme",
    )
    parser.add_argument("--page-size", default="A4", help="CSS page size, e.g. A4, Letter")
    parser.add_argument("--margin", default=None, help="CSS page margin, e.g. '1.4cm 1.6cm'")
    parser.add_argument("--font-size", default=None, help="Base font size, e.g. 10.5pt")
    parser.add_argument("--line-height", default=None, help="Base line height, e.g. 1.5")
    parser.add_argument("--font-family", default=None, help="CSS font-family override")
    parser.add_argument("--rtl", action="store_true", help="Force RTL direction for Persian/Arabic notes")
    parser.add_argument(
        "--no-auto-rtl",
        action="store_true",
        help="Disable automatic RTL detection from note content",
    )
    parser.add_argument("--no-page-numbers", action="store_true", help="Hide footer page numbers")
    parser.add_argument("--title", help="Override PDF document title")
    return parser.parse_args()


def style_from_args(args: argparse.Namespace) -> PdfStyle:
    preset_values = PRESETS[args.preset]
    return apply_preset(
        PdfStyle(
            page_size=args.page_size,
            margin=args.margin or preset_values["margin"],
            font_size=args.font_size or preset_values["font_size"],
            line_height=args.line_height or preset_values["line_height"],
            font_family=args.font_family or PdfStyle.font_family,
            theme=args.theme,
            preset=args.preset,
            rtl=args.rtl,
            page_numbers=not args.no_page_numbers,
        )
    )


def main() -> int:
    args = parse_args()
    inp = Path(args.input)
    css_file = Path(args.css) if args.css else None
    style = style_from_args(args)
    auto_rtl = not args.no_auto_rtl

    if args.batch or inp.is_dir():
        out_dir = Path(args.output) if args.output else inp / "pdfs"
        batch_convert(
            inp,
            out_dir,
            pattern=args.pattern,
            style=style,
            css_file=css_file,
            auto_rtl=auto_rtl,
        )
    else:
        out = Path(args.output) if args.output else inp.with_suffix(".pdf")
        result = make_pdf(
            inp,
            out,
            style=style,
            title=args.title,
            css_file=css_file,
            auto_rtl=auto_rtl,
        )
        print(f"Created PDF: {result}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
