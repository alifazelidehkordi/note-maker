#!/usr/bin/env python3
"""Convert prepared Markdown notes to embedded-font A4 portrait PDFs."""
from __future__ import annotations

import argparse
import html
import re
from dataclasses import dataclass
from pathlib import Path

import mistune
from bs4 import BeautifulSoup
from weasyprint import HTML

from pdf_pipeline_common import (
    FontConfig,
    font_config,
    font_stack,
    is_session_markdown,
    natural_key,
    parse_frontmatter,
    validate_component_pdf,
)


@dataclass(frozen=True)
class PdfStyle:
    margin_top: str = "17mm"
    margin_right: str = "15mm"
    margin_bottom: str = "18mm"
    margin_left: str = "15mm"
    font_size: str = "9.45pt"
    line_height: str = "1.43"
    page_numbers: bool = False
    is_index: bool = False


def _markdown_renderer():
    plugins = ["table", "footnotes", "strikethrough", "task_lists", "url"]
    available = []
    for plugin in plugins:
        try:
            mistune.create_markdown(plugins=[plugin])
            available.append(plugin)
        except Exception:
            pass
    return mistune.create_markdown(escape=False, plugins=available)


MARKDOWN = _markdown_renderer()


def strip_frontmatter(text: str) -> str:
    return re.sub(r"\A---\s*\n.*?\n---\s*(?:\n|\Z)", "", text, count=1, flags=re.S)


def infer_title(markdown_text: str, fallback: str) -> str:
    match = re.search(r"^#\s+(.+?)\s*$", markdown_text, re.M)
    return re.sub(r"[*_`]+", "", match.group(1)).strip() if match else fallback


def decorate_html(fragment: str) -> str:
    soup = BeautifulSoup(fragment, "html.parser")
    for heading in soup.find_all(["h2", "h3"]):
        text = heading.get_text(" ", strip=True).casefold()
        if heading.name == "h2" and text in {"key points", "نکات کلیدی", "summary", "خلاصه", "خلاصه کلیدی"}:
            wrapper = soup.new_tag("section")
            wrapper["class"] = "key-points"
            heading.wrap(wrapper)
            node = wrapper.next_sibling
            while node and getattr(node, "name", None) not in {"h1", "h2"}:
                next_node = node.next_sibling
                wrapper.append(node.extract())
                node = next_node
        elif heading.name == "h2" and any(token in text for token in ("warning", "هشدار", "pitfall", "اشتباه رایج")):
            wrapper = soup.new_tag("section")
            wrapper["class"] = "warning-box"
            heading.wrap(wrapper)
            node = wrapper.next_sibling
            while node and getattr(node, "name", None) not in {"h1", "h2"}:
                next_node = node.next_sibling
                wrapper.append(node.extract())
                node = next_node
    for table in soup.find_all("table"):
        wrapper = soup.new_tag("div")
        wrapper["class"] = "table-scroll"
        table.wrap(wrapper)
    return str(soup)


