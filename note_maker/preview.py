from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from .compat import activate_legacy_imports
from .config import ConfigError, ResolvedConfig

PREVIEW_RUN_ID = "preview"


def _patterns(values: Sequence[str]) -> tuple[str, ...]:
    patterns = tuple(value.strip() for value in values)
    if any(not value for value in patterns):
        raise ConfigError("File selection patterns may not be empty.")
    return patterns


def filter_input_files(
    files: Iterable[Path],
    *,
    include_patterns: Sequence[str] = (),
    exclude_patterns: Sequence[str] = (),
) -> list[Path]:
    """Apply deterministic filename globs while preserving collector order.

    Matching is intentionally against the top-level filename only because the
    existing PDF/DOCX/Markdown collector is non-recursive. Patterns are
    case-sensitive on every platform so a preview made on one OS has the same
    selection semantics on another.
    """

    includes = _patterns(include_patterns)
    excludes = _patterns(exclude_patterns)
    selected: list[Path] = []
    for path in files:
        name = Path(path).name
        if includes and not any(fnmatchcase(name, pattern) for pattern in includes):
            continue
        if excludes and any(fnmatchcase(name, pattern) for pattern in excludes):
            continue
        selected.append(Path(path))
    return selected


def _limit_files(files: list[Path], limit: int | None) -> list[Path]:
    return files if limit is None else files[:limit]


def _path_value(value: object, *, name: str) -> Path:
    if not isinstance(value, Path):
        raise ConfigError(f"Resolved {name} must be a path, received {value!r}.")
    return value


def _optional_path(value: object, *, name: str) -> Path | None:
    if value is None:
        return None
    return _path_value(value, name=name)


def _read_prompt(path: Path) -> str:
    if not path.is_file():
        raise ConfigError(f"Prompt file does not exist: {path}")
    try:
        prompt = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"Could not read UTF-8 prompt {path}: {exc}") from exc
    if not prompt:
        raise ConfigError(f"Prompt file is empty: {path}")
    return prompt


def _manifest_path(values: Mapping[str, Any], output_dir: Path) -> Path:
    configured = _optional_path(values.get("manifest"), name="manifest")
    return (configured or (output_dir / "manifest.json")).expanduser().resolve()


def _planning_options(values: Mapping[str, Any]) -> Any:
    from parallel_runtime.models import PlanningOptions  # type: ignore[import-not-found]

    return PlanningOptions(
        overwrite=bool(values["overwrite"]),
        resume=bool(values["resume"]),
        adopt_existing=bool(values["adopt_existing"]),
        retry_failed_only=bool(values["retry_failed"]),
    )


def _plan_payload(plan: Any, reader: Any) -> dict[str, Any]:
    runnable = {item.label: item for item in plan.runnable}
    adopted = set(plan.adopted)
    transition_reason = {
        transition.job.key: transition.reason
        for transition in plan.transitions
        if getattr(transition.kind, "value", "") == "adopted"
    }
    jobs: list[dict[str, Any]] = []
    for candidate in plan.candidates:
        existing = reader.get(candidate.job.key)
        previous_status = existing.get("status") if isinstance(existing, dict) else None
        if candidate.label in runnable:
            planned = runnable[candidate.label]
            action = "run"
            reason = planned.reason
            previous_status = planned.previous_status
        elif candidate.label in adopted:
            action = "adopt"
            reason = transition_reason.get(candidate.job.key) or "valid existing output"
        else:
            action = "skip"
            reason = plan.skipped.get(candidate.label, "not runnable")
        jobs.append(
            {
                "label": candidate.label,
                "action": action,
                "reason": reason,
                "previous_status": previous_status,
                "key": candidate.job.key,
                "source": str(candidate.job.source),
                "output": str(candidate.job.output),
                "output_exists": candidate.job.output.exists(),
                "estimated_weight": candidate.job.estimated_weight,
            }
        )

    return {
        "candidate_count": len(plan.candidates),
        "runnable_count": len(plan.runnable),
        "skipped_count": len(plan.skipped),
        "adopted_count": len(plan.adopted),
        "initial_successes": plan.initial_successes,
        "estimated_total_weight": plan.estimated_total_weight,
        "jobs": jobs,
    }


def _base_preview(
    resolved: ResolvedConfig,
    *,
    manifest_path: Path,
    plan_payload: dict[str, Any],
    selection: dict[str, Any],
) -> dict[str, Any]:
    return {
        "read_only": True,
        "browser_will_start": False,
        "manifest_will_be_modified": False,
        "runtime_will_be_created": False,
        "claims_will_be_created": False,
        "browser_provider": resolved.runtime.browser_provider,
        "parallel_runs": resolved.runtime.parallel_runs,
        "profile_snapshot": resolved.runtime.profile_snapshot,
        "manifest": str(manifest_path),
        "manifest_exists": manifest_path.is_file(),
        "selection": selection,
        "plan": plan_payload,
    }


