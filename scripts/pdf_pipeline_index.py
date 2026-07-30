#!/usr/bin/env python3
"""Reference-style bilingual Study Index generation."""
from __future__ import annotations

import html
from typing import Sequence
from urllib.parse import quote

from pdf_pipeline_data import Session, group_sessions, parse_range


def note_uri(session: Session) -> str:
    return f"note://{quote(session.stem, safe='_-')}"


def html_escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def build_index_markdown(
    sessions: Sequence[Session],
    course_title: str,
    *,
    total_pages: int | None = None,
) -> str:
    """Build the compact bilingual Study Index used at the front of the book.

    The visual design intentionally mirrors the provided reference: a blue hero
    panel, a short usage note, one chapter/group table, and one complete session
    table with bilingual headers. All values are computed from Index/metadata.
    """
    groups = group_sessions(sessions)
    source_page_total = 0
    for group in groups:
        page_range = parse_range(group.source_pages)
        if page_range:
            source_page_total += page_range[1] - page_range[0] + 1
    overall_book = f"1-{total_pages}" if total_pages else "پس از صفحه‌آرایی / after layout"

    lines: list[str] = [
        '<div class="study-index" dir="rtl">',
        '<div class="index-topline"><span>فهرست مطالعه</span><span dir="ltr">Study Index</span></div>',
        '<section class="index-hero">',
        '<div class="hero-kicker" dir="ltr">STUDY BOOK</div>',
        f'<div class="hero-title" dir="ltr">{html_escape(course_title)}</div>',
        '<div class="hero-subtitle">فهرست یکپارچه‌ی جلسات با لینک داخلی، بوکمارک سلسله‌مراتبی و شماره‌گذاری پیوسته</div>',
        '<div class="hero-stats">',
        f'<div><strong>{len(sessions)}</strong><span>جلسه / Sessions</span></div>',
        f'<div><strong>{len(groups)}</strong><span>فصل / Groups</span></div>',
        f'<div><strong>{source_page_total or "—"}</strong><span>صفحات منبع / Source pages</span></div>',
        f'<div><strong>{overall_book}</strong><span>صفحات کتاب / Book pages</span></div>',
        '</div>',
        '</section>',
        '<section class="index-guide">',
        '<h2>راهنمای استفاده</h2>',
        '<p>عنوان هر جلسه در جدول زیر قابل کلیک است و مستقیماً به نخستین صفحه‌ی همان جلسه منتقل می‌شود. بوکمارک‌های PDF نیز فصل‌ها و جلسات را به همان ترتیب نمایش می‌دهند.</p>',
        '</section>',
        '<section class="group-table">',
        '<h2>فصل‌ها و گروه‌ها <span dir="ltr">/ Chapters and Groups</span></h2>',
        '',
        '| # | فصل / Group | جلسات / Sessions | صفحات منبع / Source pages | صفحات کتاب / Book pages | تعداد / Count |',
        '|---:|---|---:|---:|---:|---:|',
    ]
    for i, group in enumerate(groups, 1):
        session_span = str(group.sessions[0].number) if len(group.sessions) == 1 else f"{group.sessions[0].number}-{group.sessions[-1].number}"
        lines.append(
            f"| {i} | {group.title} | {session_span} | {group.source_pages} | {group.book_pages} | {len(group.sessions)} |"
        )

    lines += [
        '',
        '</section>',
        '<section class="session-table">',
        '<h2>جدول کامل جلسات <span dir="ltr">/ Complete Session Table</span></h2>',
        '',
        '| # | عنوان جلسه / Session title | صفحات منبع / Source pages | صفحات کتاب / Book pages | زمان / Time | تمرکز مطالعه / Study focus |',
        '|---:|---|---:|---:|---:|---|',
    ]
    for session in sessions:
        lines.append(
            f"| {session.number} | [{session.title}]({note_uri(session)}) | {session.source_pages} | {session.book_pages} | {session.duration} | {session.study_focus} |"
        )
    lines += [
        '',
        '</section>',
        '<p class="index-footer-note">این فهرست از فایل Index و metadata/Markdown آماده ساخته شده است؛ فایل Index به‌عنوان جلسه وارد کتاب نشده است.</p>',
        '</div>',
        '',
    ]
    return "\n".join(lines)
