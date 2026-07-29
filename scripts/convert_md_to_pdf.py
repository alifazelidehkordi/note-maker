#!/usr/bin/env python3
"""Markdown PDF renderer with backward-compatible batch APIs and final-book helpers."""
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

_WEASYPRINT_IMPORT_ERROR: Exception | None = None
try:
    from weasyprint import HTML
except (ModuleNotFoundError, OSError) as exc:  # pragma: no cover
    HTML = None
    _WEASYPRINT_IMPORT_ERROR = exc

import mistune
from bs4 import BeautifulSoup

from pdf_common import Session, strip_frontmatter


@dataclass(frozen=True)
class BatchResult:
    created: list[Path]
    failed: list[tuple[Path, str]]

    @property
    def succeeded(self) -> bool:
        return not self.failed


@dataclass(frozen=True)
class PdfStyle:
    page_size: str = "A4"
    margin: str = "1.45cm 1.55cm"
    font_size: str = "10.4pt"
    line_height: str = "1.48"
    font_family: str = 'Vazirmatn, "Noto Naskh Arabic", Tahoma, sans-serif'
    theme: str = "medical-blue"
    preset: str = "study"
    rtl: bool = False
    page_numbers: bool = True


THEMES = {
    "medical-blue": {"text": "#172033", "muted": "#64748b", "heading": "#0f3a66", "accent": "#2563eb", "surface": "#f8fafc", "border": "#dbe4ee"},
    "ink": {"text": "#111827", "muted": "#6b7280", "heading": "#111827", "accent": "#374151", "surface": "#fafafa", "border": "#d4d4d8"},
    "emerald": {"text": "#17231d", "muted": "#64746c", "heading": "#064e3b", "accent": "#059669", "surface": "#f8faf9", "border": "#d1e7dd"},
}
PRESETS = {
    "study": {"font_size": "10.4pt", "line_height": "1.48", "margin": "1.45cm 1.55cm"},
    "compact": {"font_size": "9.6pt", "line_height": "1.34", "margin": "1.15cm 1.25cm"},
    "comfortable": {"font_size": "11pt", "line_height": "1.6", "margin": "1.7cm 1.8cm"},
    "print": {"font_size": "10pt", "line_height": "1.42", "margin": "1.35cm 1.45cm"},
}
FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n", re.S | re.M)
METADATA_LINE_RE = re.compile(r"(?m)^\s*(?:\*\*منبع اصلی:\*\*.*|منبع اصلی:.*|book_pages:.*|chapter:.*|part:.*|pdf_pages:.*|source:.*)$")
RTL_SCRIPT_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]")
TOPIC_NOTE_RE = re.compile(r"^\d{1,3}(?:_\d{1,3})?_", re.I)
RICH_INDEX_NAMES = ("STUDY_INDEX-rewritten.md", "STUDY_INDEX.md")
META_NOTE_NAMES = {"index.md", "readme.md", "study_index.md", "study_index-rewritten.md", "study_index_verification.md", "combined_notes.md"}
MARKDOWN_EXTENSIONS = ["extra", "sane_lists", "smarty", "tables", "fenced_code", "footnotes", "toc"]
MARKDOWN_EXTENSION_CONFIGS: dict[str, dict[str, Any]] = {"toc": {"permalink": False}}
KEY_TITLES = {"key points", "نکات کلیدی", "summary", "خلاصه", "high-yield points"}
WARNING_TITLES = {"warning", "warnings", "هشدار", "هشدارها", "pitfalls", "common mistakes"}


def apply_preset(style: PdfStyle) -> PdfStyle:
    values = PRESETS.get(style.preset, PRESETS["study"])
    defaults = PdfStyle()
    return PdfStyle(
        page_size=style.page_size,
        margin=style.margin if style.margin != defaults.margin else values["margin"],
        font_size=style.font_size if style.font_size != defaults.font_size else values["font_size"],
        line_height=style.line_height if style.line_height != defaults.line_height else values["line_height"],
        font_family=style.font_family, theme=style.theme, preset=style.preset,
        rtl=style.rtl, page_numbers=style.page_numbers,
    )


