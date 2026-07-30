#!/usr/bin/env python3
"""Public facade for shared final-PDF helpers.

The modules behind this facade contain no browser automation. They only read
prepared Markdown/metadata, render A4 portrait PDFs, merge them, and validate
output.
"""
from pdf_pipeline_data import (
    A4_HEIGHT_PT,
    A4_SIZE,
    A4_WIDTH_PT,
    FontConfig,
    Group,
    Session,
    destination_name,
    extract_study_focus,
    fallback_sessions,
    group_sessions,
    infer_course_title,
    is_excluded_path,
    is_session_markdown,
    locate_index_file,
    markdown_title,
    natural_key,
    normalize_space,
    pages_coverage,
    parse_frontmatter,
    parse_index_sessions,
    parse_range,
    strip_markdown,
)
from pdf_pipeline_fonts import font_config, font_stack, validate_font_coverage
from pdf_pipeline_index import build_index_markdown, html_escape, note_uri
from pdf_pipeline_validation import (
    aliases_from_uri,
    check_a4_portrait,
    collect_embedded_fonts,
    session_aliases,
    validate_component_pdf,
    write_json,
)

__all__ = [name for name in globals() if not name.startswith("_")]
