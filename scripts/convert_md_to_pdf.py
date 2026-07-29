#!/usr/bin/env python3
"""Convert study-note Markdown to styled PDFs using only supplied fonts."""
from __future__ import annotations

import argparse
import html
import re
from dataclasses import dataclass
from pathlib import Path

try:
    import markdown as py_markdown
except ModuleNotFoundError:  # pragma: no cover
    py_markdown = None

try:
    import mistune
except ModuleNotFoundError:  # pragma: no cover
    mistune = None

try:
    from weasyprint import HTML
except (ModuleNotFoundError, OSError) as exc:  # pragma: no cover
    HTML = None
    _WEASYPRINT_ERROR = exc
else:
    _WEASYPRINT_ERROR = None

FRONT_RE = re.compile(r"\A---\s*\n.*?\n---\s*(?:\n|\Z)", re.S)
H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.M)
TOPIC_RE = re.compile(r"^\d{1,3}(?:_\d{1,3})?[_-]", re.I)
EXCLUDED_NAMES = {
    "readme.md", "index.md", "study_index.md", "study_index-rewritten.md",
    "study_index_verification.md", "qa_report.md", "structure.md", "boundaries.md",
    "combined_notes.md", "verification.md",
}
RTL_RE = re.compile(r"[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff]")
BLOCK_TAG_RE = re.compile(r"<(p|li|td|th|blockquote)(?=[ >])", re.I)
KEY_HEADING_RE = re.compile(r"^(key points|نکات کلیدی|خلاصه(?: کلیدی)?)$", re.I)
WARNING_HEADING_RE = re.compile(r"^(warnings?|هشدارها?|pitfalls?|اشتباهات رایج)$", re.I)


@dataclass(frozen=True)
class FontConfig:
    arabic_regular: Path
    latin_regular: Path
    latin_bold: Path
    arabic_bold: Path | None = None

    def validate(self) -> "FontConfig":
        for label, path in {
            "FONT_FILE": self.arabic_regular,
            "LATIN_FONT_FILE": self.latin_regular,
            "FONT_BOLD_FILE": self.latin_bold,
        }.items():
            if not Path(path).is_file():
                raise FileNotFoundError(f"{label} not found: {path}")
        if self.arabic_bold and not Path(self.arabic_bold).is_file():
            raise FileNotFoundError(f"ARABIC_FONT_BOLD_FILE not found: {self.arabic_bold}")
        return self


@dataclass(frozen=True)
class PdfStyle:
    page_size: str = "A4"
    margin: str = "1.45cm 1.55cm 1.75cm"
    font_size: str = "10.2pt"
    line_height: str = "1.48"
    index_landscape: bool = True
    page_numbers: bool = True


def natural_key(path: Path) -> tuple:
    return tuple(int(x) if x.isdigit() else x for x in re.split(r"(\d+)", path.name.casefold()))


def is_topic_note(path: Path) -> bool:
    name = path.name.casefold()
    return path.is_file() and path.suffix.casefold() == ".md" and name not in EXCLUDED_NAMES and bool(TOPIC_RE.match(path.stem))


def infer_title(markdown_text: str, fallback: str = "Study Notes") -> str:
    match = H1_RE.search(FRONT_RE.sub("", markdown_text, count=1))
    return match.group(1).strip() if match else fallback


def find_rich_index_md(notes_dir: Path) -> Path | None:
    for name in ("STUDY_INDEX.md", "STUDY_INDEX-rewritten.md", "study_index.md"):
        for candidate in (notes_dir / name, notes_dir.parent / name):
            if candidate.is_file():
                return candidate
    return None


def _path_uri(path: Path) -> str:
    return Path(path).resolve().as_uri()


def _font_css(fonts: FontConfig) -> str:
    arabic_bold = fonts.arabic_bold or fonts.arabic_regular
    return f"""
@font-face {{ font-family: 'StudyArabic'; src: url('{_path_uri(fonts.arabic_regular)}'); font-style: normal; font-weight: 400; }}
@font-face {{ font-family: 'StudyArabic'; src: url('{_path_uri(arabic_bold)}'); font-style: normal; font-weight: 700; }}
@font-face {{ font-family: 'StudyLatin'; src: url('{_path_uri(fonts.latin_regular)}'); font-style: normal; font-weight: 400; }}
@font-face {{ font-family: 'StudyLatin'; src: url('{_path_uri(fonts.latin_bold)}'); font-style: normal; font-weight: 700; }}
"""