def build_css(fonts: FontConfig, style: PdfStyle) -> str:
    regular = font_stack(fonts.regular_families)
    bold = font_stack(fonts.bold_families)
    footer = "content: counter(page);" if style.page_numbers else "content: '';"
    index_css = """
.study-index { direction:rtl; text-align:right; }
.index-topline { display:flex; justify-content:flex-end; gap:2mm; align-items:baseline; color:#194f7d; font-family:BOLD_STACK; font-size:10pt; border-bottom:1.4px solid #2f7fbe; padding-bottom:1.7mm; margin-bottom:2.7mm; }
.index-topline span[dir="ltr"] { font-size:9.2pt; }
.index-hero { color:#fff; background:linear-gradient(135deg,#0d3b67 0%,#1f68a4 100%); border-radius:9px; padding:9mm 10mm 8mm; margin:0 0 6mm; direction:rtl; text-align:right; }
.hero-kicker { font-family:BOLD_STACK; font-size:7.2pt; letter-spacing:1.1px; opacity:.8; margin-bottom:2mm; }
.hero-title { font-family:BOLD_STACK; font-size:20.5pt; line-height:1.18; text-align:left; margin:0 0 2.2mm; unicode-bidi:plaintext; }
.hero-subtitle { font-size:8.8pt; opacity:.93; margin-bottom:6mm; }
.hero-stats { display:grid; grid-template-columns:repeat(4,1fr); gap:2.5mm; direction:ltr; }
.hero-stats > div { border:1px solid rgba(255,255,255,.27); border-radius:6px; padding:3mm 3.3mm; min-height:16mm; display:flex; flex-direction:column; justify-content:center; }
.hero-stats strong { font-family:BOLD_STACK; font-size:13.7pt; line-height:1; color:#fff; }
.hero-stats span { direction:rtl; text-align:left; font-size:6.7pt; color:#e5f2ff; margin-top:1.4mm; }
.index-guide { background:#f6f9fc; border-right:3.5px solid #2f7fbe; padding:3mm 4mm; margin:0 0 5mm; border-radius:3px; }
.index-guide h2 { border:0; padding:0; margin:0 0 1mm; font-size:10.5pt; }
.index-guide p { margin:0; font-size:8pt; line-height:1.45; }
.study-index h2 { font-size:11.1pt; margin:4mm 0 2mm; border-right:4px solid #2f7fbe; border-left:0; padding-right:2.3mm; padding-left:0; }
.study-index h2 span { font-size:9.1pt; color:#47657e; }
.group-table table { font-size:7.1pt; line-height:1.2; table-layout:fixed; }
.group-table th, .group-table td { padding:1.25mm 1.05mm; }
.group-table th:nth-child(1), .group-table td:nth-child(1) { width:5%; text-align:center; }
.group-table th:nth-child(2), .group-table td:nth-child(2) { width:30%; direction:ltr; text-align:left; }
.group-table th:nth-child(3), .group-table td:nth-child(3) { width:13%; text-align:center; }
.group-table th:nth-child(4), .group-table td:nth-child(4) { width:17%; text-align:center; }
.group-table th:nth-child(5), .group-table td:nth-child(5) { width:21%; text-align:center; }
.group-table th:nth-child(6), .group-table td:nth-child(6) { width:14%; text-align:center; }
.session-table table { font-size:6.7pt; line-height:1.22; table-layout:fixed; }
.session-table th, .session-table td { box-sizing:border-box; padding:1.35mm 1.05mm; overflow-wrap:anywhere; word-break:normal; }
.session-table th:nth-child(1), .session-table td:nth-child(1) { width:5%; text-align:center; }
.session-table th:nth-child(2), .session-table td:nth-child(2) { width:24%; direction:ltr; text-align:left; }
.session-table th:nth-child(3), .session-table td:nth-child(3) { width:11%; text-align:center; }
.session-table th:nth-child(4), .session-table td:nth-child(4) { width:11%; text-align:center; }
.session-table th:nth-child(5), .session-table td:nth-child(5) { width:9%; text-align:center; direction:ltr; }
.session-table th:nth-child(6), .session-table td:nth-child(6) { width:40%; direction:ltr; text-align:left; }
.index-footer-note { font-size:7pt; color:#728096; margin-top:3mm; }
""".replace("BOLD_STACK", bold) if style.is_index else ""

    return f"""
{fonts.css}
@page {{
  size: A4 portrait;
  margin: {style.margin_top} {style.margin_right} {style.margin_bottom} {style.margin_left};
  @top-left {{ content: element(running-book-title); vertical-align:bottom; padding-bottom:1.4mm; }}
  @top-right {{ content: element(running-section-title); vertical-align:bottom; padding-bottom:1.4mm; }}
  @bottom-center {{ {footer} font-family: {regular}; font-size:8pt; color:#64748b; }}
}}
html, body {{ margin:0; padding:0; }}
body {{
  font-family:{regular}; font-size:{style.font_size}; line-height:{style.line_height};
  color:#172033; direction:ltr; text-align:left; overflow-wrap:anywhere;
}}
body, p, li, td, th, blockquote, h1, h2, h3, h4, a, span {{ unicode-bidi:plaintext; }}
h1, h2, h3, h4, strong, b, th {{ font-family:{bold}; }}
h1, h2, h3, h4 {{ color:#0f3a66; line-height:1.24; break-after:avoid; page-break-after:avoid; orphans:3; widows:3; }}
h1 {{ font-size:16.8pt; border-bottom:2px solid #2f7fbe; padding-bottom:2mm; margin:0 0 3.8mm; }}
h2 {{ font-size:11.8pt; border-left:4px solid #60a5fa; padding-left:2.4mm; margin:4.7mm 0 2mm; }}
[dir="rtl"] h2 {{ border-left:none; border-right:4px solid #60a5fa; padding-left:0; padding-right:2.4mm; }}
h3 {{ font-size:10.1pt; color:#355d80; margin:3.5mm 0 1.3mm; }}
h4 {{ font-size:9.7pt; margin:2.8mm 0 1mm; }}
p {{ margin:1.15mm 0; }}
ul, ol {{ margin:1.2mm 0 2.1mm; padding-inline-start:5.8mm; }}
li {{ margin:.8mm 0; }}
a {{ color:#1d63a4; text-decoration:none; }}
blockquote {{ margin:3mm 0; padding:2.7mm 3.2mm; background:#f8fafc; border-left:4px solid #cbd5e1; break-inside:avoid; }}
[dir="rtl"] blockquote {{ border-left:none; border-right:4px solid #cbd5e1; }}
code, pre {{ font-family:{regular}; direction:ltr; unicode-bidi:isolate; }}
code {{ background:#eef2f7; padding:.4mm 1mm; border-radius:3px; font-size:8.2pt; }}
pre {{ white-space:pre-wrap; overflow-wrap:anywhere; background:#eef2f7; padding:2.6mm 3mm; border-radius:6px; break-inside:avoid; font-size:8pt; }}
.table-scroll {{ width:100%; max-width:100%; overflow:hidden; margin:2.7mm 0; }}
table {{ width:100%; max-width:100%; border-collapse:collapse; table-layout:fixed; font-size:8.15pt; line-height:1.28; }}
thead {{ display:table-header-group; }}
tfoot {{ display:table-footer-group; }}
tr {{ break-inside:avoid; page-break-inside:avoid; }}
th, td {{ border:1px solid #d9e3ec; padding:1.55mm 1.8mm; vertical-align:top; overflow-wrap:anywhere; word-break:normal; }}
th {{ background:#eaf3fb; color:#194f7d; }}
img, svg {{ max-width:100%; max-height:230mm; height:auto; object-fit:contain; break-inside:avoid; }}
figure {{ margin:3mm auto; break-inside:avoid; }}
figcaption {{ font-size:8pt; color:#64748b; text-align:center; }}
.key-points, .warning-box {{ break-inside:avoid; border-radius:7px; padding:3.1mm 4mm; margin:4mm 0; }}
.key-points {{ background:#eaf4ff; border:1.2px solid #73afe0; }}
.warning-box {{ background:#fff7ed; border:1.2px solid #fdba74; }}
.key-points h2, .warning-box h2 {{ margin-top:0; }}
hr {{ border:0; border-top:1px solid #dbe4ee; margin:4mm 0; }}
.running-book-title {{ position:running(running-book-title); font-family:{bold}; font-size:6.6pt; letter-spacing:.8px; color:#8491a1; text-transform:uppercase; white-space:nowrap; }}
.running-section-title {{ position:running(running-section-title); font-family:{regular}; font-size:6.5pt; color:#8491a1; white-space:nowrap; max-width:92mm; text-overflow:ellipsis; overflow:hidden; }}
.session-group {{ font-family:{bold}; font-size:8pt; color:#5d7187; margin:0 0 2.2mm; }}
.session-ribbon {{ display:grid; grid-template-columns:1fr 1.2fr 1fr; gap:0; margin:0 0 3.2mm; background:#f4f8fc; border:1px solid #e4ebf2; font-size:7.15pt; color:#5c7186; }}
.session-ribbon > span {{ padding:1.65mm 2.2mm; }}
.session-ribbon > span:nth-child(1) {{ text-align:left; }}
.session-ribbon > span:nth-child(2) {{ text-align:center; border-left:1px solid #e4ebf2; border-right:1px solid #e4ebf2; }}
.session-ribbon > span:nth-child(3) {{ text-align:right; }}
.session-document p, .session-document li {{ font-size:9.2pt; }}
{index_css}
"""


