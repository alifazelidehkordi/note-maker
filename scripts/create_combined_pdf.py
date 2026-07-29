#!/usr/bin/env python3
"""Create the final portrait A4 study PDF in the reference-book visual style."""
from __future__ import annotations

import argparse
import re
import tempfile
from pathlib import Path

import mistune
from pypdf import PdfReader, PdfWriter
from pypdf.constants import PageLabelStyle
from weasyprint import HTML

from pdf_common import (
    StudyIndex,
    escape,
    find_index_file,
    normalize_visual_glyphs,
    parse_index,
    require_directory,
    require_readable_file,
)

MARKDOWN = mistune.create_markdown(
    escape=False,
    plugins=["table", "footnotes", "strikethrough", "task_lists", "url"],
)


def strip_first_h1(text: str) -> tuple[str, str]:
    match = re.search(r"(?m)^#\s+(.+?)\s*$", text)
    if not match:
        return "", text
    return match.group(1).strip(), text[: match.start()] + text[match.end() :]


def note_html(text: str) -> str:
    rendered = MARKDOWN(normalize_visual_glyphs(text))
    rendered = re.sub(
        r"(<h2[^>]*>\s*(?:Key Points|نکات کلیدی|Summary)\s*</h2>)(.*?)(?=<h2|$)",
        r'<div class="key-points">\1\2</div>',
        rendered,
        flags=re.I | re.S,
    )
    rendered = re.sub(
        r"(<h2[^>]*>\s*(?:Warnings?|هشدارها?|Pitfalls?|Common mistakes)\s*</h2>)(.*?)(?=<h2|$)",
        r'<div class="warning-box">\1\2</div>',
        rendered,
        flags=re.I | re.S,
    )
    return rendered


def source_range(items) -> str:
    first = re.findall(r"\d+", items[0].pdf_pages)
    last = re.findall(r"\d+", items[-1].pdf_pages)
    return f"{first[0]}-{last[-1]}" if first and last else "-"


def session_span(items) -> str:
    first, last = items[0].order, items[-1].order
    return str(first) if first == last else f"{first}-{last}"


def short_header(title: str, limit: int = 78) -> str:
    title = re.sub(r"\s+", " ", title).strip()
    return title if len(title) <= limit else title[: limit - 1].rstrip() + "…"


