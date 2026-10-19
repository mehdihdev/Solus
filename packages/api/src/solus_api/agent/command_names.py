"""Program-name normalisation shared by the deny table and the risk badges.

Security review 2026-10-18 item 4: `/usr/bin/Python3.13t`, `python3-dbg`,
`pythonw`, `pypy3.10`, `nodejs` and `luajit` must all be judged as the
interpreter they are.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Iterable
from typing import Final

from solus_api.agent.command_interpreters import INLINE_CODE

#: Interpreter aliases after normalisation (security review item 4).
_ALIASES: Final = {"pypy": "python", "nodejs": "node", "luajit": "lua", "rscript": "Rscript"}
INTERPRETERS: Final = {name.lower(): name for name in INLINE_CODE} | _ALIASES
_DEBUG_SUFFIX: Final = re.compile(r"-dbg$")
_VERSION_SUFFIX: Final = re.compile(r"[-_.]?[0-9][0-9.]*[a-z]*$")


def prefix_match(base: str, names: Iterable[str]) -> str | None:
    """Fail closed by PREFIX (security review round 2): `python3.12-intel64`,
    `perl5.34-thread-multi`, `php-cgi`, `node-arm64` are the interpreter they
    start with — a known name followed by a non-letter (or the end)."""
    lowered = posixpath.basename(base).lower()
    for name in sorted(names, key=len, reverse=True):
        key = name.lower()
        if lowered == key or (lowered.startswith(key) and not lowered[len(key)].isalpha()):
            return name
    return None


def normalise(program: str) -> str:
    """The interpreter `program` is (`/usr/bin/Python3.13t`, `python3-dbg`,
    `pythonw`, `nodejs`, `php-cgi` → its canonical name), else the lower-cased
    basename with version/build suffixes stripped (`pip3.12` → `pip`)."""
    lowered = posixpath.basename(program).lower()
    matched = prefix_match(lowered, INTERPRETERS)
    if matched is not None:
        return INTERPRETERS[matched]
    stem = _VERSION_SUFFIX.sub("", _DEBUG_SUFFIX.sub("", lowered))
    if stem.endswith("w") and stem[:-1] in INTERPRETERS:
        return INTERPRETERS[stem[:-1]]
    return stem
