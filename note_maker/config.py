from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib

from scripts import runtime_flags


class ConfigError(ValueError):
    """Raised when a configuration file or override cannot be resolved safely."""


COMMAND_DEFAULTS: dict[str, dict[str, Any]] = {
    "pdf": {
        "input_dir": "inputs",
        "output_dir": "outputs/opml",
        "prompt": "prompts/prompt-mind-map.md",
        "output_ext": "opml",
        "overwrite": False,
        "limit": None,
        "model": None,
        "save_diagnostics": False,
        "save_page_source": False,
        "max_attempts": 3,
        "download_timeout": 90,
        "close_delay": 20,
        "no_warm_up": False,
        "keep_browser": False,
        "manifest": None,
        "resume": True,
        "retry_failed": False,
        "adopt_existing": False,
    },
    "markdown": {
        "markdown_file": None,
        "output_dir": "outputs/markdown",
        "prompt": "prompts/prompt-mind-map.md",
        "sections": None,
        "output_ext": "opml",
        "overwrite": False,
        "limit": None,
        "model": None,
        "save_diagnostics": False,
        "save_page_source": False,
        "max_section_attempts": 3,
        "download_timeout": 90,
        "close_delay": 20,
        "chrome_profile_dir": None,
        "no_warm_up": False,
        "keep_browser": False,
        "manifest": None,
        "resume": True,
        "retry_failed": False,
        "adopt_existing": False,
    },
}

PATH_KEYS = {
    "input_dir",
    "output_dir",
    "prompt",
    "manifest",
    "markdown_file",
    "runtime_dir",
    "chrome_profile_dir",
}
RUNTIME_KEYS = tuple(field.name for field in fields(runtime_flags.RuntimeSettings))

_ENV_TYPES: dict[str, type] = {
    "browser_provider": str,
    "parallel_runs": int,
    "runtime_dir": str,
    "profile_snapshot": str,
    "keep_runtime": bool,
    "worker_heartbeat_interval": float,
    "worker_timeout": float,
    "worker_ready_timeout": float,
    "worker_startup_stagger": float,
    "max_worker_restarts": int,
    "shutdown_grace_seconds": float,
    "global_rate_limit_cooldown": float,
    "auth_failures_before_abort": int,
    "rate_limit_failures_before_abort": int,
    "rate_limit_window_seconds": float,
    "adaptive_concurrency": bool,
    "adaptive_scale_down_threshold": int,
    "adaptive_recovery_seconds": float,
    "worker_max_jobs": int,
    "worker_memory_limit_mb": float,
    "network_retries": int,
    "browser_retries": int,
    "download_retries": int,
    "rate_limit_retries": int,
    "retry_backoff_base": float,
    "retry_backoff_cap": float,
    "retry_jitter_ratio": float,
    "input_dir": str,
    "output_dir": str,
    "prompt": str,
    "manifest": str,
    "markdown_file": str,
    "output_ext": str,
    "model": str,
    "limit": int,
    "overwrite": bool,
    "save_diagnostics": bool,
    "save_page_source": bool,
    "download_timeout": int,
    "close_delay": int,
    "no_warm_up": bool,
    "keep_browser": bool,
    "resume": bool,
    "retry_failed": bool,
    "adopt_existing": bool,
}


@dataclass(frozen=True)
class ResolvedConfig:
    command: str
    values: Mapping[str, Any]
    runtime: runtime_flags.RuntimeSettings
    config_path: Path | None
    profile: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "profile": self.profile,
            "config_path": str(self.config_path) if self.config_path else None,
            "values": _json_safe(dict(self.values)),
        }


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    return value


