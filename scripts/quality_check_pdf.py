#!/usr/bin/env python3
"""Acceptance-critical quality checks for the final combined study PDF."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Iterable

from pypdf import PdfReader
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject

from pdf_utils import (
    A4_HEIGHT_PT,
    A4_TOLERANCE_PT,
    A4_WIDTH_PT,
    PipelineError,
    StudyIndexData,
    find_index_file,
    parse_study_index,
)

try:
    import fitz  # PyMuPDF: positional footer/layout verification
except ModuleNotFoundError:  # pragma: no cover
    fitz = None

FORBIDDEN_FONT_RE = re.compile(r"(?:Helvetica|Times|Courier)(?:$|[-,])", re.I)
SUBSET_PREFIX_RE = re.compile(r"^[A-Z]{6}\+")


def _object(value: Any) -> Any:
    return value.get_object() if hasattr(value, "get_object") else value


def _destination_page(reader: PdfReader, destination: Any) -> int | None:
    if destination is None:
        return None
    if isinstance(destination, str):
        named = reader.named_destinations.get(destination)
        return reader.get_destination_page_number(named) if named is not None else None
    if hasattr(destination, "title") and hasattr(destination, "page"):
        try:
            return reader.get_destination_page_number(destination)
        except Exception:
            return None
    if isinstance(destination, (ArrayObject, list, tuple)) and destination:
        target = _object(destination[0])
        target_ref = getattr(destination[0], "idnum", None)
        for index, page in enumerate(reader.pages):
            page_ref = getattr(page, "indirect_reference", None)
            if target_ref is not None and page_ref is not None:
                if destination[0].idnum == page_ref.idnum and destination[0].generation == page_ref.generation:
                    return index
            if target is page:
                return index
    return None


def _font_descriptor(font: DictionaryObject) -> DictionaryObject | None:
    font = _object(font)
    descriptor = font.get("/FontDescriptor")
    if descriptor:
        return _object(descriptor)
    descendants = font.get("/DescendantFonts") or []
    for descendant in descendants:
        descriptor = _object(descendant).get("/FontDescriptor")
        if descriptor:
            return _object(descriptor)
    return None


def _font_name(font: DictionaryObject) -> str:
    font = _object(font)
    name = font.get("/BaseFont")
    if not name:
        descendants = font.get("/DescendantFonts") or []
        if descendants:
            name = _object(descendants[0]).get("/BaseFont")
    return str(name or "Unknown").lstrip("/")


def _font_is_embedded(font: DictionaryObject) -> bool:
    descriptor = _font_descriptor(font)
    if not descriptor:
        return False
    return any(descriptor.get(key) is not None for key in ("/FontFile", "/FontFile2", "/FontFile3"))


def _walk_resources(resources: Any, seen: set[tuple[int, int]] | None = None) -> Iterable[DictionaryObject]:
    seen = seen or set()
    resources = _object(resources)
    if not isinstance(resources, DictionaryObject):
        return
    fonts = _object(resources.get("/Font") or {})
    for font_ref in fonts.values():
        if isinstance(font_ref, IndirectObject):
            ref_key = (font_ref.idnum, font_ref.generation)
            if ref_key in seen:
                continue
            seen.add(ref_key)
        yield _object(font_ref)
    xobjects = _object(resources.get("/XObject") or {})
    for xobject_ref in xobjects.values():
        xobject = _object(xobject_ref)
        nested = xobject.get("/Resources") if isinstance(xobject, DictionaryObject) else None
        if nested:
            yield from _walk_resources(nested, seen)


def inspect_fonts(reader: PdfReader) -> tuple[list[str], list[str], list[str], list[str]]:
    raw_names: set[str] = set()
    unembedded: set[str] = set()
    forbidden: set[str] = set()
    unexpected: set[str] = set()
    for page in reader.pages:
        for font in _walk_resources(page.get("/Resources") or {}):
            name = _font_name(font)
            raw_names.add(name)
            if not _font_is_embedded(font):
                unembedded.add(name)
            normalized = SUBSET_PREFIX_RE.sub("", name)
            if FORBIDDEN_FONT_RE.search(normalized):
                forbidden.add(name)
            if not normalized.startswith(("StudyRegular", "StudyBold")):
                unexpected.add(name)
    normalized_names = sorted({SUBSET_PREFIX_RE.sub("", name) for name in raw_names})
    return normalized_names, sorted(unembedded), sorted(forbidden), sorted(unexpected)


def flatten_outline(reader: PdfReader) -> list[tuple[int, str, int | None]]:
    flattened: list[tuple[int, str, int | None]] = []

    def walk(items: list[Any], level: int) -> None:
        for item in items:
            if isinstance(item, list):
                walk(item, level + 1)
                continue
            title = str(getattr(item, "title", item.get("/Title", "")))
            try:
                page = reader.get_destination_page_number(item)
            except Exception:
                page = None
            flattened.append((level, title, page))

    walk(reader.outline, 0)
    return flattened


def _expected_outline(data: StudyIndexData, named_pages: dict[str, int]) -> list[tuple[int, str, int]]:
    expected: list[tuple[int, str, int]] = [(0, "فهرست مطالعه / Study Index", 0)]
    for group in data.groups:
        first = group.sessions[0]
        expected.append((0, group.title, named_pages[first.anchor]))
        for session in group.sessions:
            expected.append((1, session.title, named_pages[session.anchor]))
    return expected


def _link_destination(annotation: DictionaryObject) -> Any:
    annotation = _object(annotation)
    if annotation.get("/Dest") is not None:
        return annotation.get("/Dest")
    action = _object(annotation.get("/A") or {})
    if action.get("/S") == "/GoTo":
        return action.get("/D")
    return None


def inspect_links(
    reader: PdfReader,
    data: StudyIndexData,
    index_pages: int,
    named_pages: dict[str, int],
) -> tuple[int, int, list[str], list[str]]:
    expected_anchors = {session.anchor for session in data.sessions}
    annotation_count = 0
    unique_linked: set[str] = set()
    unresolved: list[str] = []
    mismatched: list[str] = []
    for page_index, page in enumerate(reader.pages):
        annotations = page.get("/Annots") or []
        for annotation_ref in annotations:
            annotation = _object(annotation_ref)
            if annotation.get("/Subtype") != "/Link":
                continue
            action = _object(annotation.get("/A") or {})
            if action.get("/S") == "/URI":
                uri = str(action.get("/URI", ""))
                if uri.casefold().startswith("note://"):
                    unresolved.append(uri)
                continue
            destination = _link_destination(annotation)
            if destination is None:
                continue
            anchor = str(destination)
            if anchor not in expected_anchors:
                continue
            annotation_count += 1
            unique_linked.add(anchor)
            target = _destination_page(reader, destination)
            if page_index >= index_pages:
                mismatched.append(f"{anchor}: link annotation is outside Study Index (page {page_index + 1})")
            if target != named_pages[anchor]:
                mismatched.append(
                    f"{anchor}: annotation target page {None if target is None else target + 1} "
                    f"!= destination page {named_pages[anchor] + 1}"
                )
    missing = sorted(expected_anchors - unique_linked)
    return annotation_count, len(unique_linked), unresolved + missing, mismatched


def inspect_footer_and_bounds(pdf_path: Path, total_pages: int) -> tuple[list[int], list[str]]:
    if fitz is None:
        return [], ["PyMuPDF unavailable; footer-position and block-bound checks were skipped"]
    doc = fitz.open(pdf_path)
    missing_footers: list[int] = []
    layout_issues: list[str] = []
    for index, page in enumerate(doc, 1):
        rect = page.rect
        blocks = page.get_text("blocks")
        footer_blocks = []
        for block in blocks:
            x0, y0, x1, y1, text = block[:5]
            if x0 < -1 or y0 < -1 or x1 > rect.width + 1 or y1 > rect.height + 1:
                layout_issues.append(
                    f"Page {index}: text block outside MediaBox ({x0:.1f}, {y0:.1f}, {x1:.1f}, {y1:.1f})"
                )
            if y0 >= rect.height - 45 and text.strip() == str(index):
                footer_blocks.append((x0, y0, x1, y1))
        if not footer_blocks:
            missing_footers.append(index)
            continue
        footer = min(footer_blocks, key=lambda item: abs(((item[0] + item[2]) / 2) - rect.width / 2))
        center = (footer[0] + footer[2]) / 2
        if abs(center - rect.width / 2) > 22:
            layout_issues.append(f"Page {index}: footer number is not centered")
        for block in blocks:
            x0, y0, x1, y1, text = block[:5]
            if text.strip() == str(index) and y0 >= rect.height - 45:
                continue
            intersects = not (x1 <= footer[0] or x0 >= footer[2] or y1 <= footer[1] or y0 >= footer[3])
            if intersects:
                layout_issues.append(f"Page {index}: footer overlaps another text block")
                break
    doc.close()
    return missing_footers, layout_issues


def _write_report(report: dict[str, Any], report_path: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    text_path = report_path.with_suffix(".txt")
    fonts = ", ".join(report.get("embedded_fonts", [])) or "—"
    lines = [
        f"Final PDF: {report['final_pdf']}",
        f"Total pages: {report['total_pages']}",
        f"Study Index pages: {report['study_index_pages']}",
        f"Sessions: {report['sessions']}",
        f"Groups: {report['groups']}",
        f"Converted internal link annotations: {report['converted_internal_links']}",
        f"Unique linked sessions: {report['unique_linked_sessions']}",
        f"Unresolved links: {report['unresolved_links']}",
        f"Bookmarks: {report['bookmarks']}",
        f"Page number range: 1-{report['total_pages']}",
        f"Embedded fonts: {fonts}",
        "Page size: A4",
        "Page orientation: Portrait",
        f"Portrait pages: {report['portrait_pages']}",
        f"Landscape pages: {report['landscape_pages']}",
        f"Rotated pages: {report['rotated_pages']}",
        f"Quality check: {report['quality_check']}",
    ]
    if report.get("failures"):
        lines.append("Failures:")
        lines.extend(f"- {item}" for item in report["failures"])
    if report.get("warnings"):
        lines.append("Warnings:")
        lines.extend(f"- {item}" for item in report["warnings"])
    text_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_quality_checks(
    pdf_path: Path,
    data: StudyIndexData,
    *,
    report_path: Path | None = None,
    raise_on_failure: bool = True,
) -> dict[str, Any]:
    pdf_path = Path(pdf_path).resolve()
    if not pdf_path.is_file() or pdf_path.stat().st_size == 0:
        raise FileNotFoundError(f"Final PDF does not exist or is empty: {pdf_path}")
    reader = PdfReader(pdf_path)
    total_pages = len(reader.pages)
    failures: list[str] = []
    warnings: list[str] = []

    landscape_pages: list[int] = []
    rotated_pages: list[int] = []
    non_a4_pages: list[int] = []
    portrait_pages = 0
    for page_number, page in enumerate(reader.pages, 1):
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        rotation = int(page.get("/Rotate", 0) or 0) % 360
        if width >= height:
            landscape_pages.append(page_number)
        else:
            portrait_pages += 1
        if rotation in (90, 270):
            rotated_pages.append(page_number)
        if abs(width - A4_WIDTH_PT) > A4_TOLERANCE_PT or abs(height - A4_HEIGHT_PT) > A4_TOLERANCE_PT:
            non_a4_pages.append(page_number)
    if landscape_pages:
        failures.append(f"Landscape pages: {landscape_pages}")
    if rotated_pages:
        failures.append(f"Pages rotated 90/270 degrees: {rotated_pages}")
    if non_a4_pages:
        failures.append(f"Pages outside A4 tolerance: {non_a4_pages}")

    named_pages: dict[str, int] = {}
    for session in data.sessions:
        destination = reader.named_destinations.get(session.anchor)
        if destination is None:
            failures.append(f"Missing named destination: {session.anchor} ({session.title})")
            continue
        page = reader.get_destination_page_number(destination)
        if page < 0 or page >= total_pages:
            failures.append(f"Invalid destination page for {session.anchor}: {page}")
        else:
            named_pages[session.anchor] = page
    if len(named_pages) != len(data.sessions):
        index_pages = 0
    else:
        first_pages = [named_pages[session.anchor] for session in data.sessions]
        if first_pages != sorted(first_pages) or len(set(first_pages)) != len(first_pages):
            failures.append("Session destinations are duplicated or not in Index order")
        index_pages = first_pages[0]
        if index_pages < 1:
            failures.append("Study Index must occupy at least one page before session 1")

    converted = unique_links = 0
    unresolved: list[str] = []
    mismatched_links: list[str] = []
    if len(named_pages) == len(data.sessions):
        converted, unique_links, unresolved, mismatched_links = inspect_links(
            reader, data, index_pages, named_pages
        )
        if unresolved:
            failures.append(f"Unresolved or missing session links: {unresolved}")
        if mismatched_links:
            failures.extend(mismatched_links)
        if unique_links != len(data.sessions):
            failures.append(
                f"Only {unique_links}/{len(data.sessions)} sessions have a clickable index title"
            )

    try:
        raw_bytes = pdf_path.read_bytes()
        if b"note://" in raw_bytes.lower():
            failures.append("Raw note:// marker remains in the final PDF")
    except OSError as exc:
        failures.append(f"Could not scan PDF bytes: {exc}")

    outline = flatten_outline(reader)
    if len(named_pages) == len(data.sessions):
        expected_outline = _expected_outline(data, named_pages)
        if len(outline) != len(expected_outline):
            failures.append(
                f"Bookmark count mismatch: expected {len(expected_outline)}, got {len(outline)}"
            )
        for index, expected in enumerate(expected_outline):
            if index >= len(outline):
                break
            actual = outline[index]
            if actual != expected:
                failures.append(f"Bookmark mismatch at position {index + 1}: expected {expected}, got {actual}")
                break

    labels = reader.page_labels
    expected_labels = [str(number) for number in range(1, total_pages + 1)]
    if labels != expected_labels:
        failures.append("PDF page labels are not the continuous decimal range 1..N")

    embedded_fonts, unembedded_fonts, forbidden_fonts, unexpected_fonts = inspect_fonts(reader)
    if not embedded_fonts:
        failures.append("No embedded fonts were detected")
    if unembedded_fonts:
        failures.append(f"Unembedded fonts detected: {unembedded_fonts}")
    if forbidden_fonts:
        failures.append(f"Forbidden fallback fonts detected: {forbidden_fonts}")
    if unexpected_fonts:
        failures.append(f"Fonts not supplied through FONT_FILE/FONT_BOLD_FILE detected: {unexpected_fonts}")

    missing_footers, layout_issues = inspect_footer_and_bounds(pdf_path, total_pages)
    if missing_footers:
        failures.append(f"Missing or unreadable printed footer numbers on pages: {missing_footers}")
    if layout_issues:
        failures.extend(layout_issues[:30])
        if len(layout_issues) > 30:
            failures.append(f"...and {len(layout_issues) - 30} additional layout issues")

    report = {
        "final_pdf": str(pdf_path),
        "total_pages": total_pages,
        "study_index_pages": index_pages,
        "sessions": len(data.sessions),
        "groups": len(data.groups),
        "converted_internal_links": converted,
        "unique_linked_sessions": unique_links,
        "unresolved_links": len(unresolved),
        "bookmarks": len(outline),
        "page_number_range": f"1-{total_pages}",
        "embedded_fonts": embedded_fonts,
        "unembedded_fonts": unembedded_fonts,
        "forbidden_fonts": forbidden_fonts,
        "unexpected_fonts": unexpected_fonts,
        "page_width_pt": float(reader.pages[0].mediabox.width) if total_pages else None,
        "page_height_pt": float(reader.pages[0].mediabox.height) if total_pages else None,
        "page_size": "A4",
        "orientation": "Portrait",
        "portrait_pages": portrait_pages,
        "landscape_pages": len(landscape_pages),
        "landscape_page_numbers": landscape_pages,
        "rotated_pages": len(rotated_pages),
        "rotated_page_numbers": rotated_pages,
        "non_a4_page_numbers": non_a4_pages,
        "missing_footer_pages": missing_footers,
        "failures": failures,
        "warnings": warnings,
        "quality_check": "PASSED" if not failures else "FAILED",
    }
    report_path = Path(report_path).resolve() if report_path else pdf_path.with_suffix(".qa.json")
    _write_report(report, report_path)
    if failures and raise_on_failure:
        raise PipelineError("PDF quality check failed:\n- " + "\n- ".join(failures))
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate the final study-book PDF")
    parser.add_argument("pdf")
    parser.add_argument("--notes-dir", required=True)
    parser.add_argument("--index-md")
    parser.add_argument("--report")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        notes_dir = Path(args.notes_dir).resolve()
        index_path = find_index_file(notes_dir, Path(args.index_md) if args.index_md else None)
        data = parse_study_index(index_path, notes_dir)
        report = run_quality_checks(
            Path(args.pdf),
            data,
            report_path=Path(args.report) if args.report else None,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
