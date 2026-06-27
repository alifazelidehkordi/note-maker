#!/usr/bin/env python3
"""
Enrich rewritten clean notes with original source page information.

Usage:
  python scripts/enrich_rewritten_notes.py \
    --original-parts /path/to/original/parts \
    --rewritten-dir outputs/notes \
    --inplace
"""

import argparse
import re
from pathlib import Path

import yaml


def parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        fm = yaml.safe_load(parts[1]) or {}
        return fm, parts[2]
    except Exception:
        return {}, text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--original-parts", required=True)
    parser.add_argument("--rewritten-dir", required=True)
    parser.add_argument("--inplace", action="store_true")
    args = parser.parse_args()

    orig_dir = Path(args.original_parts)
    rew_dir = Path(args.rewritten_dir)

    for orig in sorted(orig_dir.glob("*.md")):
        fm = parse_frontmatter(orig.read_text(encoding="utf-8"))[0]
        if not fm.get("pdf_pages"):
            continue

        rew_file = rew_dir / orig.name
        if not rew_file.exists():
            print(f"Skipping (no rewritten): {orig.name}")
            continue

        content = rew_file.read_text(encoding="utf-8")
        fm_rew, body = parse_frontmatter(content)

        # Merge important source fields
        for key in ["pdf_pages", "book_pages", "source", "chapter", "part"]:
            if key in fm and key not in fm_rew:
                fm_rew[key] = fm[key]

        # Rebuild frontmatter
        new_fm = yaml.dump(fm_rew, allow_unicode=True, default_flow_style=False).strip()
        new_content = f"---\n{new_fm}\n---\n{body}"

        # Add visible source line right after the first # Title if not present
        if "منبع اصلی" not in new_content and "Source" not in new_content:
            new_content = re.sub(
                r"^(# .+?)\n",
                r"\1\n\n**منبع اصلی:** PDF pp. " + str(fm.get("pdf_pages", "")) + "\n",
                new_content,
                count=1,
                flags=re.MULTILINE,
            )

        if args.inplace:
            rew_file.write_text(new_content, encoding="utf-8")
            print(f"Enriched: {rew_file.name}")
        else:
            print(f"Would enrich: {rew_file.name} (use --inplace)")

    if args.inplace:
        print("\nDone. Source page info added to rewritten notes.")


if __name__ == "__main__":
    main()
