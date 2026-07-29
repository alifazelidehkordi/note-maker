#!/usr/bin/env python3
"""Convert Markdown study notes to A4 portrait PDFs with embedded custom fonts."""
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
except ModuleNotFoundError:  # pragma: no cover
    markdown = None

try:
    import mistune
except ModuleNotFoundError:  # pragma: no cover
    mistune = None

_WEASYPRINT_IMPORT_ERROR: Exception | None = None
try:
    from weasyprint import HTML
except (ModuleNotFoundError, OSError) as exc:  # pragma: no cover
    HTML = None
    _WEASYPRINT_IMPORT_ERROR = exc

from pdf_common import CUSTOM_FONT_STACK, FontConfig, assert_portrait_a4, is_topic_markdown, natural_key


@dataclass(frozen=True)
class BatchResult:
    created: list[Path]
    failed: list[tuple[Path, str]]

    @property
    def succeeded(self) -> bool:
        return not self.failed


@dataclass(frozen=True)
class PdfStyle:
    page_size: str = "A4 portrait"
    margin: str = "1.45cm 1.55cm 1.6cm"
    font_size: str = "10.4pt"
    line_height: str = "1.48"
    font_family: str = CUSTOM_FONT_STACK
    theme: str = "medical-blue"
    preset: str = "study"
    rtl: bool = False
    page_numbers: bool = True


THEMES: dict[str, dict[str, str]] = {
    "medical-blue": {"text": "#172033", "muted": "#64748b", "heading": "#0f3a66", "accent": "#2563eb", "accent_soft": "#dbeafe", "accent_border": "#60a5fa", "surface": "#f8fafc", "surface_strong": "#eff6ff", "border": "#dbe4ee", "code_bg": "#eef2f7", "danger": "#b91c1c"},
    "ink": {"text": "#111827", "muted": "#6b7280", "heading": "#111827", "accent": "#374151", "accent_soft": "#f3f4f6", "accent_border": "#9ca3af", "surface": "#fafafa", "surface_strong": "#f4f4f5", "border": "#d4d4d8", "code_bg": "#f4f4f5", "danger": "#991b1b"},
    "emerald": {"text": "#17231d", "muted": "#64746c", "heading": "#064e3b", "accent": "#059669", "accent_soft": "#d1fae5", "accent_border": "#6ee7b7", "surface": "#f8faf9", "surface_strong": "#ecfdf5", "border": "#d1e7dd", "code_bg": "#eef7f2", "danger": "#b91c1c"},
}

PRESETS: dict[str, dict[str, str]] = {
    "study": {"font_size": "10.4pt", "line_height": "1.48", "margin": "1.45cm 1.55cm 1.6cm"},
    "compact": {"font_size": "9.6pt", "line_height": "1.34", "margin": "1.15cm 1.25cm 1.4cm"},
    "comfortable": {"font_size": "11pt", "line_height": "1.6", "margin": "1.7cm 1.8cm 1.85cm"},
    "print": {"font_size": "10pt", "line_height": "1.42", "margin": "1.35cm 1.45cm 1.55cm"},
}

FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL | re.MULTILINE)
METADATA_LINE_RE = re.compile(r"(?m)^\s*(?:\*\*منبع اصلی:\*\*.*|منبع اصلی:.*|book_pages:.*|chapter:.*|part:.*|pdf_pages:.*|source:.*)$")
KEY_SECTION_RE = re.compile(r"(<h2[^>]*>\s*(?:Key Points|نکات کلیدی|خلاصه(?:\s+کلیدی)?)\s*</h2>)(.*?)(?=<h2|$)", re.I | re.S)
WARNING_SECTION_RE = re.compile(r"(<h2[^>]*>\s*(?:Warnings?|هشدارها?|Pitfalls?|اشتباهات رایج)\s*</h2>)(.*?)(?=<h2|$)", re.I | re.S)
RTL_SCRIPT_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]")
RICH_INDEX_NAMES = ("STUDY_INDEX-rewritten.md", "STUDY_INDEX.md")
MARKDOWN_EXTENSIONS = ["extra", "sane_lists", "smarty", "tables", "fenced_code", "footnotes", "toc"]
MARKDOWN_EXTENSION_CONFIGS: dict[str, dict[str, Any]] = {"toc": {"permalink": False}}
VISUAL_GLYPH_NORMALISATION = str.maketrans({"⮚": "→", "🡪": "→"})