def build_index_html(model: StudyIndex) -> str:
    group_rows: list[str] = []
    for number, (group, items) in enumerate(model.groups, 1):
        group_rows.append(
            "<tr>"
            f"<td class='num'>{number}</td>"
            f"<td class='group-name'>{escape(group)}</td>"
            f"<td class='num'>{escape(session_span(items))}</td>"
            f"<td class='num'>{escape(source_range(items))}</td>"
            f"<td class='num'>{len(items)}</td>"
            "</tr>"
        )

    session_rows: list[str] = []
    for item in model.sessions:
        session_rows.append(
            "<tr>"
            f"<td class='num'>{item.order}</td>"
            f"<td class='session-cell'><a href='#{escape(item.destination)}'>{escape(item.title)}</a></td>"
            f"<td class='num'>{escape(item.pdf_pages)}</td>"
            f"<td class='num'>{escape(item.book_pages)}</td>"
            f"<td class='num'>{escape(item.duration)}</td>"
            f"<td class='focus'>{escape(item.focus)}</td>"
            "</tr>"
        )

    source_pages = model.physical_pages
    if not re.search(r"\d", source_pages):
        numbers = [int(x) for x in re.findall(r"\d+", model.coverage)]
        source_pages = str(max(numbers)) if numbers else model.coverage

    return f"""
<section class="study-index" id="study-index">
  <span class="book-string">{escape(model.title.upper())}</span>
  <h1 class="study-index-title"><span dir="rtl">فهرست مطالعه</span><span class="title-slash">/</span><span>Study Index</span></h1>

  <div class="hero-card">
    <div class="hero-kicker">{escape(model.title.upper())} · STUDY BOOK</div>
    <div class="hero-title">{escape(model.title)}</div>
    <div class="hero-subtitle" dir="rtl">فهرست یکپارچه‌ی جلسات با لینک داخلی، بوکمارک سلسله‌مراتبی و شماره‌گذاری پیوسته</div>
    <div class="hero-stats">
      <div class="hero-stat"><strong>{len(model.sessions)}</strong><span>جلسه / Sessions</span></div>
      <div class="hero-stat"><strong>{len(model.groups)}</strong><span>فصل / Groups</span></div>
      <div class="hero-stat"><strong>{escape(source_pages)}</strong><span>صفحات منبع / Source pages</span></div>
    </div>
  </div>

  <div class="index-guide" dir="rtl">
    <div class="guide-title">راهنمای استفاده</div>
    <div class="guide-text">عنوان هر جلسه در جدول زیر قابل کلیک است و مستقیماً به نخستین صفحه‌ی همان جلسه منتقل می‌شود. بوکمارک‌های PDF نیز فصل‌ها و جلسات را به همان ترتیب نمایش می‌دهند.</div>
  </div>

  <h2 class="index-heading"><span dir="rtl">فصل‌ها و گروه‌ها</span><span class="heading-slash">/</span><span>Chapters and Groups</span></h2>
  <table class="group-table">
    <thead><tr><th>#</th><th>فصل / Group</th><th>جلسات / Sessions</th><th>صفحات منبع / Source pages</th><th>تعداد / Count</th></tr></thead>
    <tbody>{''.join(group_rows)}</tbody>
  </table>

  <h2 class="index-heading session-index-heading"><span dir="rtl">جدول کامل جلسات</span><span class="heading-slash">/</span><span>Complete Session Table</span></h2>
  <table class="session-table">
    <thead><tr><th>#</th><th>عنوان جلسه / Session title</th><th>صفحات منبع / Source</th><th>صفحات کتاب / Book</th><th>زمان / Time</th><th>تمرکز مطالعه / Study focus</th></tr></thead>
    <tbody>{''.join(session_rows)}</tbody>
  </table>
</section>
"""


def font_css(latin_regular: Path, latin_bold: Path, arabic_regular: Path) -> str:
    lr = require_readable_file(latin_regular, "LATIN_REGULAR").as_uri()
    lb = require_readable_file(latin_bold, "LATIN_BOLD").as_uri()
    ar = require_readable_file(arabic_regular, "ARABIC_REGULAR").as_uri()
    return f"""
@font-face {{ font-family: StudyLatin; src: url('{lr}'); font-style: normal; font-weight: 400; }}
@font-face {{ font-family: StudyLatin; src: url('{lb}'); font-style: normal; font-weight: 600 900; }}
@font-face {{ font-family: StudyArabic; src: url('{ar}'); font-style: normal; font-weight: 400 900; }}
"""


