#!/usr/bin/env python3
"""Backward-compatible entry point for combined-PDF generation.

The reference-style strict pipeline and the pre-existing component-PDF pipeline
have intentionally different contracts. Keep both implementations isolated
and dispatch based on whether the strict font contract is requested.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import create_combined_pdf_legacy as _legacy
from convert_md_to_pdf import make_pdf


# Public compatibility helpers retained for callers/tests built against the
# original component-PDF combiner.
aliases_from_uri = _legacy.aliases_from_uri
add_continuous_page_numbers = _legacy.add_continuous_page_numbers
pdf_rebuild_reason = _legacy.pdf_rebuild_reason
pdf_needs_rebuild = _legacy.pdf_needs_rebuild


def _strict_module():
    """Import the strict WeasyPrint pipeline only when it is actually needed.

    Legacy callers must remain importable on platforms where WeasyPrint's
    optional native libraries are unavailable (notably bare Windows runners).
    """
    import create_combined_pdf_strict as strict

    return strict


def create_combined(
    notes_dir: Path,
    pdf_dir: Path | None = None,
    output_path: Path | None = None,
    index_md: Path | None = None,
    *,
    title: str | None = None,
    font_file: Path | None = None,
    font_bold_file: Path | None = None,
    latin_regular_file: Path | None = None,
    latin_bold_file: Path | None = None,
    arabic_regular_file: Path | None = None,
    qc_report: Path | None = None,
    debug_html: Path | None = None,
    css_file: Path | None = None,
    continuous_page_numbers: bool = True,
    page_number_start: int = 1,
    **kwargs: Any,
) -> Path:
    """Build a combined PDF without breaking either supported API generation.

    Supplying ``font_file`` and ``font_bold_file`` opts into the strict,
    reference-style one-pass builder. Omitting both preserves the historical
    component-PDF workflow used by the Phase 1 acceptance suite and existing
    callers. Supplying only one font is rejected instead of silently falling
    back to a weaker validation path.
    """
    if font_file is None and font_bold_file is None:
        # Tests and downstream callers may monkey-patch this module's renderer;
        # forward that patch into the isolated compatibility implementation.
        _legacy.make_pdf = make_pdf
        return _legacy.create_combined(
            notes_dir,
            pdf_dir,
            output_path,
            index_md,
            title=title or "Study Notes",
            css_file=css_file,
            continuous_page_numbers=continuous_page_numbers,
            page_number_start=page_number_start,
        )

    if font_file is None or font_bold_file is None:
        raise ValueError("font_file and font_bold_file must be provided together")

    return _strict_module().create_combined(
        notes_dir,
        pdf_dir,
        output_path,
        index_md,
        title=title,
        font_file=font_file,
        font_bold_file=font_bold_file,
        latin_regular_file=latin_regular_file,
        latin_bold_file=latin_bold_file,
        arabic_regular_file=arabic_regular_file,
        qc_report=qc_report,
        debug_html=debug_html,
        **kwargs,
    )


def main() -> int:
    """Preserve both command-line interfaces.

    The production final-book script passes the strict font flags. Legacy CLI
    invocations without those flags continue to use the component-PDF combiner.
    """
    strict_flags = {"--font-file", "--font-bold-file"}
    if any(flag in sys.argv[1:] for flag in strict_flags):
        return _strict_module().main()
    return _legacy.main()


def __getattr__(name: str):
    """Expose implementation helpers without forcing strict imports eagerly."""
    # Import machinery probes dunder attributes such as ``__path__`` even for
    # ordinary modules. Never satisfy those probes by importing the optional
    # strict renderer and its native WeasyPrint dependencies.
    if name.startswith("__"):
        raise AttributeError(name)
    if hasattr(_legacy, name):
        return getattr(_legacy, name)
    strict = _strict_module()
    if hasattr(strict, name):
        return getattr(strict, name)
    raise AttributeError(name)


if __name__ == "__main__":
    raise SystemExit(main())
