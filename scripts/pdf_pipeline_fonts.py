#!/usr/bin/env python3
"""Supplied-font loading, embedding CSS, and glyph-coverage checks."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable, Sequence

from fontTools.ttLib import TTFont

from pdf_pipeline_data import FontConfig


def _split_font_value(value: str | os.PathLike[str]) -> list[Path]:
    raw = str(value)
    parts = [p.strip() for p in re.split(r"[,:;]", raw) if p.strip()]
    # A Windows drive letter can be split by ':'; repair the common case.
    if len(parts) >= 2 and len(parts[0]) == 1 and parts[1].startswith(("\\", "/")):
        parts = [parts[0] + ":" + parts[1], *parts[2:]]
    return [Path(p).expanduser().resolve() for p in parts]


def font_config(font_file: str | Path | None = None, font_bold_file: str | Path | None = None) -> FontConfig:
    regular_value = str(font_file or os.environ.get("FONT_FILE", "")).strip()
    bold_value = str(font_bold_file or os.environ.get("FONT_BOLD_FILE", "")).strip()
    if not regular_value or not bold_value:
        raise EnvironmentError("FONT_FILE and FONT_BOLD_FILE must both be set")
    regular_files = _split_font_value(regular_value)
    bold_files = _split_font_value(bold_value)
    for p in [*regular_files, *bold_files]:
        if not p.is_file() or not os.access(p, os.R_OK):
            raise FileNotFoundError(f"Font file is missing or unreadable: {p}")
    regular_families = [f"StudyNotesRegular{i + 1}" for i in range(len(regular_files))]
    bold_families = [f"StudyNotesBold{i + 1}" for i in range(len(bold_files))]
    css_lines: list[str] = []
    expected: set[str] = set()
    for weight, files, families in ((400, regular_files, regular_families), (700, bold_files, bold_families)):
        for path, family in zip(files, families):
            uri = path.as_uri().replace("'", "%27")
            css_lines.append(
                f"@font-face {{ font-family: '{family}'; src: url('{uri}'); font-style: normal; font-weight: {weight}; font-display: block; }}"
            )
            try:
                font = TTFont(path, lazy=True)
                for record in font["name"].names:
                    if record.nameID == 6:
                        expected.add(record.toUnicode())
                        break
            except Exception:
                pass
    return FontConfig(regular_files, bold_files, regular_families, bold_families, "\n".join(css_lines), expected)


def validate_font_coverage(config: FontConfig, text_paths: Iterable[Path], extra_text: str = "") -> None:
    cmap: set[int] = set()
    for path in set(config.regular_files + config.bold_files):
        font = TTFont(path, lazy=True)
        for table in font["cmap"].tables:
            cmap.update(table.cmap)
    content = extra_text
    for path in text_paths:
        content += path.read_text(encoding="utf-8", errors="strict")
    missing = sorted({ord(ch) for ch in content if not ch.isspace() and ord(ch) not in cmap})
    if missing:
        sample = ", ".join(f"U+{cp:04X} {chr(cp)!r}" for cp in missing[:20])
        raise RuntimeError(f"Provided fonts do not cover all document characters ({len(missing)} missing): {sample}")


def font_stack(families: Sequence[str]) -> str:
    return ", ".join(f"'{name}'" for name in families)
