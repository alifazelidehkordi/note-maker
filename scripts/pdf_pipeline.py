#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import fitz
import mistune
from pypdf import PdfReader, PdfWriter
from pypdf.constants import PageLabelStyle
from reportlab.lib.pagesizes import A4
from weasyprint import HTML

PAGE_SIZE = A4
PAGE_WIDTH, PAGE_HEIGHT = A4
assert PAGE_WIDTH < PAGE_HEIGHT
A4_TOLERANCE = 2.0

INDEX_NAMES = ("STUDY_INDEX-rewritten.md", "STUDY_INDEX.md", "study_index.md")
NON_SESSION_RE = re.compile(
    r"(?:readme|study[_-]?index|verification|qa|debug|combined|manifest|log)", re.I
)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.M)
NOTE_LINK_RE = re.compile(r"\[([^\]]+)\]\(note://([^\)]+)\)")
RTL_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]")


@dataclass
class Session:
    sid: str
    number: int
    title: str
    group: str
    markdown: str
    source_pages: str = "-"
    focus: str = "-"
    book_pages: str = "-"


@dataclass
class HeadingEntry:
    hid: str
    level: int
    title: str
    session_sid: str
    book_page: str = "-"


@dataclass
class FontConfig:
    arabic: Path
    latin_regular: Path
    latin_bold: Path


def natural_key(v: str | Path):
    s = Path(v).name if isinstance(v, Path) else str(v)
    return [int(x) if x.isdigit() else x.casefold() for x in re.split(r"(\d+)", s)]


