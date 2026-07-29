#!/usr/bin/env python3
"""Shared utilities for the Markdown-to-PDF study-book pipeline.

The final book is deliberately generated as one HTML/PDF document. This keeps
internal destinations, hierarchical bookmarks, page counters, and page labels
synchronized without estimating page offsets or merging independently paginated
component PDFs.
"""
from __future__ import annotations

import html
import os
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import unquote

try:  # Existing project dependency.
    import markdown as _markdown
except ModuleNotFoundError:  # pragma: no cover - exercised in lean environments
    _markdown = None

try:  # Lightweight, reliable fallback available in many Python environments.
    import mistune as _mistune
except ModuleNotFoundError:  # pragma: no cover - dependency validation handles this
    _mistune = None

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover
    yaml = None

A4_WIDTH_PT = 595.275590551
A4_HEIGHT_PT = 841.88976378
A4_TOLERANCE_PT = 2.5

DIGIT_TRANSLATION = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.S)
H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.M)
TOPIC_NAME_RE = re.compile(r"^(\d{1,3})(?:_(\d{1,3}))?[_-].+\.md$", re.I)
PAGE_FILENAME_RE = re.compile(r"(?:^|[_-])pp(\d{1,4})[-–](\d{1,4})(?:[_-]|$)", re.I)
INDEX_SESSION_RE = re.compile(r"^###\s+(\d+)\.\s+\[([^]]+)\]\(([^)]+)\)\s*$")
INDEX_FIELD_RE = re.compile(r"^-\s+\*\*(.+?):\*\*\s*(.*?)\s*$")
INDEX_GROUP_RE = re.compile(r"^##\s+(.+?)\s*$")
INDEX_TITLE_RE = re.compile(r"^#\s+(.+?)\s*$")
PDF_PAGES_RE = re.compile(
    r"(?P<source>\d+\s*[-–]\s*\d+|\d+)"
    r"(?:\s*\(\s*printed\s+(?P<book>\d+\s*[-–]\s*\d+|\d+)\s*\))?",
    re.I,
)
META_NAMES = {
    "readme.md",
    "index.md",
    "study_index.md",
    "study_index-rewritten.md",
    "study_index_verification.md",
    "qa_report.md",
    "boundaries.md",
    "structure.md",
    "combined_notes.md",
}
META_STEMS = {
    "readme",
    "index",
    "study_index",
    "study_index-rewritten",
    "study_index_verification",
    "qa_report",
    "boundaries",
    "structure",
    "combined_notes",
}
NON_NOTE_TOKENS = {
    "verification",
    "quality",
    "report",
    "debug",
    "temporary",
    "temp",
    "cache",
    "manifest",
    "inventory",
    "coverage",
    "final_study_notes",
}
OVERVIEW_GROUP_HEADINGS = {"package overview", "recommended sequence", "overview"}
KEY_SECTION_RE = re.compile(
    r"(<h2[^>]*>\s*(?:Key Points|نکات کلیدی|خلاصه(?:\s+کلیدی)?)\s*</h2>)"
    r"(.*?)(?=<h2\b|\Z)",
    re.I | re.S,
)
WARNING_SECTION_RE = re.compile(
    r"(<h2[^>]*>\s*(?:Warnings?|هشدارها?|Pitfalls?|اشتباهات رایج)\s*</h2>)"
    r"(.*?)(?=<h2\b|\Z)",
    re.I | re.S,
)


@dataclass(frozen=True)
class FontBundle:
    """Font sources supplied only through FONT_FILE and FONT_BOLD_FILE.

    Each environment variable may contain one or more paths separated by the OS
    path separator (":" on Linux). This allows a custom Arabic font and a custom
    Latin font to work together while still keeping all typography constrained to
    the two required variables.
    """

    regular: tuple[Path, ...]
    bold: tuple[Path, ...]

    @property
    def all_files(self) -> tuple[Path, ...]:
        unique: list[Path] = []
        for item in (*self.regular, *self.bold):
            if item not in unique:
                unique.append(item)
        return tuple(unique)


@dataclass(frozen=True)
class StudySession:
    number: int
    title: str
    group: str
    group_number: int
    note_path: Path
    source_pages: str
    book_pages: str
    duration: str
    study_focus: str
    density: str = ""
    scope: str = ""
    source_link: str = ""

    @property
    def anchor(self) -> str:
        return f"session-{self.number:03d}"


