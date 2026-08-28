#!/usr/bin/env python3
"""Convert exactly one Markdown file into one validated A4 portrait PDF.

The converter preserves Markdown content and only changes presentation. It builds
an in-document clickable table of contents from Markdown headings, creates a
hierarchical PDF outline, embeds the fonts supplied by FONT_FILE and
FONT_BOLD_FILE, adds continuous page numbers/page labels, and runs strict PDF
quality checks before publishing the requested output path.
"""

from __future__ import annotations

import argparse
import html
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

try:
    import mistune
except ModuleNotFoundError:  # pragma: no cover - runtime dependency check
    mistune = None

_WEASYPRINT_IMPORT_ERROR: Exception | None = None
try:
    from weasyprint import HTML
except (ModuleNotFoundError, OSError) as exc:  # pragma: no cover - environment dependent
    HTML = None
    _WEASYPRINT_IMPORT_ERROR = exc

try:
    from pypdf import PdfReader, PdfWriter
    from pypdf.constants import PageLabelStyle
except ModuleNotFoundError:  # pragma: no cover - runtime dependency check
    PdfReader = None
    PdfWriter = None
    PageLabelStyle = None


A4_WIDTH_PT = 595.2755905511812
A4_HEIGHT_PT = 841.8897637795277
A4_TOLERANCE_PT = 1.0
DEFAULT_OUTPUT = Path("outputs/notes/FINAL_STUDY_NOTES.pdf")
FONT_FAMILY = "StudyNotesFont"
FONT_FAMILY_BOLD = "StudyNotesFont-Bold"
TOC_DEPTH = 3
HEADING_TAG_RE = re.compile(r"<[^>]+>")
BLOCK_DIR_RE = re.compile(
    r"<(p|li|blockquote|td|th|h[1-6])(\s[^>]*)?>", re.IGNORECASE
)
RTL_CHAR_RE = re.compile(r"[\u0590-\u08FF\uFB1D-\uFDFD\uFE70-\uFEFC]")
FORBIDDEN_BASE_FONT_RE = re.compile(r"(?:Helvetica|Times|Courier)", re.IGNORECASE)


@dataclass(frozen=True)
class Heading:
    level: int
    title: str
    anchor: str


@dataclass(frozen=True)
class QualityReport:
    total_pages: int
    toc_pages: int
    markdown_headings: int
    toc_internal_links: int
    unresolved_links: int
    bookmarks: int
    embedded_fonts: tuple[str, ...]
    portrait_pages: int
    landscape_pages: int
    rotated_pages: int


class ValidationError(RuntimeError):
    """Raised when a required quality check fails."""


class StudyRenderer(mistune.HTMLRenderer if mistune else object):
    """Mistune renderer that assigns deterministic anchors to Markdown headings."""

    def __init__(self) -> None:
        if mistune is None:  # pragma: no cover
            return
        super().__init__(escape=False)
        self.headings: list[Heading] = []

    def heading(self, text: str, level: int, **attrs: Any) -> str:
        anchor = f"md-heading-{len(self.headings) + 1:04d}"
        title = html.unescape(HEADING_TAG_RE.sub("", text)).strip()
        self.headings.append(Heading(level=level, title=title, anchor=anchor))
        return f'<h{level} id="{anchor}" dir="auto">{text}</h{level}>\n'


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert one Markdown file to one validated A4 portrait PDF."
    )
    parser.add_argument(
        "input",
        nargs="?",
        help="Input Markdown path. Falls back to INPUT_MD when omitted.",
    )
    parser.add_argument(
        "output",
        nargs="?",
        help=(
            "Output PDF path. Falls back to COMBINED_OUTPUT, then "
            "outputs/notes/FINAL_STUDY_NOTES.pdf."
        ),
    )
    return parser.parse_args()