def slug(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    value = re.sub(r"[^\w\u0600-\u06ff]+", "-", text, flags=re.UNICODE).strip("-").casefold()
    return value or "section"


def resolve_fonts(repo: Path) -> FontConfig:
    env_regular = os.getenv("FONT_FILE")
    env_bold = os.getenv("FONT_BOLD_FILE")
    roots = [repo / "fonts", repo, Path.cwd()]
    files = [
        p
        for root in roots
        if root.exists()
        for p in root.rglob("*")
        if p.suffix.lower() in {".ttf", ".otf"}
    ]

    def pick(env_value: str | None, names: list[str]) -> Path:
        if env_value:
            p = Path(env_value).expanduser().resolve()
            if not p.is_file():
                raise RuntimeError(f"Required font not found: {p}")
            return p
        for name in names:
            for p in files:
                if p.name.casefold() == name.casefold():
                    return p.resolve()
        raise RuntimeError(f"Required font not found; tried {names}")

    return FontConfig(
        pick(None, ["SF-Arabic-Rounded.ttf", "SF-Arabic.ttf"]),
        pick(env_regular, ["SF-Pro-Rounded-Regular.otf", "SF-Pro-Rounded-Regular (2).otf"]),
        pick(env_bold, ["SF-Pro-Rounded-Bold.otf", "SF-Pro-Rounded-Semibold.otf"]),
    )


def is_session_file(path: Path, index_paths: set[Path] | None = None) -> bool:
    if path.suffix.lower() != ".md" or path.name.startswith("."):
        return False
    if index_paths and path.resolve() in index_paths:
        return False
    if NON_SESSION_RE.search(path.stem):
        return False
    return path.is_file()


def discover_index(notes_dir: Path, explicit: Path | None = None) -> Path | None:
    if explicit:
        p = explicit.resolve()
        if not p.is_file():
            raise RuntimeError(f"Index not found: {p}")
        return p
    for base in (notes_dir, notes_dir.parent):
        for name in INDEX_NAMES:
            p = base / name
            if p.is_file():
                return p.resolve()
    return None


def plain_markdown_title(text: str) -> str:
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    text = re.sub(r"[*_~]+", "", text)
    return html.unescape(text).strip()


def exact_focus(md: str) -> str:
    for block in re.split(r"\n\s*\n", md):
        text = re.sub(r"[`*_>#\[\]()]+", "", block).strip()
        if text and not text.startswith(("|", "- ", "1. ")):
            return text[:180] + ("..." if len(text) > 180 else "")
    return "-"


def sessions_from_markdown(path: Path) -> list[Session]:
    text = path.read_text(encoding="utf-8")
    h1 = [m for m in HEADING_RE.finditer(text) if len(m.group(1)) == 1]
    if not h1:
        title = path.stem.replace("_", " ").replace("-", " ").strip()
        return [Session(f"session-1-{slug(title)}", 1, title, path.stem, text)]
    out: list[Session] = []
    for i, match in enumerate(h1):
        start = match.start()
        end = h1[i + 1].start() if i + 1 < len(h1) else len(text)
        chunk = text[start:end].strip() + "\n"
        title = plain_markdown_title(match.group(2))
        out.append(
            Session(
                f"session-{i + 1}-{slug(title)}",
                i + 1,
                title,
                path.stem,
                chunk,
                focus=exact_focus(chunk[len(match.group(0)) :]),
            )
        )
    return out


def sessions_from_index(index: Path, notes_dir: Path) -> list[Session]:
    links = NOTE_LINK_RE.findall(index.read_text(encoding="utf-8"))
    if not links:
        return []
    md_files = [p for p in notes_dir.glob("*.md") if is_session_file(p, {index})]
    aliases = {a: p for p in md_files for a in {p.stem.casefold(), p.name.casefold()}}
    out = []
    for i, (title, target) in enumerate(links, 1):
        p = aliases.get(Path(target).name.casefold()) or aliases.get(Path(target).stem.casefold())
        if not p:
            raise RuntimeError(f"Index session unresolved: title={title!r}, link=note://{target}")
        md = p.read_text(encoding="utf-8")
        out.append(
            Session(
                f"session-{i}-{slug(title)}",
                i,
                plain_markdown_title(title),
                p.parent.name or notes_dir.name,
                md,
                focus=exact_focus(md),
            )
        )
    return out


def load_sessions(notes_dir: Path, index: Path | None) -> tuple[list[Session], str, bool]:
    if index:
        indexed = sessions_from_index(index, notes_dir)
        if indexed:
            return indexed, index.stem, True
    files = sorted(
        [p for p in notes_dir.glob("*.md") if is_session_file(p, {index} if index else set())],
        key=natural_key,
    )
    if not files:
        raise RuntimeError(f"No valid Markdown content in {notes_dir}")
    out: list[Session] = []
    offset = 0
    for p in files:
        for item in sessions_from_markdown(p):
            offset += 1
            item.number = offset
            item.sid = f"session-{offset}-{slug(item.title)}"
            item.group = p.stem
            out.append(item)
    title = files[0].stem if len(files) == 1 else notes_dir.name
    return out, title, False


def extract_heading_entries(sessions: list[Session]) -> list[HeadingEntry]:
    entries: list[HeadingEntry] = []
    global_n = 0
    for session in sessions:
        local_n = 0
        for match in HEADING_RE.finditer(session.markdown):
            level = len(match.group(1))
            title = plain_markdown_title(match.group(2))
            local_n += 1
            global_n += 1
            hid = session.sid if local_n == 1 and level == 1 else f"heading-{global_n}-l{level}-{slug(title)}"
            entries.append(HeadingEntry(hid, level, title, session.sid))
    return entries


def headings_by_session(entries: list[HeadingEntry]) -> dict[str, list[HeadingEntry]]:
    result: dict[str, list[HeadingEntry]] = {}
    for entry in entries:
        result.setdefault(entry.session_sid, []).append(entry)
    return result


def markdown_renderer():
    return mistune.create_markdown(
        escape=False,
        plugins=["table", "strikethrough", "footnotes", "task_lists"],
    )


def font_uri(path: Path) -> str:
    return path.resolve().as_uri()


def build_css(fonts: FontConfig) -> str:
    return f'''
@font-face {{font-family:"CustomArabic";src:url("{font_uri(fonts.arabic)}");font-style:normal;font-weight:100 900;}}
@font-face {{font-family:"CustomLatin";src:url("{font_uri(fonts.latin_regular)}");font-style:normal;font-weight:400;}}
@font-face {{font-family:"CustomLatin";src:url("{font_uri(fonts.latin_bold)}");font-style:normal;font-weight:700 900;}}
@page {{size:A4 portrait;margin:16mm 15mm 18mm 15mm;@bottom-center {{content:counter(page);font-family:"CustomArabic","CustomLatin";font-size:8.5pt;color:#64748b;}}}}
html,body {{font-family:"CustomArabic","CustomLatin";font-size:10.2pt;line-height:1.48;color:#172033;}}
body {{direction:ltr;text-align:left;}}
p,li,td,th,h1,h2,h3,h4,h5,h6,a,span,div {{font-family:"CustomArabic","CustomLatin";unicode-bidi:plaintext;overflow-wrap:anywhere;}}
[dir="rtl"] {{direction:rtl;text-align:right;}} [dir="ltr"] {{direction:ltr;text-align:left;}}
h1,h2,h3,h4,h5,h6 {{color:#0f3a66;break-after:avoid;page-break-after:avoid;orphans:3;widows:3;}}
.content h1 {{font-size:18.5pt;border-bottom:2px solid #2563eb;padding-bottom:5pt;margin:21pt 0 9pt;}}
.content h2 {{font-size:14pt;border-left:4px solid #60a5fa;padding-left:8pt;margin:15pt 0 6pt;}}
.content h3 {{font-size:12pt;margin:11pt 0 4pt;}}
.content h4 {{font-size:10.8pt;margin:9pt 0 3pt;color:#244b73;}}
.content h5,.content h6 {{font-size:10.2pt;margin:8pt 0 3pt;color:#365f86;}}
p {{margin:4pt 0;}} strong,b {{font-weight:700;color:#0f3a66;}}
ul,ol {{padding-inline-start:20pt;margin:5pt 0 8pt;}} li {{margin:2.6pt 0;}}
blockquote {{background:#f8fafc;border-left:4px solid #cbd5e1;padding:7pt 10pt;margin:9pt 0;break-inside:avoid;}}
a {{color:#1d4ed8;text-decoration:none;}}
code,pre,pre code {{font-family:"CustomArabic","CustomLatin" !important;direction:ltr;unicode-bidi:isolate;}}
code {{background:#eef2f7;padding:1pt 3pt;border-radius:3pt;font-size:8.8pt;}}
pre {{background:#eef2f7;padding:7pt 9pt;border-radius:5pt;white-space:pre-wrap;overflow-wrap:anywhere;break-inside:avoid;font-size:8.7pt;}}
table {{width:100%;border-collapse:collapse;margin:9pt 0 11pt;font-size:8.8pt;table-layout:fixed;}}
thead {{display:table-header-group;}} tr {{break-inside:avoid;}}
th,td {{border:1px solid #dbe4ee;padding:4pt 5pt;vertical-align:top;overflow-wrap:anywhere;}}
th {{background:#eff6ff;color:#0f3a66;font-weight:700;}}
img,svg {{max-width:100%;height:auto;break-inside:avoid;}}
.study-index {{direction:ltr;}}
.study-index-title {{font-size:22pt;margin:0 0 4pt;border-bottom:2.5px solid #2563eb;padding-bottom:7pt;}}
.study-meta {{color:#64748b;margin:0 0 5pt;font-size:9.4pt;}}
.study-note {{color:#475569;background:#f8fafc;border:1px solid #e2e8f0;border-radius:5pt;padding:5pt 7pt;margin:8pt 0 10pt;font-size:8.8pt;}}
.toc-table {{margin-top:5pt;font-size:8.7pt;table-layout:auto;}}
.toc-table th {{padding:4pt 5pt;}} .toc-table td {{padding:2.4pt 4.5pt;border-left:0;border-right:0;border-color:#e7edf4;}}
.toc-title {{width:auto;}} .toc-page {{width:38pt;text-align:right;direction:ltr;white-space:nowrap;color:#475569;}}
.toc-row.level-1 td {{background:#f5f9ff;border-top:1.2px solid #bfd7f4;padding-top:5pt;padding-bottom:4pt;font-weight:700;font-size:9.6pt;}}
.toc-row.level-2 .toc-link {{font-weight:600;}}
.toc-row.level-3 .toc-link {{color:#365f86;}}
.toc-row.level-4 .toc-link {{color:#5b7188;font-size:8.25pt;}}
.toc-row.level-5 .toc-link,.toc-row.level-6 .toc-link {{color:#64748b;font-size:8pt;}}
.toc-link {{display:block;color:inherit;}}
.content {{break-before:page;page-break-before:always;}}
.session-section {{margin:0;padding:0;}}
.key-points,.warning-box {{break-inside:avoid;padding:8pt 10pt;border-radius:6pt;margin:10pt 0;}}
.key-points {{background:#dbeafe;border:1px solid #60a5fa;}} .warning-box {{background:#fff7ed;border:1px solid #fb923c;}}
'''


def direction_attr(text: str) -> str:
    return "rtl" if RTL_RE.search(text) else "ltr"


def html_escape_text(value: object) -> str:
    return html.escape(str(value), quote=True)


def render_hierarchical_index(title: str, sessions: list[Session], headings: list[HeadingEntry], *, has_real_index: bool) -> str:
    top_level = sum(1 for h in headings if h.level == 1)
    meta = [f"Top-level topics: {top_level}", f"Headings: {len(headings)}"]
    if has_real_index:
        meta.insert(0, f"Indexed sessions: {len(sessions)}")
    rows = []
    for h in headings:
        level = min(max(h.level, 1), 6)
        indent_pt = max(0, level - 1) * 14
        rows.append(
            f'<tr class="toc-row level-{level}">'
            f'<td class="toc-title" dir="{direction_attr(h.title)}">'
            f'<a class="toc-link" data-heading-link="{h.hid}" href="#{h.hid}">'
            f'<span class="toc-indent" style="display:inline-block;width:{indent_pt}pt"></span>'
            f'{html_escape_text(h.title)}</a></td>'
            f'<td class="toc-page">{html_escape_text(h.book_page)}</td></tr>'
        )
    return f'''<section id="study-index" class="study-index">
<h1 class="study-index-title">{html_escape_text(title)} - فهرست مطالب / Contents</h1>
<div class="study-meta">{" &nbsp;|&nbsp; ".join(meta)}</div>
<div class="study-note" dir="rtl">عنوان‌ها قابل کلیک هستند و به محل دقیق همان سرفصل در جزوه می‌روند. تورفتگی ردیف‌ها hierarchy واقعی Markdown را نشان می‌دهد.</div>
<table class="toc-table"><thead><tr><th>Title / عنوان</th><th class="toc-page">Page</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
</section>'''


def add_heading_ids(rendered_html: str, entries: list[HeadingEntry]) -> str:
    pos = 0
    pattern = re.compile(r"<h([1-6])([^>]*)>(.*?)</h\1>", re.I | re.S)

    def repl(match: re.Match[str]) -> str:
        nonlocal pos
        if pos >= len(entries):
            return match.group(0)
        entry = entries[pos]
        level = int(match.group(1))
        if level != entry.level:
            raise RuntimeError(f"Markdown heading render mismatch: expected H{entry.level} {entry.title!r}, got H{level}")
        pos += 1
        attrs = re.sub(r'\s+id=("[^"]*"|\'[^\']*\')', "", match.group(2), flags=re.I)
        return f'<h{level}{attrs} id="{entry.hid}">{match.group(3)}</h{level}>'

    output = pattern.sub(repl, rendered_html)
    if pos != len(entries):
        raise RuntimeError(f"Markdown heading count mismatch: expected {len(entries)}, rendered {pos}")
    return output


def build_html(title: str, sessions: list[Session], headings: list[HeadingEntry], fonts: FontConfig, *, has_real_index: bool) -> str:
    md = markdown_renderer()
    per_session = headings_by_session(headings)
    sections = []
    for session in sessions:
        content = add_heading_ids(md(session.markdown), per_session.get(session.sid, []))
        content = re.sub(r'(<h2[^>]*>\s*(?:Key Points|نکات کلیدی|Summary)\s*</h2>)(.*?)(?=<h2|$)', r'<div class="key-points">\1\2</div>', content, flags=re.I | re.S)
        content = re.sub(r'(<h2[^>]*>\s*(?:Warning|Warnings|هشدار|هشدارها|Pitfalls?)\s*</h2>)(.*?)(?=<h2|$)', r'<div class="warning-box">\1\2</div>', content, flags=re.I | re.S)
        sections.append(f'<section class="session-section" data-session="{session.sid}" dir="{direction_attr(session.title)}">{content}</section>')
    return '<!doctype html><html><head><meta charset="utf-8"><style>' + build_css(fonts) + '</style></head><body>' + render_hierarchical_index(title, sessions, headings, has_real_index=has_real_index) + '<main class="content">' + ''.join(sections) + '</main></body></html>'


def render_pdf(html_text: str, out: Path, base: Path):
    out.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html_text, base_url=str(base)).write_pdf(str(out))


