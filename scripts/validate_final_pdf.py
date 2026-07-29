#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import fitz
from pypdf import PdfReader

from generate_study_index import group_sessions, parse_index
from pdf_common import A4_HEIGHT_PT, A4_WIDTH_PT, locate_index


def flatten_outline(items, depth=0):
    out = []
    for item in items:
        if isinstance(item, list):
            out.extend(flatten_outline(item, depth + 1))
        else:
            out.append((depth, getattr(item, "title", str(item))))
    return out


def collect_fonts(reader: PdfReader) -> tuple[set[str], set[str]]:
    embedded = set()
    unembedded = set()
    for page in reader.pages:
        resources = page.get("/Resources") or {}
        fonts = resources.get("/Font") or {}
        if hasattr(fonts, "get_object"):
            fonts = fonts.get_object()
        for ref in fonts.values():
            font = ref.get_object()
            base = str(font.get("/BaseFont", "unknown"))
            descendants = font.get("/DescendantFonts") or []
            descendant_embedded = False
            for dref in descendants:
                desc_font = dref.get_object()
                dbase = str(desc_font.get("/BaseFont", base))
                desc = desc_font.get("/FontDescriptor")
                if desc and hasattr(desc, "get_object"):
                    desc = desc.get_object()
                d_emb = bool(desc and any(k in desc for k in ("/FontFile", "/FontFile2", "/FontFile3")))
                descendant_embedded = descendant_embedded or d_emb
                (embedded if d_emb else unembedded).add(dbase)
            descriptor = font.get("/FontDescriptor")
            if descriptor and hasattr(descriptor, "get_object"):
                descriptor = descriptor.get_object()
            direct_embedded = bool(descriptor and any(k in descriptor for k in ("/FontFile", "/FontFile2", "/FontFile3")))
            if direct_embedded or descendant_embedded:
                embedded.add(base)
            elif not descendants:
                unembedded.add(base)
    unembedded -= embedded
    return embedded, unembedded


def count_internal_links(reader: PdfReader) -> tuple[int, int, list[str]]:
    internal = unresolved = 0
    note_uris = []
    for page in reader.pages:
        annots = page.get("/Annots") or []
        for ref in annots:
            annot = ref.get_object()
            if str(annot.get("/Subtype")) != "/Link":
                continue
            if annot.get("/Dest") is not None:
                internal += 1
                continue
            action = annot.get("/A")
            if action and hasattr(action, "get_object"):
                action = action.get_object()
            if action and str(action.get("/S")) == "/GoTo":
                internal += 1
            elif action and str(action.get("/S")) == "/URI":
                uri = str(action.get("/URI", ""))
                if uri.casefold().startswith("note://"):
                    note_uris.append(uri)
                    unresolved += 1
    return internal, unresolved, note_uris


def named_destinations(reader: PdfReader) -> set[str]:
    try:
        return set(reader.named_destinations.keys())
    except Exception:
        return set()


