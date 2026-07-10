from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path


def escape_xml_attribute_value(value: str) -> str:
    value = re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9A-Fa-f]+;)", "&amp;", value)
    return value.replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


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
    root = ET.parse(path).getroot()

    if _local_name(root.tag) != "opml":
        raise ValueError("Root element is not <opml>")
    body = next((element for element in root.iter() if _local_name(element.tag) == "body"), None)
    if body is None:
        raise ValueError("Missing <body> element")
    if not any(_local_name(element.tag) == "outline" for element in body.iter()):
        raise ValueError("OPML body contains no <outline> element")
