"""Unified configuration and command-line interface for Note Maker."""

from .config import ConfigError, ResolvedConfig, resolve_config

__all__ = ["ConfigError", "ResolvedConfig", "resolve_config"]
