from __future__ import annotations

import sys
from pathlib import Path


def activate_legacy_imports() -> Path:
    """Expose packaged ``scripts/`` modules under their historical top-level names."""
    import scripts

    scripts_dir = Path(scripts.__file__).resolve().parent
    value = str(scripts_dir)
    if value not in sys.path:
        sys.path.insert(0, value)
    return scripts_dir