def destination_pages(pdf: Path, ids: list[str]) -> dict[str, int]:
    reader = PdfReader(pdf)
    named = reader.named_destinations
    result = {}
    missing = []
    for item_id in ids:
        dest = named.get(item_id)
        if dest is None:
            missing.append(item_id)
            continue
        page = reader.get_destination_page_number(dest)
        if page is None or page < 0:
            missing.append(item_id)
            continue
        result[item_id] = int(page)
    if missing:
        raise RuntimeError(f"Internal destinations missing: {missing[:20]}")
    return result


def compute_heading_pages(pdf: Path, headings: list[HeadingEntry]) -> tuple[dict[str, int], int]:
    starts = destination_pages(pdf, [h.hid for h in headings])
    total = len(PdfReader(pdf).pages)
    for h in headings:
        h.book_page = str(starts[h.hid] + 1)
    return starts, total


def compute_session_ranges(sessions: list[Session], headings: list[HeadingEntry], heading_pages: dict[str, int], total: int):
    first_heading = {}
    for h in headings:
        first_heading.setdefault(h.session_sid, h.hid)
    ordered = [heading_pages[first_heading[s.sid]] for s in sessions]
    for i, session in enumerate(sessions):
        a = ordered[i] + 1
        b = ordered[i + 1] if i + 1 < len(ordered) else total
        session.book_pages = str(a) if a == b else f"{a}-{b}"