def _deep_merge(target: dict[str, Any], source: Mapping[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, Mapping) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value


def _table(value: Any, *, label: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ConfigError(f"{label} must be a TOML table.")
    return value


def load_config_file(path: Path) -> Mapping[str, Any]:
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except OSError as exc:
        raise ConfigError(f"Could not read configuration file {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid TOML in {path}: {exc}") from exc
    if not isinstance(data, Mapping):
        raise ConfigError(f"Configuration file {path} must contain a TOML document.")
    return data


def discover_config_path(explicit: Path | str | None, *, cwd: Path | None = None) -> Path | None:
    if explicit is not None:
        return Path(explicit).expanduser().resolve()
    env_value = os.environ.get("NOTE_MAKER_CONFIG", "").strip()
    if env_value:
        return Path(env_value).expanduser().resolve()
    candidate = (cwd or Path.cwd()) / "note-maker.toml"
    return candidate.resolve() if candidate.is_file() else None


def _parse_bool(value: str, *, name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"Environment override {name} must be true or false.")


def _coerce_env(name: str, value: str, expected: type) -> Any:
    try:
        if expected is bool:
            return _parse_bool(value, name=name)
        return expected(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Invalid environment override {name}={value!r}.") from exc


def environment_overrides(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    environ = environ or os.environ
    resolved: dict[str, Any] = {}
    for key, expected in _ENV_TYPES.items():
        env_name = f"NOTE_MAKER_{key.upper()}"
        raw = environ.get(env_name)
        if raw is None or raw == "":
            continue
        resolved[key] = _coerce_env(env_name, raw, expected)
    return resolved


def _normalize_paths(values: dict[str, Any], base_dir: Path) -> None:
    for key in PATH_KEYS:
        raw = values.get(key)
        if raw in (None, ""):
            values[key] = None if raw == "" else raw
            continue
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = base_dir / path
        values[key] = path.resolve()


def _runtime_from_values(values: Mapping[str, Any]) -> runtime_flags.RuntimeSettings:
    runtime_values = {
        key: values[key]
        for key in RUNTIME_KEYS
        if key in values
    }
    try:
        return runtime_flags.validate_runtime_settings(**runtime_values)
    except runtime_flags.RuntimeConfigurationError as exc:
        raise ConfigError(str(exc)) from exc


def resolve_config(
    command: str,
    *,
    config_path: Path | str | None = None,
    profile: str | None = None,
    cli_overrides: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> ResolvedConfig:
    if command not in COMMAND_DEFAULTS:
        raise ConfigError(f"Unknown command configuration: {command!r}.")

    cwd = (cwd or Path.cwd()).resolve()
    selected_path = discover_config_path(config_path, cwd=cwd)
    if selected_path is not None and not selected_path.is_file():
        raise ConfigError(f"Configuration file does not exist: {selected_path}")

    values: dict[str, Any] = asdict(runtime_flags.RuntimeSettings())
    values.update(COMMAND_DEFAULTS[command])
    base_dir = cwd

    if selected_path is not None:
        document = load_config_file(selected_path)
        base_dir = selected_path.parent
        _deep_merge(values, _table(document.get("runtime"), label="runtime"))
        commands = _table(document.get("commands"), label="commands")
        _deep_merge(values, _table(commands.get(command), label=f"commands.{command}"))

        if profile:
            profiles = _table(document.get("profiles"), label="profiles")
            selected_profile = profiles.get(profile)
            if selected_profile is None:
                available = ", ".join(sorted(str(name) for name in profiles)) or "none"
                raise ConfigError(
                    f"Profile {profile!r} was not found in {selected_path}; available: {available}."
                )
            profile_table = _table(selected_profile, label=f"profiles.{profile}")
            _deep_merge(
                values,
                _table(profile_table.get("runtime"), label=f"profiles.{profile}.runtime"),
            )
            profile_commands = _table(
                profile_table.get("commands"), label=f"profiles.{profile}.commands"
            )
            _deep_merge(
                values,
                _table(
                    profile_commands.get(command),
                    label=f"profiles.{profile}.commands.{command}",
                ),
            )

    _deep_merge(values, environment_overrides(environ))
    if cli_overrides:
        _deep_merge(
            values,
            {key: value for key, value in cli_overrides.items() if value is not None},
        )

    _normalize_paths(values, base_dir)
    runtime = _runtime_from_values(values)
    for key, value in asdict(runtime).items():
        values[key] = value

    if command == "markdown" and values.get("markdown_file") is None:
        raise ConfigError(
            "markdown_file is required. Set it in note-maker.toml, NOTE_MAKER_MARKDOWN_FILE, or --markdown-file."
        )

    return ResolvedConfig(
        command=command,
        values=values,
        runtime=runtime,
        config_path=selected_path,
        profile=profile,
    )
