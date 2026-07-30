#!/usr/bin/env python3
"""Strict automated quality control for FINAL_STUDY_NOTES.pdf."""
from __future__ import annotations
import argparse
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from PIL import Image, ImageChops
from pypdf import PdfReader
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject
from pdf_common import A4_HEIGHT, A4_TOLERANCE, A4_WIDTH, StudyIndex, find_index_file, iter_outline_items, parse_index, require_directory

FORBIDDEN_FONT_NAMES = ("helvetica", "times", "courier", "dejavu", "liberation", "noto", "vazir")
ALLOWED_FONT_NAMES = ("sfarabic", "sfpro", "study")


def _obj(value):
    return value.get_object() if hasattr(value, "get_object") else value


def _dest_page(reader: PdfReader, dest) -> int | None:
    try:
        if isinstance(dest, str):
            named = reader.named_destinations.get(dest)
            return reader.get_destination_page_number(named) if named else None
        dest = _obj(dest)
        if isinstance(dest, ArrayObject) and dest:
            target = dest[0]
            target = target.get_object() if hasattr(target, "get_object") else target
            for i, page in enumerate(reader.pages):
                if page.indirect_reference == (dest[0] if isinstance(dest[0], IndirectObject) else None):
                    return i
                if page == target:
                    return i
        return None
    except Exception:
        return None


def _outline(reader: PdfReader):
    rows = []
    for level, item in iter_outline_items(reader.outline):
        try: page = reader.get_destination_page_number(item)
        except Exception: page = -1
        rows.append((level, str(getattr(item, "title", item)), page))
    return rows


def _fonts(pdf: Path) -> list[dict]:
    result = subprocess.run(["pdffonts", str(pdf)], check=True, capture_output=True, text=True).stdout.splitlines()
    rows = []
    for line in result[2:]:
        parts = line.split()
        if len(parts) >= 7:
            rows.append({"name":parts[0], "type":" ".join(parts[1:-6]), "encoding":parts[-6], "emb":parts[-5], "sub":parts[-4], "uni":parts[-3]})
    return rows


def _page_footer_numbers(reader: PdfReader) -> tuple[list[int], list[int]]:
    ok=[]; bad=[]
    for page_no,page in enumerate(reader.pages,1):
        found=[]
        def visitor(text, cm, tm, font_dict, font_size):
            if text and tm and float(tm[5]) > float(page.mediabox.height) * 1.18:
                found.append(text.strip())
        try: page.extract_text(visitor_text=visitor)
        except Exception: pass
        tokens=[]
        for value in found:
            tokens.extend(re.findall(r"\d+", value.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))))
        if str(page_no) in tokens: ok.append(page_no)
        else: bad.append(page_no)
    return ok,bad



def _render_margin_scan(pdf_path: Path, expected_pages: int) -> tuple[int, list[int]]:
    renderer = shutil.which("pdftocairo") or shutil.which("pdftoppm")
    if not renderer:
        raise RuntimeError("pdftocairo or pdftoppm is required for the rendered layout QC")
    with tempfile.TemporaryDirectory() as tmp:
        prefix = Path(tmp) / "page"
        if Path(renderer).name == "pdftocairo":
            cmd = [renderer, "-png", "-r", "50", str(pdf_path), str(prefix)]
        else:
            cmd = [renderer, "-png", "-r", "50", str(pdf_path), str(prefix)]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        images = sorted(Path(tmp).glob("page-*.png"))
        if len(images) != expected_pages:
            raise RuntimeError(f"Rendered page count mismatch: {len(images)} != {expected_pages}")
        overflow = []
        for page_number, image_path in enumerate(images, 1):
            image = Image.open(image_path).convert("RGB")
            white = Image.new("RGB", image.size, "white")
            diff = ImageChops.difference(image, white).convert("L")
            mask = diff.point(lambda value: 255 if value > 10 else 0)
            bbox = mask.getbbox()
            if bbox is None:
                overflow.append(page_number)
                continue
            left, top, right, bottom = bbox
            margins = (left, image.width - right, top, image.height - bottom)
            if min(margins) < 2:
                overflow.append(page_number)
        return len(images), overflow

