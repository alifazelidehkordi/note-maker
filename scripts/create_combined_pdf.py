#!/usr/bin/env python3
"""Create one final A4 portrait study book with index, links, and bookmarks.

Unlike the legacy merger, this implementation lays out the rich Index and every
Markdown session in one WeasyPrint document. Internal anchors therefore resolve
after pagination, bookmarks naturally target the true first page of each
session, and one CSS page counter numbers the complete book continuously.
"""
from __future__ import annotations

import argparse
import html
import sys
from pathlib import Path

try:
    from weasyprint import HTML
except (ModuleNotFoundError, OSError) as exc:  # pragma: no cover
    HTML = None
    _WEASYPRINT_ERROR = exc
else:
    _WEASYPRINT_ERROR = None

from pdf_utils import (
    FontBundle,
    PipelineError,
    StudyIndexData,
    StudySession,
    build_document_css,
    find_index_file,
    html_escape,
    load_font_bundle,
    markdown_to_html,
    parse_study_index,
    strip_first_h1,
)
from quality_check_pdf import run_quality_checks


def _require_renderer() -> None:
    if HTML is None:
        detail = f": {_WEASYPRINT_ERROR}" if _WEASYPRINT_ERROR else ""
        raise PipelineError(f"WeasyPrint is required to create the final PDF{detail}")


def _index_html(data: StudyIndexData) -> str:
    source_card = data.source_coverage
    physical_detail = (
        f" · {data.physical_source_pages} physical source pages"
        if data.physical_source_pages is not None
        else ""
    )
    group_rows = []
    for number, group in enumerate(data.groups, 1):
        group_rows.append(
            "<tr>"
            f"<td>{number}</td>"
            f"<td>{html_escape(group.title)}</td>"
            f"<td>{html_escape(group.number_span)}</td>"
            f"<td>{html_escape(group.source_span)}</td>"
            f"<td>{html_escape(group.book_span)}</td>"
            f"<td>{len(group.sessions)}</td>"
            "</tr>"
        )

    session_rows = []
    for session in data.sessions:
        session_rows.append(
            "<tr>"
            f"<td>{session.number}</td>"
            f'<td><a class="session-link" href="#{session.anchor}">{html_escape(session.title)}</a></td>'
            f"<td>{html_escape(session.source_pages)}</td>"
            f"<td>{html_escape(session.book_pages)}</td>"
            f"<td>{html_escape(session.duration)}</td>"
            f"<td>{html_escape(session.study_focus)}</td>"
            "</tr>"
        )

    return f"""
<section class="index" id="study-index">
  <h1 class="index-title">فهرست مطالعه / Study Index</h1>
  <div class="hero">
    <p class="hero-kicker">STUDY BOOK · INTEGRATED EDITION</p>
    <h2 class="hero-title">{html_escape(data.course_title)}</h2>
    <p class="hero-subtitle" dir="rtl">
      فهرست یکپارچه با لینک داخلی، بوکمارک سلسله‌مراتبی، صفحه‌آرایی عمودی و شماره‌گذاری پیوسته
    </p>
    <div class="stat-grid">
      <div class="stat-card"><span class="stat-number">{len(data.sessions)}</span><span class="stat-label">جلسه / Sessions</span></div>
      <div class="stat-card"><span class="stat-number">{len(data.groups)}</span><span class="stat-label">فصل / Groups</span></div>
      <div class="stat-card"><span class="stat-number">{html_escape(source_card)}</span><span class="stat-label">صفحات منبع / Source pages</span></div>
    </div>
  </div>

  <aside class="guide-box" dir="rtl">
    <h2 class="guide-title">راهنمای استفاده / How to use</h2>
    <p>عنوان هر جلسه در جدول کامل قابل کلیک است و مستقیماً به نخستین صفحه‌ی همان جلسه منتقل می‌شود.</p>
    <p dir="ltr">Every session title in the complete table links to the exact first page of that session. PDF bookmarks follow the same group and session order.</p>
  </aside>

  <h2 class="index-section-title">فصل‌ها و گروه‌ها / Chapters and Groups</h2>
  <p class="index-note">Source coverage: {html_escape(data.source_coverage)} · Book/printed coverage: {html_escape(data.book_coverage)}{html_escape(physical_detail)} · Estimated study time: {html_escape(data.total_study_time)}</p>
  <table class="groups-table">
    <colgroup><col class="c-num"><col class="c-group"><col class="c-sessions"><col class="c-source"><col class="c-book"><col class="c-count"></colgroup>
    <thead><tr>
      <th>#</th><th>فصل / Group</th><th>جلسات / Sessions</th><th>صفحات منبع / Source</th><th>صفحات کتاب / Book</th><th>تعداد / Count</th>
    </tr></thead>
    <tbody>{''.join(group_rows)}</tbody>
  </table>

  <div class="page-break"></div>
  <h2 class="index-section-title">جدول کامل جلسات / Complete Session Table</h2>
  <p class="index-note" dir="rtl">برای رفتن به جلسه، روی عنوان آن کلیک کنید. / Click a session title to jump to its first page.</p>
  <table class="sessions-table">
    <colgroup><col class="c-num"><col class="c-title"><col class="c-source"><col class="c-book"><col class="c-time"><col class="c-focus"></colgroup>
    <thead><tr>
      <th>#</th><th>عنوان جلسه / Session title</th><th>صفحات منبع / Source</th><th>صفحات کتاب / Book</th><th>زمان / Time</th><th>تمرکز مطالعه / Study focus</th>
    </tr></thead>
    <tbody>{''.join(session_rows)}</tbody>
  </table>
</section>
"""