@dataclass
class StudyGroup:
    title: str
    sessions: list[StudySession] = field(default_factory=list)

    @property
    def number_span(self) -> str:
        if not self.sessions:
            return "—"
        first = self.sessions[0].number
        last = self.sessions[-1].number
        return str(first) if first == last else f"{first}-{last}"

    @property
    def source_span(self) -> str:
        return range_span(s.source_pages for s in self.sessions)

    @property
    def book_span(self) -> str:
        return range_span(s.book_pages for s in self.sessions)


@dataclass(frozen=True)
class StudyIndexData:
    course_title: str
    sessions: tuple[StudySession, ...]
    groups: tuple[StudyGroup, ...]
    source_coverage: str
    book_coverage: str
    physical_source_pages: int | None
    total_study_time: str
    index_path: Path


class PipelineError(RuntimeError):
    """A fatal input, generation, or validation error."""


def natural_key(value: str | Path) -> tuple[object, ...]:
    text = Path(value).name if isinstance(value, Path) else str(value)
    return tuple(int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", text))


def is_topic_note(path: Path) -> bool:
    """Return True only for substantive numbered Markdown session files."""
    path = Path(path)
    if not path.is_file() or path.suffix.casefold() != ".md":
        return False
    if path.name.startswith(".") or any(part.startswith(".") for part in path.parts):
        return False
    name = path.name.casefold()
    stem = path.stem.casefold()
    if name in META_NAMES or stem in META_STEMS:
        return False
    if any(token in stem for token in NON_NOTE_TOKENS):
        return False
    return bool(TOPIC_NAME_RE.match(path.name))


def find_index_file(notes_dir: Path, explicit: Path | None = None) -> Path:
    notes_dir = Path(notes_dir).resolve()
    if explicit is not None:
        explicit = Path(explicit).resolve()
        if not explicit.is_file():
            raise FileNotFoundError(f"Index Markdown not found: {explicit}")
        return explicit
    preferred = ("INDEX.md", "STUDY_INDEX.md", "STUDY_INDEX-rewritten.md")
    for name in preferred:
        for candidate in (notes_dir / name, notes_dir.parent / name):
            if candidate.is_file():
                return candidate.resolve()
    candidates = sorted(
        (
            p
            for p in notes_dir.glob("*.md")
            if "index" in p.stem.casefold() and not p.name.startswith(".")
        ),
        key=natural_key,
    )
    if not candidates:
        raise FileNotFoundError(f"No Index Markdown file found in or beside {notes_dir}")
    return candidates[0].resolve()


def _clean_course_title(raw: str) -> str:
    title = re.sub(r"\s*(?:/|-)?\s*(?:Study\s+Index|فهرست\s+مطالعه)\s*$", "", raw, flags=re.I).strip()
    return title or "Study Notes"


def _parse_frontmatter(path: Path) -> dict:
    if yaml is None:
        return {}
    try:
        text = path.read_text(encoding="utf-8", errors="strict")
    except OSError:
        return {}
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}
    try:
        data = yaml.safe_load(match.group(1)) or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _first_heading(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="strict")
    match = H1_RE.search(text)
    if match:
        return match.group(1).strip()
    return path.stem.replace("_", " ").replace("-", " ").strip().title()


def _fallback_excerpt(path: Path, limit: int = 220) -> str:
    text = clean_markdown(path.read_text(encoding="utf-8", errors="strict"))
    text = H1_RE.sub("", text, count=1)
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "|", "```", "---")):
            continue
        line = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", line)
        line = re.sub(r"[*_`>#]+", "", line)
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"
    return "Review the central mechanisms, comparisons, and clinical implications in this session."


def _normalize_range(value: str | None) -> str:
    if not value:
        return "—"
    text = str(value).translate(DIGIT_TRANSLATION).strip()
    text = re.sub(r"\s*[-–]\s*", "-", text)
    return text or "—"


def _page_fields(value: str | None) -> tuple[str, str]:
    if not value:
        return "—", "—"
    match = PDF_PAGES_RE.search(str(value).translate(DIGIT_TRANSLATION))
    if not match:
        return _normalize_range(value), "—"
    return _normalize_range(match.group("source")), _normalize_range(match.group("book"))


