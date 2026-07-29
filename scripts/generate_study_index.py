#!/usr/bin/env python3
"""Parse the prepared Index and generate dynamic bilingual Study Index HTML."""
from __future__ import annotations

import argparse
import html
import re
from collections import OrderedDict
from pathlib import Path

from pdf_common import Session, first_h1, is_session_file, locate_index, natural_key, read_frontmatter

INDEX_H1_RE = re.compile(r"^#\s+(?:Index\s*[—:-]\s*)?(.+?)\s*$", re.M | re.I)
ENTRY_RE = re.compile(
    r"^###\s+(\d{1,3})\.\s+\[([^\]]+)\]\(([^)]+)\)\s*$"
    r"(.*?)(?=^###\s+\d{1,3}\.\s+\[|^##\s+Excluded pages|\Z)",
    re.M | re.S,
)
FIELD_RE = re.compile(r"^-\s+\*\*([^*]+):\*\*\s*(.*?)\s*$", re.M)
TOTAL_RE = re.compile(r"^-\s+\*\*Numbered study parts:\*\*\s*(\d+)", re.M | re.I)
OVERALL_RE = re.compile(r"^-\s+\*\*Total PDF pages:\*\*\s*([^\n]+)", re.M | re.I)


def _field_map(block: str) -> dict[str, str]:
    return {key.strip().casefold(): value.strip() for key, value in FIELD_RE.findall(block)}


def _note_map(notes_dir: Path) -> dict[str, Path]:
    files = [p for p in notes_dir.glob("*.md") if is_session_file(p)]
    result: dict[str, Path] = {}
    for path in files:
        result[path.name.casefold()] = path
        result[path.stem.casefold()] = path
    return result


def parse_index(index_path: Path, notes_dir: Path) -> tuple[str, str, list[Session]]:
    text = index_path.read_text(encoding="utf-8", errors="strict")
    title_match = INDEX_H1_RE.search(text)
    course_title = title_match.group(1).strip() if title_match else "Study Notes"
    overall_match = OVERALL_RE.search(text)
    overall_pages = overall_match.group(1).strip() if overall_match else "—"
    note_map = _note_map(notes_dir)
    sessions: list[Session] = []
    missing: list[str] = []

    for number_raw, title, target, block in ENTRY_RE.findall(text):
        number = int(number_raw)
        fields = _field_map(block)
        target_name = Path(target).name
        note = note_map.get(target_name.casefold()) or note_map.get(Path(target_name).stem.casefold())
        if note is None:
            candidates = sorted(notes_dir.glob(f"{number:02d}_*.md"), key=natural_key)
            candidates = [p for p in candidates if is_session_file(p)]
            note = candidates[0] if len(candidates) == 1 else None
        if note is None:
            missing.append(f"{number:02d}: {target}")
            continue

        meta = read_frontmatter(note)
        group = fields.get("major division") or str(meta.get("chapter_title_en") or meta.get("group") or "Study Sections")
        pdf_pages = fields.get("pdf pages") or str(meta.get("pdf_pages") or "—")
        book_pages = fields.get("book pages") or str(meta.get("book_pages") or "—")
        focus = fields.get("scope/objective") or str(meta.get("study_focus") or "—")
        duration = fields.get("approximate study time") or str(meta.get("duration") or "—")
        sessions.append(Session(
            number=number,
            title=title.strip() or first_h1(note),
            filename=note.name,
            stem=note.stem,
            group=group.strip(),
            pdf_pages=pdf_pages.strip(),
            book_pages=book_pages.strip(),
            study_focus=focus.strip(),
            duration=duration.strip(),
            note_path=note,
        ))

    if missing:
        raise RuntimeError("Index entries without matching note files: " + "; ".join(missing))
    sessions.sort(key=lambda s: s.number)
    expected = int(TOTAL_RE.search(text).group(1)) if TOTAL_RE.search(text) else len(sessions)
    if len(sessions) != expected:
        raise RuntimeError(f"Index/session count mismatch: index={expected}, parsed={len(sessions)}")
    numbers = [s.number for s in sessions]
    if len(numbers) != len(set(numbers)):
        raise RuntimeError("Duplicate session numbers in Index")
    if numbers != sorted(numbers):
        raise RuntimeError("Session order is not increasing")
    return course_title, overall_pages, sessions


