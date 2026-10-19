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


#: §9 item 11 (final rule): for a program that is NOT workspace-relative, a known
#: name followed by the end or by ANY non-letter is that name (`zsh-5.9`, `bash+x`,
#: `php-cgi8.2`, `sudo.ws`, `perl5.36.0-x86_64-linux`, `env-x`). Fail closed.
_SUFFIX_SHAPED: Final = r"(?:[^a-z].*)?"


def is_workspace_relative(program: str) -> bool:
    """`./env_setup.sh`, `tools/flash`: a relative path naming a workspace file."""
    return "/" in program and not program.startswith(("/", "~"))


def prefix_match(base: str, names: Iterable[str]) -> str | None:
    """The denied name `base` is: the name itself plus a suffix-shaped tail."""
    lowered = posixpath.basename(base).lower()
    for name in sorted(names, key=len, reverse=True):
        if re.fullmatch(re.escape(name.lower()) + _SUFFIX_SHAPED, lowered, re.DOTALL):
            return name
    return None


def exact_match(base: str, names: Iterable[str]) -> str | None:
    """The exact lower-cased basename — for workspace-relative programs, where a
    name rule is cosmetic anyway (renaming the file defeats it)."""
    lowered = posixpath.basename(base).lower()
    return {name.lower(): name for name in names}.get(lowered)


def name_match(base: str, names: Iterable[str], *, exact: bool, gnu: bool = False) -> str | None:
    """`prefix_match` (or `exact_match`), plus the GNU `g`-prefixed build of a
    name when `gnu` (`gtimeout`, `genv`) for programs that are not workspace files."""
    match = exact_match if exact else prefix_match
    found = match(base, names)
    lowered = posixpath.basename(base).lower()
    if found is None and gnu and not exact and lowered.startswith("g"):
        found = prefix_match(lowered[1:], names)
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
