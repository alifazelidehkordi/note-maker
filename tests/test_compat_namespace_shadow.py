from __future__ import annotations

"""Phase-2 regression tests: namespace-package shadow must not crash the CLI.

The real-world failure (found by running the CLI with cwd outside the repo in
a checkout whose ``scripts`` resolved as a namespace package): compat.py used
``Path(scripts.__file__)`` and crashed with ``TypeError: expected str, bytes
or os.PathLike object, not NoneType``. The regression test below reproduces
that exact condition in a subprocess — and carries a sanity guard so it
FAILS LOUDLY if the shadow condition did not hold, rather than passing
vacuously (critic issue 1, phase-2 review round 1).
"""

import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]

SUBPROC_SCRIPT = textwrap.dedent(
    """
    import json, sys
    # Sanity guard: the shadow condition MUST hold, or the test is invalid.
    import scripts
    if scripts.__file__ is not None:
        print(json.dumps({"sanity": "shadow-not-effective",
                          "scripts_file": scripts.__file__}))
        raise SystemExit(3)
    from note_maker.compat import activate_legacy_imports
    scripts_dir = activate_legacy_imports()
    from browser_runtime import selectors  # legacy import now resolves
    print(json.dumps({
        "sanity": "ok",
        "scripts_dir": str(scripts_dir),
        "selector": selectors.ASSISTANT_MESSAGE_SELECTOR[:40],
    }))
    """
)


class NamespaceShadowTests(unittest.TestCase):
    def test_compat_resolves_packaged_scripts_under_namespace_shadow(self):
        """PYTHONPATH shadow dir (scripts/ without __init__.py) must not
        break activate_legacy_imports; the sanity guard proves the shadow
        condition held."""
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ)
            # Simulate the real-world condition: a checkout whose scripts/
            # lacks __init__.py (namespace package). Copy the repo's
            # scripts/note_maker dirs without the package marker, and hide
            # any regular `scripts` package by pointing PYTHONPATH at the
            # namespace copy FIRST. (A regular package anywhere on sys.path
            # beats a namespace package, so the copy must not carry
            # scripts/__init__.py and the real ROOT must not be importable.)
            copy_root = Path(tmp) / "checkout"
            shutil.copytree(ROOT / "scripts", copy_root / "scripts",
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            (copy_root / "scripts" / "__init__.py").unlink(missing_ok=True)
            shutil.copytree(ROOT / "note_maker", copy_root / "note_maker",
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            (copy_root / "note_maker" / "__init__.py").write_text("")
            env = dict(os.environ)
            # REPLACE any inherited PYTHONPATH: the parent test run may carry
            # the repo root (which holds a regular scripts package) on it,
            # and a regular package anywhere on sys.path beats a namespace
            # package. The subprocess must see only the namespace copy.
            env["PYTHONPATH"] = str(copy_root)
            r = subprocess.run(
                [sys.executable, "-c", SUBPROC_SCRIPT],
                capture_output=True,
                text=True,
                env=env,
                cwd=tmp,  # foreign cwd, exactly the real-world condition
                timeout=120,
            )
            self.assertNotEqual(
                r.returncode,
                3,
                "sanity guard: namespace shadow did not take effect; test invalid",
            )
            self.assertEqual(
                r.returncode,
                0,
                f"compat must survive namespace shadow; stderr:\n{r.stderr}",
            )
            self.assertNotIn("TypeError", r.stderr)
            payload = json.loads(r.stdout.strip().splitlines()[-1])
            self.assertEqual(payload["sanity"], "ok")
            self.assertTrue(
                (Path(payload["scripts_dir"]) / "browser_runtime").is_dir(),
                "resolved scripts dir must be the packaged one",
            )

    def test_decoy_scripts_dir_in_cwd_never_wins(self):
        """A decoy scripts/ directory in the user's cwd must not be chosen."""
        with tempfile.TemporaryDirectory() as tmp:
            decoy = Path(tmp) / "decoy_cwd" / "scripts"
            decoy.mkdir(parents=True)  # exists but has no browser_runtime
            probe = textwrap.dedent(
                """
                import json
                from note_maker.compat import resolve_scripts_dir
                print(json.dumps({"resolved": str(resolve_scripts_dir())}))
                """
            )
            env = dict(os.environ)
            env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
            r = subprocess.run(
                [sys.executable, "-c", probe],
                capture_output=True,
                text=True,
                env=env,
                cwd=Path(tmp) / "decoy_cwd",
                timeout=120,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            resolved = json.loads(r.stdout.strip().splitlines()[-1])["resolved"]
            self.assertTrue(
                (Path(resolved) / "browser_runtime").is_dir(),
                "must resolve the packaged dir",
            )
            self.assertNotIn(str(decoy), resolved)


if __name__ == "__main__":
    unittest.main()