def css(latin_regular: Path, latin_bold: Path, arabic_regular: Path) -> str:
    return font_css(latin_regular, latin_bold, arabic_regular) + r"""
:root {
  --ink: #17263a;
  --blue: #124274;
  --blue-2: #1f6eac;
  --line: #2b78bd;
  --soft-line: #b7cce0;
  --pale: #edf5fd;
  --pale-2: #f5f9fd;
  --muted: #5d7189;
}

@page index {
  size: A4 portrait;
  margin: 17mm 15mm 18mm 15mm;
  @top-left {
    content: string(book-title);
    font-family: StudyLatin, StudyArabic;
    font-size: 6.8pt;
    letter-spacing: .16em;
    color: #6a7f97;
    text-transform: uppercase;
  }
  @top-right {
    content: "Study Index / فهرست مطالعه";
    font-family: StudyLatin, StudyArabic;
    font-size: 6.8pt;
    color: #6a7f97;
  }
  @bottom-center {
    content: counter(page);
    font-family: StudyLatin, StudyArabic;
    font-size: 8pt;
    color: #52677f;
  }
}
@page index:first {
  @top-left { content: none; }
  @top-right { content: none; }
}
@page notes {
  size: A4 portrait;
  margin: 17mm 15mm 18mm 15mm;
  @top-left {
    content: string(book-title);
    font-family: StudyLatin, StudyArabic;
    font-size: 6.8pt;
    letter-spacing: .16em;
    color: #6a7f97;
    text-transform: uppercase;
  }
  @top-right {
    content: string(running-session, first);
    font-family: StudyLatin, StudyArabic;
    font-size: 6.8pt;
    color: #6a7f97;
  }
  @bottom-center {
    content: counter(page);
    font-family: StudyLatin, StudyArabic;
    font-size: 8pt;
    color: #52677f;
  }
}

html, body { margin: 0; padding: 0; }
*, *::before, *::after { box-sizing: border-box; }
body {
  font-family: StudyLatin, StudyArabic;
  font-size: 9.35pt;
  line-height: 1.43;
  color: var(--ink);
  overflow-wrap: anywhere;
  font-weight: 400;
}
body, p, li, td, th, blockquote, h1, h2, h3, h4 { unicode-bidi: plaintext; }
[dir="rtl"], :lang(fa) { font-family: StudyArabic, StudyLatin; }
.book-string {
  string-set: book-title content();
  position: absolute;
  width: 0;
  height: 0;
  overflow: hidden;
  color: transparent;
}

/* Study index */
.study-index { page: index; }
.study-index-title {
  bookmark-level: 1;
  bookmark-label: "Study Index / فهرست مطالعه";
  display: flex;
  align-items: baseline;
  gap: 8pt;
  margin: 0 0 10pt;
  padding: 0 0 8pt;
  border-bottom: 2.2px solid var(--line);
  color: var(--blue);
  font-size: 21pt;
  font-weight: 400;
  line-height: 1.15;
}
.study-index-title [dir="rtl"] { font-weight: 700; }
.title-slash, .heading-slash { color: var(--blue); font-weight: 400; }
.hero-card {
  height: 224pt;
  border-radius: 10pt;
  padding: 42pt 34pt 30pt;
  margin: 0 0 30pt;
  color: white;
  background: linear-gradient(135deg, #123c6b 0%, #1d5f97 58%, #226fac 100%);
  break-inside: avoid;
}
.hero-kicker {
  font-size: 8pt;
  letter-spacing: .035em;
  opacity: .96;
  margin-bottom: 12pt;
}
.hero-title {
  font-size: 24pt;
  line-height: 1.1;
  font-weight: 400;
  margin-bottom: 14pt;
}
.hero-subtitle {
  font-size: 10pt;
  opacity: .96;
  margin-bottom: 21pt;
}
.hero-stats { display: flex; gap: 9pt; direction: ltr; }
.hero-stat {
  flex: 1;
  min-width: 0;
  height: 68pt;
  padding: 11pt 10pt;
  border: 1px solid rgba(255,255,255,.38);
  border-radius: 6pt;
  background: rgba(11,45,80,.10);
}
.hero-stat strong {
  display: block;
  font-size: 18pt;
  line-height: 1.05;
  font-weight: 400;
  color: white;
  margin-bottom: 7pt;
}
.hero-stat span { display: block; font-size: 7.5pt; color: white; }
.index-guide {
  position: relative;
  min-height: 71pt;
  padding: 18pt 18pt 14pt 20pt;
  margin: 0 0 14pt;
  background: #f0f6fc;
  border-right: 4px solid #2d7fc3;
  color: #1b3048;
}
.index-guide::before {
  content: "";
  position: absolute;
  left: 11pt;
  top: 22pt;
  width: 4px;
  height: 18pt;
  background: #84bceb;
}
.guide-title {
  font-size: 14pt;
  line-height: 1.2;
  font-weight: 700;
  color: var(--blue);
  margin-bottom: 7pt;
}
.guide-text { font-size: 8.5pt; line-height: 1.5; }
.index-heading {
  bookmark-level: none;
  display: flex;
  align-items: baseline;
  gap: 5pt;
  position: relative;
  font-size: 13.3pt;
  font-weight: 400;
  line-height: 1.25;
  color: var(--blue);
  margin: 13pt 0 7pt;
  padding-left: 10pt;
}
.index-heading [dir="rtl"] { font-weight: 700; }
.index-heading::before {
  content: "";
  position: absolute;
  left: 0;
  top: 1pt;
  width: 4px;
  height: 18pt;
  background: #82b9e7;
}
.session-index-heading { margin-top: 16pt; }

table {
  width: 100%;
  table-layout: fixed;
  border-collapse: collapse;
  margin: 6pt 0 10pt;
}
thead { display: table-header-group; }
tr { break-inside: avoid; page-break-inside: avoid; }
th, td {
  border: .65px solid var(--soft-line);
  padding: 3.2pt 4pt;
  vertical-align: top;
  overflow-wrap: anywhere;
  word-break: normal;
}
th {
  background: #e8f1fa;
  color: var(--blue);
  font-weight: 700;
}
.num { text-align: center; direction: ltr; white-space: nowrap; }
.group-table { font-size: 7.05pt; line-height: 1.22; }
.group-table th, .group-table td { padding-top: 3pt; padding-bottom: 3pt; }
.group-table th:nth-child(1), .group-table td:nth-child(1) { width: 5%; }
.group-table th:nth-child(2), .group-table td:nth-child(2) { width: 42%; }
.group-table th:nth-child(3), .group-table td:nth-child(3) { width: 16%; }
.group-table th:nth-child(4), .group-table td:nth-child(4) { width: 23%; }
.group-table th:nth-child(5), .group-table td:nth-child(5) { width: 14%; }
.group-name { color: #1d2f45; }
.session-table { font-size: 6.55pt; line-height: 1.28; }
.session-table th, .session-table td { padding: 3pt 3.4pt; }
.session-table th:nth-child(1), .session-table td:nth-child(1) { width: 4%; }
.session-table th:nth-child(2), .session-table td:nth-child(2) { width: 22%; }
.session-table th:nth-child(3), .session-table td:nth-child(3) { width: 9%; }
.session-table th:nth-child(4), .session-table td:nth-child(4) { width: 8%; }
.session-table th:nth-child(5), .session-table td:nth-child(5) { width: 11%; }
.session-table th:nth-child(6), .session-table td:nth-child(6) { width: 46%; }
.session-cell a {
  color: #2a6da5;
  text-decoration: none;
  font-weight: 600;
}
.focus { color: #273a50; }

/* Session pages */
.session-note {
  page: notes;
  break-before: page;
  page-break-before: always;
}
.running-session {
  string-set: running-session content();
  position: absolute;
  width: 0;
  height: 0;
  overflow: hidden;
  color: transparent;
}
.session-group {
  font-size: 9.2pt;
  color: #356a9b;
  margin: 0 0 9pt;
  line-height: 1.2;
}
.group-bookmark {
  bookmark-level: 2;
  bookmark-label: attr(data-bookmark);
}
.session-meta {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  align-items: center;
  min-height: 23pt;
  border: .65px solid #c4d8eb;
  background: #f7fafd;
  color: #5a718a;
  font-size: 7.4pt;
  margin-bottom: 11pt;
  padding: 0 8pt;
  direction: ltr;
}
.session-meta span:nth-child(1) { text-align: left; }
.session-meta span:nth-child(2) { text-align: center; }
.session-meta span:nth-child(3) { text-align: right; }
.session-title {
  bookmark-level: 3;
  bookmark-label: attr(data-bookmark);
  string-set: none;
  color: var(--blue);
  font-size: 18.4pt;
  font-weight: 400;
  line-height: 1.16;
  margin: 0 0 12pt;
  padding: 0 0 7pt;
  border-bottom: 2.2px solid var(--line);
}
h1, h2, h3, h4 {
  font-family: StudyLatin, StudyArabic;
  color: var(--blue);
  break-after: avoid;
  page-break-after: avoid;
  orphans: 3;
  widows: 3;
  bookmark-level: none;
}
h2 {
  position: relative;
  font-size: 13.8pt;
  line-height: 1.22;
  font-weight: 400;
  margin: 16pt 0 8pt;
  padding-left: 10pt;
  border: 0;
}
h2::before {
  content: "";
  position: absolute;
  left: 0;
  top: 1pt;
  width: 4px;
  height: 18pt;
  background: #82b9e7;
}
h3 {
  font-size: 11.2pt;
  line-height: 1.28;
  font-weight: 400;
  margin: 11pt 0 4pt;
}
h4 {
  font-size: 10.1pt;
  line-height: 1.3;
  font-weight: 600;
  margin: 9pt 0 3pt;
}
p { margin: 4.1pt 0; }
strong, b { color: #0f4c80; font-weight: 700; }
em { color: inherit; }
ul, ol {
  margin-top: 5pt;
  margin-bottom: 8pt;
  padding-inline-start: 21pt;
}
ul { list-style-type: disc; }
ul ul { list-style-type: circle; }
ul ul ul { list-style-type: disc; }
li { margin: 2.4pt 0; }
li > p { margin: 1.5pt 0; }
.session-note table { font-size: 8.15pt; line-height: 1.3; margin: 8pt 0 12pt; }
.session-note th, .session-note td { padding: 4.5pt 5pt; }
.session-note th { background: #e8f1fa; font-weight: 400; }
blockquote {
  margin: 10pt 0;
  padding: 8pt 10pt;
  background: #f4f8fc;
  border-left: 4px solid #a7c9e7;
  break-inside: avoid;
}
pre, code {
  font-family: StudyLatin, StudyArabic;
  direction: ltr;
  unicode-bidi: isolate;
}
code {
  background: #eef3f8;
  padding: 1pt 3pt;
  border-radius: 2pt;
  font-size: 8.4pt;
}
pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  background: #eef3f8;
  padding: 8pt 10pt;
  border-radius: 5pt;
  break-inside: avoid;
}
img, svg {
  max-width: 100%;
  height: auto;
  break-inside: avoid;
}
.key-points, .warning-box {
  break-inside: avoid;
  page-break-inside: avoid;
  border-radius: 7pt;
  padding: 15pt 15pt 13pt;
  margin: 14pt 0;
}
.key-points {
  background: #eaf4ff;
  border: 1.2px solid #5daaf0;
}
.warning-box {
  background: #fff7ed;
  border: 1.2px solid #eaa15e;
}
.key-points h2, .warning-box h2 {
  margin: 0 0 8pt;
  padding-left: 10pt;
  font-size: 13.4pt;
}
.key-points ul, .warning-box ul { margin-bottom: 0; }
.key-points strong, .key-points b { color: inherit; font-weight: 400; }
"""