def _session_html(session: StudySession, *, first_in_group: bool) -> str:
    body_md = strip_first_h1(session.note_path.read_text(encoding="utf-8", errors="strict"))
    body_html = markdown_to_html(body_md)
    group_class = "group-kicker" if first_in_group else "group-kicker repeat"
    second_meta = f"Source pages {html_escape(session.source_pages)}"
    if session.book_pages != "—":
        second_meta += f" · Book {html_escape(session.book_pages)}"
    return f"""
<section class="session" id="{session.anchor}">
  <h1 class="{group_class}">{html_escape(session.group)}</h1>
  <div class="session-meta">
    <span>Session {session.number:02d}</span>
    <span>{second_meta}</span>
    <span>{html_escape(session.duration)}</span>
  </div>
  <h2 class="session-title">{html_escape(session.title)}</h2>
  <div class="session-content">{body_html}</div>
</section>
"""


def build_combined_html(
    data: StudyIndexData,
    fonts: FontBundle,
    *,
    extra_css: str = "",
) -> str:
    css = build_document_css(fonts, data.course_title, extra_css)
    sessions_html: list[str] = []
    previous_group_number: int | None = None
    for session in data.sessions:
        sessions_html.append(
            _session_html(session, first_in_group=session.group_number != previous_group_number)
        )
        previous_group_number = session.group_number
    return f"""<!doctype html>
<html lang="en" dir="auto">
<head>
  <meta charset="utf-8">
  <meta name="author" content="note-maker">
  <meta name="description" content="Integrated study notes with clickable bilingual Study Index">
  <title>{html.escape(data.course_title)}</title>
  <style>{css}</style>
</head>
<body>
{_index_html(data)}
{''.join(sessions_html)}
</body>
</html>"""


