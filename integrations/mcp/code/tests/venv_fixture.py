"""A fabricated virtualenv that passes `plan.venv_python`'s authenticity check
the way a real one does: a `pyvenv.cfg` marker and a `bin/python` that is a
symlink to an interpreter OUTSIDE the workspace (every venv on this platform
links to the base interpreter). Used by the plan/probe/server/execute suites."""

from __future__ import annotations

import os
from pathlib import Path


def fake_venv(root: Path, name: str = ".venv", body: str = "#!/bin/sh\n") -> Path:
    """Create `root/name` as a venv; return the workspace-side `bin/python` path."""
    outside = root.parent / f"{root.name}.interp-{name.replace('/', '_')}"
    outside.mkdir(parents=True, exist_ok=True)
    interpreter = outside / "python"
    interpreter.write_text(body)
    interpreter.chmod(0o755)
    python = root / name / "bin" / "python"
    python.parent.mkdir(parents=True)
    (root / name / "pyvenv.cfg").write_text("home = /usr/bin\nversion = 3.12.0\n")
    os.symlink(interpreter, python)
    return python
