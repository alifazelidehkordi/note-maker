from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path


def escape_xml_attribute_value(value: str) -> str:
    value = re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9A-Fa-f]+;)", "&amp;", value)
    return value.replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def repair_and_validate_opml(path: Path) -> None:
    text = path.read_text(encoding="utf-8")

    def replace_attr(match: re.Match[str]) -> str:
        return f'{match.group(1)}="{escape_xml_attribute_value(match.group(2))}"'

    repaired = re.sub(r'\b(text|title)="([^"]*)"', replace_attr, text)
    repaired = re.sub(
        r"(<title>)(.*?)(</title>)",
        lambda match: f"{match.group(1)}{escape_xml_attribute_value(match.group(2))}{match.group(3)}",
        repaired,
        flags=re.DOTALL,
    )
    path.write_text(repaired, encoding="utf-8")
    ET.parse(path)