def make_pdf(
    markdown_path: Path,
    output_path: Path,
    *,
    title: str | None = None,
    fonts: FontConfig | None = None,
    style: PdfStyle | None = None,
    extra_css: str = "",
    session_meta: dict | None = None,
    running_book_title: str | None = None,
) -> Path:
    markdown_path = Path(markdown_path).resolve()
    output_path = Path(output_path).resolve()
    if not markdown_path.is_file():
        raise FileNotFoundError(markdown_path)
    fonts = fonts or font_config()
    style = style or PdfStyle()
    source = strip_frontmatter(markdown_path.read_text(encoding="utf-8", errors="strict"))
    fragment = decorate_html(MARKDOWN(source))
    doc_title = title or infer_title(source, markdown_path.stem)
    css = build_css(fonts, style) + "\n" + extra_css
    running = (
        f'<div class="running-book-title">{html.escape(running_book_title or doc_title)}</div>'
        f'<div class="running-section-title">{html.escape(doc_title if not style.is_index else "Study Index / فهرست مطالعه")}</div>'
    )
    lead = ""
    if session_meta:
        group = html.escape(str(session_meta.get("group", "Study Sessions")))
        number = int(session_meta.get("number", 0) or 0)
        source_pages = html.escape(str(session_meta.get("source_pages", "—")))
        duration = html.escape(str(session_meta.get("duration", "—")))
        lead = (
            f'<div class="session-group">{group}</div>'
            '<div class="session-ribbon">'
            f'<span>Session {number:02d}</span>'
            f'<span>Source pages {source_pages}</span>'
            f'<span>{duration}</span>'
            '</div>'
        )
    body_class = "study-index-document" if style.is_index else "session-document"
    document = (
        '<!doctype html><html><head><meta charset="utf-8">'
        f'<title>{html.escape(doc_title)}</title><style>{css}</style></head>'
        f'<body class="{body_class}">{running}{lead}{fragment}</body></html>'
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=document, base_url=str(markdown_path.parent)).write_pdf(output_path)
    validate_component_pdf(output_path)
    return output_path


