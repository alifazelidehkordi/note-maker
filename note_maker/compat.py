"""Expose packaged ``scripts/`` modules under their historical top-level names.

Resolution priority (phase-2 plan item A1, critic-pinned):
  (a) the packaged location — the ``scripts/`` directory that ships next to
      the ``note_maker`` package (works for regular and editable installs
      because ``note_maker.__file__`` is always a real file, and it does not
      depend on sys.path search order, so a decoy ``scripts/`` directory in
      the user's cwd can never win);
  (b) an imported ``scripts`` module with a real ``__file__`` — namespace
      packages (``__file__ is None``) are explicitly rejected;
  (c) last resort — the repo layout relative to this file.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path


def resolve_scripts_dir() -> Path:
    """Return the packaged ``scripts/`` directory, shadow-proof."""
    # (a) packaged location via the note_maker package itself
    import note_maker

    note_maker_file = getattr(note_maker, "__file__", None)
    if note_maker_file:
        candidate = Path(note_maker_file).resolve().parent.parent / "scripts"
        if (candidate / "browser_runtime").is_dir():
            return candidate

    # (b) an already-resolvable regular package (never a namespace package)
    try:
        scripts = importlib.import_module("scripts")
    except Exception:  # pragma: no cover - import machinery failure
        scripts = None
    scripts_file = getattr(scripts, "__file__", None)
    if scripts_file:
        return Path(scripts_file).resolve().parent

    # (c) repo-layout last resort
    return Path(__file__).resolve().parents[1] / "scripts"


def activate_legacy_imports() -> Path:
    scripts_dir = resolve_scripts_dir()
    value = str(scripts_dir)
    if value not in sys.path:
        sys.path.insert(0, value)
    return scripts_dir