def verify_pdf(pdf_path: Path, model: StudyIndex, *, font_file: Path, font_bold_file: Path) -> dict:
    pdf_path=Path(pdf_path).resolve(); reader=PdfReader(pdf_path)
    failures=[]
    portrait=[]; landscape=[]; rotated=[]; wrong_size=[]
    for n,page in enumerate(reader.pages,1):
        w=float(page.mediabox.width); h=float(page.mediabox.height); r=int(page.get("/Rotate",0) or 0)%360
        if w < h: portrait.append(n)
        else: landscape.append(n)
        if r in (90,270): rotated.append(n)
        if abs(w-A4_WIDTH)>A4_TOLERANCE or abs(h-A4_HEIGHT)>A4_TOLERANCE: wrong_size.append(n)
    if landscape: failures.append(f"Landscape pages: {landscape}")
    if rotated: failures.append(f"Rotated pages: {rotated}")
    if wrong_size: failures.append(f"Non-A4 pages: {wrong_size}")

    rendered_pages, edge_overflow = _render_margin_scan(pdf_path, len(reader.pages))
    if edge_overflow: failures.append(f"Rendered content touches/crosses page edge: {edge_overflow}")

    outline=_outline(reader)
    session_outline=[x for x in outline if x[0]>=2 and re.match(r"\d{2}\.\s", x[1])]
    group_outline=[x for x in outline if x[0]==1]
    index_outline=[x for x in outline if x[0]==0 and "Study Index" in x[1]]
    if len(index_outline)!=1 or index_outline[0][2]!=0: failures.append("Study Index bookmark missing or invalid")
    if len(group_outline)!=len(model.groups): failures.append(f"Group bookmark count mismatch: {len(group_outline)} != {len(model.groups)}")
    if len(session_outline)!=len(model.sessions): failures.append(f"Session bookmark count mismatch: {len(session_outline)} != {len(model.sessions)}")
    expected_titles=[f"{s.order:02d}." for s in model.sessions]
    if [x[1].split()[0] for x in session_outline] != expected_titles: failures.append("Session bookmark order mismatch")
    starts=[x[2] for x in session_outline]
    if any(p<0 for p in starts): failures.append("Invalid bookmark destinations")
    index_pages=starts[0] if starts else 0

    link_targets=[]; unresolved=0; uri_local=0
    for page_index in range(min(index_pages,len(reader.pages))):
        for ref in reader.pages[page_index].get("/Annots") or []:
            annot=_obj(ref)
            if annot.get("/Subtype")!="/Link": continue
            action=_obj(annot.get("/A")) if annot.get("/A") else None
            if action and action.get("/S")=="/URI":
                uri=str(action.get("/URI",""))
                if uri.startswith(("note://","file://")): uri_local+=1
                continue
            dest=annot.get("/Dest")
            if dest is None and action and action.get("/S")=="/GoTo": dest=action.get("/D")
            target=_dest_page(reader,dest)
            if target is None: unresolved+=1
            else: link_targets.append(target)
    if uri_local: failures.append(f"Local URI links remain: {uri_local}")
    if unresolved: failures.append(f"Unresolved internal links: {unresolved}")
    unique_link_targets = sorted(set(link_targets))
    if len(unique_link_targets)!=len(model.sessions): failures.append(f"Linked session destination count mismatch: {len(unique_link_targets)} != {len(model.sessions)}")
    if starts and unique_link_targets!=sorted(starts): failures.append("Session link destinations do not match session starts")

    fonts=_fonts(pdf_path)
    if not fonts: failures.append("No fonts reported by pdffonts")
    for row in fonts:
        low=row["name"].casefold()
        if row["emb"].casefold()!="yes": failures.append(f"Font not embedded: {row['name']}")
        if any(x in low for x in FORBIDDEN_FONT_NAMES): failures.append(f"Forbidden fallback font: {row['name']}")
        if not any(x in low for x in ALLOWED_FONT_NAMES): failures.append(f"Unexpected font: {row['name']}")

    labels=list(reader.page_labels)
    expected_labels=[str(i) for i in range(1,len(reader.pages)+1)]
    if labels!=expected_labels: failures.append("PDF page labels are not continuous 1..N")
    footer_ok,footer_bad=_page_footer_numbers(reader)
    if footer_bad: failures.append(f"Visible footer page numbers missing/mismatched: {footer_bad}")

    page_bytes=pdf_path.read_bytes()
    if b"note://" in page_bytes: failures.append("Raw note:// marker remains in final PDF")
    if len(model.sessions)!=len(session_outline): failures.append("Session completeness check failed")

    result="PASSED" if not failures else "FAILED"
    names=", ".join(sorted({x['name'] for x in fonts})) or "—"
    text="\n".join([
        f"Final PDF: {pdf_path}",
        f"Total pages: {len(reader.pages)}",
        f"Study Index pages: {index_pages}",
        f"Sessions: {len(model.sessions)}",
        f"Groups: {len(model.groups)}",
        f"Converted internal links: {len(set(link_targets))}",
        f"Internal link annotations: {len(link_targets)}",
        f"Unresolved links: {unresolved}",
        f"Bookmarks: {len(outline)}",
        f"Page number range: 1-{len(reader.pages)}",
        f"Embedded fonts: {names}",
        "Page size: A4 (595.28 x 841.89 pt)",
        "Page orientation: Portrait",
        f"Portrait pages: {len(portrait)}",
        f"Landscape pages: {len(landscape)}",
        f"Rotated pages: {len(rotated)}",
        f"Orientation/rotation error pages: {sorted(set(landscape+rotated+wrong_size)) or 'none'}",
        f"Visible footer numbers verified: {len(footer_ok)}/{len(reader.pages)}",
        f"Rendered margin scan: {rendered_pages}/{len(reader.pages)}",
        f"Edge-overflow pages: {len(edge_overflow)}",
        f"Quality check: {result}",
    ] + (["Failures:"]+[f"- {x}" for x in failures] if failures else [])) + "\n"
    if failures: raise RuntimeError(text)
    return {"text":text, "index_pages":index_pages, "pages":len(reader.pages), "links":len(set(link_targets)), "link_annotations":len(link_targets), "bookmarks":len(outline), "fonts":fonts}


def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("pdf"); parser.add_argument("--notes-dir",required=True); parser.add_argument("--index-md"); parser.add_argument("--font-file",required=True); parser.add_argument("--font-bold-file",required=True)
    args=parser.parse_args(); notes=require_directory(Path(args.notes_dir),"NOTES_DIR"); index=find_index_file(notes,Path(args.index_md) if args.index_md else None); model=parse_index(index,notes)
    report=verify_pdf(Path(args.pdf),model,font_file=Path(args.font_file),font_bold_file=Path(args.font_bold_file)); print(report["text"]); return 0

if __name__=="__main__": raise SystemExit(main())