def build_css(style: PdfStyle, fonts: FontConfig, *, is_index: bool = False, extra_css: str = "") -> str:
    orientation = " landscape" if is_index and style.index_landscape else ""
    page_counter = "content: counter(page);" if style.page_numbers else "content: '';"
    index_rules = """
body.study-index { font-size: 8.4pt; line-height: 1.35; }
body.study-index h1 { font-size: 18pt; }
body.study-index h2 { font-size: 13.5pt; margin-top: 15pt; }
body.study-index h3 { font-size: 11.2pt; margin-top: 12pt; }
body.study-index table { font-size: 7.8pt; table-layout: fixed; }
body.study-index th:nth-child(1), body.study-index td:nth-child(1) { width: 5%; }
body.study-index th:nth-child(2), body.study-index td:nth-child(2) { width: 25%; }
body.study-index th:nth-child(3), body.study-index td:nth-child(3) { width: 10%; }
body.study-index th:nth-child(4), body.study-index td:nth-child(4) { width: 10%; }
body.study-index th:nth-child(5), body.study-index td:nth-child(5) { width: 10%; }
body.study-index th:nth-child(6), body.study-index td:nth-child(6) { width: 40%; }
""" if is_index else ""
    return f"""
{_font_css(fonts)}
@page {{
  size: {style.page_size}{orientation};
  margin: {style.margin};
  @bottom-center {{
    {page_counter}
    font-family: 'StudyArabic', 'StudyLatin';
    font-size: 8.5pt;
    color: #64748b;
  }}
}}
html, body {{ margin: 0; padding: 0; }}
body {{
  font-family: 'StudyArabic', 'StudyLatin';
  font-size: {style.font_size};
  line-height: {style.line_height};
  color: #172033;
  direction: ltr;
  text-align: start;
  font-variant-ligatures: common-ligatures;
}}
[dir='rtl'] {{ direction: rtl; unicode-bidi: isolate; }}
[dir='ltr'] {{ direction: ltr; unicode-bidi: isolate; }}
p, li, td, th, blockquote, h1, h2, h3, h4, a, code, pre {{
  font-family: 'StudyArabic', 'StudyLatin';
  unicode-bidi: plaintext;
  overflow-wrap: anywhere;
}}
h1, h2, h3, h4 {{
  color: #123f6d;
  font-weight: 700;
  line-height: 1.25;
  break-after: avoid;
  page-break-after: avoid;
}}
h1 {{ font-size: 18pt; margin: 0 0 14pt; padding-bottom: 7pt; border-bottom: 2.5px solid #2563eb; }}
h2 {{ font-size: 14pt; margin: 17pt 0 7pt; border-inline-start: 5px solid #60a5fa; padding-inline-start: 9pt; }}
h3 {{ font-size: 12pt; margin: 12pt 0 4pt; }}
h4 {{ font-size: 10.8pt; margin: 9pt 0 3pt; }}
p {{ margin: 3.5pt 0; orphans: 3; widows: 3; }}
strong, b {{ color: #123f6d; font-weight: 700; }}
ul, ol {{ margin: 5pt 0 8pt; padding-inline-start: 20pt; }}
li {{ margin: 3pt 0; }}
li::marker {{ font-family: 'StudyArabic', 'StudyLatin'; }}
ul li::marker {{ content: '•  '; }}
a {{ color: #1d4ed8; text-decoration: none; }}
blockquote {{ margin: 10pt 0; padding: 8pt 11pt; background: #f8fafc; border-inline-start: 4px solid #cbd5e1; break-inside: avoid; }}
hr {{ border: 0; border-top: 1px solid #dbe4ee; margin: 12pt 0; }}
table {{ width: 100%; border-collapse: collapse; margin: 10pt 0 12pt; font-size: 9.1pt; table-layout: auto; }}
th, td {{ border: 1px solid #dbe4ee; padding: 5pt 6pt; vertical-align: top; }}
th {{ background: #eff6ff; color: #123f6d; font-weight: 700; }}
tr {{ break-inside: avoid; page-break-inside: avoid; }}
img, svg {{ max-width: 100%; height: auto; break-inside: avoid; }}
svg.equilibrium-symbol {{ width: 1.25em; height: 0.85em; vertical-align: -0.12em; overflow: visible; }}
code, pre {{ font-family: 'StudyLatin', 'StudyArabic'; background: #eef2f7; direction: ltr; unicode-bidi: isolate; }}
code {{ padding: 1.5pt 4pt; border-radius: 3pt; font-size: 8.7pt; }}
pre {{ padding: 8pt 10pt; border-radius: 5pt; white-space: pre-wrap; break-inside: avoid; }}
.key-points {{ background: #dbeafe; border: 1.4px solid #60a5fa; border-radius: 7pt; padding: 9pt 11pt; margin: 13pt 0; break-inside: avoid; }}
.warning-box {{ background: #fff7ed; border: 1.4px solid #fb923c; border-radius: 7pt; padding: 9pt 11pt; margin: 13pt 0; break-inside: avoid; }}
.key-points > h2:first-child, .warning-box > h2:first-child {{ margin-top: 0; }}
{index_rules}
{extra_css}
"""


