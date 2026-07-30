#!/usr/bin/env python3
"""Normalize a prepared flat Index for the final-study PDF branch.

The source Index remains authoritative. This helper only makes its existing
metadata explicit for the branch parser: it inserts group headings from
``Major division`` and normalizes bullet labels/bold markup. It never creates or
fetches scientific content.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

SESSION_RE = re.compile(r"^###\s+\d+\.\s+\[[^]]+\]\([^)]+\)\s*$")
FIELD_RE = re.compile(r"^-\s+(?:\*\*)?(.+?)(?::\*\*|:)\s*(.*?)\s*$")
HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")
ALIASES = {
    "total physical pdf pages": "Physical PDF pages",
    "physical pdf pages": "Physical PDF pages",
    "primary learning objective": "Learning objective",
    "learning objective": "Learning objective",
    "topic scope": "Scope",
    "scope": "Scope",
}


def find_index(notes_dir: Path, explicit: Path | None) -> Path:
    if explicit:
        path = explicit.resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Index Markdown not found: {path}")
        return path
    for name in ("INDEX.md", "STUDY_INDEX.md", "STUDY_INDEX-rewritten.md"):
        path = notes_dir / name
        if path.is_file():
            return path.resolve()
    raise FileNotFoundError(f"No prepared Index found in {notes_dir}")


def normalize_field(line: str) -> tuple[str, str] | None:
    match = FIELD_RE.match(line)
    if not match:
        return None
    original = re.sub(r"\s+", " ", match.group(1).strip())
    canonical = ALIASES.get(original.casefold(), original)
    return canonical, f"- **{canonical}:** {match.group(2).strip()}"


def normalize_index(source: Path) -> str:
    lines = source.read_text(encoding="utf-8", errors="strict").splitlines()
    output: list[str] = []
    current_group: str | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        if not SESSION_RE.match(line):
            normalized = normalize_field(line)
            output.append(normalized[1] if normalized else line)
            index += 1
            continue

        block = [line]
        index += 1
        while index < len(lines) and not SESSION_RE.match(lines[index]) and not HEADING_RE.match(lines[index]):
            block.append(lines[index])
            index += 1

        fields: dict[str, str] = {}
        normalized_block = [block[0]]
        for item in block[1:]:
            normalized = normalize_field(item)
            if normalized:
                label, rendered = normalized
                fields[label.casefold()] = FIELD_RE.match(rendered).group(2).strip()
                normalized_block.append(rendered)
            else:
                normalized_block.append(item)

        group = fields.get("major division") or fields.get("chapter") or fields.get("group")
        if not group:
            title_match = re.search(r"\[([^]]+)\]", block[0])
            title = title_match.group(1) if title_match else "Study Sections"
            group = title.split(":", 1)[0].strip() or "Study Sections"
        if group != current_group:
            if output and output[-1] != "":
                output.append("")
            output.extend([f"## {group}", ""])
            current_group = group
        output.extend(normalized_block)
    return "\n".join(output).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--notes-dir", required=True)
    parser.add_argument("--index-md")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    notes_dir = Path(args.notes_dir).resolve()
    source = find_index(notes_dir, Path(args.index_md) if args.index_md else None)
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(normalize_index(source), encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
