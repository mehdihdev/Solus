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


#: §9 item 11: what may follow a shell/interpreter name — a version, then dash
#: tokens (`python3.12-intel64`, `perl5.34-thread-multi`, `php-cgi`, `bash5.2`).
_VERSION_SHAPED: Final = r"(?:[0-9][0-9.]*)?(?:-[a-z0-9]+)*"


def prefix_match(base: str, names: Iterable[str]) -> str | None:
    """A shell or interpreter `base` is, by its name plus a VERSION-SHAPED suffix
    only (§9 item 11). `sh_build.sh`, `nu_test` and `bashful` are not shells."""
    lowered = posixpath.basename(base).lower()
    for name in sorted(names, key=len, reverse=True):
        if re.fullmatch(re.escape(name.lower()) + _VERSION_SHAPED, lowered):
            return name
    return None


def exact_match(base: str, names: Iterable[str]) -> str | None:
    """A wrapper or elevation tool: the exact lower-cased basename, or the GNU
    `g`-prefixed build of one (`gtimeout`, `genv`)."""
    lowered = posixpath.basename(base).lower()
    table = {name.lower(): name for name in names}
    found = table.get(lowered)
    if found is None and lowered.startswith("g"):
        found = table.get(lowered[1:])
    return found


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