def _resolve_note_path(notes_dir: Path, link: str, number: int) -> Path:
    decoded = unquote(link).replace("\\", "/")
    candidates = [notes_dir / decoded, notes_dir / Path(decoded).name]
    for candidate in candidates:
        if candidate.is_file() and is_topic_note(candidate):
            return candidate.resolve()
    basename = Path(decoded).name
    recursive = [p for p in notes_dir.rglob(basename) if p.is_file() and is_topic_note(p)]
    if len(recursive) == 1:
        return recursive[0].resolve()
    numbered = sorted(
        (p for p in notes_dir.rglob(f"{number:02d}_*.md") if is_topic_note(p)),
        key=natural_key,
    )
    if len(numbered) == 1:
        return numbered[0].resolve()
    raise PipelineError(f"Could not resolve Markdown note for session {number}: {link}")


def _extract_overview_value(text: str, label: str) -> str | None:
    pattern = re.compile(rf"^-\s+\*\*{re.escape(label)}:\*\*\s*(.*?)\s*$", re.I | re.M)
    match = pattern.search(text)
    return match.group(1).strip() if match else None


def parse_study_index(index_path: Path, notes_dir: Path) -> StudyIndexData:
    """Parse the existing Index as the primary source of ordering and metadata."""
    index_path = Path(index_path).resolve()
    notes_dir = Path(notes_dir).resolve()
    text = index_path.read_text(encoding="utf-8", errors="strict")
    lines = text.splitlines()

    course_title = "Study Notes"
    for line in lines:
        match = INDEX_TITLE_RE.match(line)
        if match:
            course_title = _clean_course_title(match.group(1).strip())
            break

    physical_raw = _extract_overview_value(text, "Physical PDF pages")
    physical_match = re.search(r"\d+", physical_raw.translate(DIGIT_TRANSLATION)) if physical_raw else None
    physical_pages = int(physical_match.group()) if physical_match else None
    total_time = _extract_overview_value(text, "Approximate total study time") or "—"
    expected_count_raw = _extract_overview_value(text, "Numbered study parts")
    expected_count_match = (
        re.search(r"\d+", expected_count_raw.translate(DIGIT_TRANSLATION)) if expected_count_raw else None
    )
    expected_count = int(expected_count_match.group()) if expected_count_match else None

    current_group: str | None = None
    current_group_number = 0
    raw_sessions: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for line in lines:
        group_match = INDEX_GROUP_RE.match(line)
        if group_match:
            candidate = group_match.group(1).strip()
            if candidate.casefold() not in OVERVIEW_GROUP_HEADINGS and candidate.casefold() != "supplementary material":
                current_group = candidate
                current_group_number += 1
            elif candidate.casefold() == "supplementary material":
                current_group = None
            continue
        session_match = INDEX_SESSION_RE.match(line)
        if session_match:
            if not current_group:
                raise PipelineError(
                    f"Session {session_match.group(1)} appears before a chapter/group heading in {index_path}"
                )
            current = {
                "number": int(session_match.group(1)),
                "title": session_match.group(2).strip(),
                "source_link": session_match.group(3).strip(),
                "group": current_group,
                "group_number": current_group_number,
                "fields": {},
            }
            raw_sessions.append(current)
            continue
        field_match = INDEX_FIELD_RE.match(line)
        if field_match and current is not None:
            fields = current["fields"]
            assert isinstance(fields, dict)
            fields[field_match.group(1).strip()] = field_match.group(2).strip()

    if not raw_sessions:
        raise PipelineError(f"No numbered study sessions found in {index_path}")

    sessions: list[StudySession] = []
    seen_numbers: set[int] = set()
    seen_paths: set[Path] = set()
    for raw in raw_sessions:
        number = int(raw["number"])
        if number in seen_numbers:
            raise PipelineError(f"Duplicate session number in Index: {number}")
        seen_numbers.add(number)
        note_path = _resolve_note_path(notes_dir, str(raw["source_link"]), number)
        if note_path in seen_paths:
            raise PipelineError(f"A Markdown file is assigned to more than one session: {note_path.name}")
        seen_paths.add(note_path)
        fields = raw["fields"]
        assert isinstance(fields, dict)
        source_pages, book_pages = _page_fields(str(fields.get("PDF pages", "")))
        meta = _parse_frontmatter(note_path)
        if source_pages == "—":
            fallback = meta.get("pdf_pages") or meta.get("pages") or meta.get("page_range")
            if fallback:
                source_pages = _normalize_range(str(fallback))
            else:
                page_match = PAGE_FILENAME_RE.search(note_path.stem)
                if page_match:
                    source_pages = f"{int(page_match.group(1))}-{int(page_match.group(2))}"
        if book_pages == "—":
            fallback_book = meta.get("book_pages")
            if fallback_book:
                book_pages = _normalize_range(str(fallback_book))
        title = str(raw["title"]).strip() or str(meta.get("title") or _first_heading(note_path))
        duration = str(fields.get("Approximate study time") or meta.get("estimated_time") or "—").strip()
        focus = str(
            fields.get("Learning objective")
            or meta.get("study_focus")
            or meta.get("focus")
            or _fallback_excerpt(note_path)
        ).strip()
        sessions.append(
            StudySession(
                number=number,
                title=title,
                group=str(raw["group"]).strip(),
                group_number=int(raw["group_number"]),
                note_path=note_path,
                source_pages=source_pages,
                book_pages=book_pages,
                duration=duration,
                study_focus=focus,
                density=str(fields.get("Density", "")).strip(),
                scope=str(fields.get("Scope", "")).strip(),
                source_link=str(raw["source_link"]).strip(),
            )
        )

    sessions.sort(key=lambda item: item.number)
    expected_sequence = list(range(sessions[0].number, sessions[-1].number + 1))
    actual_sequence = [session.number for session in sessions]
    if actual_sequence != expected_sequence:
        raise PipelineError(
            f"Session numbering is not continuous: expected {expected_sequence}, got {actual_sequence}"
        )
    if expected_count is not None and expected_count != len(sessions):
        raise PipelineError(
            f"Index overview says {expected_count} sessions, but {len(sessions)} numbered sessions were parsed"
        )

    available_notes = {p.resolve() for p in notes_dir.rglob("*.md") if is_topic_note(p)}
    missing_from_index = sorted(available_notes - seen_paths, key=natural_key)
    if missing_from_index:
        names = ", ".join(path.name for path in missing_from_index)
        raise PipelineError(f"Substantive numbered Markdown files missing from Index: {names}")

    grouped: OrderedDict[int, StudyGroup] = OrderedDict()
    for session in sessions:
        grouped.setdefault(session.group_number, StudyGroup(session.group)).sessions.append(session)

    return StudyIndexData(
        course_title=course_title,
        sessions=tuple(sessions),
        groups=tuple(grouped.values()),
        source_coverage=range_span(s.source_pages for s in sessions),
        book_coverage=range_span(s.book_pages for s in sessions),
        physical_source_pages=physical_pages,
        total_study_time=total_time,
        index_path=index_path,
    )