def apply_preset(style: PdfStyle) -> PdfStyle:
    values = PRESETS.get(style.preset, PRESETS["study"])
    defaults = PdfStyle()
    return replace(
        style,
        margin=style.margin if style.margin != defaults.margin else values["margin"],
        font_size=style.font_size if style.font_size != defaults.font_size else values["font_size"],
        line_height=style.line_height if style.line_height != defaults.line_height else values["line_height"],
    )


def build_css(style: PdfStyle, extra_css: str | None = None, css_file: Path | None = None) -> str:
    palette = THEMES.get(style.theme, THEMES["medical-blue"])
    direction = "rtl" if style.rtl else "ltr"
    text_align = "right" if style.rtl else "left"
    border_side = "right" if style.rtl else "left"
    padding_side = "padding-right" if style.rtl else "padding-left"
    page_counter = "content: counter(page);" if style.page_numbers else "content: '';"
    font_config = FontConfig.from_env(required=True)
    assert font_config is not None
    css = f"""
{font_config.css()}
@page {{
  size: A4 portrait;
  margin: {style.margin};
  @bottom-center {{
    {page_counter}
    font-family: {style.font_family};
    font-size: 8.5pt;
    color: {palette['muted']};
  }}
}}
* {{
  box-sizing: border-box;
  font-family: {style.font_family} !important;
}}
html {{ font-variant-ligatures: common-ligatures; }}
body {{
  direction: {direction}; text-align: {text_align};
  font-size: {style.font_size}; line-height: {style.line_height};
  color: {palette['text']}; max-width: 100%; margin: 0;
  overflow-wrap: anywhere; word-break: normal;
}}
body, p, li, blockquote, td, th, h1, h2, h3, h4 {{ unicode-bidi: plaintext; }}
[dir="rtl"], .rtl-section {{ direction: rtl; text-align: right; }}
[dir="ltr"], .ltr-section {{ direction: ltr; text-align: left; }}
h1, h2, h3, h4 {{ color: {palette['heading']}; line-height: 1.25; break-after: avoid; page-break-after: avoid; orphans: 3; widows: 3; }}
h1 {{ font-size: 18pt; margin: 0 0 14pt; padding-bottom: 7pt; border-bottom: 2.5px solid {palette['accent']}; }}
h2 {{ font-size: 14pt; margin: 17pt 0 7pt; border-{border_side}: 5px solid {palette['accent_border']}; {padding_side}: 9pt; }}
h3 {{ font-size: 12.1pt; font-weight: 700; margin: 11pt 0 4pt; }}
h4 {{ font-size: 10.9pt; font-weight: 700; margin: 9pt 0 3pt; }}
p {{ margin: 3.5pt 0; orphans: 3; widows: 3; }}
strong, b {{ color: {palette['heading']}; font-weight: 700; }}
ul, ol {{ margin: 5pt 0 8pt; padding-inline-start: 18pt; }}
ul li::marker {{ content: "• "; font-family: {style.font_family} !important; }}
ul ul li::marker {{ content: "◦ "; font-family: {style.font_family} !important; }}
ol li::marker {{ font-family: {style.font_family} !important; }}
li {{ margin: 3.3pt 0; }} li > p {{ margin: 2pt 0; }}
blockquote {{ margin: 10pt 0; padding: 7pt 10pt; background: {palette['surface']}; border-{border_side}: 4px solid {palette['border']}; break-inside: avoid; }}
hr {{ border: 0; border-top: 1px solid {palette['border']}; margin: 11pt 0; }}
a {{ color: {palette['accent']}; text-decoration: none; overflow-wrap: anywhere; }}
code {{ direction: ltr; unicode-bidi: isolate; background: {palette['code_bg']}; padding: 1.6pt 4pt; border-radius: 3pt; font-size: 8.7pt; }}
pre {{ direction: ltr; unicode-bidi: isolate; background: {palette['code_bg']}; padding: 7pt 9pt; border-radius: 5pt; white-space: pre-wrap; overflow-wrap: anywhere; break-inside: avoid; }}
pre code {{ background: transparent; padding: 0; }}
table {{ width: 100%; max-width: 100%; border-collapse: collapse; table-layout: fixed; margin: 10pt 0 12pt; font-size: 8.2pt; break-inside: auto; }}
thead {{ display: table-header-group; }} tfoot {{ display: table-footer-group; }}
th, td {{ border: 1px solid {palette['border']}; padding: 4.2pt 4.8pt; vertical-align: top; overflow-wrap: anywhere; word-break: break-word; }}
th {{ background: {palette['surface_strong']}; color: {palette['heading']}; font-weight: 700; }}
tr {{ break-inside: avoid; page-break-inside: avoid; }}
.sessions-table th:nth-child(1), .sessions-table td:nth-child(1) {{ width: 7%; text-align: center; }}
.sessions-table th:nth-child(2), .sessions-table td:nth-child(2) {{ width: 23%; }}
.sessions-table th:nth-child(3), .sessions-table td:nth-child(3) {{ width: 10%; text-align: center; }}
.sessions-table th:nth-child(4), .sessions-table td:nth-child(4) {{ width: 10%; text-align: center; }}
.sessions-table th:nth-child(5), .sessions-table td:nth-child(5) {{ width: 11%; text-align: center; }}
.sessions-table th:nth-child(6), .sessions-table td:nth-child(6) {{ width: 39%; }}
.groups-table th:nth-child(1), .groups-table td:nth-child(1) {{ width: 23%; }}
.groups-table th:nth-child(2), .groups-table td:nth-child(2) {{ width: 10%; text-align: center; }}
.groups-table th:nth-child(3), .groups-table td:nth-child(3) {{ width: 8%; text-align: center; }}
.groups-table th:nth-child(4), .groups-table td:nth-child(4) {{ width: 12%; text-align: center; }}
.groups-table th:nth-child(5), .groups-table td:nth-child(5) {{ width: 47%; }}
img, svg {{ max-width: 100%; height: auto; max-height: 23cm; object-fit: contain; break-inside: avoid; }}
sup, sub {{ line-height: 0; }}
.key-points, .keypoints, .summary-box {{ background: {palette['accent_soft']}; border: 1.4px solid {palette['accent_border']}; border-radius: 7pt; padding: 8.5pt 11pt; margin: 13pt 0; break-inside: avoid; }}
.warning-box {{ background: #fff7ed; border: 1.4px solid #fb923c; border-radius: 7pt; padding: 8.5pt 11pt; margin: 13pt 0; break-inside: avoid; }}
.key-points h2, .keypoints h2, .summary-box h2, .warning-box h2 {{ margin-top: 0; border: 0; padding: 0; font-size: 13.2pt; }}
.warning-box h2 {{ color: {palette['danger']}; }}
.page-break, div[style*="page-break-before"] {{ break-before: page; page-break-before: always; display: block; height: 0; }}
.index-cover {{ min-height: 4.8cm; padding-top: 1.1cm; text-align: center; break-after: page; page-break-after: always; }}
.index-cover h1 {{ font-size: 24pt; border: 0; margin-top: 1cm; }}
.index-cover h2 {{ border: 0; padding: 0; text-align: center; }}
.index-group {{ break-before: page; page-break-before: always; }}
"""
    if css_file:
        css_path = Path(css_file)
        if not css_path.is_file():
            raise FileNotFoundError(f"CSS file not found: {css_path}")
        css += "\n" + css_path.read_text(encoding="utf-8")
    if extra_css:
        css += "\n" + extra_css
    return css