def build_css(style: PdfStyle, extra_css: str | None = None, css_file: Path | None = None) -> str:
    """Retained standalone conversion API."""
    style = apply_preset(style)
    palette = THEMES.get(style.theme, THEMES["medical-blue"])
    direction, align = ("rtl", "right") if style.rtl else ("ltr", "left")
    counter = "content: counter(page);" if style.page_numbers else "content: '';"
    css = f'''@page {{ size: {style.page_size}; margin: {style.margin}; @bottom-center {{ {counter} font-size:8.5pt; }} }}
body {{ direction:{direction}; text-align:{align}; font-family:{style.font_family}; font-size:{style.font_size}; line-height:{style.line_height}; color:{palette['text']}; }}
body,p,li,td,th,h1,h2,h3,h4 {{ unicode-bidi:plaintext; }} h1,h2,h3,h4 {{ color:{palette['heading']}; break-after:avoid; }}
table {{ width:100%; border-collapse:collapse; table-layout:fixed; }} thead {{ display:table-header-group; }} tr {{ break-inside:avoid; }} th,td {{ border:1px solid {palette['border']}; padding:5pt; overflow-wrap:anywhere; }}
pre {{ direction:ltr; unicode-bidi:isolate; white-space:pre-wrap; overflow-wrap:anywhere; background:{palette['surface']}; padding:7pt; }} img,svg {{ max-width:100%; height:auto; }}
.key-points {{ background:#eaf4ff; border:1px solid #77afe1; padding:8pt 10pt; break-inside:avoid; }} .warning-box {{ background:#fff5e9; border:1px solid #ee9a45; padding:8pt 10pt; break-inside:avoid; }}'''
    if css_file and Path(css_file).is_file():
        css += "\n" + Path(css_file).read_text(encoding="utf-8")
    if extra_css:
        css += "\n" + extra_css
    return css


def clean_markdown(md_text: str) -> str:
    if md_text.lstrip().startswith("---"):
        md_text = FRONTMATTER_RE.sub("", md_text, count=1).lstrip()
    return METADATA_LINE_RE.sub("", md_text).strip()


def contains_rtl_script(text: str) -> bool:
    return bool(RTL_SCRIPT_RE.search(text))


def resolve_style(style: PdfStyle, md_text: str, *, auto_rtl: bool) -> PdfStyle:
    style = apply_preset(style)
    return replace(style, rtl=True) if auto_rtl and not style.rtl and contains_rtl_script(md_text) else style


def infer_title(md_text: str, fallback: str, *, cleaned: bool = False) -> str:
    text = md_text if cleaned else clean_markdown(md_text)
    match = re.search(r"^#\s+(.+)$", text, re.M)
    return match.group(1).strip() if match else fallback


def require_dependencies(*, require_pdf_renderer: bool = True) -> None:
    missing = []
    if markdown is None:
        missing.append("markdown")
    if require_pdf_renderer and HTML is None:
        missing.append("weasyprint native runtime")
    if missing:
        detail = f"\nRenderer import error: {_WEASYPRINT_IMPORT_ERROR}" if require_pdf_renderer and _WEASYPRINT_IMPORT_ERROR else ""
        print("Missing required dependency: " + ", ".join(missing) + detail, file=sys.stderr)
        raise SystemExit(2)


def wrap_special_sections(body_html: str) -> str:
    soup = BeautifulSoup(body_html, "html.parser")
    for heading in list(soup.find_all("h2")):
        title = heading.get_text(" ", strip=True).casefold()
        cls = "key-points" if title in KEY_TITLES else ("warning-box" if title in WARNING_TITLES else None)
        if not cls:
            continue
        wrapper = soup.new_tag("section")
        wrapper["class"] = cls
        heading.insert_before(wrapper)
        wrapper.append(heading.extract())
        sibling = wrapper.next_sibling
        while sibling is not None:
            nxt = sibling.next_sibling
            if getattr(sibling, "name", None) == "h2":
                break
            wrapper.append(sibling.extract())
            sibling = nxt
    return str(soup)


