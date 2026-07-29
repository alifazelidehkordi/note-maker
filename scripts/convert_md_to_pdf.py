#!/usr/bin/env python3
"""Convert numbered Markdown study notes to custom-font A4 portrait PDFs."""
from __future__ import annotations

import argparse
import html
import re
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    from weasyprint import HTML
except (ModuleNotFoundError, OSError) as exc:  # pragma: no cover
    HTML = None
    _WEASYPRINT_ERROR = exc
else:
    _WEASYPRINT_ERROR = None

from pdf_utils import (
    FontBundle,
    PipelineError,
    build_document_css,
    clean_markdown,
    html_escape,
    is_topic_note,
    load_font_bundle,
    markdown_to_html,
    natural_key,
    strip_first_h1,
)

H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.M)


@dataclass(frozen=True)
class BatchResult:
    created: list[Path]
    failed: list[tuple[Path, str]]

    @property
    def succeeded(self) -> bool:
        return not self.failed


@dataclass(frozen=True)
class PdfStyle:
    """Compatibility style object; the acceptance-critical page size is fixed."""

    page_size: str = "A4"
    margin: str = "portrait-safe"
    font_size: str = "9.65pt"
    line_height: str = "1.46"
    font_family: str = "custom-only"
    theme: str = "medical-blue"
    preset: str = "study"
    rtl: bool = False
    page_numbers: bool = True


def require_dependencies() -> None:
    if HTML is None:
        detail = f": {_WEASYPRINT_ERROR}" if _WEASYPRINT_ERROR else ""
        raise PipelineError(f"WeasyPrint is required to create PDFs{detail}")


def infer_title(md_text: str, fallback: str, *, cleaned: bool = False) -> str:
    text = md_text if cleaned else clean_markdown(md_text)
    match = H1_RE.search(text)
    return match.group(1).strip() if match else fallback


def find_rich_index_md(notes_dir: Path) -> Path | None:
    for name in ("INDEX.md", "STUDY_INDEX.md", "STUDY_INDEX-rewritten.md"):
        for candidate in (Path(notes_dir) / name, Path(notes_dir).parent / name):
            if candidate.is_file():
                return candidate.resolve()
    return None


def build_css(
    style: PdfStyle | None = None,
    extra_css: str | None = None,
    css_file: Path | None = None,
    *,
    fonts: FontBundle | None = None,
    course_title: str = "Study Notes",
) -> str:
    del style
    fonts = fonts or load_font_bundle()
    appended = ""
    if css_file:
        css_file = Path(css_file).resolve()
        if not css_file.is_file():
            raise FileNotFoundError(f"CSS file not found: {css_file}")
        appended += css_file.read_text(encoding="utf-8")
    if extra_css:
        appended += "\n" + extra_css
    return build_document_css(fonts, course_title, appended)


def md_to_html(md_text: str, *, cleaned: bool = False) -> str:
    return markdown_to_html(md_text if cleaned else clean_markdown(md_text))


def _single_note_html(
    md_path: Path,
    *,
    title: str,
    course_title: str,
    css: str,
) -> str:
    body = markdown_to_html(strip_first_h1(md_path.read_text(encoding="utf-8", errors="strict")))
    return f"""<!doctype html>
<html lang="en" dir="auto">
<head>
  <meta charset="utf-8">
  <title>{html.escape(title)}</title>
  <style>{css}</style>
</head>
<body>
<section class="session" id="session-001">
  <h1 class="group-kicker">{html_escape(course_title)}</h1>
  <div class="session-meta">
    <span>Session 01</span><span>Study note</span><span>A4 Portrait</span>
  </div>
  <h2 class="session-title">{html_escape(title)}</h2>
  <div class="session-content">{body}</div>
</section>
</body>
</html>"""