def clean_markdown(md_text: str) -> str:
    if md_text.lstrip().startswith("---"):
        md_text = FRONTMATTER_RE.sub("", md_text, count=1).lstrip()
    return METADATA_LINE_RE.sub("", md_text).strip()


def is_topic_note(path: Path) -> bool:
    return is_topic_markdown(path)


def find_rich_index_md(notes_dir: Path) -> Path | None:
    notes_dir = Path(notes_dir)
    for name in RICH_INDEX_NAMES:
        for candidate in (notes_dir / name, notes_dir.parent / name):
            if candidate.is_file():
                return candidate
    return None


def contains_rtl_script(text: str) -> bool:
    return bool(RTL_SCRIPT_RE.search(text))


def resolve_style(style: PdfStyle, md_text: str, *, auto_rtl: bool) -> PdfStyle:
    style = apply_preset(style)
    if auto_rtl and not style.rtl and contains_rtl_script(md_text) and "rtl-section" not in md_text:
        return replace(style, rtl=True)
    return style


def require_dependencies(*, require_pdf_renderer: bool = True) -> None:
    missing: list[str] = []
    if markdown is None and mistune is None:
        missing.append("markdown or mistune")
    if require_pdf_renderer and HTML is None:
        missing.append("weasyprint native runtime")
    if missing:
        detail = f"\nRenderer import error: {_WEASYPRINT_IMPORT_ERROR}" if _WEASYPRINT_IMPORT_ERROR else ""
        print("Missing required dependency: " + ", ".join(missing) + detail, file=sys.stderr)
        raise SystemExit(2)