def md_to_html(md_text: str, *, cleaned: bool = False) -> str:
    require_dependencies(require_pdf_renderer=False)
    text = md_text if cleaned else clean_markdown(md_text)
    converter = markdown.Markdown(extensions=MARKDOWN_EXTENSIONS, extension_configs=MARKDOWN_EXTENSION_CONFIGS, output_format="html5")
    try:
        return wrap_special_sections(converter.convert(text))
    finally:
        converter.reset()


def is_topic_note(path: Path) -> bool:
    if path.suffix.casefold() != ".md":
        return False
    name = path.name.casefold()
    if name.startswith(".") or name in META_NOTE_NAMES or name.startswith(("study_index", "combined_notes")):
        return False
    return bool(TOPIC_NOTE_RE.match(path.name)) or path.is_file()


def find_rich_index_md(notes_dir: Path) -> Path | None:
    notes_dir = Path(notes_dir)
    for name in RICH_INDEX_NAMES:
        for candidate in (notes_dir / name, notes_dir.parent / name):
            if candidate.is_file():
                return candidate
    return None


def make_pdf(md_path: Path, output_pdf: Path | None = None, *, style: PdfStyle | None = None, title: str | None = None, extra_css: str | None = None, css_file: Path | None = None, prebuilt_css: str | None = None, auto_rtl: bool = True) -> Path:
    require_dependencies()
    raw = Path(md_path).read_text(encoding="utf-8")
    cleaned = clean_markdown(raw)
    resolved = resolve_style(style or PdfStyle(), cleaned, auto_rtl=auto_rtl)
    body = md_to_html(cleaned, cleaned=True)
    css = prebuilt_css if prebuilt_css is not None else build_css(resolved, extra_css=extra_css, css_file=css_file)
    doc_title = title or infer_title(cleaned, Path(md_path).stem, cleaned=True)
    full = f'<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(doc_title)}</title><style>{css}</style></head><body>{body}</body></html>'
    out = Path(output_pdf) if output_pdf else Path(md_path).with_suffix(".pdf")
    out.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=full, base_url=str(Path(md_path).parent)).write_pdf(str(out))
    return out


def batch_convert(input_dir: Path, output_dir: Path, *, pattern: str = "*.md", style: PdfStyle | None = None, css_file: Path | None = None, auto_rtl: bool = True) -> BatchResult:
    require_dependencies()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    created, failed = [], []
    for md_path in sorted(Path(input_dir).glob(pattern)):
        if not md_path.is_file() or not is_topic_note(md_path):
            continue
        try:
            created.append(make_pdf(md_path, output_dir / f"{md_path.stem}.pdf", style=style, css_file=css_file, auto_rtl=auto_rtl))
        except Exception as exc:  # noqa: BLE001
            failed.append((md_path, str(exc)))
    return BatchResult(created, failed)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Markdown notes -> styled study PDFs")
    parser.add_argument("input"); parser.add_argument("--output"); parser.add_argument("--batch", action="store_true")
    parser.add_argument("--pattern", default="*.md"); parser.add_argument("--css")
    parser.add_argument("--preset", choices=sorted(PRESETS), default="study"); parser.add_argument("--theme", choices=sorted(THEMES), default="medical-blue")
    parser.add_argument("--page-size", default="A4"); parser.add_argument("--margin"); parser.add_argument("--font-size"); parser.add_argument("--line-height"); parser.add_argument("--font-family")
    parser.add_argument("--rtl", action="store_true"); parser.add_argument("--no-auto-rtl", action="store_true"); parser.add_argument("--no-page-numbers", action="store_true"); parser.add_argument("--title")
    return parser.parse_args()


def style_from_args(args: argparse.Namespace) -> PdfStyle:
    values = PRESETS[args.preset]
    return apply_preset(PdfStyle(page_size=args.page_size, margin=args.margin or values["margin"], font_size=args.font_size or values["font_size"], line_height=args.line_height or values["line_height"], font_family=args.font_family or PdfStyle.font_family, theme=args.theme, preset=args.preset, rtl=args.rtl, page_numbers=not args.no_page_numbers))