def group_sessions(sessions: list[Session]) -> OrderedDict[str, list[Session]]:
    groups: OrderedDict[str, list[Session]] = OrderedDict()
    for session in sessions:
        groups.setdefault(session.group, []).append(session)
    return groups


def build_study_index_html(course_title: str, overall_pages: str, sessions: list[Session]) -> str:
    groups = group_sessions(sessions)
    esc = html.escape
    group_rows = []
    for idx, (name, items) in enumerate(groups.items(), 1):
        session_span = str(items[0].number) if len(items) == 1 else f"{items[0].number}-{items[-1].number}"
        page_span = f"{items[0].pdf_pages.split('–')[0].split('-')[0]}-{items[-1].pdf_pages.split('–')[-1].split('-')[-1]}"
        group_rows.append(
            f'<tr><td>{idx}</td><td>{esc(name)}</td><td>{esc(session_span)}</td><td>{esc(page_span)}</td><td>{len(items)}</td></tr>'
        )

    session_rows = []
    for s in sessions:
        session_rows.append(
            "<tr>"
            f"<td>{s.number}</td>"
            f'<td class="session-link"><a href="#{esc(s.anchor)}">{esc(s.title)}</a></td>'
            f"<td>{esc(s.pdf_pages)}</td>"
            f"<td>{esc(s.book_pages)}</td>"
            f"<td>{esc(s.duration)}</td>"
            f"<td class=\"focus\">{esc(s.study_focus)}</td>"
            "</tr>"
        )

    return f'''
<section id="study-index" class="study-index">
  <h1 class="index-bookmark">فهرست مطالعه / Study Index</h1>
  <div class="cover-card">
    <div class="eyebrow">LABORATORY MEDICINE · STUDY BOOK</div>
    <h2>{esc(course_title)}</h2>
    <p class="lead-fa" lang="fa" dir="rtl">فهرست یکپارچه‌ی جلسات با لینک داخلی، بوک‌مارک سلسله‌مراتبی و شماره‌گذاری پیوسته</p>
    <div class="metrics">
      <div><strong>{len(sessions)}</strong><span>جلسه / Sessions</span></div>
      <div><strong>{len(groups)}</strong><span>فصل / Groups</span></div>
      <div><strong>{esc(overall_pages)}</strong><span>صفحات منبع / Source pages</span></div>
    </div>
  </div>

  <div class="index-intro" lang="fa" dir="rtl">
    <h2>راهنمای استفاده</h2>
    <p>عنوان هر جلسه در جدول زیر قابل‌کلیک است و مستقیماً به نخستین صفحه‌ی همان جلسه منتقل می‌شود. بوک‌مارک‌های PDF نیز فصل‌ها و جلسات را به همان ترتیب نمایش می‌دهند.</p>
  </div>

  <h2>فصل‌ها و گروه‌ها / Chapters and Groups</h2>
  <table class="groups-table">
    <thead><tr><th>#</th><th>فصل / Group</th><th>جلسات / Sessions</th><th>صفحات منبع / Source pages</th><th>تعداد / Count</th></tr></thead>
    <tbody>{''.join(group_rows)}</tbody>
  </table>

  <h2>جدول کامل جلسات / Complete Session Table</h2>
  <table class="sessions-table">
    <thead><tr><th>#</th><th>عنوان جلسه / Session title</th><th>صفحات منبع / Source</th><th>صفحات کتاب / Book</th><th>زمان / Time</th><th>تمرکز مطالعه / Study focus</th></tr></thead>
    <tbody>{''.join(session_rows)}</tbody>
  </table>
</section>
'''


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--notes-dir", required=True)
    parser.add_argument("--index")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    notes_dir = Path(args.notes_dir)
    index_path = Path(args.index) if args.index else locate_index(notes_dir)
    title, pages, sessions = parse_index(index_path, notes_dir)
    Path(args.output).write_text(build_study_index_html(title, pages, sessions), encoding="utf-8")
    print(f"Study Index HTML: {args.output} ({len(sessions)} sessions, {len(group_sessions(sessions))} groups)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
