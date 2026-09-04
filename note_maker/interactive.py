from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from .compat import activate_legacy_imports
from .config import ConfigError, ResolvedConfig, resolve_config

_PROMPT_SUFFIXES = {".md", ".txt"}
_CANCEL_WORDS = {"q", "quit", "cancel"}


class InteractiveCancelled(Exception):
    """Raised when the wizard is cancelled without an error traceback."""


class InteractiveInputError(ValueError):
    """Raised for a retryable wizard input error."""


@dataclass(frozen=True)
class InteractivePlan:
    resolved: ResolvedConfig
    input_files: tuple[Path, ...] | None = None


def _batch_common() -> Any:
    activate_legacy_imports()
    import batch_common  # type: ignore[import-not-found]

    return batch_common


def discover_supported_files(directory: Path) -> list[Path]:
    return list(_batch_common().collect_input_files(directory))


def is_supported_source(path: Path) -> bool:
    if not path.is_file():
        return False
    return path.resolve() in discover_supported_files(path.parent)


def parse_selection(raw: str, count: int) -> list[int]:
    """Parse 1-based comma/range selections into sorted zero-based indexes."""
    if count <= 0:
        raise InteractiveInputError("No files are available to select.")
    text = raw.strip().lower()
    if text in {"", "all", "*"}:
        return list(range(count))

    selected: set[int] = set()
    try:
        for part in text.split(","):
            token = part.strip()
            if not token:
                continue
            if "-" in token:
                start_text, end_text = token.split("-", 1)
                start, end = int(start_text), int(end_text)
                if start <= 0 or end < start:
                    raise InteractiveInputError(f"Invalid selection range: {token}")
                selected.update(range(start - 1, end))
            else:
                selected.add(int(token) - 1)
    except ValueError as exc:
        raise InteractiveInputError("Use selections like 1,3-5, or all.") from exc

    if not selected:
        raise InteractiveInputError("Select at least one file.")
    if min(selected) < 0 or max(selected) >= count:
        raise InteractiveInputError(f"Selection must be between 1 and {count}.")
    return sorted(selected)


def discover_prompt_files(
    *,
    cwd: Path,
    project_root: Path,
    config_path: Path | None,
    default_prompt: Path | None,
) -> list[Path]:
    roots = [cwd / "prompts", project_root / "prompts"]
    if config_path is not None:
        roots.insert(1, config_path.parent / "prompts")
    candidates: list[Path] = []
    for root in roots:
        if root.is_dir():
            candidates.extend(
                path.resolve()
                for path in sorted(root.iterdir(), key=lambda item: item.name.lower())
                if path.is_file() and path.suffix.lower() in _PROMPT_SUFFIXES
            )
    if default_prompt is not None and default_prompt.is_file():
        candidates.append(default_prompt.resolve())
    return list(dict.fromkeys(candidates))


def validate_output_dir(path: Path) -> None:
    if path.exists() and not path.is_dir():
        raise InteractiveInputError(f"Output path exists and is not a directory: {path}")
    ancestor = path
    while not ancestor.exists() and ancestor != ancestor.parent:
        ancestor = ancestor.parent
    if ancestor.exists() and not ancestor.is_dir():
        raise InteractiveInputError(f"Output parent is not a directory: {ancestor}")