def md_to_html(md_text: str, *, cleaned: bool = False) -> str:
    require_dependencies(require_pdf_renderer=False)
    text = md_text if cleaned else clean_markdown(md_text)
    text = text.translate(VISUAL_GLYPH_NORMALISATION)
    if markdown is not None:
        converter = markdown.Markdown(extensions=MARKDOWN_EXTENSIONS, extension_configs=MARKDOWN_EXTENSION_CONFIGS, output_format="html5")
        try:
            html_body = converter.convert(text)
        finally:
            converter.reset()
    else:
        assert mistune is not None
        converter = mistune.create_markdown(escape=False, plugins=["table", "footnotes", "strikethrough", "task_lists", "url"])
        html_body = converter(text)
    html_body = KEY_SECTION_RE.sub(r'<div class="key-points">\1\2</div>', html_body)
    html_body = WARNING_SECTION_RE.sub(r'<div class="warning-box">\1\2</div>', html_body)
    return html_body


def infer_title(md_text: str, fallback: str, *, cleaned: bool = False) -> str:
    text = md_text if cleaned else clean_markdown(md_text)
    match = re.search(r"^#\s+(.+)$", text, re.M)
    return match.group(1).strip() if match else fallback


def make_pdf(md_path: Path, output_pdf: Path | None = None, *, style: PdfStyle | None = None, title: str | None = None, extra_css: str | None = None, css_file: Path | None = None, prebuilt_css: str | None = None, auto_rtl: bool = True) -> Path:
    require_dependencies()
    md_path = Path(md_path).resolve()
    md_text = md_path.read_text(encoding="utf-8")
    cleaned = clean_markdown(md_text)
    style = resolve_style(style or PdfStyle(), cleaned, auto_rtl=auto_rtl)
    body_html = md_to_html(cleaned, cleaned=True)
    document_title = title or infer_title(cleaned, md_path.stem, cleaned=True)
    css = prebuilt_css if prebuilt_css is not None else build_css(style, extra_css=extra_css, css_file=css_file)
    dir_attr = "rtl" if style.rtl else "ltr"
    lang_attr = "fa" if style.rtl else "en"
    full_html = f'<!DOCTYPE html><html lang="{lang_attr}" dir="{dir_attr}"><head><meta charset="utf-8"><title>{html.escape(document_title)}</title><style>{css}</style></head><body>{body_html}</body></html>'
    output_pdf = Path(output_pdf).resolve() if output_pdf else md_path.with_suffix(".pdf")
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=full_html, base_url=str(md_path.parent)).write_pdf(output_pdf)
    assert_portrait_a4(output_pdf, label=output_pdf.name)
    return output_pdf


