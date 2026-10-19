"""Program-name normalisation shared by the deny table and the risk badges.

Security review 2026-10-18 item 4: `/usr/bin/Python3.13t`, `python3-dbg`,
`pythonw`, `pypy3.10`, `nodejs` and `luajit` must all be judged as the
interpreter they are.
"""

from __future__ import annotations

import posixpath
import re
from typing import Final

from solus_api.agent.command_interpreters import INLINE_CODE

#: Interpreter aliases after normalisation (security review item 4).
_ALIASES: Final = {"pypy": "python", "nodejs": "node", "luajit": "lua", "rscript": "Rscript"}
INTERPRETERS: Final = {name.lower(): name for name in INLINE_CODE} | _ALIASES
_DEBUG_SUFFIX: Final = re.compile(r"-dbg$")
_VERSION_SUFFIX: Final = re.compile(r"[-_.]?[0-9][0-9.]*[a-z]*$")


def normalise(program: str) -> str:
    """Lower-cased basename with debug/version/build suffixes stripped:
    `/usr/bin/Python3.13t` → `python`, `python3-dbg` → `python`, `pythonw` →
    `python`, `nodejs` → `node`. Unknown names are returned stripped but not
    aliased (`ros2` → `ros`); callers check both spellings."""
    stem = _VERSION_SUFFIX.sub("", _DEBUG_SUFFIX.sub("", posixpath.basename(program).lower()))
    if stem not in INTERPRETERS and stem.endswith("w") and stem[:-1] in INTERPRETERS:
        stem = stem[:-1]
    return INTERPRETERS.get(stem, stem)