def _batch_session_meta(note: Path, fallback_number: int) -> dict:
    meta = parse_frontmatter(note)
    name_match = re.match(r"^(\d{1,4})(?:_(\d{1,4}))?_", note.name)
    filename_number = int(name_match.group(2) or name_match.group(1)) if name_match else fallback_number

    def first(*keys: str, default: str = "—") -> str:
        for key in keys:
            value = meta.get(key)
            if value not in (None, ""):
                return str(value).strip()
        return default

    try:
        number = int(first("session", "part", "section", default=str(filename_number)))
    except ValueError:
        number = filename_number
    group = first("chapter_title_fa", "chapter_title", "group_title", "group", "chapter", default="Study Sessions")
    source_pages = first("pdf_pages", "source_pages", "pages", "page_range")
    duration = first("estimated_time", "duration", "time")
    return {
        "number": number,
        "group": group,
        "source_pages": source_pages,
        "duration": duration,
    }


def convert_batch(
    input_dir: Path,
    output_dir: Path,
    *,
    fonts: FontConfig,
    force: bool = True,
    running_book_title: str | None = None,
    extra_css: str = "",
) -> list[Path]:
    input_dir = Path(input_dir).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    notes = sorted((p for p in input_dir.glob("*.md") if is_session_markdown(p)), key=natural_key)
    if not notes:
        raise ValueError(f"No session Markdown files found in {input_dir}")
    book_title = running_book_title or input_dir.name.replace("_", " ").replace("-", " ").title()
    outputs: list[Path] = []
    for fallback_number, note in enumerate(notes, 1):
        pdf = output_dir / f"{note.stem}.pdf"
        if force or not pdf.exists() or note.stat().st_mtime_ns > pdf.stat().st_mtime_ns:
            print(f"Rendering A4 portrait: {note.name}")
            make_pdf(
                note,
                pdf,
                fonts=fonts,
                style=PdfStyle(page_numbers=False),
                extra_css=extra_css,
                session_meta=_batch_session_meta(note, fallback_number),
                running_book_title=book_title,
            )
        else:
            validate_component_pdf(pdf)
        outputs.append(pdf)
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert Markdown notes to embedded-font A4 portrait PDF")
    parser.add_argument("input", nargs="?")
    parser.add_argument("--batch", action="store_true")
    parser.add_argument("--output", required=True)
    parser.add_argument("--title")
    parser.add_argument("--index", action="store_true", help="Use compact Study Index table styling")
    parser.add_argument("--page-numbers", action="store_true")
    parser.add_argument("--no-force", action="store_true")
    parser.add_argument("--css")
    parser.add_argument("--running-title", help="Running book title for batch session PDFs")
    args = parser.parse_args()
    if not args.input:
        parser.error("input path is required")
    fonts = font_config()
    extra_css = Path(args.css).read_text(encoding="utf-8") if args.css else ""
    if args.batch:
        convert_batch(
            Path(args.input),
            Path(args.output),
            fonts=fonts,
            force=not args.no_force,
            running_book_title=args.running_title,
            extra_css=extra_css,
        )
    else:
        make_pdf(
            Path(args.input),
            Path(args.output),
            title=args.title,
            fonts=fonts,
            style=PdfStyle(page_numbers=args.page_numbers, is_index=args.index),
            extra_css=extra_css,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
