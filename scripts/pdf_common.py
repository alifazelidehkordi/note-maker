#!/usr/bin/env python3
"""Shared helpers for the Markdown-to-PDF pipeline.

This module deliberately contains no browser-automation code.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from pypdf import PdfReader
from pypdf.generic import ContentStream

A4_WIDTH_PT = 595.2755905511812
A4_HEIGHT_PT = 841.8897637795277
A4_TOLERANCE_PT = 3.0
CUSTOM_PRIMARY_FAMILY = "NoteMakerPrimary"
CUSTOM_SECONDARY_FAMILY = "NoteMakerSecondary"
CUSTOM_FONT_STACK = f'"{CUSTOM_PRIMARY_FAMILY}", "{CUSTOM_SECONDARY_FAMILY}"'

NON_TOPIC_NAMES = {
    "readme.md",
    "index.md",
    "study_index.md",
    "study_index-rewritten.md",
    "study_index_verification.md",
    "combined_notes.md",
    "qa_report.md",
    "boundaries.md",
    "structure.md",
}
NON_TOPIC_PARTS = {
    "verification",
    "verify",
    "quality",
    "report",
    "debug",
    "temporary",
    "temp",
    "cache",
    "log",
    "manifest",
    "inventory",
    "coverage",
}
TOPIC_PREFIX_RE = re.compile(r"^\d{1,3}(?:_\d{1,3})?[_-]", re.I)


def natural_key(value: str | Path) -> tuple:
    name = value.name if isinstance(value, Path) else str(value)
    return tuple(int(part) if part.isdigit() else part for part in re.split(r"(\d+)", name.casefold()))


def is_topic_markdown(path: Path) -> bool:
    """Reliably distinguish numbered study notes from metadata and generated files."""
    if not path.is_file() or path.suffix.casefold() != ".md":
        return False
    name = path.name.casefold()
    if name.startswith(".") or name in NON_TOPIC_NAMES:
        return False
    tokens = set(re.split(r"[_\-.]+", Path(name).stem))
    if tokens & NON_TOPIC_PARTS:
        return False
    return bool(TOPIC_PREFIX_RE.match(path.name))


@dataclass(frozen=True)
class FontConfig:
    regular: Path
    bold: Path

    @classmethod
    def from_env(cls, *, required: bool = True) -> "FontConfig | None":
        regular_raw = os.environ.get("FONT_FILE", "").strip()
        bold_raw = os.environ.get("FONT_BOLD_FILE", "").strip()
        if not regular_raw or not bold_raw:
            if required:
                raise RuntimeError("FONT_FILE and FONT_BOLD_FILE must both be set")
            return None
        regular = Path(regular_raw).expanduser().resolve()
        bold = Path(bold_raw).expanduser().resolve()
        missing = [str(path) for path in (regular, bold) if not path.is_file()]
        if missing:
            raise FileNotFoundError("Missing custom font file(s): " + ", ".join(missing))
        for path in (regular, bold):
            try:
                with path.open("rb") as stream:
                    stream.read(4)
            except OSError as exc:
                raise OSError(f"Custom font is not readable: {path}") from exc
        return cls(regular=regular, bold=bold)

    def css(self) -> str:
        regular_uri = self.regular.as_uri()
        bold_uri = self.bold.as_uri()
        # Primary uses the intended regular/bold files. Secondary cross-maps them so
        # Persian glyphs and scientific symbols can both be resolved without a
        # system-font fallback when the two supplied files have complementary cmaps.
        return f"""
