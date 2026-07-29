#!/usr/bin/env python3
"""Create one final portrait A4 PDF with clickable index, bookmarks and QC."""
from __future__ import annotations
import argparse
import html
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import mistune
from pypdf import PdfReader, PdfWriter
from pypdf.constants import PageLabelStyle
from weasyprint import HTML

from pdf_common import (
    A4_HEIGHT, A4_TOLERANCE, A4_WIDTH, StudyIndex, escape, find_index_file,
    font_face_css, normalize_visual_glyphs, parse_index, require_directory,
    require_readable_file,
)

MARKDOWN = mistune.create_markdown(escape=False, plugins=["table", "footnotes", "strikethrough", "task_lists", "url"])


def strip_first_h1(text: str) -> tuple[str, str]:
    match = re.search(r"(?m)^#\s+(.+?)\s*$", text)
    return (match.group(1).strip(), text[:match.start()] + text[match.end():]) if match else ("", text)


def note_html(text: str) -> str:
    text = normalize_visual_glyphs(text)
    rendered = MARKDOWN(text)
    rendered = re.sub(r"(<h2[^>]*>\s*(?:Key Points|نکات کلیدی|Summary)\s*</h2>)(.*?)(?=<h2|$)", r'<div class="key-points">\1\2</div>', rendered, flags=re.I|re.S)
    rendered = re.sub(r"(<h2[^>]*>\s*(?:Warnings?|هشدارها?|Pitfalls?|Common mistakes)\s*</h2>)(.*?)(?=<h2|$)", r'<div class="warning-box">\1\2</div>', rendered, flags=re.I|re.S)
    return rendered


def _range(items) -> str:
    first = re.findall(r"\d+", items[0].pdf_pages)
    last = re.findall(r"\d+", items[-1].pdf_pages)
    return f"{first[0]}-{last[-1]}" if first and last else "—"


def build_index_html(model: StudyIndex) -> str:
    groups = model.groups
    group_rows = []
    for group, items in groups:
        group_rows.append(
            "<tr>"
            f"<td class='group-name'>{escape(group)}</td>"
            f"<td class='num'>{items[0].order}-{items[-1].order}</td>"
            f"<td class='num'>{escape(_range(items))}</td>"
            f"<td>{escape(' · '.join(i.title for i in items[:3]))}{' · …' if len(items)>3 else ''}</td>"
            "</tr>"
        )
    session_rows = []
    for item in model.sessions:
        session_rows.append(
            "<tr>"
            f"<td class='num'>{item.order}</td>"
            f"<td class='session-cell'><a href='#{escape(item.destination)}'>{escape(item.title)}</a><div class='group-mini'>{escape(item.group)}</div></td>"
            f"<td class='num'>{escape(item.pdf_pages)}</td>"
            f"<td class='num'>{escape(item.book_pages)}</td>"
            f"<td class='focus'>{escape(item.focus)}</td>"
            "</tr>"
        )
    return f"""
<section class="study-index" id="study-index">
  <h1 class="study-index-title">فهرست مطالعه / Study Index</h1>
  <p class="course-title" dir="auto">{escape(model.title)}</p>
  <div class="stats">
    <div><strong>{len(model.sessions)}</strong><span>جلسه / Sessions</span></div>
    <div><strong>{len(groups)}</strong><span>فصل یا گروه / Groups</span></div>
    <div><strong>{escape(model.coverage)}</strong><span>صفحات منبع / Source pages</span></div>
    <div><strong>{escape(model.total_minutes)}</strong><span>زمان مطالعه / Study time</span></div>
  </div>
  <div class="index-note" dir="rtl">عنوان هر جلسه قابل کلیک است و مستقیماً به نخستین صفحه همان جلسه می‌رود.<br><span dir="ltr">Each session title is clickable and opens the first page of that session.</span></div>
  <h2 class="index-heading">فصل‌ها و گروه‌ها / Chapters and groups</h2>
  <table class="group-table"><thead><tr><th>گروه / Group</th><th>جلسات<br>Sessions</th><th>صفحات<br>Pages</th><th>موضوعات اصلی / Main topics</th></tr></thead><tbody>{''.join(group_rows)}</tbody></table>
  <h2 class="index-heading">فهرست کامل جلسات / Complete session table</h2>
  <table class="session-table"><thead><tr><th>#</th><th>عنوان جلسه / Session title</th><th>صفحات منبع<br>Source</th><th>صفحات کتاب<br>Printed</th><th>تمرکز مطالعه / Study focus</th></tr></thead><tbody>{''.join(session_rows)}</tbody></table>
</section>
"""