def markdown_to_html(text: str) -> str:
    clean = FRONT_RE.sub("", text, count=1)
    if py_markdown is not None:
        rendered = py_markdown.markdown(clean, extensions=["extra", "sane_lists", "tables", "fenced_code", "footnotes", "toc"], extension_configs={"toc": {"permalink": False}}, output_format="html5")
    elif mistune is not None:  # local validation fallback
        renderer = mistune.HTMLRenderer(escape=False)
        md = mistune.create_markdown(renderer=renderer, plugins=["table", "strikethrough", "footnotes"])
        rendered = md(clean)
    else:  # pragma: no cover
        raise RuntimeError("Install the 'markdown' package (or mistune) before conversion")
    rendered = BLOCK_TAG_RE.sub(r'<\1 dir="auto"', rendered)
    rendered = rendered.replace(
        "⇌",
        '<svg class="equilibrium-symbol" viewBox="0 0 28 16" role="img" aria-label="equilibrium">'
        '<path d="M2 5 H23 M19 2 L23 5 L19 8 M26 11 H5 M9 8 L5 11 L9 14" '
        'fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>'
        '</svg>'
    )
    return _wrap_special_sections(rendered)


def _wrap_special_sections(rendered: str) -> str:
    heading_pattern = re.compile(r"<h2([^>]*)>(.*?)</h2>", re.I | re.S)
    matches = list(heading_pattern.finditer(rendered))
    if not matches:
        return rendered
    output: list[str] = []
    cursor = 0
    for idx, match in enumerate(matches):
        plain = re.sub(r"<[^>]+>", "", html.unescape(match.group(2))).strip()
        cls = "key-points" if KEY_HEADING_RE.match(plain) else "warning-box" if WARNING_HEADING_RE.match(plain) else None
        if not cls:
            continue
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(rendered)
        output.append(rendered[cursor:start])
        output.append(f'<section class="{cls}">{rendered[start:end]}</section>')
        cursor = end
    output.append(rendered[cursor:])
    return "".join(output)


def make_pdf(
    markdown_path: Path,
    output_path: Path,
    *,
    title: str | None = None,
    css_file: Path | None = None,
    font_config: FontConfig,
    page_numbers: bool = True,
    force_index: bool | None = None,
) -> Path:
    if HTML is None:  # pragma: no cover
        raise RuntimeError(f"WeasyPrint is unavailable: {_WEASYPRINT_ERROR}")
    markdown_path = Path(markdown_path).resolve()
    output_path = Path(output_path).resolve()
    font_config.validate()
    text = markdown_path.read_text(encoding="utf-8", errors="strict")
    doc_title = title or infer_title(text, markdown_path.stem)
    is_index = force_index if force_index is not None else ("study_index" in markdown_path.name.casefold() or "document_type: study_index" in text[:500].casefold())
    extra_css = ""
    if css_file:
        extra_css = Path(css_file).resolve().read_text(encoding="utf-8")
    style = PdfStyle(page_numbers=page_numbers)
    body_class = "study-index" if is_index else "study-note"
    content = markdown_to_html(text)
    language = "fa" if RTL_RE.search(text) else "en"
    document = f"""<!doctype html>
<html lang="{language}"><head><meta charset="utf-8"><title>{html.escape(doc_title)}</title><style>{build_css(style, font_config, is_index=is_index, extra_css=extra_css)}</style></head>
<body class="{body_class}" dir="auto">{content}</body></html>"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=document, base_url=str(markdown_path.parent)).write_pdf(output_path)
    return output_path


def batch_convert(input_dir: Path, output_dir: Path, *, css_file: Path | None, font_config: FontConfig, page_numbers: bool) -> list[Path]:
    notes = sorted((p for p in Path(input_dir).glob("*.md") if is_topic_note(p)), key=natural_key)
    if not notes:
        raise ValueError(f"No topic Markdown files found in {input_dir}")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    created = []
    for note in notes:
        out = output_dir / f"{note.stem}.pdf"
        print(f"Converting {note.name} -> {out.name}")
        created.append(make_pdf(note, out, css_file=css_file, font_config=font_config, page_numbers=page_numbers))
    return created


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert Markdown study notes to PDF with supplied fonts")
    parser.add_argument("input", nargs="?", help="Markdown file, or directory with --batch")
    parser.add_argument("--output", required=True)
    parser.add_argument("--batch", action="store_true")
    parser.add_argument("--css")
    parser.add_argument("--font-file", required=True, help="Arabic/Persian regular font")
    parser.add_argument("--font-bold-file", required=True, help="Latin bold font")
    parser.add_argument("--latin-font-file", required=True, help="Latin regular font")
    parser.add_argument("--arabic-font-bold-file")
    parser.add_argument("--no-page-numbers", action="store_true")
    parser.add_argument("--title")
    parser.add_argument("--index", action="store_true", help="Force Study Index landscape styling")
    args = parser.parse_args()
    if not args.input:
        parser.error("input path is required")
    fonts = FontConfig(Path(args.font_file), Path(args.latin_font_file), Path(args.font_bold_file), Path(args.arabic_font_bold_file) if args.arabic_font_bold_file else None)
    css = Path(args.css) if args.css else None
    if args.batch:
        created = batch_convert(Path(args.input), Path(args.output), css_file=css, font_config=fonts, page_numbers=not args.no_page_numbers)
        print(f"Created {len(created)} PDFs in {Path(args.output).resolve()}")
    else:
        output = make_pdf(Path(args.input), Path(args.output), title=args.title, css_file=css, font_config=fonts, page_numbers=not args.no_page_numbers, force_index=True if args.index else None)
        print(f"Created PDF: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