def range_bounds(value: str) -> tuple[int, int] | None:
    if not value or value.strip() in {"—", "-"}:
        return None
    numbers = [int(item) for item in re.findall(r"\d+", value.translate(DIGIT_TRANSLATION))]
    if not numbers:
        return None
    return min(numbers), max(numbers)


def range_span(values: Iterable[str]) -> str:
    bounds = [item for value in values if (item := range_bounds(value)) is not None]
    if not bounds:
        return "—"
    low = min(item[0] for item in bounds)
    high = max(item[1] for item in bounds)
    return str(low) if low == high else f"{low}-{high}"


def clean_markdown(text: str) -> str:
    """Remove YAML frontmatter only; scientific Markdown content is preserved."""
    if text.lstrip().startswith("---"):
        text = FRONTMATTER_RE.sub("", text, count=1).lstrip()
    return text.strip()


def strip_first_h1(text: str) -> str:
    """Remove the first Markdown H1 because the session title is rendered separately."""
    cleaned = clean_markdown(text)
    return H1_RE.sub("", cleaned, count=1).lstrip()


def markdown_to_html(text: str) -> str:
    """Convert Markdown while retaining tables, nested lists, and inline HTML."""
    cleaned = clean_markdown(text)
    if _markdown is not None:
        converter = _markdown.Markdown(
            extensions=["extra", "sane_lists", "tables", "fenced_code", "footnotes"],
            output_format="html5",
        )
        try:
            body = converter.convert(cleaned)
        finally:
            converter.reset()
    elif _mistune is not None:
        renderer = _mistune.HTMLRenderer(escape=False)
        converter = _mistune.create_markdown(
            renderer=renderer,
            plugins=["table", "strikethrough", "url"],
        )
        body = converter(cleaned)
    else:
        raise PipelineError("Install either 'markdown' or 'mistune' to convert Markdown to HTML")
    body = KEY_SECTION_RE.sub(r'<section class="key-points">\1\2</section>', body)
    body = WARNING_SECTION_RE.sub(r'<section class="warning-box">\1\2</section>', body)
    return body