def css(font_file: Path, font_bold_file: Path) -> str:
    return font_face_css(font_file, font_bold_file) + """
@page { size: A4 portrait; margin: 16mm 15mm 18mm 15mm; @bottom-center { content: counter(page); font-family: StudyArabic, StudyLatin; font-size: 8.5pt; color: #64748b; } }
html,body { margin:0; padding:0; }
*, *::before, *::after { box-sizing:border-box; }
body { font-family: StudyArabic, StudyLatin; font-size: 10pt; line-height:1.48; color:#172033; overflow-wrap:anywhere; }
body,p,li,td,th,blockquote,h1,h2,h3,h4 { unicode-bidi: plaintext; }
.study-index-title { bookmark-level:1; bookmark-label:"Study Index / فهرست مطالعه"; font-size:23pt; margin:0 0 4pt; padding-bottom:8pt; border-bottom:3px solid #2563eb; color:#0f3a66; }
.course-title { font-size:15pt; font-weight:700; margin:7pt 0 13pt; color:#334155; }
.stats { display:flex; gap:7pt; margin:8pt 0 12pt; }
.stats div { flex:1; min-width:0; background:#eff6ff; border:1px solid #bfdbfe; border-radius:7pt; padding:7pt 6pt; text-align:center; }
.stats strong { display:block; font-size:14pt; color:#0f3a66; }
.stats span { display:block; font-size:7.4pt; color:#475569; }
.index-note { background:#f8fafc; border:1px solid #dbe4ee; border-right:4px solid #60a5fa; border-radius:6pt; padding:8pt 10pt; margin:10pt 0 13pt; font-size:9pt; }
.index-heading { bookmark-level:none; font-size:13.5pt; color:#0f3a66; margin:14pt 0 6pt; border-right:5px solid #60a5fa; padding-right:8pt; }
.group-bookmark { bookmark-level:2; font-size:10pt; color:#2563eb; background:#eff6ff; border-radius:6pt; padding:5pt 8pt; margin:0 0 7pt; }
.session-title { bookmark-level:3; font-size:18pt; color:#0f3a66; border-bottom:2.5px solid #2563eb; padding-bottom:7pt; margin:0 0 11pt; }
h1,h2,h3,h4 { bookmark-level:none; font-family:StudyArabic,StudyLatin; color:#123b66; break-after:avoid; page-break-after:avoid; orphans:3; widows:3; }
h2 { font-size:14pt; margin:16pt 0 7pt; border-left:4px solid #60a5fa; padding-left:8pt; }
h3 { font-size:11.8pt; margin:11pt 0 4pt; }
h4 { font-size:10.6pt; margin:9pt 0 3pt; }
p { margin:3.2pt 0; }
ul,ol { margin-top:5pt; margin-bottom:7pt; padding-inline-start:18pt; }
ul { list-style-type:disc; }
ul ul { list-style-type:circle; }
ul ul ul { list-style-type:disc; }
li { margin:2.7pt 0; }
.session-note { break-before:page; page-break-before:always; }
table { width:100%; table-layout:fixed; border-collapse:collapse; margin:8pt 0 11pt; font-size:8.1pt; }
thead { display:table-header-group; }
tr { break-inside:avoid; page-break-inside:avoid; }
th,td { border:1px solid #dbe4ee; padding:4.2pt; vertical-align:top; overflow-wrap:anywhere; word-break:break-word; }
th { background:#eff6ff; color:#0f3a66; font-weight:700; }
.num { text-align:center; direction:ltr; white-space:nowrap; }
.group-table th:nth-child(1), .group-table td:nth-child(1) { width:22%; }
.group-table th:nth-child(2), .group-table td:nth-child(2) { width:10%; }
.group-table th:nth-child(3), .group-table td:nth-child(3) { width:11%; }
.group-table th:nth-child(4), .group-table td:nth-child(4) { width:57%; }
.session-table { font-size:7.1pt; }
.session-table th,.session-table td { padding:3.5pt; }
.session-table th:nth-child(1), .session-table td:nth-child(1) { width:4%; }
.session-table th:nth-child(2), .session-table td:nth-child(2) { width:25%; }
.session-table th:nth-child(3), .session-table td:nth-child(3) { width:9%; }
.session-table th:nth-child(4), .session-table td:nth-child(4) { width:9%; }
.session-table th:nth-child(5), .session-table td:nth-child(5) { width:53%; }
.session-cell a { font-weight:700; color:#1d4ed8; text-decoration:none; }
.group-mini { margin-top:1.5pt; color:#64748b; font-size:6.3pt; }
.focus { line-height:1.32; }
blockquote { margin:9pt 0; padding:7pt 10pt; background:#f8fafc; border-left:4px solid #dbe4ee; break-inside:avoid; }
pre,code { font-family:StudyLatin,StudyArabic; direction:ltr; unicode-bidi:isolate; }
code { background:#eef2f7; padding:1pt 3pt; border-radius:3pt; font-size:8.7pt; }
pre { white-space:pre-wrap; overflow-wrap:anywhere; background:#eef2f7; padding:7pt 9pt; border-radius:5pt; break-inside:avoid; }
img,svg { max-width:100%; height:auto; break-inside:avoid; }
.key-points,.warning-box { break-inside:avoid; page-break-inside:avoid; border-radius:7pt; padding:8.5pt 10pt; margin:12pt 0; }
.key-points { background:#dbeafe; border:1.3px solid #60a5fa; }
.warning-box { background:#fff7ed; border:1.3px solid #fb923c; }
.key-points h2,.warning-box h2 { margin-top:0; border:0; padding:0; font-size:13pt; }
"""