def main() -> int:
    args = parse_args(); inp = Path(args.input); style = style_from_args(args); css_file = Path(args.css) if args.css else None
    if args.batch or inp.is_dir():
        result = batch_convert(inp, Path(args.output) if args.output else inp / "pdfs", pattern=args.pattern, style=style, css_file=css_file, auto_rtl=not args.no_auto_rtl)
        return 2 if result.failed else 0
    make_pdf(inp, Path(args.output) if args.output else inp.with_suffix(".pdf"), style=style, title=args.title, css_file=css_file, auto_rtl=not args.no_auto_rtl)
    return 0


def markdown_renderer():
    return mistune.create_markdown(escape=False, plugins=["table", "strikethrough", "footnotes", "task_lists", "url"])


def note_to_html(session: Session, *, group_start: bool) -> str:
    text = strip_frontmatter(session.note_path.read_text(encoding="utf-8", errors="strict"))
    soup = BeautifulSoup(wrap_special_sections(markdown_renderer()(text)), "html.parser")
    first = soup.find("h1")
    if first:
        first["class"] = list(first.get("class", [])) + ["note-title"]
    group_marker = f'<h2 class="group-bookmark" data-bookmark-label="{html.escape(session.group)}">{html.escape(session.group)}</h2>' if group_start else ""
    return f'<section class="note-section" id="{html.escape(session.anchor)}">{group_marker}<div class="session-bookmark" data-bookmark-label="{html.escape(session.title)}"></div><div class="session-meta"><span>Session {session.number:02d}</span><span>Source pages {html.escape(session.pdf_pages)}</span><span>{html.escape(session.duration)}</span></div>{soup}</section>'