def _split_font_value(value: str | None, variable_name: str) -> tuple[Path, ...]:
    if not value:
        raise PipelineError(f"{variable_name} is required and must point to a supplied font file")
    paths = tuple(Path(part).expanduser().resolve() for part in value.split(os.pathsep) if part.strip())
    if not paths:
        raise PipelineError(f"{variable_name} did not contain a usable path")
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"Font file from {variable_name} not found: {path}")
        if path.suffix.casefold() not in {".ttf", ".otf", ".woff", ".woff2"}:
            raise PipelineError(f"Unsupported font format in {variable_name}: {path}")
    return paths


def load_font_bundle(
    font_file: str | Path | Sequence[str | Path] | None = None,
    font_bold_file: str | Path | Sequence[str | Path] | None = None,
) -> FontBundle:
    """Load and validate only the fonts supplied through the required variables."""

    def normalize(
        supplied: str | Path | Sequence[str | Path] | None,
        env_name: str,
    ) -> tuple[Path, ...]:
        if supplied is None:
            return _split_font_value(os.environ.get(env_name), env_name)
        if isinstance(supplied, (str, Path)):
            return _split_font_value(str(supplied), env_name)
        joined = os.pathsep.join(str(item) for item in supplied)
        return _split_font_value(joined, env_name)

    return FontBundle(
        regular=normalize(font_file, "FONT_FILE"),
        bold=normalize(font_bold_file, "FONT_BOLD_FILE"),
    )


def font_face_css(fonts: FontBundle) -> str:
    """Create glyph-fallback families from only the supplied regular/bold files."""
    lines: list[str] = []
    regular_families: list[str] = []
    bold_families: list[str] = []
    for index, path in enumerate(fonts.regular, 1):
        family = f"StudyRegular{index}"
        regular_families.append(f'"{family}"')
        lines.append(
            "@font-face {"
            f" font-family: '{family}'; src: url('{path.as_uri()}');"
            " font-style: normal; font-weight: 400; font-display: block; }"
        )
    for index, path in enumerate(fonts.bold, 1):
        family = f"StudyBold{index}"
        bold_families.append(f'"{family}"')
        lines.append(
            "@font-face {"
            f" font-family: '{family}'; src: url('{path.as_uri()}');"
            " font-style: normal; font-weight: 700; font-display: block; }"
        )
    lines.append(f":root {{ --study-regular: {', '.join(regular_families)}; }}")
    lines.append(f":root {{ --study-bold: {', '.join(bold_families)}; }}")
    return "\n".join(lines)


def css_string(value: str) -> str:
    """Escape a dynamic string for CSS generated-content syntax."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def build_document_css(fonts: FontBundle, course_title: str, extra_css: str = "") -> str:
    """Return the complete A4 portrait stylesheet for index and note pages."""
    title = css_string(course_title.upper())
    css = f"""
{font_face_css(fonts)}

@page index {{
  size: A4 portrait;
  margin: 12mm 13mm 14mm 13mm;
  @bottom-center {{
    content: counter(page);
    font-family: var(--study-regular);
    font-size: 8pt;
    color: #64748b;
  }}
}}

@page notes {{
  size: A4 portrait;
  margin: 17mm 15mm 15mm 15mm;
  @top-left {{
    content: "{title}";
    font-family: var(--study-regular);
    font-size: 6.8pt;
    letter-spacing: 0.14em;
    color: #60738d;
  }}
  @top-right {{
    content: string(session-title);
    font-family: var(--study-regular);
    font-size: 6.6pt;
    color: #60738d;
  }}
  @bottom-center {{
    content: counter(page);
    font-family: var(--study-regular);
    font-size: 8pt;
    color: #64748b;
  }}
}}

