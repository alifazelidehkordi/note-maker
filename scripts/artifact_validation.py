from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from opml_utils import repair_and_validate_opml

MARKDOWN_EXTENSIONS = {".md", ".markdown"}
OPML_EXTENSIONS = {".opml"}
DEFAULT_MIN_MARKDOWN_BYTES = 100

_ASSISTANT_ERROR_PATTERNS = (
    re.compile(r"\bi(?:['’]m| am) sorry\b", re.IGNORECASE),
    re.compile(r"\bi can(?:not|'t) (?:create|generate|provide|complete)\b", re.IGNORECASE),
    re.compile(r"\bsomething went wrong\b", re.IGNORECASE),
    re.compile(r"\btry again later\b", re.IGNORECASE),
    re.compile(r"\bunable to (?:create|generate|provide|complete)\b", re.IGNORECASE),
    re.compile(r"متأسفم|متاسفم|امکان (?:ایجاد|تولید)|خطایی رخ داد"),
)


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    errors: tuple[str, ...]
    detected_type: str | None = None

    def require_valid(self) -> None:
        if not self.valid:
            raise ValueError("; ".join(self.errors))


class ArtifactValidationError(ValueError):
    """Raised when a downloaded artifact fails validation.

    ``rejected_path`` points to the preserved invalid candidate when available.
    """

    def __init__(
        self,
        output_path: Path,
        result: ValidationResult,
        *,
        rejected_path: Path | None = None,
    ) -> None:
        self.output_path = output_path
        self.result = result
        self.rejected_path = rejected_path
        detail = "; ".join(result.errors) or "unknown validation error"
        suffix = f" Rejected candidate: {rejected_path}" if rejected_path else ""
        super().__init__(f"Artifact validation failed for {output_path.name}: {detail}.{suffix}")


def normalize_extensions(expected_extensions: Iterable[str]) -> set[str]:
    normalized: set[str] = set()
    for extension in expected_extensions:
        value = str(extension).strip().lower()
        if not value:
            continue
        normalized.add(value if value.startswith(".") else f".{value}")
    return normalized


def _read_utf8(path: Path) -> tuple[str | None, list[str]]:
    try:
        return path.read_text(encoding="utf-8"), []
    except UnicodeDecodeError as exc:
        return None, [f"File is not valid UTF-8: {exc}"]
    except OSError as exc:
        return None, [f"Could not read file: {exc}"]


def validate_markdown(
    path: Path,
    *,
    min_bytes: int = DEFAULT_MIN_MARKDOWN_BYTES,
) -> ValidationResult:
    errors: list[str] = []
    try:
        size = path.stat().st_size
    except OSError as exc:
        return ValidationResult(False, (f"Could not stat file: {exc}",), "markdown")

    if size == 0:
        errors.append("File is empty")
    elif size < min_bytes:
        errors.append(f"File is smaller than the minimum {min_bytes} bytes")

    text, read_errors = _read_utf8(path)
    errors.extend(read_errors)
    if text is None:
        return ValidationResult(False, tuple(errors), "markdown")

    stripped = text.strip()
    if not stripped:
        errors.append("File contains no text")
        return ValidationResult(False, tuple(dict.fromkeys(errors)), "markdown")

    if not re.search(r"(?m)^#(?!#)\s+\S", text):
        errors.append("Missing H1 title")
    if not re.search(r"(?m)^##(?!#)\s+\S", text):
        errors.append("Missing level-2 heading")

    error_scan = stripped[:4000]
    for pattern in _ASSISTANT_ERROR_PATTERNS:
        if pattern.search(error_scan):
            errors.append("Output contains an assistant error or apology message")
            break

    lowered = stripped[:2000].lower()
    looks_like_html = (
        lowered.startswith("<!doctype html")
        or lowered.startswith("<html")
        or ("<html" in lowered and "</html>" in lowered)
    )
    if looks_like_html:
        errors.append("Output appears to be an HTML page, not Markdown")

    non_empty_lines = [line.strip() for line in text.splitlines() if line.strip()]
    content_lines = [
        line
        for line in non_empty_lines
        if not line.startswith("#")
        and not re.fullmatch(r"\[.*?\]\([^)]*\)", line)
        and not re.fullmatch(r"https?://\S+", line)
    ]
    if not content_lines:
        errors.append("Output contains headings or download links but no note content")

    return ValidationResult(not errors, tuple(dict.fromkeys(errors)), "markdown")


def validate_opml(path: Path, *, repair: bool = True) -> ValidationResult:
    errors: list[str] = []
    try:
        if path.stat().st_size == 0:
            return ValidationResult(False, ("File is empty",), "opml")
    except OSError as exc:
        return ValidationResult(False, (f"Could not stat file: {exc}",), "opml")

    try:
        if repair:
            repair_and_validate_opml(path)
        else:
            ET.parse(path)
    except (OSError, UnicodeError, ET.ParseError, ValueError) as exc:
        errors.append(f"Invalid OPML/XML: {exc}")
        return ValidationResult(False, tuple(errors), "opml")

    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        return ValidationResult(False, (f"Invalid OPML/XML: {exc}",), "opml")

    def local_name(tag: str) -> str:
        return tag.rsplit("}", 1)[-1].lower()

    if local_name(root.tag) != "opml":
        errors.append("Root element is not <opml>")

    body = next((element for element in root.iter() if local_name(element.tag) == "body"), None)
    if body is None:
        errors.append("Missing <body> element")
    elif not any(local_name(element.tag) == "outline" for element in body.iter()):
        errors.append("OPML body contains no <outline> element")

    return ValidationResult(not errors, tuple(errors), "opml")


def validate_artifact(
    path: Path,
    expected_extensions: Iterable[str],
    *,
    min_markdown_bytes: int = DEFAULT_MIN_MARKDOWN_BYTES,
    repair_opml: bool = True,
) -> ValidationResult:
    if not path.exists() or not path.is_file():
        return ValidationResult(False, ("Artifact file does not exist",), None)

    extensions = normalize_extensions(expected_extensions)
    if not extensions:
        return ValidationResult(False, ("No expected artifact extension was provided",), None)

    expects_markdown = bool(extensions & MARKDOWN_EXTENSIONS)
    expects_opml = bool(extensions & OPML_EXTENSIONS)
    if expects_markdown and expects_opml:
        return ValidationResult(
            False,
            ("Expected extensions span more than one artifact type",),
            None,
        )
    if expects_markdown:
        return validate_markdown(path, min_bytes=min_markdown_bytes)
    if expects_opml:
        return validate_opml(path, repair=repair_opml)

    joined = ", ".join(sorted(extensions))
    return ValidationResult(False, (f"Unsupported expected artifact extension(s): {joined}",), None)