def build_html(
    model: StudyIndex,
    latin_regular: Path,
    latin_bold: Path,
    arabic_regular: Path,
) -> str:
    parts = [build_index_html(model)]
    previous_group: str | None = None
    for session in model.sessions:
        raw = session.note_path.read_text(encoding="utf-8")
        actual_title, rest = strip_first_h1(raw)
        title = actual_title or session.title
        group_class = "session-group"
        bookmark_attr = ""
        if session.group != previous_group:
            group_class += " group-bookmark"
            bookmark_attr = f" data-bookmark='{escape(session.group)}'"
            previous_group = session.group
        bookmark_title = f"{session.order:02d}. {title}"
        parts.append(
            f"""
<section class="session-note">
  <span class="running-session">{escape(short_header(title))}</span>
  <div class="{group_class}"{bookmark_attr}>{escape(session.group)}</div>
  <div class="session-meta"><span>Session {session.order:02d}</span><span>Source pages {escape(session.pdf_pages)}</span><span>{escape(session.duration)}</span></div>
  <h1 class="session-title" id="{escape(session.destination)}" data-bookmark="{escape(bookmark_title)}">{escape(title)}</h1>
  {note_html(rest)}
</section>
"""
        )
    return (
        "<!doctype html><html lang='en' dir='auto'><head><meta charset='utf-8'>"
        f"<title>{escape(model.title)} - Final Study Notes</title>"
        f"<style>{css(latin_regular, latin_bold, arabic_regular)}</style>"
        f"</head><body>{''.join(parts)}</body></html>"
    )