def build_html(model: StudyIndex, font_file: Path, font_bold_file: Path) -> str:
    parts = [build_index_html(model)]
    previous_group = None
    for session in model.sessions:
        raw = session.note_path.read_text(encoding="utf-8")
        actual_title, rest = strip_first_h1(raw)
        title = actual_title or session.title
        group = ""
        if session.group != previous_group:
            group = f"<h2 class='group-bookmark'>{escape(session.group)}</h2>"
            previous_group = session.group
        parts.append(
            f"<section class='session-note'>{group}<h1 class='session-title' id='{escape(session.destination)}'>{session.order:02d}. {escape(title)}</h1>{note_html(rest)}</section>"
        )
    return f"<!doctype html><html lang='en' dir='auto'><head><meta charset='utf-8'><title>{escape(model.title)}</title><style>{css(font_file,font_bold_file)}</style></head><body>{''.join(parts)}</body></html>"


def set_page_labels(source: Path, output: Path) -> None:
    reader = PdfReader(source)
    writer = PdfWriter(clone_from=reader)
    writer.set_page_label(0, len(reader.pages)-1, style=PageLabelStyle.DECIMAL, start=1)
    writer.add_metadata({"/Title": reader.metadata.title or output.stem, "/Subject":"Combined study notes with clickable bilingual index"})
    with output.open("wb") as stream:
        writer.write(stream)


def create_combined(notes_dir: Path, pdf_dir: Path | None = None, output_path: Path | None = None, index_md: Path | None = None, *, title: str | None = None, font_file: Path, font_bold_file: Path, qc_report: Path | None = None, **_kwargs) -> Path:
    notes_dir = require_directory(notes_dir, "NOTES_DIR")
    font_file = require_readable_file(font_file, "FONT_FILE")
    font_bold_file = require_readable_file(font_bold_file, "FONT_BOLD_FILE")
    index_path = find_index_file(notes_dir, index_md)
    model = parse_index(index_path, notes_dir)
    if title:
        model.title = title
    output = Path(output_path or notes_dir / "FINAL_STUDY_NOTES.pdf").resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    html_doc = build_html(model, font_file, font_bold_file)
    with tempfile.TemporaryDirectory() as tmp:
        raw_pdf = Path(tmp) / "raw.pdf"
        HTML(string=html_doc, base_url=str(notes_dir)).write_pdf(raw_pdf)
        set_page_labels(raw_pdf, output)
    from verify_final_pdf import verify_pdf
    report = verify_pdf(output, model, font_file=font_file, font_bold_file=font_bold_file)
    report_path = Path(qc_report or output.with_suffix(".qc.txt")).resolve()
    report_path.write_text(report["text"], encoding="utf-8")
    print(report["text"])
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the final Study Notes PDF")
    parser.add_argument("--notes-dir", required=True)
    parser.add_argument("--pdf-dir")
    parser.add_argument("--output", required=True)
    parser.add_argument("--index-md")
    parser.add_argument("--title")
    parser.add_argument("--font-file", required=True)
    parser.add_argument("--font-bold-file", required=True)
    parser.add_argument("--qc-report")
    parser.add_argument("--css")
    args = parser.parse_args()
    create_combined(Path(args.notes_dir), Path(args.pdf_dir) if args.pdf_dir else None, Path(args.output), Path(args.index_md) if args.index_md else None, title=args.title, font_file=Path(args.font_file), font_bold_file=Path(args.font_bold_file), qc_report=Path(args.qc_report) if args.qc_report else None)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