def build_final_css(font_file: Path, font_bold_file: Path) -> str:
    regular_uri, bold_uri = Path(font_file).resolve().as_uri(), Path(font_bold_file).resolve().as_uri()
    return f'''
@font-face {{ font-family:"StudyCustom"; src:url("{regular_uri}") format("truetype"); font-weight:100 900; unicode-range:U+0600-06FF,U+0750-077F,U+08A0-08FF,U+FB50-FDFF,U+FE70-FEFF; }}
@font-face {{ font-family:"StudyCustom"; src:url("{bold_uri}") format("opentype"); font-weight:100 900; unicode-range:U+0000-05FF,U+2000-206F,U+2070-209F,U+20A0-20CF,U+2100-214F,U+2190-21FF,U+2200-22FF,U+2300-23FF,U+2500-25FF,U+2700-27BF; }}
@page {{ size:A4 portrait; margin:17mm 15mm; @top-left {{ content:"LABORATORY MEDICINE"; font-family:"StudyCustom"; font-size:7.4pt; letter-spacing:.12em; color:#64748b; }} @top-right {{ content:string(section-title); font-family:"StudyCustom"; font-size:7.4pt; color:#64748b; }} @bottom-center {{ content:counter(page); font-family:"StudyCustom"; font-size:8.4pt; color:#475569; }} }} @page:first {{ @top-left {{ content:none }} @top-right {{ content:none }} }}
* {{ box-sizing:border-box }} html,body {{ font-family:"StudyCustom" }} body {{ margin:0; color:#182231; font-size:9.65pt; line-height:1.47 }} body,p,li,td,th,h1,h2,h3,h4,h5,blockquote {{ unicode-bidi:plaintext }} p {{ margin:4pt 0 6pt; orphans:3; widows:3 }} a {{ color:#1557a0; text-decoration:none }} strong,b {{ color:#0f355c }}
h1,h2,h3,h4,h5 {{ bookmark-level:none; color:#113b65; line-height:1.22; break-after:avoid }} h1 {{ font-size:18pt; margin:0 0 11pt; padding-bottom:7pt; border-bottom:2.2pt solid #2d72b8; string-set:section-title content() }} h2 {{ font-size:13.7pt; margin:17pt 0 7pt; border-left:4pt solid #78aee0; padding-left:7pt }} h3 {{ font-size:11.8pt }}
ul,ol {{ padding-inline-start:18pt; margin:5pt 0 8pt }} ::marker {{ font-family:"StudyCustom" }} li {{ margin:2.7pt 0 }} blockquote {{ padding:7pt 10pt; background:#f7f9fc; border-left:3pt solid #b8cbe0; break-inside:avoid }} code,pre {{ font-family:"StudyCustom"; direction:ltr; unicode-bidi:isolate }} pre {{ background:#eef3f8; padding:7pt 8pt; white-space:pre-wrap; overflow-wrap:anywhere; break-inside:avoid }} img,svg {{ max-width:100%; max-height:235mm; height:auto; break-inside:avoid }}
table {{ width:100%; border-collapse:collapse; table-layout:fixed; margin:10pt 0 12pt; font-size:8.35pt; line-height:1.32 }} thead {{ display:table-header-group }} tr {{ break-inside:avoid }} th,td {{ border:.65pt solid #cbd7e4; padding:4pt 4.5pt; vertical-align:top; overflow-wrap:anywhere }} th {{ background:#eaf2fa; color:#123f6d }}
.key-points,.warning-box {{ margin:13pt 0; padding:8pt 10pt; border-radius:6pt; break-inside:avoid }} .key-points {{ background:#eaf4ff; border:1pt solid #77afe1 }} .warning-box {{ background:#fff5e9; border:1pt solid #ee9a45 }}
.note-section {{ break-before:page }} .session-bookmark {{ bookmark-level:3; bookmark-label:attr(data-bookmark-label); height:0 }} .group-bookmark {{ bookmark-level:2; bookmark-label:attr(data-bookmark-label); border:0; padding:0; margin:0 0 8pt; font-size:9pt; color:#55728f }} .session-meta {{ display:flex; justify-content:space-between; margin:0 0 10pt; padding:5pt 7pt; border:.7pt solid #d3deea; background:#f7f9fc; color:#53677c; font-size:7.7pt }}
.index-bookmark {{ bookmark-level:1; bookmark-label:"Study Index" }} .study-index h2 {{ bookmark-level:none }} .study-index {{ direction:ltr }} .cover-card {{ min-height:93mm; padding:18mm 13mm; margin:0 0 13mm; border-radius:10pt; background:linear-gradient(145deg,#0f355c,#1d5f9d); color:white; display:flex; flex-direction:column; justify-content:center }} .cover-card h2 {{ color:white; border:0; padding:0; margin:11pt 0 8pt; font-size:24pt }} .lead-fa {{ color:white; font-size:11pt; text-align:right }} .metrics {{ display:flex; gap:8pt; margin-top:15pt }} .metrics div {{ flex:1; padding:9pt; border:.7pt solid rgba(255,255,255,.32); border-radius:6pt }} .metrics strong {{ color:white; display:block; font-size:17pt }} .metrics span {{ display:block; font-size:7.4pt }} .index-intro {{ padding:8pt 10pt; background:#f1f6fb; border-right:4pt solid #2d72b8; margin-bottom:12pt }}
.study-index table {{ font-size:7.25pt; line-height:1.24 }} .study-index th,.study-index td {{ padding:3.5pt 3.7pt }} .groups-table th:nth-child(1),.groups-table td:nth-child(1){{width:6%}} .groups-table th:nth-child(2),.groups-table td:nth-child(2){{width:42%}} .groups-table th:nth-child(3),.groups-table td:nth-child(3){{width:16%}} .groups-table th:nth-child(4),.groups-table td:nth-child(4){{width:23%}} .groups-table th:nth-child(5),.groups-table td:nth-child(5){{width:13%}} .sessions-table th:nth-child(1),.sessions-table td:nth-child(1){{width:5%}} .sessions-table th:nth-child(2),.sessions-table td:nth-child(2){{width:25%}} .sessions-table th:nth-child(3),.sessions-table td:nth-child(3){{width:10%}} .sessions-table th:nth-child(4),.sessions-table td:nth-child(4){{width:9%}} .sessions-table th:nth-child(5),.sessions-table td:nth-child(5){{width:10%}} .sessions-table th:nth-child(6),.sessions-table td:nth-child(6){{width:41%}}
'''


def write_html_pdf(full_html: str, output_pdf: Path, base_url: Path) -> None:
    if HTML is None:
        raise RuntimeError("WeasyPrint is unavailable")
    Path(output_pdf).parent.mkdir(parents=True, exist_ok=True)
    HTML(string=full_html, base_url=str(base_url)).write_pdf(str(output_pdf))


if __name__ == "__main__":
    raise SystemExit(main())