* {{ box-sizing: border-box; }}
html {{ font-variant-ligatures: common-ligatures; }}
body {{
  margin: 0;
  color: #172033;
  background: #ffffff;
  font-family: var(--study-regular);
  font-size: 9.65pt;
  line-height: 1.46;
  text-align: left;
}}
body, p, li, td, th, h1, h2, h3, h4, h5, h6, a, span, div {{
  unicode-bidi: plaintext;
}}
p, li, td, th {{ overflow-wrap: anywhere; }}
strong, b, h1, h2, h3, h4, h5, h6, th {{
  font-family: var(--study-bold);
  font-weight: 700;
}}
a {{ color: #1f5f9d; text-decoration: none; }}

/* Disable automatic outline entries. Only explicit index/group/session classes opt in. */
h1, h2, h3, h4, h5, h6 {{ bookmark-level: none; }}

.index {{ page: index; }}
.index-title {{
  bookmark-level: 1;
  bookmark-label: content(text);
  margin: 0 0 10pt;
  padding-bottom: 7pt;
  border-bottom: 2.2pt solid #2f73b9;
  color: #173e68;
  font-size: 18pt;
  line-height: 1.2;
}}
.hero {{
  margin: 0 0 16pt;
  padding: 22pt 28pt 24pt;
  min-height: 214pt;
  border-radius: 11pt;
  color: #ffffff;
  background: linear-gradient(135deg, #153f6c, #2369a5);
}}
.hero-kicker {{
  margin: 0 0 11pt;
  font-size: 7.8pt;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  opacity: 0.9;
}}
.hero-title {{
  margin: 0 0 9pt;
  font-family: var(--study-regular);
  font-size: 22pt;
  line-height: 1.2;
  color: #ffffff;
}}
.hero-subtitle {{
  margin: 0 0 20pt;
  font-size: 9.2pt;
  line-height: 1.65;
  color: #ffffff;
}}
.stat-grid {{ display: flex; gap: 10pt; }}
.stat-card {{
  flex: 1;
  min-height: 70pt;
  padding: 12pt 13pt;
  border: 0.8pt solid rgba(255,255,255,0.36);
  border-radius: 7pt;
}}
.stat-number {{ display: block; font-size: 20pt; line-height: 1.05; }}
.stat-label {{ display: block; margin-top: 6pt; font-size: 7.6pt; }}
.guide-box {{
  margin: 0 0 14pt;
  padding: 12pt 14pt;
  border-right: 3.5pt solid #3e87c9;
  background: #eef5fc;
  color: #173e68;
}}
.guide-title {{ margin: 0 0 4pt; font-size: 12.5pt; }}
.guide-box p {{ margin: 2pt 0; font-size: 8.7pt; line-height: 1.55; }}
.index-section-title {{
  margin: 13pt 0 7pt;
  padding-left: 8pt;
  border-left: 4pt solid #65a7e2;
  color: #174b7d;
  font-size: 13.5pt;
  line-height: 1.25;
}}
.index-note {{ margin: 0 0 8pt; font-size: 8.3pt; color: #52657b; }}
.page-break {{ break-before: page; page-break-before: always; height: 0; }}

table {{
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
  margin: 5pt 0 11pt;
  font-size: 7.75pt;
  line-height: 1.28;
}}
thead {{ display: table-header-group; }}
tfoot {{ display: table-footer-group; }}
tr {{ break-inside: avoid; page-break-inside: avoid; }}
th, td {{
  border: 0.55pt solid #c9d8e7;
  padding: 3.5pt 4pt;
  vertical-align: top;
}}
th {{ color: #174b7d; background: #e9f2fb; text-align: left; }}
tbody tr:nth-child(even) td {{ background: #f9fbfd; }}
.groups-table .c-num {{ width: 5%; }}
.groups-table .c-group {{ width: 38%; }}
.groups-table .c-sessions {{ width: 15%; }}
.groups-table .c-source {{ width: 17%; }}
.groups-table .c-book {{ width: 15%; }}
.groups-table .c-count {{ width: 10%; }}
.sessions-table {{ font-size: 7.15pt; line-height: 1.25; }}
.sessions-table .c-num {{ width: 4%; }}
.sessions-table .c-title {{ width: 24%; }}
.sessions-table .c-source {{ width: 9%; }}
.sessions-table .c-book {{ width: 9%; }}
.sessions-table .c-time {{ width: 10%; }}
.sessions-table .c-focus {{ width: 44%; }}
.session-link {{ font-family: var(--study-bold); font-weight: 700; }}

.session {{ page: notes; break-before: page; page-break-before: always; }}
.group-kicker {{
  bookmark-level: 1;
  bookmark-label: content(text);
  margin: 0 0 7pt;
  color: #4d7094;
  font-size: 9.2pt;
  line-height: 1.2;
}}
.group-kicker.repeat {{ bookmark-level: none; font-family: var(--study-regular); }}
.session-meta {{
  display: table;
  width: 100%;
  margin: 0 0 10pt;
  border: 0.6pt solid #cad9e8;
  background: #f5f9fd;
  color: #536b84;
  font-size: 7.8pt;
}}
.session-meta span {{ display: table-cell; width: 33.333%; padding: 5pt 8pt; }}
.session-meta span:nth-child(2) {{ text-align: center; }}
.session-meta span:nth-child(3) {{ text-align: right; }}
.session-title {{
  string-set: session-title content(text);
  bookmark-level: 2;
  bookmark-label: content(text);
  margin: 0 0 12pt;
  padding-bottom: 7pt;
  border-bottom: 2.2pt solid #2f73b9;
  color: #123f6e;
  font-size: 17.5pt;
  line-height: 1.2;
}}
.session-content h2 {{
  margin: 14pt 0 7pt;
  padding-left: 8pt;
  border-left: 4pt solid #65a7e2;
  color: #174b7d;
  font-size: 13.2pt;
  line-height: 1.25;
  break-after: avoid;
  page-break-after: avoid;
}}
.session-content h3 {{
  margin: 10pt 0 4pt;
  color: #174b7d;
  font-size: 11.3pt;
  line-height: 1.25;
  break-after: avoid;
  page-break-after: avoid;
}}
.session-content h4 {{
  margin: 8pt 0 3pt;
  color: #244f78;
  font-size: 10.1pt;
  break-after: avoid;
  page-break-after: avoid;
}}
.session-content p {{ margin: 3pt 0 5pt; orphans: 3; widows: 3; }}
.session-content ul, .session-content ol {{
  margin: 4pt 0 7pt;
  padding-inline-start: 18pt;
}}
.session-content ul {{ list-style-type: disc; }}
.session-content li::marker {{ font-family: var(--study-regular); }}
.session-content li {{ margin: 2.2pt 0; orphans: 2; widows: 2; }}
.session-content table {{ font-size: 8pt; line-height: 1.25; }}
.session-content blockquote {{
  margin: 9pt 0;
  padding: 7pt 10pt;
  border-left: 4pt solid #b8cbe0;
  background: #f7fafc;
  break-inside: avoid;
}}
.session-content code, .session-content pre {{
  font-family: var(--study-regular);
  direction: ltr;
  unicode-bidi: isolate;
}}
.session-content code {{ padding: 1pt 3pt; background: #eef3f7; border-radius: 2pt; }}
.session-content pre {{
  padding: 7pt 9pt;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  background: #eef3f7;
  border-radius: 4pt;
  break-inside: avoid;
}}
.session-content img, .session-content svg {{
  max-width: 100%;
  height: auto;
  break-inside: avoid;
  page-break-inside: avoid;
}}
.key-points, .warning-box {{
  margin: 12pt 0;
  padding: 9pt 11pt;
  border-radius: 6pt;
  break-inside: avoid;
  page-break-inside: avoid;
}}
.key-points {{ background: #e9f4ff; border: 0.8pt solid #84b9e9; }}
.warning-box {{ background: #fff5e9; border: 0.8pt solid #f0a45c; }}
.key-points h2, .warning-box h2 {{
  margin-top: 0;
  padding-left: 0;
  border-left: 0;
  font-size: 12.5pt;
}}
.warning-box h2 {{ color: #9c4c10; }}
"""
    if extra_css:
        css += "\n" + extra_css
    return css


def html_escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def validate_portrait_page_size(width: float, height: float, rotation: int, page_number: int) -> None:
    rotation %= 360
    if width >= height:
        raise PipelineError(
            f"Landscape page detected: page={page_number}, width={width:.3f}, height={height:.3f}"
        )
    if rotation in (90, 270):
        raise PipelineError(f"Rotated page detected: page={page_number}, rotation={rotation}")
    if abs(width - A4_WIDTH_PT) > A4_TOLERANCE_PT or abs(height - A4_HEIGHT_PT) > A4_TOLERANCE_PT:
        raise PipelineError(
            f"Non-A4 page detected: page={page_number}, width={width:.3f}, height={height:.3f}"
        )
