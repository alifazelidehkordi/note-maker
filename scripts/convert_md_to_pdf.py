#!/usr/bin/env python3
"""Compatibility renderer for a single Markdown file using the shared PDF pipeline."""
from __future__ import annotations

from pathlib import Path

from pdf_pipeline import (
    build_html,
    extract_heading_entries,
    render_pdf,
    resolve_fonts,
    sessions_from_markdown,
)


def _find_repo_root(path: Path) -> Path:
    for parent in [path.parent, *path.parents]:
        if (parent / "scripts").is_dir():
            return parent
    return Path.cwd()


def make_pdf(input_md: Path, output_pdf: Path, **kwargs) -> Path:
    input_md = Path(input_md).resolve()
    output_pdf = Path(output_pdf).resolve()
    if not input_md.is_file():
        raise FileNotFoundError(input_md)
    repo = _find_repo_root(input_md)
    fonts = resolve_fonts(repo)
    sessions = sessions_from_markdown(input_md)
    headings = extract_heading_entries(sessions)
    html_text = build_html(
        kwargs.get("title") or input_md.stem,
        sessions,
        headings,
        fonts,
        has_real_index=False,
    )
    render_pdf(html_text, output_pdf, input_md.parent)
    return output_pdf