def _validate_prompt(path: Path) -> None:
    if not path.is_file():
        raise InteractiveInputError(f"Prompt file does not exist: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise InteractiveInputError(f"Could not read UTF-8 prompt {path}: {exc}") from exc
    if not text.strip():
        raise InteractiveInputError(f"Prompt file is empty: {path}")


def _size_label(path: Path) -> str:
    try:
        size = path.stat().st_size
    except OSError:
        return "size unavailable"
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


class _Wizard:
    def __init__(
        self,
        *,
        input_fn: Callable[[str], str],
        output: TextIO,
        cwd: Path,
        project_root: Path,
    ) -> None:
        self.input_fn = input_fn
        self.output = output
        self.cwd = cwd
        self.project_root = project_root

    def say(self, message: str = "") -> None:
        self.output.write(message + "\n")
        self.output.flush()

    def ask(self, prompt: str) -> str:
        try:
            value = self.input_fn(prompt).strip()
        except (EOFError, KeyboardInterrupt) as exc:
            raise InteractiveCancelled from exc
        if value.lower() in _CANCEL_WORDS:
            raise InteractiveCancelled
        return value

    def path(self, raw: str) -> Path:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = self.cwd / path
        return path.resolve()

    def choose_source(self, default: Path) -> tuple[Path, tuple[Path, ...]]:
        while True:
            raw = self.ask(f"Input file or directory [{default}]: ")
            source = default if not raw else self.path(raw)
            if not source.exists():
                self.say(f"Input does not exist: {source}")
                continue
            if source.is_file():
                if not is_supported_source(source):
                    self.say("Unsupported input. Use a PDF, DOCX, or MD file.")
                    continue
                self.say(f"Selected: {source.name} ({_size_label(source)})")
                return source.parent, (source.resolve(),)
            if not source.is_dir():
                self.say(f"Input is not a file or directory: {source}")
                continue
            files = discover_supported_files(source)
            if not files:
                self.say(f"No supported PDF, DOCX, or MD files found in {source}.")
                continue
            self.say(f"Found {len(files)} supported file(s):")
            for index, path in enumerate(files, 1):
                self.say(f"  {index:>2}. {path.name} ({_size_label(path)})")
            while True:
                try:
                    indexes = parse_selection(
                        self.ask("Select files [all] (example: 1,3-5): "), len(files)
                    )
                except InteractiveInputError as exc:
                    self.say(f"Invalid selection: {exc}")
                    continue
                return source.resolve(), tuple(files[index] for index in indexes)

    def choose_workflow(self, selected: Sequence[Path]) -> str:
        if len(selected) != 1 or selected[0].suffix.lower() != ".md":
            self.say("Workflow: file batch (PDF/DOCX/Markdown uploads)")
            return "pdf"
        self.say("Markdown workflow: 1) split by ## sections [recommended], 2) one uploaded file")
        while True:
            raw = self.ask("Workflow [1]: ")
            if raw in {"", "1"}:
                return "markdown"
            if raw == "2":
                return "pdf"
            self.say("Choose 1 or 2.")

    def choose_prompt(self, resolved: ResolvedConfig) -> Path:
        raw_default = resolved.values.get("prompt")
        default = raw_default if isinstance(raw_default, Path) else None
        prompts = discover_prompt_files(
            cwd=self.cwd,
            project_root=self.project_root,
            config_path=resolved.config_path,
            default_prompt=default,
        )
        default_index = (
            prompts.index(default) + 1 if default is not None and default in prompts else None
        )
        if prompts:
            self.say("Available prompts:")
            for index, path in enumerate(prompts, 1):
                marker = " [default]" if default_index == index else ""
                self.say(f"  {index:>2}. {path.name}{marker}")
            self.say("   c. Custom prompt path")
        while True:
            if not prompts:
                raw = self.ask("Custom prompt path: ")
                path = self.path(raw)
            else:
                raw = self.ask(f"Prompt [{default_index or 'choose'}]: ")
                if not raw and default_index is not None:
                    path = prompts[default_index - 1]
                elif raw.lower() == "c":
                    path = self.path(self.ask("Custom prompt path: "))
                else:
                    try:
                        index = int(raw) - 1
                    except ValueError:
                        self.say("Choose a prompt number or c for a custom path.")
                        continue
                    if index < 0 or index >= len(prompts):
                        self.say(f"Prompt selection must be between 1 and {len(prompts)}.")
                        continue
                    path = prompts[index]
            try:
                _validate_prompt(path)
            except InteractiveInputError as exc:
                self.say(f"Invalid prompt: {exc}")
                continue
            self.say(f"Prompt: {path}")
            return path.resolve()

    def choose_output(self, default: Path) -> Path:
        while True:
            raw = self.ask(f"Output directory [{default}]: ")
            path = default if not raw else self.path(raw)
            try:
                validate_output_dir(path)
            except InteractiveInputError as exc:
                self.say(f"Invalid output directory: {exc}")
                continue
            return path.resolve()

    def choose_choice(self, label: str, choices: set[str], default: str) -> str:
        while True:
            raw = self.ask(f"{label} [{default}]: ").lower()
            value = raw or default
            if value == "markdown" and "md" in choices:
                value = "md"
            if value in choices:
                return value
            self.say(f"Choose one of: {', '.join(sorted(choices))}.")

    def choose_bool(self, label: str, default: bool) -> bool:
        while True:
            raw = self.ask(f"{label} [{'Y/n' if default else 'y/N'}]: ").lower()
            if not raw:
                return default
            if raw in {"y", "yes"}:
                return True
            if raw in {"n", "no"}:
                return False
            self.say("Enter y or n.")

    def choose_workers(self, default: int) -> int:
        while True:
            raw = self.ask(f"Parallel workers [{default}]: ")
            if not raw:
                return default
            try:
                value = int(raw)
            except ValueError:
                value = 0
            if value > 0:
                return value
            self.say("Parallel workers must be a positive whole number.")

    def show_summary(self, plan: InteractivePlan) -> None:
        values, resolved = plan.resolved.values, plan.resolved
        self.say("\nResolved configuration")
        self.say("----------------------")
        self.say(
            f"Workflow: {'Markdown sections' if resolved.command == 'markdown' else 'File batch'}"
        )
        if plan.input_files is not None:
            self.say(f"Inputs: {len(plan.input_files)} file(s)")
            for path in plan.input_files[:8]:
                self.say(f"  - {path}")
            if len(plan.input_files) > 8:
                self.say(f"  - ... and {len(plan.input_files) - 8} more")
        else:
            self.say(f"Markdown file: {values.get('markdown_file')}")
        self.say(f"Prompt: {values.get('prompt')}")
        self.say(f"Output directory: {values.get('output_dir')}")
        self.say(f"Output format: .{values.get('output_ext')}")
        self.say(f"Overwrite existing outputs: {'yes' if values.get('overwrite') else 'no'}")
        self.say(f"Resume: {'yes' if values.get('resume') else 'no'}")
        self.say(f"Browser provider: {resolved.runtime.browser_provider}")
        self.say(f"Parallel workers: {resolved.runtime.parallel_runs}")
        self.say(f"Profile: {resolved.profile or '(none)'}")
        self.say(f"Config file: {resolved.config_path or '(built-in defaults)'}")
        if values.get("limit") is not None:
            self.say(f"Limit: {values.get('limit')}")
        if resolved.command == "markdown" and values.get("sections"):
            self.say(f"Sections: {values.get('sections')}")


def build_interactive_plan(
    *,
    config_path: Path | None,
    profile: str | None,
    input_fn: Callable[[str], str] | None = None,
    output: TextIO | None = None,
    cwd: Path | None = None,
    project_root: Path | None = None,
) -> InteractivePlan:
    cwd = (cwd or Path.cwd()).resolve()
    wizard = _Wizard(
        input_fn=input_fn if input_fn is not None else input,
        output=output if output is not None else sys.stdout,
        cwd=cwd,
        project_root=(project_root or Path(__file__).resolve().parents[1]).resolve(),
    )
    seed = resolve_config("pdf", config_path=config_path, profile=profile, cwd=cwd)
    default_input = seed.values.get("input_dir")
    if not isinstance(default_input, Path):
        raise ConfigError("Resolved PDF input_dir is not a filesystem path.")

    input_dir, selected = wizard.choose_source(default_input)
    workflow = wizard.choose_workflow(selected)
    source_overrides: dict[str, object] = (
        {"markdown_file": selected[0]} if workflow == "markdown" else {"input_dir": input_dir}
    )
    base = resolve_config(
        workflow,
        config_path=config_path,
        profile=profile,
        cli_overrides=source_overrides,
        cwd=cwd,
    )
    prompt = wizard.choose_prompt(base)
    default_output = base.values.get("output_dir")
    if not isinstance(default_output, Path):
        raise ConfigError("Resolved output_dir is not a filesystem path.")
    output_dir = wizard.choose_output(default_output)
    output_ext = wizard.choose_choice(
        "Output format (opml/md)",
        {"opml", "md"},
        (
            "md"
            if str(base.values.get("output_ext")).lower() == "markdown"
            else str(base.values.get("output_ext", "opml"))
        ),
    )
    overwrite = wizard.choose_bool("Overwrite existing outputs", bool(base.values.get("overwrite")))
    browser_provider = wizard.choose_choice(
        "Browser provider (selenium/patchright)",
        {"selenium", "patchright"},
        base.runtime.browser_provider,
    )
    parallel_runs = wizard.choose_workers(base.runtime.parallel_runs)

    resolved = resolve_config(
        workflow,
        config_path=config_path,
        profile=profile,
        cli_overrides={
            **source_overrides,
            "prompt": prompt,
            "output_dir": output_dir,
            "output_ext": output_ext,
            "overwrite": overwrite,
            "browser_provider": browser_provider,
            "parallel_runs": parallel_runs,
        },
        cwd=cwd,
    )
    plan = InteractivePlan(resolved, selected if workflow == "pdf" else None)
    wizard.show_summary(plan)
    if not wizard.choose_bool("Continue with this configuration", False):
        raise InteractiveCancelled
    return plan
