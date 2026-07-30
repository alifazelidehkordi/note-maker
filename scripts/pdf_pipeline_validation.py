#!/usr/bin/env python3
"""A4 portrait, annotation, font-embedding, and JSON validation helpers."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import unquote, urlparse

from pypdf import PdfReader

from pdf_pipeline_data import A4_HEIGHT_PT, A4_WIDTH_PT, Session


def aliases_from_uri(uri: str) -> set[str]:
    parsed = urlparse(uri)
    scheme = parsed.scheme.casefold()
    if scheme != "note":
        return set()
    raw = unquote((parsed.netloc + parsed.path).lstrip("/")).replace("\\", "/")
    name = raw.rsplit("/", 1)[-1].rstrip("/")
    if not name:
        return set()
    path = Path(name)
    return {name.casefold(), path.stem.casefold()}


def session_aliases(session: Session) -> set[str]:
    values = {session.stem, session.markdown_path.name}
    if session.pdf_path:
        values.update({session.pdf_path.stem, session.pdf_path.name})
    return {unquote(v).casefold() for v in values}


def check_a4_portrait(reader: PdfReader, tolerance: float = 2.0) -> dict:
    landscape: list[int] = []
    rotated: list[int] = []
    wrong_size: list[int] = []
    sizes: set[tuple[float, float]] = set()
    for page_number, page in enumerate(reader.pages, 1):
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        rotation = int(page.get("/Rotate", 0) or 0) % 360
        sizes.add((round(width, 3), round(height, 3)))
        if width >= height:
            landscape.append(page_number)
        if rotation in (90, 270):
            rotated.append(page_number)
        if abs(width - A4_WIDTH_PT) > tolerance or abs(height - A4_HEIGHT_PT) > tolerance:
            wrong_size.append(page_number)
    return {"landscape": landscape, "rotated": rotated, "wrong_size": wrong_size, "sizes": sorted(sizes)}


def validate_component_pdf(path: Path) -> int:
    reader = PdfReader(path)
    result = check_a4_portrait(reader)
    if result["landscape"] or result["rotated"] or result["wrong_size"]:
        raise RuntimeError(
            f"Invalid component PDF geometry: {path.name}; landscape={result['landscape']}, rotated={result['rotated']}, wrong_size={result['wrong_size']}"
        )
    if not reader.pages:
        raise RuntimeError(f"Component PDF has no pages: {path}")
    return len(reader.pages)


def collect_embedded_fonts(reader: PdfReader) -> tuple[set[str], list[str], list[str]]:
    names: set[str] = set()
    unembedded: list[str] = []
    undesired: list[str] = []
    bad_tokens = ("helvetica", "times", "courier", "dejavu", "liberation", "noto", "arial", "calibri")
    visited: set[int] = set()

    def inspect_font(font_obj) -> None:
        try:
            obj = font_obj.get_object()
        except Exception:
            obj = font_obj
        marker = id(obj)
        if marker in visited:
            return
        visited.add(marker)
        subtype = str(obj.get("/Subtype", ""))
        base = str(obj.get("/BaseFont", "Unknown")).lstrip("/")
        names.add(base)
        lower = base.casefold()
        if any(token in lower for token in bad_tokens):
            undesired.append(base)
        if subtype == "/Type0":
            descendants = obj.get("/DescendantFonts") or []
            for descendant in descendants:
                inspect_font(descendant)
            return
        descriptor = obj.get("/FontDescriptor")
        if descriptor:
            descriptor = descriptor.get_object()
            if not any(descriptor.get(key) for key in ("/FontFile", "/FontFile2", "/FontFile3")):
                unembedded.append(base)
        elif subtype not in {"/Type3"}:
            unembedded.append(base)

    for page in reader.pages:
        resources = page.get("/Resources")
        if not resources:
            continue
        resources = resources.get_object()
        fonts = resources.get("/Font") or {}
        fonts = fonts.get_object() if hasattr(fonts, "get_object") else fonts
        for font_ref in fonts.values():
            inspect_font(font_ref)
    return names, sorted(set(unembedded)), sorted(set(undesired))


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