def require_dependencies() -> None:
    missing: list[str] = []
    if mistune is None:
        missing.append("mistune")
    if HTML is None:
        missing.append("weasyprint")
    if PdfReader is None or PdfWriter is None or PageLabelStyle is None:
        missing.append("pypdf")
    if missing:
        detail = ""
        if HTML is None and _WEASYPRINT_IMPORT_ERROR is not None:
            detail = f"; WeasyPrint import error: {_WEASYPRINT_IMPORT_ERROR}"
        raise ValidationError(
            "Missing required dependency/dependencies: " + ", ".join(missing) + detail
        )


def require_readable_file(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise ValidationError(f"{label} does not exist or is not a file: {resolved}")
    if not os.access(resolved, os.R_OK):
        raise ValidationError(f"{label} is not readable: {resolved}")
    try:
        with resolved.open("rb") as handle:
            handle.read(16)
    except OSError as exc:
        raise ValidationError(f"{label} cannot be read: {resolved}: {exc}") from exc
    return resolved


def resolve_paths(args: argparse.Namespace) -> tuple[Path, Path, Path, Path]:
    input_value = args.input or os.environ.get("INPUT_MD")
    if not input_value:
        raise ValidationError("Input Markdown is required via CLI argument or INPUT_MD.")

    output_value = args.output or os.environ.get("COMBINED_OUTPUT")
    output_path = Path(output_value) if output_value else DEFAULT_OUTPUT

    font_value = os.environ.get("FONT_FILE")
    bold_value = os.environ.get("FONT_BOLD_FILE")
    if not font_value:
        raise ValidationError("FONT_FILE is required and must point to a readable font file.")
    if not bold_value:
        raise ValidationError(
            "FONT_BOLD_FILE is required because headings and bold text use a bold font."
        )

    input_path = require_readable_file(Path(input_value), "Input Markdown")
    font_path = require_readable_file(Path(font_value), "FONT_FILE")
    bold_path = require_readable_file(Path(bold_value), "FONT_BOLD_FILE")
    if input_path.suffix.lower() not in {".md", ".markdown"}:
        raise ValidationError(f"Input must be a Markdown file: {input_path}")

    output_path = output_path.expanduser().resolve()
    if output_path.suffix.lower() != ".pdf":
        raise ValidationError(f"Output path must end in .pdf: {output_path}")
    return input_path, output_path, font_path, bold_path


def render_markdown(md_text: str) -> tuple[str, list[Heading]]:
    renderer = StudyRenderer()
    markdown = mistune.create_markdown(
        renderer=renderer,
        plugins=["table", "footnotes", "strikethrough", "url"],
    )
    body = markdown(md_text)

    # Resolve direction per block at rendering time without changing Markdown.
    def add_dir(match: re.Match[str]) -> str:
        tag = match.group(1)
        attrs = match.group(2) or ""
        if re.search(r"\bdir\s*=", attrs, re.IGNORECASE):
            return match.group(0)
        return f'<{tag}{attrs} dir="auto">'

    body = BLOCK_DIR_RE.sub(add_dir, body)
    return body, renderer.headings


def is_rtl_heavy(text: str) -> bool:
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return False
    rtl_count = sum(1 for ch in letters if RTL_CHAR_RE.match(ch))
    return rtl_count / len(letters) >= 0.35


def document_title(headings: list[Heading], input_path: Path) -> str:
    if headings and headings[0].title:
        return headings[0].title
    return input_path.stem


def toc_title(md_text: str) -> str:
    return "فهرست مطالب" if is_rtl_heavy(md_text) else "Table of Contents"


def build_toc(headings: list[Heading], title: str) -> tuple[str, list[Heading]]:
    included = [heading for heading in headings if heading.level <= TOC_DEPTH]
    entries = []
    for heading in included:
        safe_title = html.escape(heading.title)
        entries.append(
            f'<div class="toc-entry toc-level-{heading.level}">'
            f'<a href="#{heading.anchor}" dir="auto">{safe_title}</a>'
            "</div>"
        )
    return (
        '<nav class="toc" aria-label="Table of Contents">'
        f'<h1 class="toc-title" dir="auto">{html.escape(title)}</h1>'
        + "".join(entries)
        + "</nav>",
        included,
    )


def build_css(font_path: Path, bold_path: Path) -> str:
    regular_uri = font_path.as_uri()
    bold_uri = bold_path.as_uri()
    return f"""
@font-face {{
  font-family: '{FONT_FAMILY}';
  src: url('{regular_uri}');
  font-weight: 400;
  font-style: normal;
}}
@font-face {{
  font-family: '{FONT_FAMILY}';
  src: url('{bold_uri}');
  font-weight: 700;
  font-style: normal;
}}

@page {{
  size: A4 portrait;
  margin: 16mm 16mm 18mm 16mm;
  @bottom-center {{
    content: counter(page);
    font-family: '{FONT_FAMILY}';
    font-size: 8.5pt;
    color: #64748b;
  }}
}}

html, body {{
  margin: 0;
  padding: 0;
  max-width: 100%;
}}

body {{
  font-family: '{FONT_FAMILY}';
  font-size: 10.25pt;
  line-height: 1.5;
  color: #172033;
  overflow-wrap: anywhere;
  word-break: normal;
}}

body, p, li, blockquote, td, th, h1, h2, h3, h4, h5, h6 {{
  unicode-bidi: plaintext;
}}

.document-bookmark-root {{
  bookmark-level: 1;
  bookmark-label: content(text);
  height: 0;
  max-height: 0;
  overflow: hidden;
  margin: 0;
  padding: 0;
  border: 0;
  font-size: 0;
  line-height: 0;
  color: transparent;
}}

.toc {{
  break-after: page;
  page-break-after: always;
  bookmark-level: none;
}}

.toc-title {{
  bookmark-level: none;
  font-family: '{FONT_FAMILY}';
  font-weight: 700;
  font-size: 19pt;
  line-height: 1.25;
  color: #0f3a66;
  margin: 0 0 14pt;
  padding-bottom: 7pt;
  border-bottom: 2pt solid #2563eb;
}}

.toc-entry {{
  font-family: '{FONT_FAMILY}';
  margin: 2.5pt 0;
  line-height: 1.35;
  break-inside: avoid;
}}

.toc-entry a {{
  font-family: '{FONT_FAMILY}';
  color: #172033;
  text-decoration: none;
}}

.toc-entry a::after {{
  content: leader('.') target-counter(attr(href), page);
  font-family: '{FONT_FAMILY}';
  color: #64748b;
}}

.toc-level-1 {{
  font-weight: 700;
  margin-top: 6pt;
}}
.toc-level-2 {{ padding-inline-start: 12pt; }}
.toc-level-3 {{ padding-inline-start: 24pt; font-size: 9.5pt; color: #475569; }}

h1, h2, h3, h4, h5, h6 {{
  font-family: '{FONT_FAMILY}';
  font-weight: 700;
  color: #0f3a66;
  line-height: 1.25;
  break-after: avoid-page;
  page-break-after: avoid;
  orphans: 3;
  widows: 3;
}}
h1 {{
  bookmark-level: 2;
  font-size: 18pt;
  margin: 16pt 0 9pt;
  padding-bottom: 5pt;
  border-bottom: 1.6pt solid #2563eb;
}}
h2 {{
  bookmark-level: 3;
  font-size: 14pt;
  margin: 15pt 0 6pt;
  padding-inline-start: 8pt;
  border-inline-start: 3pt solid #60a5fa;
}}
h3 {{ bookmark-level: 4; font-size: 12pt; margin: 11pt 0 4pt; }}
h4 {{ bookmark-level: 5; font-size: 10.8pt; margin: 9pt 0 3pt; }}
h5 {{ bookmark-level: 6; font-size: 10.4pt; margin: 8pt 0 3pt; }}
h6 {{ bookmark-level: 7; font-size: 10.1pt; margin: 8pt 0 3pt; }}

p {{ margin: 3.5pt 0 6pt; }}
strong, b {{ font-family: '{FONT_FAMILY}'; font-weight: 700; color: #0f3a66; }}
em, i {{ font-family: '{FONT_FAMILY}'; font-style: italic; }}

ul, ol {{
  margin: 4pt 0 8pt;
  padding-inline-start: 20pt;
}}
li {{ margin: 2.5pt 0; }}
li > p {{ margin: 1.5pt 0; }}

blockquote {{
  margin: 9pt 0;
  padding: 7pt 10pt;
  background: #f8fafc;
  border-inline-start: 3pt solid #cbd5e1;
  break-inside: avoid-page;
}}

hr {{
  border: 0;
  border-top: 0.8pt solid #dbe4ee;
  margin: 10pt 0;
}}

a {{
  font-family: '{FONT_FAMILY}';
  color: #1d4ed8;
  text-decoration: none;
  overflow-wrap: anywhere;
}}

mark {{
  font-family: '{FONT_FAMILY}';
  background: #fff1a8;
  color: inherit;
  padding: 0 1pt;
}}

code, pre, pre code {{
  font-family: '{FONT_FAMILY}';
}}
code {{
  background: #eef2f7;
  padding: 1pt 3pt;
  border-radius: 2pt;
  font-size: 8.9pt;
  unicode-bidi: isolate;
}}
pre {{
  direction: ltr;
  text-align: left;
  unicode-bidi: isolate;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-all;
  background: #eef2f7;
  border: 0.7pt solid #dbe4ee;
  border-radius: 4pt;
  padding: 7pt 8pt;
  margin: 8pt 0 10pt;
  font-size: 8.35pt;
  line-height: 1.38;
  max-width: 100%;
}}
pre code {{ background: transparent; padding: 0; border-radius: 0; }}

table {{
  width: 100%;
  max-width: 100%;
  table-layout: fixed;
  border-collapse: collapse;
  margin: 8pt 0 11pt;
  font-size: 8.65pt;
  line-height: 1.35;
  break-inside: auto;
}}
thead {{ display: table-header-group; }}
tr {{ break-inside: avoid; page-break-inside: avoid; }}
th, td {{
  font-family: '{FONT_FAMILY}';
  border: 0.65pt solid #dbe4ee;
  padding: 4pt 5pt;
  vertical-align: top;
  overflow-wrap: anywhere;
  word-break: break-word;
  hyphens: auto;
}}
th {{
  font-family: '{FONT_FAMILY}';
  font-weight: 700;
  color: #0f3a66;
  background: #eff6ff;
}}

img, svg {{
  display: block;
  max-width: 100%;
  max-height: 245mm;
  width: auto;
  height: auto;
  object-fit: contain;
  margin: 7pt auto;
  break-inside: avoid;
}}

sup, sub {{ line-height: 0; }}
.footnotes {{ font-size: 8.7pt; }}
"""


def build_html_document(
    md_text: str,
    body_html: str,
    headings: list[Heading],
    input_path: Path,
    css: str,
) -> tuple[str, list[Heading]]:
    title = document_title(headings, input_path)
    toc_html, toc_headings = build_toc(headings, toc_title(md_text))
    root = (
        f'<div class="document-bookmark-root" dir="auto">{html.escape(title)}</div>'
    )
    lang = "fa" if is_rtl_heavy(md_text) else "en"
    full_html = f"""<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>{css}</style>
</head>
<body>
{root}
{toc_html}
{body_html}
</body>
</html>
"""
    return full_html, toc_headings


def heading_page_map(document: Any, headings: list[Heading]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for page_index, page in enumerate(document.pages):
        for anchor in page.anchors:
            if anchor.startswith("md-heading-"):
                mapping[anchor] = page_index + 1
    missing = [heading.anchor for heading in headings if heading.anchor not in mapping]
    if missing:
        raise ValidationError(f"Heading destinations missing after layout: {missing}")
    return mapping


def validate_weasy_layout(document: Any, headings: list[Heading]) -> None:
    """Use WeasyPrint's laid-out box tree to catch obvious horizontal overflow."""
    heading_anchors = {heading.anchor for heading in headings}
    for page_number, page in enumerate(document.pages, start=1):
        page_box = page._page_box  # WeasyPrint layout tree; used only for QC.
        left = float(page_box.margin_left)
        right = left + float(page_box.width)
        top = float(page_box.margin_top)
        bottom = top + float(page_box.height)

        for box in page_box.descendants():
            tag = getattr(box, "element_tag", None)
            if not tag or tag in {"html", "body"}:
                continue
            try:
                x = float(box.border_box_x())
                y = float(box.border_box_y())
                width = float(box.border_width())
                height = float(box.border_height())
            except (AttributeError, TypeError):
                continue

            # Inline descendants can intentionally begin/end at exact boundaries;
            # 2 CSS px tolerance avoids false positives from rounding.
            if x < left - 2.0 or x + width > right + 2.0:
                raise ValidationError(
                    "Layout overflow detected: "
                    f"page={page_number}, tag={tag}, x={x:.2f}, width={width:.2f}, "
                    f"content_left={left:.2f}, content_right={right:.2f}"
                )
            if y + height > bottom + 2.0 and tag not in {"img", "svg"}:
                raise ValidationError(
                    "Vertical content overflow detected: "
                    f"page={page_number}, tag={tag}, y={y:.2f}, height={height:.2f}, "
                    f"content_bottom={bottom:.2f}"
                )

        # An anchor extremely close to the content bottom is a strong orphan signal.
        for anchor, (_x, y, _w, _h) in page.anchors.items():
            if anchor in heading_anchors and y > bottom - 34.0:
                raise ValidationError(
                    f"Orphan heading detected near page bottom: page={page_number}, "
                    f"anchor={anchor}, y={y:.2f}"
                )


def validate_weasy_links(
    document: Any,
    toc_headings: list[Heading],
    heading_pages: dict[str, int],
) -> int:
    """Ensure every generated TOC target exists after final pagination."""
    if not toc_headings:
        return 0
    first_body_page = min(heading_pages.values())
    toc_pages = document.pages[: first_body_page - 1]
    linked_targets: set[str] = set()
    for page in toc_pages:
        for link in page.links:
            if link[0] == "internal":
                linked_targets.add(str(link[1]))
    missing = [h.anchor for h in toc_headings if h.anchor not in linked_targets]
    if missing:
        raise ValidationError(f"TOC entries without clickable internal links: {missing}")
    return len(toc_headings)


def flatten_weasy_bookmarks(
    tree: Iterable[tuple[str, tuple[int, float, float], list[Any], str]],
    depth: int = 1,
) -> Iterator[tuple[int, str, int]]:
    for label, target, children, _state in tree:
        yield depth, label, int(target[0]) + 1
        yield from flatten_weasy_bookmarks(children, depth + 1)


def validate_weasy_bookmarks(
    document: Any,
    headings: list[Heading],
    title: str,
    heading_pages: dict[str, int],
) -> None:
    actual = list(flatten_weasy_bookmarks(document.make_bookmark_tree()))
    expected = [(1, title, 1)] + [
        (heading.level + 1, heading.title, heading_pages[heading.anchor])
        for heading in headings
    ]
    if actual != expected:
        raise ValidationError(
            "Bookmark tree generated by layout does not match Markdown hierarchy. "
            f"expected={expected!r}, actual={actual!r}"
        )


def add_decimal_page_labels(source_pdf: Path, labeled_pdf: Path) -> None:
    reader = PdfReader(str(source_pdf))
    if not reader.pages:
        raise ValidationError("Generated PDF has zero pages.")
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    writer.set_page_label(
        0,
        len(reader.pages) - 1,
        style=PageLabelStyle.DECIMAL,
        start=1,
    )
    with labeled_pdf.open("wb") as handle:
        writer.write(handle)


def _font_embedded(font: Any) -> bool:
    obj = font.get_object()
    if obj.get("/Subtype") == "/Type0":
        descendants = obj.get("/DescendantFonts") or []
        if not descendants:
            return False
        return all(_font_embedded(descendant) for descendant in descendants)
    descriptor = obj.get("/FontDescriptor")
    if descriptor is None:
        return False
    descriptor = descriptor.get_object()
    return any(key in descriptor for key in ("/FontFile", "/FontFile2", "/FontFile3"))


def collect_fonts(reader: Any) -> dict[str, bool]:
    fonts: dict[str, bool] = {}
    for page in reader.pages:
        resources = page.get("/Resources")
        if resources is None:
            continue
        resources = resources.get_object()
        font_dict = resources.get("/Font")
        if font_dict is None:
            continue
        font_dict = font_dict.get_object()
        for font_ref in font_dict.values():
            font = font_ref.get_object()
            base = str(font.get("/BaseFont", "<unknown>")).lstrip("/")
            fonts[base] = fonts.get(base, True) and _font_embedded(font_ref)
    return fonts


def page_number_from_destination(reader: Any, destination: Any) -> int | None:
    if isinstance(destination, str):
        named = reader.named_destinations.get(destination)
        if named is None:
            return None
        page_index = reader.get_destination_page_number(named)
        return None if page_index is None else page_index + 1

    if hasattr(destination, "get_object"):
        try:
            destination = destination.get_object()
        except Exception:  # pragma: no cover - malformed PDF object
            return None

    if isinstance(destination, (list, tuple)) and destination:
        first = destination[0]
        try:
            target_obj = first.get_object() if hasattr(first, "get_object") else first
            for page_index, page in enumerate(reader.pages):
                if page.indirect_reference == first or page.get_object() == target_obj:
                    return page_index + 1
        except Exception:  # pragma: no cover - malformed destination
            return None
    return None


def validate_internal_links(
    reader: Any,
    toc_headings: list[Heading],
    heading_pages: dict[str, int],
    toc_pages: int,
) -> tuple[int, int]:
    named = reader.named_destinations
    for heading in toc_headings:
        destination = named.get(heading.anchor)
        if destination is None:
            raise ValidationError(f"Missing named destination for TOC heading: {heading.anchor}")
        page_index = reader.get_destination_page_number(destination)
        actual_page = None if page_index is None else page_index + 1
        expected_page = heading_pages[heading.anchor]
        if actual_page != expected_page:
            raise ValidationError(
                f"TOC destination page mismatch for {heading.anchor}: "
                f"expected={expected_page}, actual={actual_page}"
            )

    unresolved = 0
    toc_targets_found: set[str] = set()
    for page_number, page in enumerate(reader.pages, start=1):
        for annot_ref in page.get("/Annots", []) or []:
            annot = annot_ref.get_object()
            if annot.get("/Subtype") != "/Link":
                continue
            destination = annot.get("/Dest")
            action = annot.get("/A")
            if destination is None and action is not None:
                action = action.get_object()
                if action.get("/S") == "/GoTo":
                    destination = action.get("/D")
            if destination is None:
                continue  # External /URI links are not internal destinations.

            if isinstance(destination, str) and page_number <= toc_pages:
                toc_targets_found.add(destination)
            if page_number_from_destination(reader, destination) is None:
                unresolved += 1

    missing_toc_links = [
        heading.anchor for heading in toc_headings if heading.anchor not in toc_targets_found
    ]
    if missing_toc_links:
        raise ValidationError(
            f"Final PDF is missing TOC link annotations for: {missing_toc_links}"
        )
    if unresolved:
        raise ValidationError(f"Unresolved internal PDF links: {unresolved}")
    return len(toc_headings), unresolved


def flatten_pypdf_outline(items: Iterable[Any], depth: int = 1) -> Iterator[tuple[int, Any]]:
    for item in items:
        if isinstance(item, list):
            yield from flatten_pypdf_outline(item, depth + 1)
        else:
            yield depth, item


def validate_pdf_bookmarks(
    reader: Any,
    headings: list[Heading],
    title: str,
    heading_pages: dict[str, int],
) -> int:
    actual: list[tuple[int, str, int]] = []
    for depth, item in flatten_pypdf_outline(reader.outline):
        page_index = reader.get_destination_page_number(item)
        actual.append((depth, str(item.get("/Title", "")), page_index + 1))
    expected = [(1, title, 1)] + [
        (heading.level + 1, heading.title, heading_pages[heading.anchor])
        for heading in headings
    ]
    if actual != expected:
        raise ValidationError(
            "Final PDF bookmarks do not match Markdown hierarchy/order. "
            f"expected={expected!r}, actual={actual!r}"
        )
    return len(actual)


def footer_text_items(page: Any) -> list[tuple[str, float]]:
    items: list[tuple[str, float]] = []

    def visitor(text: str, cm: list[float], tm: list[float], *_args: Any) -> None:
        value = text.strip()
        if not value:
            return
        # pypdf text matrices combined with WeasyPrint's PDF CTM.
        y = float(cm[5] + tm[4] * cm[1] + tm[5] * cm[3])
        items.append((value, y))

    page.extract_text(visitor_text=visitor)
    return items


def validate_page_numbers(reader: Any) -> None:
    expected_labels = [str(i) for i in range(1, len(reader.pages) + 1)]
    if list(reader.page_labels) != expected_labels:
        raise ValidationError(
            f"PDF Page Labels are not continuous 1..N: {reader.page_labels!r}"
        )

    for page_number, page in enumerate(reader.pages, start=1):
        footer_candidates = [
            text for text, y in footer_text_items(page) if y <= 32.0 and text.strip()
        ]
        expected = str(page_number)
        if expected not in footer_candidates:
            raise ValidationError(
                "Footer page number mismatch: "
                f"page={page_number}, expected={expected!r}, "
                f"footer_candidates={footer_candidates!r}"
            )


def validate_headings_in_pdf(
    reader: Any, headings: list[Heading], heading_pages: dict[str, int]
) -> None:
    def normalized(value: str) -> str:
        return re.sub(r"\s+", " ", value).strip()

    page_text = [normalized(page.extract_text() or "") for page in reader.pages]
    last_page = 0
    for heading in headings:
        title = normalized(heading.title)
        expected_page = heading_pages[heading.anchor]
        if expected_page < last_page:
            raise ValidationError(
                f"Markdown heading order changed in PDF: {title!r}, page={expected_page}"
            )
        last_page = expected_page
        # pypdf can return visually ordered glyph text for RTL runs. For RTL
        # headings, exact Unicode/title validation is already enforced through
        # bookmarks and named destinations; avoid a false negative here.
        if title and not RTL_CHAR_RE.search(title) and title not in page_text[expected_page - 1]:
            raise ValidationError(
                f"Markdown heading missing from expected PDF page: "
                f"heading={title!r}, page={expected_page}"
            )


def validate_final_pdf(
    pdf_path: Path,
    document: Any,
    headings: list[Heading],
    toc_headings: list[Heading],
    title: str,
    heading_pages: dict[str, int],
    toc_pages: int,
) -> QualityReport:
    reader = PdfReader(str(pdf_path))
    portrait = 0
    landscape = 0
    rotated = 0

    for page_number, page in enumerate(reader.pages, start=1):
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        rotation = int(page.get("/Rotate", 0) or 0) % 360
        if width >= height:
            landscape += 1
            raise ValidationError(
                f"Landscape page detected: page={page_number}, width={width}, height={height}"
            )
        portrait += 1
        if rotation in (90, 270):
            rotated += 1
            raise ValidationError(
                f"Rotated page detected: page={page_number}, rotation={rotation}"
            )
        if (
            abs(width - A4_WIDTH_PT) > A4_TOLERANCE_PT
            or abs(height - A4_HEIGHT_PT) > A4_TOLERANCE_PT
        ):
            raise ValidationError(
                "Non-A4 page detected: "
                f"page={page_number}, width={width:.3f}, height={height:.3f}"
            )

    fonts = collect_fonts(reader)
    if not fonts:
        raise ValidationError("No PDF fonts were detected.")
    not_embedded = sorted(name for name, embedded in fonts.items() if not embedded)
    if not_embedded:
        raise ValidationError(f"Fonts are not embedded: {not_embedded}")
    unexpected = sorted(
        name
        for name in fonts
        if FONT_FAMILY not in name and FONT_FAMILY_BOLD not in name
    )
    if unexpected:
        raise ValidationError(f"Unexpected fallback fonts detected: {unexpected}")
    forbidden = sorted(name for name in fonts if FORBIDDEN_BASE_FONT_RE.search(name))
    if forbidden:
        raise ValidationError(f"Forbidden default fonts detected: {forbidden}")
    if not any(FONT_FAMILY_BOLD in name for name in fonts):
        raise ValidationError("Custom bold font was not embedded/used in the PDF.")

    toc_links, unresolved = validate_internal_links(
        reader, toc_headings, heading_pages, toc_pages
    )
    bookmark_count = validate_pdf_bookmarks(
        reader, headings, title, heading_pages
    )
    validate_page_numbers(reader)
    validate_headings_in_pdf(reader, headings, heading_pages)
    validate_weasy_layout(document, headings)

    return QualityReport(
        total_pages=len(reader.pages),
        toc_pages=toc_pages,
        markdown_headings=len(headings),
        toc_internal_links=toc_links,
        unresolved_links=unresolved,
        bookmarks=bookmark_count,
        embedded_fonts=tuple(sorted(fonts)),
        portrait_pages=portrait,
        landscape_pages=landscape,
        rotated_pages=rotated,
    )


def convert(input_path: Path, output_path: Path, font_path: Path, bold_path: Path) -> QualityReport:
    md_text = input_path.read_text(encoding="utf-8")
    body_html, headings = render_markdown(md_text)
    if not headings:
        raise ValidationError("Markdown contains no headings; a dynamic TOC cannot be built.")

    css = build_css(font_path, bold_path)
    full_html, toc_headings = build_html_document(
        md_text, body_html, headings, input_path, css
    )
    title = document_title(headings, input_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="note-maker-pdf-") as temp_dir:
        temp_dir_path = Path(temp_dir)
        raw_pdf = temp_dir_path / "rendered.pdf"
        candidate_pdf = temp_dir_path / "candidate.pdf"

        document = HTML(string=full_html, base_url=str(input_path.parent)).render()
        heading_pages = heading_page_map(document, headings)
        toc_pages = min(heading_pages.values()) - 1
        if toc_pages < 1:
            raise ValidationError(
                f"TOC pagination is invalid: calculated TOC pages={toc_pages}"
            )

        validate_weasy_links(document, toc_headings, heading_pages)
        validate_weasy_bookmarks(document, headings, title, heading_pages)
        validate_weasy_layout(document, headings)

        document.write_pdf(raw_pdf)
        add_decimal_page_labels(raw_pdf, candidate_pdf)
        report = validate_final_pdf(
            candidate_pdf,
            document,
            headings,
            toc_headings,
            title,
            heading_pages,
            toc_pages,
        )
        os.replace(candidate_pdf, output_path)
    return report


def print_success(input_path: Path, output_path: Path, report: QualityReport) -> None:
    print(f"Input Markdown: {input_path}")
    print(f"Final PDF: {output_path}")
    print(f"Total pages: {report.total_pages}")
    print(f"Table of Contents pages: {report.toc_pages}")
    print(f"Markdown headings: {report.markdown_headings}")
    print(f"TOC internal links: {report.toc_internal_links}")
    print(f"Unresolved links: {report.unresolved_links}")
    print(f"Bookmarks: {report.bookmarks}")
    print(f"Page number range: 1-{report.total_pages}")
    print("Embedded fonts: " + ", ".join(report.embedded_fonts))
    print("Page size: A4")
    print("Page orientation: Portrait")
    print(f"Portrait pages: {report.portrait_pages}")
    print(f"Landscape pages: {report.landscape_pages}")
    print(f"Rotated pages: {report.rotated_pages}")
    print("Quality check: PASSED")


def main() -> int:
    try:
        require_dependencies()
        args = parse_args()
        input_path, output_path, font_path, bold_path = resolve_paths(args)
        report = convert(input_path, output_path, font_path, bold_path)
        print_success(input_path, output_path, report)
        return 0
    except (ValidationError, UnicodeError, OSError, ValueError) as exc:
        print("Quality check: FAILED", file=sys.stderr)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - fail closed for PDF generation/QC
        print("Quality check: FAILED", file=sys.stderr)
        print(f"ERROR: unexpected failure: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
