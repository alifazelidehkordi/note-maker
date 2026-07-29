#!/usr/bin/env python3
"""Markdown/HTML rendering helpers for the final portrait study book."""
from __future__ import annotations

import html
from pathlib import Path

import mistune
from bs4 import BeautifulSoup
from weasyprint import HTML

from pdf_common import Session, strip_frontmatter

KEY_TITLES = {"key points", "نکات کلیدی", "summary", "خلاصه", "high-yield points"}
WARNING_TITLES = {"warning", "warnings", "هشدار", "هشدارها", "pitfalls", "common mistakes"}


def markdown_renderer():
    plugins = ["table", "strikethrough", "footnotes", "task_lists", "url"]
    return mistune.create_markdown(escape=False, plugins=plugins)


def wrap_special_sections(body_html: str) -> str:
    soup = BeautifulSoup(body_html, "html.parser")
    for heading in list(soup.find_all(["h2"])):
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


def note_to_html(session: Session, *, group_start: bool) -> str:
    text = strip_frontmatter(session.note_path.read_text(encoding="utf-8", errors="strict"))
    rendered = markdown_renderer()(text)
    rendered = wrap_special_sections(rendered)
    soup = BeautifulSoup(rendered, "html.parser")
    first_h1 = soup.find("h1")
    if first_h1:
        first_h1["class"] = list(first_h1.get("class", [])) + ["note-title"]
    group_marker = ""
    if group_start:
        group_marker = (
            f'<h2 class="group-bookmark" data-bookmark-label="{html.escape(session.group)}">'
            f'{html.escape(session.group)}</h2>'
        )
    return (
        f'<section class="note-section" id="{html.escape(session.anchor)}" '
        f'data-session-number="{session.number}" data-session-title="{html.escape(session.title)}">'
        f'{group_marker}'
        f'<div class="session-bookmark" data-bookmark-label="{html.escape(session.title)}"></div>'
        f'<div class="session-meta"><span>Session {session.number:02d}</span><span>Source pages {html.escape(session.pdf_pages)}</span><span>{html.escape(session.duration)}</span></div>'
        f'{soup}'
        '</section>'
    )