def add_outlines_and_labels(pdf: Path, headings: list[HeadingEntry], heading_pages: dict[str, int], title: str):
    reader = PdfReader(pdf)
    writer = PdfWriter()
    writer.append(reader, import_outline=False)
    writer.set_page_label(0, len(writer.pages) - 1, style=PageLabelStyle.DECIMAL, start=1)
    writer.add_outline_item("فهرست مطالب / Study Index", 0, bold=True)
    parents: dict[int, object] = {}
    for h in headings:
        parent = next((parents[level] for level in range(h.level - 1, 0, -1) if level in parents), None)
        node = writer.add_outline_item(h.title, heading_pages[h.hid], parent=parent, bold=h.level == 1, is_open=False if h.level <= 2 else None)
        parents[h.level] = node
        for level in list(parents):
            if level > h.level:
                parents.pop(level, None)
        writer.add_named_destination(h.hid, heading_pages[h.hid])
    writer.add_metadata({"/Title": title, "/Subject": "Study notes with hierarchical clickable contents"})
    writer.page_mode = "/UseOutlines"
    tmp = pdf.with_suffix(".tmp.pdf")
    with tmp.open("wb") as stream:
        writer.write(stream)
    tmp.replace(pdf)


def inspect_fonts(pdf: Path) -> tuple[list[dict], list[str]]:
    cmd = shutil.which("pdffonts")
    if not cmd:
        raise RuntimeError("pdffonts is required for font embedding QA")
    proc = subprocess.run([cmd, str(pdf)], capture_output=True, text=True, check=True)
    fonts = []
    fallbacks = []
    for line in proc.stdout.splitlines()[2:]:
        parts = line.split()
        if len(parts) < 7:
            continue
        try:
            emb_idx = next(i for i, x in enumerate(parts) if x in {"yes", "no"})
        except StopIteration:
            continue
        name = parts[0]
        emb = parts[emb_idx] == "yes"
        sub = parts[emb_idx + 1] == "yes" if emb_idx + 1 < len(parts) else False
        uni = parts[emb_idx + 2] == "yes" if emb_idx + 2 < len(parts) else False
        fonts.append({"name": name, "embedded": emb, "subset": sub, "unicode": uni})
        if any(x.lower() in name.lower() for x in ("Helvetica", "Times", "Courier")):
            fallbacks.append(name)
    return fonts, sorted(set(fallbacks))