def validate(pdf_path: Path, notes_dir: Path, index_path: Path) -> dict:
    title, _overall_pages, sessions = parse_index(index_path, notes_dir)
    groups = group_sessions(sessions)
    reader = PdfReader(str(pdf_path))
    portrait_errors = []
    rotated_errors = []
    size_errors = []
    for i, page in enumerate(reader.pages, 1):
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        rotation = int(page.get("/Rotate", 0) or 0) % 360
        if width >= height:
            portrait_errors.append(i)
        if rotation in (90, 270):
            rotated_errors.append(i)
        if abs(width - A4_WIDTH_PT) > 2.0 or abs(height - A4_HEIGHT_PT) > 2.0:
            size_errors.append(i)

    embedded, unembedded = collect_fonts(reader)
    forbidden = {f for f in embedded | unembedded if any(x in f.casefold() for x in ("helvetica", "times", "courier", "dejavu", "noto", "liberation"))}
    internal_links, unresolved, note_uris = count_internal_links(reader)
    destinations = named_destinations(reader)
    expected_destinations = {s.anchor for s in sessions}
    missing_destinations = sorted(expected_destinations - destinations)
    first_session_page = None
    if sessions and sessions[0].anchor in reader.named_destinations:
        first_session_page = reader.get_destination_page_number(reader.named_destinations[sessions[0].anchor])
    study_index_pages = first_session_page if first_session_page is not None else 0

    expected_target_pages = {
        reader.get_destination_page_number(reader.named_destinations[s.anchor])
        for s in sessions if s.anchor in reader.named_destinations
    }
    doc_links = fitz.open(str(pdf_path))
    actual_index_targets = set()
    for pno in range(min(study_index_pages, doc_links.page_count)):
        for link in doc_links[pno].get_links():
            if link.get("kind") in (fitz.LINK_GOTO, fitz.LINK_NAMED) and isinstance(link.get("page"), int) and link["page"] >= 0:
                actual_index_targets.add(link["page"])
    doc_links.close()
    missing_link_targets = sorted(expected_target_pages - actual_index_targets)
    outline = flatten_outline(reader.outline)
    outline_titles = [outline_title for _, outline_title in outline]
    missing_group_bookmarks = [g for g in groups if g not in outline_titles]
    missing_session_bookmarks = [s.title for s in sessions if s.title not in outline_titles]

    labels = reader.page_labels
    expected_labels = [str(i) for i in range(1, len(reader.pages) + 1)]
    label_errors = [i + 1 for i, (a, b) in enumerate(zip(labels, expected_labels)) if a != b]
    if len(labels) != len(expected_labels):
        label_errors.extend(range(min(len(labels), len(expected_labels)) + 1, max(len(labels), len(expected_labels)) + 1))

    doc = fitz.open(str(pdf_path))
    out_of_bounds = []
    footer_collisions = []
    for i, page in enumerate(doc, 1):
        rect = page.rect
        for block in page.get_text("blocks"):
            x0, y0, x1, y1 = block[:4]
            if x0 < -0.5 or y0 < -0.5 or x1 > rect.width + 0.5 or y1 > rect.height + 0.5:
                out_of_bounds.append(i)
                break
        words = page.get_text("words")
        low_words = [w for w in words if w[1] > rect.height - 34 and str(w[4]).strip() and not re.fullmatch(r"\d+", str(w[4]).strip())]
        if low_words:
            footer_collisions.append(i)
    doc.close()

    critical = {
        "landscape_pages": portrait_errors,
        "rotated_pages": rotated_errors,
        "wrong_size_pages": size_errors,
        "unresolved_links": unresolved,
        "note_uris": note_uris,
        "missing_destinations": missing_destinations,
        "missing_link_targets": missing_link_targets,
        "missing_group_bookmarks": missing_group_bookmarks,
        "missing_session_bookmarks": missing_session_bookmarks,
        "page_label_errors": label_errors,
        "forbidden_fonts": sorted(forbidden),
        "unembedded_fonts": sorted(unembedded),
        "out_of_bounds_pages": sorted(set(out_of_bounds)),
        "footer_collision_pages": sorted(set(footer_collisions)),
    }
    passed = not any(bool(v) for v in critical.values()) and internal_links >= len(sessions)
    report = {
        "final_pdf": str(pdf_path),
        "course_title": title,
        "total_pages": len(reader.pages),
        "study_index_pages": study_index_pages,
        "sessions": len(sessions),
        "groups": len(groups),
        "converted_internal_links": internal_links,
        "unresolved_links": unresolved,
        "bookmarks": len(outline),
        "page_number_range": f"1-{len(reader.pages)}",
        "embedded_fonts": sorted(embedded),
        "unembedded_fonts": sorted(unembedded),
        "page_size": "A4",
        "page_orientation": "Portrait",
        "portrait_pages": len(reader.pages) - len(portrait_errors),
        "landscape_pages": len(portrait_errors),
        "rotated_pages": rotated_errors,
        "named_destinations": len(destinations),
        "quality_check": "PASSED" if passed else "FAILED",
        "critical": critical,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf")
    parser.add_argument("--notes-dir", required=True)
    parser.add_argument("--index")
    parser.add_argument("--json-output")
    args = parser.parse_args()
    notes_dir = Path(args.notes_dir).resolve()
    index_path = Path(args.index).resolve() if args.index else locate_index(notes_dir)
    report = validate(Path(args.pdf).resolve(), notes_dir, index_path)
    if args.json_output:
        Path(args.json_output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Final PDF: {report['final_pdf']}")
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
    print(f"Rotated pages: {len(report['rotated_pages'])}")
    print(f"Quality check: {report['quality_check']}")
    if report["quality_check"] != "PASSED":
        print(json.dumps(report["critical"], ensure_ascii=False, indent=2))
        return 2
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