def batch_convert(input_dir: Path, output_dir: Path, *, pattern: str = "*.md", style: PdfStyle | None = None, css_file: Path | None = None, auto_rtl: bool = True) -> BatchResult:
    require_dependencies()
    input_dir, output_dir = Path(input_dir), Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    base_style = apply_preset(style or PdfStyle())
    created: list[Path] = []
    failed: list[tuple[Path, str]] = []
    for md in sorted((p for p in input_dir.glob(pattern) if is_topic_note(p)), key=natural_key):
        pdf = output_dir / f"{md.stem}.pdf"
        try:
            created.append(make_pdf(md, pdf, style=base_style, css_file=css_file, auto_rtl=auto_rtl))
            print(f"[ok] {md.name} -> {pdf.name}")
        except Exception as exc:  # noqa: BLE001
            failed.append((md, str(exc)))
            print(f"[error] Failed {md.name}: {exc}")
    return BatchResult(created, failed)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Markdown notes -> A4 portrait study PDFs")
    parser.add_argument("input")
    parser.add_argument("--output")
    parser.add_argument("--batch", action="store_true")
    parser.add_argument("--pattern", default="*.md")
    parser.add_argument("--css")
    parser.add_argument("--preset", choices=sorted(PRESETS), default="study")
    parser.add_argument("--theme", choices=sorted(THEMES), default="medical-blue")
    parser.add_argument("--page-size", default="A4 portrait")
    parser.add_argument("--margin")
    parser.add_argument("--font-size")
    parser.add_argument("--line-height")
    parser.add_argument("--font-family")
    parser.add_argument("--rtl", action="store_true")
    parser.add_argument("--no-auto-rtl", action="store_true")
    parser.add_argument("--no-page-numbers", action="store_true")
    parser.add_argument("--title")
    return parser.parse_args()


def style_from_args(args: argparse.Namespace) -> PdfStyle:
    values = PRESETS[args.preset]
    page_size = str(args.page_size).strip().casefold()
    if page_size not in {"a4", "a4 portrait", "portrait a4"}:
        raise ValueError("Only A4 portrait is supported by the final study-book pipeline")
    return apply_preset(PdfStyle(page_size="A4 portrait", margin=args.margin or values["margin"], font_size=args.font_size or values["font_size"], line_height=args.line_height or values["line_height"], font_family=args.font_family or CUSTOM_FONT_STACK, theme=args.theme, preset=args.preset, rtl=args.rtl, page_numbers=not args.no_page_numbers))


def main() -> int:
    args = parse_args()
    inp = Path(args.input)
    style = style_from_args(args)
    css_file = Path(args.css) if args.css else None
    if args.batch or inp.is_dir():
        result = batch_convert(inp, Path(args.output) if args.output else inp / "pdfs", pattern=args.pattern, style=style, css_file=css_file, auto_rtl=not args.no_auto_rtl)
        print(f"Batch complete: {len(result.created)} created, {len(result.failed)} failed.")
        return 2 if result.failed else 0
    out = make_pdf(inp, Path(args.output) if args.output else inp.with_suffix(".pdf"), style=style, title=args.title, css_file=css_file, auto_rtl=not args.no_auto_rtl)
    print(f"Created PDF: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