def set_page_labels(source: Path, output: Path, title: str) -> None:
    reader = PdfReader(source)
    writer = PdfWriter(clone_from=reader)
    writer.set_page_label(0, len(reader.pages) - 1, style=PageLabelStyle.DECIMAL, start=1)
    writer.add_metadata(
        {
            "/Title": f"{title} - Final Study Notes",
            "/Subject": "Combined study notes with clickable bilingual index",
        }
    )
    writer.page_mode = "/UseOutlines"
    with output.open("wb") as stream:
        writer.write(stream)


def create_combined(
    notes_dir: Path,
    pdf_dir: Path | None = None,
    output_path: Path | None = None,
    index_md: Path | None = None,
    *,
    title: str | None = None,
    font_file: Path,
    font_bold_file: Path,
    latin_regular_file: Path | None = None,
    latin_bold_file: Path | None = None,
    arabic_regular_file: Path | None = None,
    qc_report: Path | None = None,
    debug_html: Path | None = None,
    **_kwargs,
) -> Path:
    """Build and strictly verify the final combined PDF.

    ``FONT_FILE`` and ``FONT_BOLD_FILE`` remain the compatibility inputs. The
    optional Latin/Arabic paths allow the supplied multi-font family to match
    the reference layout more closely without introducing system fallbacks.
    """
    del pdf_dir
    notes_dir = require_directory(Path(notes_dir), "NOTES_DIR")
    index_path = find_index_file(notes_dir, Path(index_md) if index_md else None)
    model = parse_index(index_path, notes_dir)
    if title:
        model.title = title

    compatibility_regular = require_readable_file(Path(font_file), "FONT_FILE")
    compatibility_bold = require_readable_file(Path(font_bold_file), "FONT_BOLD_FILE")
    latin_regular = require_readable_file(
        Path(latin_regular_file or compatibility_regular), "LATIN_REGULAR_FILE"
    )
    latin_bold = require_readable_file(
        Path(latin_bold_file or compatibility_bold), "LATIN_BOLD_FILE"
    )
    arabic_regular = require_readable_file(
        Path(arabic_regular_file or compatibility_regular), "ARABIC_REGULAR_FILE"
    )

    output = Path(output_path or notes_dir / "FINAL_STUDY_NOTES.pdf").resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    html_doc = build_html(model, latin_regular, latin_bold, arabic_regular)
    if debug_html:
        debug_path = Path(debug_html).resolve()
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        debug_path.write_text(html_doc, encoding="utf-8")

    with tempfile.TemporaryDirectory() as tmp:
        raw_pdf = Path(tmp) / "raw.pdf"
        HTML(string=html_doc, base_url=str(notes_dir)).write_pdf(raw_pdf)
        set_page_labels(raw_pdf, output, model.title)

    from verify_final_pdf import verify_pdf

    report = verify_pdf(
        output,
        model,
        font_file=arabic_regular,
        font_bold_file=latin_bold,
    )
    report_path = Path(qc_report or output.with_suffix(".qc.txt")).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report["text"], encoding="utf-8")
    print(report["text"])
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the final styled Study Notes PDF")
    parser.add_argument("--notes-dir", required=True)
    parser.add_argument("--pdf-dir")
    parser.add_argument("--index-md")
    parser.add_argument("--output", required=True)
    parser.add_argument("--qc-report")
    parser.add_argument("--title")
    parser.add_argument("--font-file", required=True)
    parser.add_argument("--font-bold-file", required=True)
    parser.add_argument("--latin-regular-file")
    parser.add_argument("--latin-bold-file")
    parser.add_argument("--arabic-regular-file")
    parser.add_argument("--debug-html")
    parser.add_argument("--css", help="Accepted for backward compatibility; built-in reference styling is used")
    args = parser.parse_args()

    create_combined(
        Path(args.notes_dir),
        Path(args.pdf_dir) if args.pdf_dir else None,
        Path(args.output),
        Path(args.index_md) if args.index_md else None,
        title=args.title,
        font_file=Path(args.font_file),
        font_bold_file=Path(args.font_bold_file),
        latin_regular_file=Path(args.latin_regular_file) if args.latin_regular_file else None,
        latin_bold_file=Path(args.latin_bold_file) if args.latin_bold_file else None,
        arabic_regular_file=Path(args.arabic_regular_file) if args.arabic_regular_file else None,
        qc_report=Path(args.qc_report) if args.qc_report else None,
        debug_html=Path(args.debug_html) if args.debug_html else None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