def build_pdf_preview(
    resolved: ResolvedConfig,
    *,
    include_patterns: Sequence[str] = (),
    exclude_patterns: Sequence[str] = (),
) -> dict[str, Any]:
    """Build the same file/manifest plan a PDF run would use, without writes."""

    activate_legacy_imports()
    import batch_common  # type: ignore[import-not-found]
    import batch_pdf  # type: ignore[import-not-found]
    import manifest as manifest_store  # type: ignore[import-not-found]
    from parallel_runtime.job_sources import build_file_candidates  # type: ignore[import-not-found]
    from parallel_runtime.planner import plan_jobs  # type: ignore[import-not-found]

    values = resolved.values
    input_dir = _path_value(values["input_dir"], name="input_dir")
    output_dir = _path_value(values["output_dir"], name="output_dir")
    prompt_path = _path_value(values["prompt"], name="prompt")
    if not input_dir.is_dir():
        raise ConfigError(f"Input directory does not exist: {input_dir}")
    prompt = _read_prompt(prompt_path)

    discovered = batch_common.collect_input_files(input_dir)
    filtered = filter_input_files(
        discovered,
        include_patterns=include_patterns,
        exclude_patterns=exclude_patterns,
    )
    limit_value = values.get("limit")
    limit = None if limit_value is None else int(limit_value)
    selected = _limit_files(filtered, limit)

    ext = str(values["output_ext"]).lstrip(".").lower()
    manifest_path = _manifest_path(values, output_dir)
    reader = manifest_store.ManifestStore.reader(manifest_path)
    candidates = build_file_candidates(
        selected,
        input_dir=input_dir,
        output_dir=output_dir,
        prompt_path=prompt_path,
        prompt_hash=manifest_store.hash_text(prompt),
        output_ext=ext,
        mode=f"pdf-{ext}",
        model=values.get("model"),
        key_builder=batch_pdf._job_key,
    )
    plan = plan_jobs(
        candidates,
        reader,
        run_id=PREVIEW_RUN_ID,
        options=_planning_options(values),
    )
    selection = {
        "kind": "files",
        "input_dir": str(input_dir),
        "discovered_count": len(discovered),
        "filtered_count": len(filtered),
        "selected_count": len(selected),
        "include": list(_patterns(include_patterns)),
        "exclude": list(_patterns(exclude_patterns)),
        "limit": limit,
        "matching": "case-sensitive filename globs",
    }
    return _base_preview(
        resolved,
        manifest_path=manifest_path,
        plan_payload=_plan_payload(plan, reader),
        selection=selection,
    )


def _preview_section_file(section: Any, section_dir: Path) -> Path:
    return section_dir / f"{section.output_stem}.md"


def build_markdown_preview(resolved: ResolvedConfig) -> dict[str, Any]:
    """Build a Markdown-section plan without materializing section files."""

    activate_legacy_imports()
    import batch_markdown  # type: ignore[import-not-found]
    import manifest as manifest_store
    from parallel_runtime.job_sources import build_section_candidates
    from parallel_runtime.planner import plan_jobs

    values = resolved.values
    markdown_file = _path_value(values["markdown_file"], name="markdown_file")
    output_dir = _path_value(values["output_dir"], name="output_dir")
    prompt_path = _path_value(values["prompt"], name="prompt")
    if not markdown_file.is_file():
        raise ConfigError(f"Markdown source does not exist: {markdown_file}")
    prompt = _read_prompt(prompt_path)

    try:
        all_sections = batch_markdown.split_markdown_sections(markdown_file)
        section_filter = batch_markdown.parse_section_numbers(values.get("sections"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ConfigError(f"Could not preview Markdown sections: {exc}") from exc
    limit_value = values.get("limit")
    limit = None if limit_value is None else int(limit_value)
    selected = batch_markdown.select_sections(all_sections, section_filter, limit)

    ext = str(values["output_ext"]).lstrip(".").lower()
    section_dir = output_dir / "_md_sections"
    manifest_path = _manifest_path(values, output_dir)
    reader = manifest_store.ManifestStore.reader(manifest_path)
    candidates = build_section_candidates(
        selected,
        markdown_file=markdown_file,
        section_dir=section_dir,
        output_dir=output_dir,
        prompt_path=prompt_path,
        prompt_hash=manifest_store.hash_text(prompt),
        output_ext=ext,
        mode=f"markdown-{ext}",
        model=values.get("model"),
        key_builder=batch_markdown._section_job_key,
        section_file_writer=_preview_section_file,
    )
    plan = plan_jobs(
        candidates,
        reader,
        run_id=PREVIEW_RUN_ID,
        options=_planning_options(values),
    )
    selection = {
        "kind": "markdown-sections",
        "markdown_file": str(markdown_file),
        "detected_count": len(all_sections),
        "selected_count": len(selected),
        "sections": values.get("sections"),
        "limit": limit,
        "section_files_will_be_materialized": False,
    }
    return _base_preview(
        resolved,
        manifest_path=manifest_path,
        plan_payload=_plan_payload(plan, reader),
        selection=selection,
    )


@contextmanager
def selected_pdf_collection(
    *,
    include_patterns: Sequence[str] = (),
    exclude_patterns: Sequence[str] = (),
) -> Iterator[None]:
    """Apply Part 2B selectors to the existing collector for one CLI run only."""

    activate_legacy_imports()
    import batch_common

    includes = _patterns(include_patterns)
    excludes = _patterns(exclude_patterns)
    original = batch_common.collect_input_files

    def collect_selected(input_dir: Path) -> list[Path]:
        return filter_input_files(
            original(input_dir),
            include_patterns=includes,
            exclude_patterns=excludes,
        )

    batch_common.collect_input_files = collect_selected
    try:
        yield
    finally:
        batch_common.collect_input_files = original