def make_pdf(
    md_path: Path,
    output_pdf: Path | None = None,
    *,
    style: PdfStyle | None = None,
    title: str | None = None,
    extra_css: str | None = None,
    css_file: Path | None = None,
    prebuilt_css: str | None = None,
    auto_rtl: bool = True,
    fonts: FontBundle | None = None,
    course_title: str = "Study Notes",
) -> Path:
    """Convert one Markdown note with custom supplied fonts only."""
    del auto_rtl
    require_dependencies()
    md_path = Path(md_path).resolve()
    if not md_path.is_file():
        raise FileNotFoundError(md_path)
    if style and style.page_size.casefold() not in {"a4", "a4 portrait", "portrait a4"}:
        raise PipelineError("Only A4 Portrait is supported by the final study-book pipeline")
    fonts = fonts or load_font_bundle()
    raw = md_path.read_text(encoding="utf-8", errors="strict")
    document_title = title or infer_title(raw, md_path.stem)
    css = prebuilt_css or build_css(
        style,
        extra_css=extra_css,
        css_file=css_file,
        fonts=fonts,
        course_title=course_title,
    )
    full_html = _single_note_html(
        md_path,
        title=document_title,
        course_title=course_title,
        css=css,
    )
    output_pdf = Path(output_pdf).resolve() if output_pdf else md_path.with_suffix(".pdf")
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=full_html, base_url=str(md_path.parent)).write_pdf(output_pdf)
    return output_pdf


def batch_convert(
    input_dir: Path,
    output_dir: Path,
    *,
    pattern: str = "*.md",
    style: PdfStyle | None = None,
    css_file: Path | None = None,
    auto_rtl: bool = True,
    fonts: FontBundle | None = None,
) -> BatchResult:
    require_dependencies()
    input_dir = Path(input_dir).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    fonts = fonts or load_font_bundle()
    shared_css = build_css(style, css_file=css_file, fonts=fonts)
    created: list[Path] = []
    failed: list[tuple[Path, str]] = []
    notes = sorted((p for p in input_dir.glob(pattern) if is_topic_note(p)), key=natural_key)
    for note in notes:
        target = output_dir / f"{note.stem}.pdf"
        try:
            result = make_pdf(
                note,
                target,
                style=style,
                prebuilt_css=shared_css,
                auto_rtl=auto_rtl,
                fonts=fonts,
            )
            created.append(result)
            print(f"[ok] {note.name} -> {target.name}")
        except Exception as exc:  # noqa: BLE001 - aggregate batch errors
            failed.append((note, str(exc)))
            print(f"[error] {note.name}: {exc}", file=sys.stderr)
    return BatchResult(created=created, failed=failed)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Markdown notes -> A4 portrait custom-font PDFs")
    parser.add_argument("input", help="Single Markdown file or directory")
    parser.add_argument("--output", help="Output PDF or batch output directory")
    parser.add_argument("--batch", action="store_true")
    parser.add_argument("--pattern", default="*.md")
    parser.add_argument("--css")
    parser.add_argument("--font-file", help="Overrides FONT_FILE")
    parser.add_argument("--font-bold-file", help="Overrides FONT_BOLD_FILE")
    parser.add_argument("--title")
    parser.add_argument("--page-size", default="A4")
    parser.add_argument("--preset", default="study")
    parser.add_argument("--theme", default="medical-blue")
    parser.add_argument("--margin")
    parser.add_argument("--font-size")
    parser.add_argument("--line-height")
    parser.add_argument("--font-family")
    parser.add_argument("--rtl", action="store_true")
    parser.add_argument("--no-auto-rtl", action="store_true")
    parser.add_argument("--no-page-numbers", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        style = PdfStyle(page_size=args.page_size)
        fonts = load_font_bundle(args.font_file, args.font_bold_file)
        input_path = Path(args.input)
        css_file = Path(args.css) if args.css else None
        if args.batch or input_path.is_dir():
            output = Path(args.output) if args.output else input_path / "pdfs"
            result = batch_convert(
                input_path,
                output,
                pattern=args.pattern,
                style=style,
                css_file=css_file,
                auto_rtl=not args.no_auto_rtl,
                fonts=fonts,
            )
            print(f"Batch complete: {len(result.created)} created, {len(result.failed)} failed")
            return 0 if result.succeeded else 2
        output = Path(args.output) if args.output else input_path.with_suffix(".pdf")
        result = make_pdf(
            input_path,
            output,
            style=style,
            title=args.title,
            css_file=css_file,
            auto_rtl=not args.no_auto_rtl,
            fonts=fonts,
        )
        print(f"Created PDF: {result}")
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