def get_page_labels(pdf: Path) -> list[str]:
    doc = fitz.open(pdf)
    return [page.get_label() for page in doc]


def footer_numbers(pdf: Path) -> list[int | None]:
    doc = fitz.open(pdf)
    out = []
    for page in doc:
        candidates = []
        for block in page.get_text("blocks"):
            _x0, y0, _x1, _y1, text, *_ = block
            if y0 > page.rect.height - 55:
                candidates.extend(int(m.group(1)) for m in re.finditer(r"\b(\d+)\b", text))
        out.append(candidates[-1] if candidates else None)
    return out


def flatten_outline(reader: PdfReader) -> list[tuple[int, str, int | None]]:
    result = []
    def walk(items, depth=0):
        for item in items:
            if isinstance(item, list):
                walk(item, depth + 1)
            else:
                try:
                    page = reader.get_destination_page_number(item)
                except Exception:
                    page = None
                result.append((depth, getattr(item, "title", ""), page))
    walk(reader.outline)
    return result


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).replace("\u00ad", "")
    return re.sub(r"\s+", " ", value).strip()


def qa(pdf: Path, sessions: list[Session], headings: list[HeadingEntry], heading_pages: dict[str, int], index_pages: int, report_path: Path, *, has_real_index: bool) -> dict:
    errors = []
    reader = PdfReader(pdf)
    total = len(reader.pages)
    invalid = []
    rotated = []
    for i, page in enumerate(reader.pages, 1):
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        rotation = int(page.get("/Rotate", 0) or 0) % 360
        if not (width < height and abs(width - PAGE_WIDTH) <= A4_TOLERANCE and abs(height - PAGE_HEIGHT) <= A4_TOLERANCE):
            invalid.append({"page": i, "width": width, "height": height})
        if rotation in (90, 270):
            rotated.append(i)
    if invalid:
        errors.append(f"Invalid A4/portrait pages: {[x['page'] for x in invalid]}")
    if rotated:
        errors.append(f"Rotated pages: {rotated}")

    fonts, fallbacks = inspect_fonts(pdf)
    custom = [f for f in fonts if "CustomArabic" in f["name"] or "CustomLatin" in f["name"]]
    if not custom or not all(f["embedded"] for f in custom):
        errors.append("Custom fonts missing or not embedded")
    if not any("CustomLatin" in f["name"] for f in custom):
        errors.append("Custom Latin font missing")
    if not any("CustomArabic" in f["name"] for f in custom):
        errors.append("Custom Arabic font missing")
    if fallbacks:
        errors.append(f"Visible fallback fonts detected: {fallbacks}")

    named = reader.named_destinations
    expected_ids = [h.hid for h in headings]
    missing_dest = [hid for hid in expected_ids if hid not in named]
    if missing_dest:
        errors.append(f"Internal destinations missing: {missing_dest[:20]}")
    seen_ids = []
    raw_uris = []
    for pno in range(index_pages):
        for ref in reader.pages[pno].get("/Annots") or []:
            annot = ref.get_object()
            dest = annot.get("/Dest")
            action = annot.get("/A")
            if dest and str(dest) in expected_ids:
                seen_ids.append(str(dest))
            if action:
                action = action.get_object() if hasattr(action, "get_object") else action
                uri = action.get("/URI")
                if uri:
                    raw_uris.append(str(uri))
    unique_seen = list(dict.fromkeys(seen_ids))
    unresolved = [u for u in raw_uris if u.casefold().startswith("note://")]
    if unique_seen != expected_ids:
        errors.append(f"Index link ids/order mismatch: expected {len(expected_ids)}, got {len(unique_seen)}")
    if unresolved:
        errors.append(f"Unresolved note links: {unresolved[:10]}")
    actual_pages = [reader.get_destination_page_number(named[hid]) for hid in expected_ids if hid in named]
    expected_pages = [heading_pages[hid] for hid in expected_ids]
    if actual_pages != expected_pages:
        errors.append("Internal link destination pages do not match heading starts")

    outline = flatten_outline(reader)
    if len(outline) != 1 + len(headings):
        errors.append(f"Bookmark count mismatch: expected {1 + len(headings)}, found {len(outline)}")
    else:
        if outline[0][1] != "فهرست مطالب / Study Index" or outline[0][2] != 0:
            errors.append("Study Index bookmark missing or invalid")
        if [x[1] for x in outline[1:]] != [h.title for h in headings]:
            errors.append("Bookmark title/order hierarchy mismatch")
        if [x[2] for x in outline[1:]] != expected_pages:
            errors.append("Bookmark destinations mismatch")

    labels = get_page_labels(pdf)
    if labels != [str(i) for i in range(1, total + 1)]:
        errors.append("Page labels are not continuous 1-N")
    footers = footer_numbers(pdf)
    if footers != list(range(1, total + 1)):
        bad = [i + 1 for i, (a, b) in enumerate(zip(footers, range(1, total + 1))) if a != b][:20]
        errors.append(f"Footer numbering mismatch on pages {bad}")

    doc = fitz.open(pdf)
    text_norm = normalize_text(" ".join(page.get_text() for page in doc))
    missing_titles = [h.title for h in headings if normalize_text(h.title) not in text_norm]
    if missing_titles:
        errors.append(f"Heading titles missing from PDF: {missing_titles[:20]}")

    top_h1 = [h for h in headings if h.level == 1]
    top_pages = [heading_pages[h.hid] for h in top_h1]
    shared = sum(1 for a, b in zip(top_pages, top_pages[1:]) if a == b)
    if len(set(top_pages)) == len(top_pages) and len(top_pages) > 3:
        errors.append("All top-level topics start on distinct pages; forced page breaks may still be active")

    report = {
        "status": "PASSED" if not errors else "FAILED",
        "pdf": str(pdf),
        "total_pages": total,
        "study_index_pages": index_pages,
        "sessions": len(sessions),
        "groups": None if not has_real_index else len(dict.fromkeys(s.group for s in sessions)),
        "top_level_sections": len(top_h1),
        "headings": len(headings),
        "internal_links": {"expected": len(headings), "converted": len(unique_seen), "unresolved": len(unresolved)},
        "bookmarks": len(outline),
        "page_number_range": f"1-{total}",
        "fonts": fonts,
        "page_size": "A4",
        "orientation": "Portrait",
        "portrait_pages": total - len(invalid),
        "landscape_pages": len(invalid),
        "rotated_pages": rotated,
        "continuous_body": {"top_level_topics": len(top_h1), "distinct_start_pages": len(set(top_pages)), "shared_start_page_transitions": shared},
        "index_mode": "existing-index" if has_real_index else "markdown-heading-hierarchy",
        "quality_check": "PASSED" if not errors else "FAILED",
        "errors": errors,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if errors:
        raise RuntimeError("QA FAILED: " + "; ".join(errors))
    return report


def build(notes_dir: Path, output: Path, index: Path | None, title: str | None, repo: Path) -> dict:
    if not notes_dir.is_dir():
        raise RuntimeError(f"NOTES_DIR missing: {notes_dir}")
    if not os.access(notes_dir, os.R_OK):
        raise RuntimeError(f"NOTES_DIR not readable: {notes_dir}")
    output.parent.mkdir(parents=True, exist_ok=True)
    if not os.access(output.parent, os.W_OK):
        raise RuntimeError(f"Output directory not writable: {output.parent}")
    fonts = resolve_fonts(repo)
    index = discover_index(notes_dir, index)
    sessions, derived_title, has_real_index = load_sessions(notes_dir, index)
    title = title or derived_title.replace("_", " ").title()
    headings = extract_heading_entries(sessions)
    if not headings:
        raise RuntimeError("No Markdown headings available for hierarchical navigation")

    with tempfile.TemporaryDirectory() as td:
        draft = Path(td) / "draft.pdf"
        previous = None
        for _ in range(6):
            render_pdf(build_html(title, sessions, headings, fonts, has_real_index=has_real_index), draft, notes_dir)
            heading_pages, total = compute_heading_pages(draft, headings)
            compute_session_ranges(sessions, headings, heading_pages, total)
            state = tuple(h.book_page for h in headings)
            if state == previous:
                break
            previous = state
        render_pdf(build_html(title, sessions, headings, fonts, has_real_index=has_real_index), output, notes_dir)

    heading_pages, total = compute_heading_pages(output, headings)
    compute_session_ranges(sessions, headings, heading_pages, total)
    index_pages = min(heading_pages[h.hid] for h in headings if h.level == 1)
    add_outlines_and_labels(output, headings, heading_pages, title)
    final_heading_pages, _ = compute_heading_pages(output, headings)
    return qa(output, sessions, headings, final_heading_pages, index_pages, output.with_suffix(".qa.json"), has_real_index=has_real_index)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--notes-dir", default=os.getenv("NOTES_DIR", "outputs/notes"))
    ap.add_argument("--output", default=os.getenv("COMBINED_OUTPUT", "outputs/notes/FINAL_STUDY_NOTES.pdf"))
    ap.add_argument("--index-md", default=os.getenv("INDEX_MD"))
    ap.add_argument("--title", default=os.getenv("BOOK_TITLE"))
    ap.add_argument("--repo", default=".")
    args = ap.parse_args()
    try:
        report = build(
            Path(args.notes_dir).resolve(),
            Path(args.output).resolve(),
            Path(args.index_md).resolve() if args.index_md else None,
            args.title,
            Path(args.repo).resolve(),
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
