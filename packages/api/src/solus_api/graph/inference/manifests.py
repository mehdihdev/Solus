"""Pure manifest parsers: `package.json` (npm) and `package.xml` (ROS) → `ManifestDep`.

Manifest text is ingested, untrusted data (CLAUDE.md §7): names and specifiers are shape-checked
per ecosystem so a dependency can carry a version, never a sentence; XML refuses any DTD and is
size-capped; malformed input yields `[]`, never an exception. The companion's `deps.py` carries
the stdlib-only twin of these rules for the local scanner.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Final, Literal

Ecosystem = Literal["python", "npm", "ros"]

MAX_NAME_CHARS: Final = 128
MAX_SPECIFIER_CHARS: Final = 128
MAX_XML_BYTES: Final = 1024 * 1024

NAME_RULES: Final[dict[str, re.Pattern[str]]] = {
    "python": re.compile(r"^[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?$"),
    "npm": re.compile(r"^(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*$"),
    "ros": re.compile(r"^[a-z][a-z0-9_]*$"),
}
#: The tail of a protocol ref (`npm:`, `file:`, `git+ssh:`, `workspace:`…) or an alias
#: (`pkg@range`): a bounded printable charset, never free-form `\S*` (review of 06feb9eb).
_NPM_REF_TAIL: Final = r"[A-Za-z0-9._/@^~<>=*+:#-]{1,64}"
#: A URL-ish scheme (`npm:`, `file:`, `git+ssh:`, `workspace:`…): generic, never a vendor list.
_NPM_SCHEME: Final = r"[a-z][a-z0-9+]{0,15}"
#: One semver-range token: a version-ish thing, a wildcard, a keyword or a protocol ref.
_NPM_RANGE_ATOM: Final = (
    rf"(?:[\^~<>=|v]*\d[\w.+-]*|\*|x|latest|next|{_NPM_SCHEME}:{_NPM_REF_TAIL}"
    rf"|[\w.@/-]+@{_NPM_REF_TAIL}|-|\|\|)"
)
SPECIFIER_RULES: Final[dict[str, re.Pattern[str]]] = {
    "python": re.compile(r"^(?:(?:===|~=|==|!=|<=|>=|<|>)[A-Za-z0-9.*+!_-]+,?)*$"),
    "npm": re.compile(rf"^(?:{_NPM_RANGE_ATOM}(?: {_NPM_RANGE_ATOM}){{0,3}})?$", re.IGNORECASE),
    "ros": re.compile(r"^$"),
}
NPM_GROUPS: Final = ("dependencies", "devDependencies")
ROS_GROUPS: Final = ("depend", "build_depend", "exec_depend")


@dataclass(frozen=True)
class ManifestDep:
    name: str
    specifier: str
    ecosystem: Ecosystem
    group: str
    line: int = 0


def valid_dependency(name: str, specifier: str, ecosystem: str) -> bool:
    rule, spec = NAME_RULES.get(ecosystem), SPECIFIER_RULES.get(ecosystem)
    return (
        rule is not None
        and spec is not None
        and 0 < len(name) <= MAX_NAME_CHARS
        and len(specifier) <= MAX_SPECIFIER_CHARS
        and rule.match(name) is not None
        and spec.match(specifier) is not None
    )


def _line_containing(lines: list[str], needle: str, after: int) -> int:
    """1-based line of the first line at/after `after` containing `needle`, else 0."""
    for index in range(after, len(lines)):
        if needle in lines[index]:
            return index + 1
    return 0


def parse_package_json(text: str) -> list[ManifestDep]:
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):
        return []
    if not isinstance(data, dict):
        return []
    lines = text.splitlines()
    found: list[ManifestDep] = []
    cursor = 0
    for group in NPM_GROUPS:
        table = data.get(group)
        if not isinstance(table, dict):
            continue
        for raw_name, raw_spec in table.items():
            if not isinstance(raw_name, str) or not isinstance(raw_spec, str):
                continue
            name, specifier = raw_name.strip().lower(), raw_spec.strip()
            if not valid_dependency(name, specifier, "npm"):
                continue
            line = _line_containing(lines, f'"{raw_name}"', cursor)
            cursor = max(cursor, line - 1) if line else cursor
            found.append(ManifestDep(name, specifier, "npm", group, line))
    return found


def _xml_root(text: str) -> object:
    if len(text) > MAX_XML_BYTES or "<!DOCTYPE" in text or "<!ENTITY" in text:
        raise ValueError("refused")
    try:
        from defusedxml.ElementTree import (  # type: ignore[import-not-found,import-untyped,unused-ignore]
            fromstring,
        )
    except ImportError:
        from xml.etree.ElementTree import fromstring  # noqa: S405 — DTDs refused above
    return fromstring(text)  # noqa: S314 — DTDs refused above


def parse_package_xml(text: str) -> list[ManifestDep]:
    try:
        root = _xml_root(text)
    except Exception:  # noqa: BLE001 — a hostile file yields nothing, never a crash
        return []
    if getattr(root, "tag", None) != "package":
        return []
    lines = text.splitlines()
    found: list[ManifestDep] = []
    cursor = 0
    for element in root:  # type: ignore[attr-defined]
        group = element.tag
        if group not in ROS_GROUPS:
            continue
        name = (element.text or "").strip()
        if not valid_dependency(name, "", "ros"):
            continue
        line = _line_containing(lines, f"<{group}>{name}<", cursor)
        cursor = max(cursor, line - 1) if line else cursor
        found.append(ManifestDep(name, "", "ros", group, line))
    return found


def parse_dependency_manifest(path: str, text: str) -> list[ManifestDep]:
    """Dispatch on the file name; anything that is not a known manifest parses to `[]`."""
    name = path.rsplit("/", 1)[-1].lower()
    if name == "package.json":
        return parse_package_json(text)
    if name == "package.xml":
        return parse_package_xml(text)
    return []