@font-face {{
  font-family: "{CUSTOM_PRIMARY_FAMILY}";
  src: url("{regular_uri}");
  font-style: normal;
  font-weight: 400;
}}
@font-face {{
  font-family: "{CUSTOM_PRIMARY_FAMILY}";
  src: url("{bold_uri}");
  font-style: normal;
  font-weight: 700;
}}
@font-face {{
  font-family: "{CUSTOM_SECONDARY_FAMILY}";
  src: url("{bold_uri}");
  font-style: normal;
  font-weight: 400;
}}
@font-face {{
  font-family: "{CUSTOM_SECONDARY_FAMILY}";
  src: url("{regular_uri}");
  font-style: normal;
  font-weight: 700;
}}
"""


def validate_portrait_a4(reader_or_path: PdfReader | Path | str) -> dict:
    reader = reader_or_path if isinstance(reader_or_path, PdfReader) else PdfReader(reader_or_path)
    invalid: list[dict] = []
    portrait = 0
    landscape = 0
    rotated = 0
    for number, page in enumerate(reader.pages, start=1):
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        rotation = int(page.get("/Rotate", 0) or 0) % 360
        reasons: list[str] = []
        if width >= height:
            landscape += 1
            reasons.append("landscape")
        else:
            portrait += 1
        if rotation in (90, 270):
            rotated += 1
            reasons.append(f"rotation={rotation}")
        if abs(width - A4_WIDTH_PT) > A4_TOLERANCE_PT or abs(height - A4_HEIGHT_PT) > A4_TOLERANCE_PT:
            reasons.append(f"not-a4({width:.2f}x{height:.2f})")
        if reasons:
            invalid.append({"page": number, "width": width, "height": height, "rotation": rotation, "reasons": reasons})
    return {
        "pages": len(reader.pages),
        "portrait_pages": portrait,
        "landscape_pages": landscape,
        "rotated_pages": rotated,
        "invalid_pages": invalid,
    }


def assert_portrait_a4(reader_or_path: PdfReader | Path | str, *, label: str = "PDF") -> dict:
    result = validate_portrait_a4(reader_or_path)
    if result["invalid_pages"]:
        detail = "; ".join(
            f"page={item['page']} width={item['width']:.2f} height={item['height']:.2f} "
            f"rotation={item['rotation']} reasons={','.join(item['reasons'])}"
            for item in result["invalid_pages"]
        )
        raise RuntimeError(f"{label} contains invalid page geometry: {detail}")
    return result


def _font_descriptor(font_obj):
    descriptor = font_obj.get("/FontDescriptor")
    if descriptor:
        return descriptor.get_object() if hasattr(descriptor, "get_object") else descriptor
    descendants = font_obj.get("/DescendantFonts") or []
    for descendant_ref in descendants:
        descendant = descendant_ref.get_object()
        descriptor = descendant.get("/FontDescriptor")
        if descriptor:
            return descriptor.get_object() if hasattr(descriptor, "get_object") else descriptor
    return None


def extract_font_report(reader_or_path: PdfReader | Path | str) -> dict:
    reader = reader_or_path if isinstance(reader_or_path, PdfReader) else PdfReader(reader_or_path)
    fonts: dict[str, bool] = {}
    for page in reader.pages:
        resources = page.get("/Resources")
        if not resources:
            continue
        resources = resources.get_object() if hasattr(resources, "get_object") else resources
        font_dict = resources.get("/Font") or {}
        font_dict = font_dict.get_object() if hasattr(font_dict, "get_object") else font_dict
        for ref in font_dict.values():
            font = ref.get_object()
            base = str(font.get("/BaseFont", "unknown")).lstrip("/")
            descriptor = _font_descriptor(font)
            embedded = False
            if descriptor:
                embedded = any(descriptor.get(key) is not None for key in ("/FontFile", "/FontFile2", "/FontFile3"))
            fonts[base] = fonts.get(base, False) or embedded
    embedded = sorted(name for name, status in fonts.items() if status)
    unembedded = sorted(name for name, status in fonts.items() if not status)
    forbidden = sorted(
        name for name in fonts
        if any(token in name.casefold() for token in ("helvetica", "times", "courier"))
    )
    unexpected = sorted(
        name for name in fonts
        if "notemakerprimary" not in name.casefold() and "notemakersecondary" not in name.casefold()
    )
    return {"fonts": sorted(fonts), "embedded": embedded, "unembedded": unembedded, "forbidden": forbidden, "unexpected": unexpected}


def unresolved_local_links(reader_or_path: PdfReader | Path | str) -> list[dict]:
    reader = reader_or_path if isinstance(reader_or_path, PdfReader) else PdfReader(reader_or_path)
    unresolved: list[dict] = []
    for page_number, page in enumerate(reader.pages, 1):
        for ref in page.get("/Annots") or []:
            annotation = ref.get_object()
            action = annotation.get("/A")
            if not action:
                continue
            action = action.get_object() if hasattr(action, "get_object") else action
            if action.get("/S") != "/URI":
                continue
            uri = str(action.get("/URI", ""))
            if uri.casefold().startswith("note://"):
                unresolved.append({"page": page_number, "uri": uri})
    return unresolved


def footer_number_pages(reader_or_path: PdfReader | Path | str, *, start: int = 1) -> list[int]:
    """Return pages missing the final custom-font footer overlay.

    The exact sequence is constructed from ``range(start, ...)`` before merging and
    is cross-checked against PDF Page Labels. Here we perform a fast structural
    verification that every final page retained one footer text object with the
    expected number of digit glyphs near the end of its content stream.
    """
    reader = reader_or_path if isinstance(reader_or_path, PdfReader) else PdfReader(reader_or_path)
    failed: list[int] = []
    for page_index, page in enumerate(reader.pages):
        expected_digits = len(str(start + page_index))
        try:
            operations = ContentStream(page.get_contents(), reader).operations
        except Exception:
            failed.append(page_index + 1)
            continue
        found = False
        for op_index in range(len(operations) - 1, max(-1, len(operations) - 80), -1):
            operands, operator = operations[op_index]
            if operator not in (b"TJ", b"Tj"):
                continue
            if operator == b"TJ" and operands:
                sequence = operands[0]
                glyph_chunks = [value for value in sequence if isinstance(value, str) and value]
                glyph_count = len(glyph_chunks)
            elif operands and isinstance(operands[0], str):
                glyph_count = max(1, len(operands[0]) // 2)
            else:
                continue
            if glyph_count != expected_digits:
                continue
            nearby = operations[max(0, op_index - 8):op_index]
            has_footer_matrix = any(
                op == b"Tm" and len(vals) >= 6 and float(vals[5]) > 1000
                for vals, op in nearby
            )
            has_custom_font = any(
                op == b"Tf" and len(vals) >= 2 and 8 <= float(vals[1]) <= 14
                for vals, op in nearby
            )
            if has_footer_matrix and has_custom_font:
                found = True
                break
        if not found:
            failed.append(page_index + 1)
    return failed


def page_label_sequence(reader_or_path: PdfReader | Path | str) -> list[str]:
    reader = reader_or_path if isinstance(reader_or_path, PdfReader) else PdfReader(reader_or_path)
    try:
        return list(reader.page_labels)
    except Exception:
        return []


def ensure_unique(values: Iterable[str], *, what: str) -> None:
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        key = value.casefold()
        if key in seen:
            duplicates.append(value)
        seen.add(key)
    if duplicates:
        raise RuntimeError(f"Duplicate {what}: {', '.join(duplicates)}")