def build_css(font_file: Path, font_bold_file: Path) -> str:
    regular_uri = font_file.resolve().as_uri()
    bold_uri = font_bold_file.resolve().as_uri()
    return f'''
@font-face {{
  font-family: "StudyCustom";
  src: url("{regular_uri}") format("truetype");
  font-style: normal;
  font-weight: 100 900;
  unicode-range: U+0600-06FF, U+0750-077F, U+08A0-08FF, U+FB50-FDFF, U+FE70-FEFF;
}}
@font-face {{
  font-family: "StudyCustom";
  src: url("{bold_uri}") format("opentype");
  font-style: normal;
  font-weight: 100 900;
  unicode-range: U+0000-05FF, U+2000-206F, U+2070-209F, U+20A0-20CF, U+2100-214F, U+2190-21FF, U+2200-22FF, U+2300-23FF, U+2500-25FF, U+2700-27BF;
}}
@page {{
  size: A4 portrait;
  margin: 17mm 15mm 17mm 15mm;
  @top-left {{ content: "LABORATORY MEDICINE"; font-family: "StudyCustom"; font-size: 7.4pt; letter-spacing: 0.12em; color: #64748b; }}
  @top-right {{ content: string(section-title); font-family: "StudyCustom"; font-size: 7.4pt; color: #64748b; }}
  @bottom-center {{ content: counter(page); font-family: "StudyCustom"; font-size: 8.4pt; color: #475569; }}
}}
@page:first {{ @top-left {{ content: none; }} @top-right {{ content: none; }} }}
* {{ box-sizing: border-box; }}
html {{ font-family: "StudyCustom"; font-synthesis: weight; }}
body {{ margin: 0; color: #182231; font-family: "StudyCustom"; font-size: 9.65pt; line-height: 1.47; }}
body, p, li, td, th, h1, h2, h3, h4, h5, blockquote {{ unicode-bidi: plaintext; }}
p {{ margin: 4pt 0 6pt; orphans: 3; widows: 3; }}
a {{ color: #1557a0; text-decoration: none; }}
strong, b {{ color: #0f355c; font-weight: 700; }}
h1, h2, h3, h4, h5 {{ bookmark-level: none; color: #113b65; line-height: 1.22; break-after: avoid; page-break-after: avoid; orphans: 3; widows: 3; }}
h1 {{ font-size: 18pt; margin: 0 0 11pt; padding-bottom: 7pt; border-bottom: 2.2pt solid #2d72b8; string-set: section-title content(); }}
h2 {{ font-size: 13.7pt; margin: 17pt 0 7pt; border-left: 4pt solid #78aee0; padding-left: 7pt; }}
h3 {{ font-size: 11.8pt; margin: 12pt 0 4pt; }}
h4 {{ font-size: 10.5pt; margin: 9pt 0 3pt; }}
h5 {{ font-size: 9.8pt; margin: 8pt 0 3pt; }}
ul, ol {{ padding-inline-start: 18pt; margin: 5pt 0 8pt; }}
ul {{ list-style-type: disc; }}
ul ul, ol ul {{ list-style-type: disc; }}
::marker {{ font-family: "StudyCustom"; }}
li {{ margin: 2.7pt 0; }}
blockquote {{ margin: 10pt 0; padding: 7pt 10pt; background: #f7f9fc; border-left: 3pt solid #b8cbe0; break-inside: avoid; }}
hr {{ border: 0; border-top: 0.8pt solid #d7e0ea; margin: 12pt 0; }}
code, pre {{ font-family: "StudyCustom"; direction: ltr; unicode-bidi: isolate; }}
code {{ background: #eef3f8; padding: 1pt 3pt; border-radius: 2pt; overflow-wrap: anywhere; }}
pre {{ background: #eef3f8; border: 0.8pt solid #d6e0eb; padding: 7pt 8pt; white-space: pre-wrap; overflow-wrap: anywhere; break-inside: avoid; font-size: 8.3pt; line-height: 1.35; }}
img, svg {{ max-width: 100%; max-height: 235mm; height: auto; object-fit: contain; break-inside: avoid; }}
table {{ width: 100%; border-collapse: collapse; table-layout: fixed; margin: 10pt 0 12pt; font-size: 8.35pt; line-height: 1.32; }}
thead {{ display: table-header-group; }}
tr {{ break-inside: avoid; page-break-inside: avoid; }}
th, td {{ border: 0.65pt solid #cbd7e4; padding: 4pt 4.5pt; vertical-align: top; overflow-wrap: anywhere; word-break: normal; }}
th {{ background: #eaf2fa; color: #123f6d; font-weight: 700; }}
.key-points, .warning-box {{ margin: 13pt 0; padding: 8pt 10pt; border-radius: 6pt; break-inside: avoid; }}
.key-points {{ background: #eaf4ff; border: 1pt solid #77afe1; }}
.warning-box {{ background: #fff5e9; border: 1pt solid #ee9a45; }}
.key-points h2, .warning-box h2 {{ margin-top: 0; padding-left: 0; border-left: 0; }}
.note-section {{ break-before: page; page-break-before: always; }}
.note-section:first-of-type {{ break-before: page; }}
.note-title {{ bookmark-level: none; }}
.session-bookmark {{ bookmark-level: 3; bookmark-label: attr(data-bookmark-label); height: 0; margin: 0; padding: 0; }}
.group-bookmark {{ bookmark-level: 2; bookmark-label: attr(data-bookmark-label); border: 0; padding: 0; margin: 0 0 8pt; font-size: 9pt; letter-spacing: .08em; text-transform: uppercase; color: #55728f; }}
.session-meta {{ display: flex; justify-content: space-between; gap: 8pt; margin: 0 0 10pt; padding: 5pt 7pt; border: .7pt solid #d3deea; background: #f7f9fc; color: #53677c; font-size: 7.7pt; break-inside: avoid; }}
.index-bookmark {{ bookmark-level: 1; bookmark-label: "Study Index"; }}
.study-index h2 {{ bookmark-level: none; }}
.study-index {{ direction: ltr; }}
.cover-card {{ min-height: 93mm; padding: 18mm 13mm; margin: 0 0 13mm; border-radius: 10pt; background: linear-gradient(145deg, #0f355c, #1d5f9d); color: white; display: flex; flex-direction: column; justify-content: center; }}
.cover-card .eyebrow {{ font-size: 8pt; letter-spacing: .18em; opacity: .82; }}
.cover-card h2 {{ color: white; border: 0; padding: 0; margin: 11pt 0 8pt; font-size: 24pt; line-height: 1.13; }}
.lead-fa {{ color: white; opacity: .92; font-size: 11pt; text-align: right; }}
.metrics {{ display: flex; gap: 8pt; margin-top: 15pt; }}
.metrics div {{ flex: 1; padding: 9pt; border: .7pt solid rgba(255,255,255,.32); border-radius: 6pt; background: rgba(255,255,255,.08); }}
.metrics strong {{ color: white; display: block; font-size: 17pt; }}
.metrics span {{ display: block; font-size: 7.4pt; opacity: .82; margin-top: 3pt; }}
.index-intro {{ padding: 8pt 10pt; background: #f1f6fb; border-right: 4pt solid #2d72b8; margin: 0 0 12pt; }}
.index-intro h2 {{ margin: 0 0 4pt; border: 0; padding: 0; text-align: right; }}
.study-index table {{ font-size: 7.25pt; line-height: 1.24; }}
.study-index th, .study-index td {{ padding: 3.5pt 3.7pt; }}
.groups-table th:nth-child(1), .groups-table td:nth-child(1) {{ width: 6%; }}
.groups-table th:nth-child(2), .groups-table td:nth-child(2) {{ width: 42%; }}
.groups-table th:nth-child(3), .groups-table td:nth-child(3) {{ width: 16%; }}
.groups-table th:nth-child(4), .groups-table td:nth-child(4) {{ width: 23%; }}
.groups-table th:nth-child(5), .groups-table td:nth-child(5) {{ width: 13%; }}
.sessions-table th:nth-child(1), .sessions-table td:nth-child(1) {{ width: 5%; }}
.sessions-table th:nth-child(2), .sessions-table td:nth-child(2) {{ width: 25%; }}
.sessions-table th:nth-child(3), .sessions-table td:nth-child(3) {{ width: 10%; }}
.sessions-table th:nth-child(4), .sessions-table td:nth-child(4) {{ width: 9%; }}
.sessions-table th:nth-child(5), .sessions-table td:nth-child(5) {{ width: 10%; }}
.sessions-table th:nth-child(6), .sessions-table td:nth-child(6) {{ width: 41%; }}
.session-link a {{ font-weight: 700; }}
.focus {{ text-align: left; }}
@media print {{ a {{ color: #1557a0; }} }}
'''


def write_html_pdf(full_html: str, output_pdf: Path, base_url: Path) -> None:
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=full_html, base_url=str(base_url)).write_pdf(str(output_pdf))