def create_combined(
    notes_dir: Path,
    pdf_dir: Path | None = None,
    output_path: Path | None = None,
    index_md: Path | None = None,
    *,
    title: str | None = None,
    css_file: Path | None = None,
    continuous_page_numbers: bool = True,
    page_number_start: int = 1,
    font_file: str | Path | None = None,
    font_bold_file: str | Path | None = None,
    qa_report: Path | None = None,
) -> Path:
    """Build the complete book and fail if any acceptance-critical QA check fails."""
    del pdf_dir
    if not continuous_page_numbers or page_number_start != 1:
        raise PipelineError("The final book requires continuous page numbering beginning at 1")
    _require_renderer()
    notes_dir = Path(notes_dir).resolve()
    if not notes_dir.is_dir():
        raise FileNotFoundError(f"NOTES_DIR not found: {notes_dir}")
    index_path = find_index_file(notes_dir, index_md)
    data = parse_study_index(index_path, notes_dir)
    if title:
        data = StudyIndexData(
            course_title=title,
            sessions=data.sessions,
            groups=data.groups,
            source_coverage=data.source_coverage,
            book_coverage=data.book_coverage,
            physical_source_pages=data.physical_source_pages,
            total_study_time=data.total_study_time,
            index_path=data.index_path,
        )
    fonts = load_font_bundle(font_file, font_bold_file)
    extra_css = ""
    if css_file:
        css_file = Path(css_file).resolve()
        if not css_file.is_file():
            raise FileNotFoundError(f"CSS_FILE not found: {css_file}")
        extra_css = css_file.read_text(encoding="utf-8")

    output = (
        Path(output_path).resolve()
        if output_path
        else (notes_dir / "FINAL_STUDY_NOTES.pdf").resolve()
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    combined_html = build_combined_html(data, fonts, extra_css=extra_css)
    HTML(string=combined_html, base_url=str(notes_dir)).write_pdf(output)

    report_path = (
        Path(qa_report).resolve()
        if qa_report
        else output.with_name(output.stem + "_QA.json")
    )
    report = run_quality_checks(output, data, report_path=report_path, raise_on_failure=True)
    print(f"Final PDF: {output}")
    print(f"Total pages: {report['total_pages']}")
    print(f"Study Index pages: {report['study_index_pages']}")
    print(f"Sessions: {report['sessions']}")
    print(f"Groups: {report['groups']}")
    print(f"Converted internal links: {report['converted_internal_links']}")
    print(f"Unresolved links: {report['unresolved_links']}")
    print(f"Bookmarks: {report['bookmarks']}")
    print(f"Page number range: {report['page_number_range']}")
    print(f"Embedded fonts: {', '.join(report['embedded_fonts'])}")
    print("Page size: A4")
    print("Page orientation: Portrait")
    print(f"Portrait pages: {report['portrait_pages']}")
    print(f"Landscape pages: {report['landscape_pages']}")
    print(f"Rotated pages: {report['rotated_pages']}")
    print(f"Quality check: {report['quality_check']}")
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a final integrated A4 portrait study-book PDF"
    )
    parser.add_argument("--notes-dir", required=True)
    parser.add_argument("--pdf-dir", help="Accepted for compatibility; final book is rendered in one pass")
    parser.add_argument("--output")
    parser.add_argument("--index-md")
    parser.add_argument("--title")
    parser.add_argument("--css")
    parser.add_argument("--font-file", help="Overrides FONT_FILE")
    parser.add_argument("--font-bold-file", help="Overrides FONT_BOLD_FILE")
    parser.add_argument("--qa-report")
    parser.add_argument("--no-continuous-page-numbers", action="store_true")
    parser.add_argument("--page-number-start", type=int, default=1)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        create_combined(
            Path(args.notes_dir),
            Path(args.pdf_dir) if args.pdf_dir else None,
            Path(args.output) if args.output else None,
            Path(args.index_md) if args.index_md else None,
            title=args.title,
            css_file=Path(args.css) if args.css else None,
            continuous_page_numbers=not args.no_continuous_page_numbers,
            page_number_start=args.page_number_start,
            font_file=args.font_file,
            font_bold_file=args.font_bold_file,
            qa_report=Path(args.qa_report) if args.qa_report else None,
        )
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
