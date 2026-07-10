from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable, TypeVar

from manifest import JobSpec

from .models import PlanningCandidate


S = TypeVar("S")


def build_file_candidates(
    input_files: Iterable[Path],
    *,
    input_dir: Path,
    output_dir: Path,
    prompt_path: Path,
    prompt_hash: str,
    output_ext: str,
    mode: str,
    model: str | None,
    key_builder: Callable[[Path, Path, str], str],
) -> tuple[PlanningCandidate[Path], ...]:
    ext = output_ext.lstrip(".").lower()
    candidates: list[PlanningCandidate[Path]] = []
    for input_path in input_files:
        output_path = output_dir / f"{input_path.stem}.{ext}"
        job = JobSpec.for_file(
            key=key_builder(input_path, input_dir, ext),
            source=input_path,
            prompt=prompt_path,
            prompt_hash=prompt_hash,
            output=output_path,
            expected_extensions={f".{ext}"},
            mode=mode,
            model=model,
            title=input_path.name,
            metadata={
                "job_kind": "file",
                "input_name": input_path.name,
            },
        )
        candidates.append(PlanningCandidate(label=input_path.name, payload=input_path, job=job))
    return tuple(candidates)


def build_section_candidates(
    sections: Iterable[S],
    *,
    markdown_file: Path,
    section_dir: Path,
    output_dir: Path,
    prompt_path: Path,
    prompt_hash: str,
    output_ext: str,
    mode: str,
    model: str | None,
    key_builder: Callable[[Path, S, str], str],
    section_file_writer: Callable[[S, Path], Path],
) -> tuple[PlanningCandidate[tuple[S, Path]], ...]:
    """Materialize stable section inputs and build browser-free job candidates."""
    ext = output_ext.lstrip(".").lower()
    candidates: list[PlanningCandidate[tuple[S, Path]]] = []
    for section in sections:
        section_file = section_file_writer(section, section_dir)
        index = int(getattr(section, "index"))
        title = str(getattr(section, "title"))
        text = str(getattr(section, "text"))
        output_stem = str(getattr(section, "output_stem"))
        label = f"section {index:02d} {title}"
        job = JobSpec.for_text(
            key=key_builder(markdown_file, section, ext),
            source=markdown_file,
            source_text=text,
            prompt=prompt_path,
            prompt_hash=prompt_hash,
            output=output_dir / f"{output_stem}.{ext}",
            expected_extensions={f".{ext}"},
            mode=mode,
            model=model,
            title=label,
            metadata={
                "job_kind": "markdown-section",
                "section_index": str(index),
                "section_title": title,
                "section_file": str(section_file.resolve()),
            },
        )
        candidates.append(
            PlanningCandidate(label=label, payload=(section, section_file), job=job)
        )
    return tuple(candidates)
