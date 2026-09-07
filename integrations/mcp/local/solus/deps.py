"""Dependency declarations for `scan_folder` (docs/api/code-environment.md §3).

Parses `requirements*.txt` (PEP 508 lines), `pyproject.toml` (`[project]`
dependencies + every optional-dependencies list, via `tomllib` — no
execution) and `environment.yml` (a minimal line reader over the
`dependencies:` list and its nested `- pip:` block — NO YAML library, the
companion's no-YAML posture). Every entry is
`{parts, ecosystem, name, specifier, extras, line}` with the name PEP 503
normalised and the specifier the raw PEP 440 set (`""` when unpinned).

Bounds: a file over MAX_DEP_FILE_BYTES is skipped, the list stops at
MAX_DEPENDENCIES (then `truncated_dependencies`), specifiers are capped at
MAX_SPECIFIER_CHARS and cut under the cloud's 40-char entropic-redaction
threshold, extras at MAX_EXTRAS. `-r`/`-c`/`-e`/option lines are skipped and
NEVER followed. Nothing here raises: a hostile file yields fewer entries.
"""

import logging
import re
import tomllib
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TypedDict

from .toolmap import is_dependency_file

logger = logging.getLogger("solus.local.deps")

ECOSYSTEM = "python"
#: Scan ceiling for dependency entries (route plan §3).
MAX_DEPENDENCIES = 500
#: Dependency files over this size are skipped outright.
MAX_DEP_FILE_BYTES = 256 * 1024
MAX_SPECIFIER_CHARS = 128
MAX_EXTRAS = 8
MAX_EXTRA_CHARS = 32
#: Strictly under the cloud's `_ENTROPIC_MIN_LEN` (40): a longer name or a
#: longer base64-ish specifier would be masked at ingress.
MAX_WIRE_CHARS = 39
_ENTROPIC = re.compile(r"^[A-Za-z0-9+/=_.-]+$")

_NAME = r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?"
_NAME_RE = re.compile(rf"^{_NAME}$")
_REQUIREMENT = re.compile(rf"^(?P<name>{_NAME})\s*(?:\[(?P<extras>[^\]]*)\])?(?P<rest>.*)$")
_SPECIFIER_SET = re.compile(r"^(?:(?:===|~=|==|!=|<=|>=|<|>)[A-Za-z0-9.*+!_-]+,?)*$")
_COMMENT = re.compile(r"(?:^|\s)#")
_YAML_ITEM = re.compile(r"^(?P<indent>\s*)-\s*(?P<body>.*)$")
_CONDA_CHANNEL = re.compile(r"^[A-Za-z0-9_.-]+::")
_CONDA_SINGLE_EQ = re.compile(r"^=(?!=)(?P<version>[A-Za-z0-9.*+!_-]+)(?:=[A-Za-z0-9.*+!_-]*)?$")


class Requirement(TypedDict):
    name: str
    specifier: str
    extras: list[str]
    line: int


class Dependency(Requirement):
    parts: list[str]
    ecosystem: str


Parser = Callable[[str], list[Requirement]]


def normalize_name(name: str) -> str:
    """PEP 503: lower-case, runs of `-_.` collapse to `-`."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _strip_comment(line: str) -> str:
    match = _COMMENT.search(line)
    return line[: match.start()] if match else line


def _bound_specifier(raw: str) -> str:
    specifier = re.sub(r"\s+", "", raw).strip("()")[:MAX_SPECIFIER_CHARS]
    if len(specifier) >= MAX_WIRE_CHARS + 1 and _ENTROPIC.match(specifier):
        return specifier[:MAX_WIRE_CHARS]
    return specifier


def _extras(raw: str | None) -> list[str]:
    if not raw:
        return []
    seen: list[str] = []
    for item in raw.split(","):
        extra = normalize_name(item.strip())
        if extra and len(extra) <= MAX_EXTRA_CHARS and _NAME_RE.match(extra) and extra not in seen:
            seen.append(extra)
    return seen[:MAX_EXTRAS]


def parse_requirement(text: str, line: int) -> Requirement | None:
    """One PEP 508 requirement (marker dropped, `@ url` dropped), or None
    when the text is not a plain named requirement."""
    body = _strip_comment(text).split(";", 1)[0].split("@", 1)[0].strip()
    match = _REQUIREMENT.match(body)
    if match is None:
        return None
    name = normalize_name(match.group("name"))
    specifier = _bound_specifier(match.group("rest"))
    if len(name) > MAX_WIRE_CHARS or _SPECIFIER_SET.match(specifier) is None:
        return None
    return {
        "name": name,
        "specifier": specifier,
        "extras": _extras(match.group("extras")),
        "line": line,
    }


def _logical_lines(text: str) -> list[tuple[int, str]]:
    """`(first physical line, joined text)` with backslash continuations folded."""
    joined: list[tuple[int, str]] = []
    pending = ""
    start = 0
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not pending:
            start = number
        if line.endswith("\\"):
            pending += line[:-1].rstrip() + " "
            continue
        joined.append((start, (pending + line).strip()))
        pending = ""
    if pending:
        joined.append((start, pending.strip()))
    return joined


def parse_requirements_txt(text: str) -> list[Requirement]:
    """PEP 508 lines; comments, blanks and every `-`/`--` option line
    (`-r`, `-c`, `-e`, `--index-url`, …) are skipped and never followed."""
    found: list[Requirement] = []
    for number, line in _logical_lines(text):
        if not line or line.startswith(("#", "-")):
            continue
        requirement = parse_requirement(line, number)
        if requirement is not None:
            found.append(requirement)
    return found


def _locate(lines: list[str], needle: str, after: int) -> int:
    """1-based line of the first line at/after `after` containing `needle`,
    else 0 (tomllib keeps no positions)."""
    for index in range(after, len(lines)):
        if needle in lines[index]:
            return index + 1
    return 0


def _string_list(value: object) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def parse_pyproject(text: str) -> list[Requirement]:
    """`[project].dependencies` then every `[project.optional-dependencies]`
    list, in file order of the tables."""
    try:
        data = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, RecursionError, ValueError):
        return []
    project = data.get("project")
    if not isinstance(project, dict):
        return []
    groups = [_string_list(project.get("dependencies"))]
    optional = project.get("optional-dependencies")
    if isinstance(optional, dict):
        groups.extend(_string_list(items) for items in optional.values())
    lines = text.splitlines()
    found: list[Requirement] = []
    cursor = 0
    for group in groups:
        for raw in group:
            line = _locate(lines, raw, cursor)
            cursor = max(cursor, line - 1) if line else cursor
            requirement = parse_requirement(raw, line)
            if requirement is not None:
                found.append(requirement)
    return found


def _unquote(body: str) -> str:
    stripped = _strip_comment(body).strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in "'\"":
        return stripped[1:-1].strip()
    return stripped


def parse_conda_item(text: str, line: int) -> Requirement | None:
    """A conda spec: `name`, `name=ver[=build]` (→ `==ver`), or `name<op>ver`."""
    body = _CONDA_CHANNEL.sub("", _unquote(text))
    match = _REQUIREMENT.match(body)
    if match is None or match.group("extras") is not None:
        return None
    rest = re.sub(r"\s+", "", match.group("rest"))
    single = _CONDA_SINGLE_EQ.match(rest)
    if single is not None:
        rest = "==" + single.group("version")
    return parse_requirement(f"{match.group('name')}{rest}", line)


def _indent(match: re.Match[str]) -> int:
    return len(match.group("indent"))


def parse_environment_yml(text: str) -> list[Requirement]:
    """The top-level `dependencies:` list — conda items plus the nested
    `- pip:` block's PEP 508 items. A minimal line reader: no YAML library."""
    found: list[Requirement] = []
    in_deps = False
    pip_indent: int | None = None
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not in_deps:
            in_deps = _strip_comment(line).strip() == "dependencies:" and not line[0].isspace()
            continue
        item = _YAML_ITEM.match(line)
        if item is None or (item.group("indent") == "" and not line.startswith("-")):
            if not line[0].isspace():
                break  # the next top-level key
            continue
        body = _unquote(item.group("body"))
        if pip_indent is not None and _indent(item) > pip_indent:
            requirement = parse_requirement(body, number) if not body.startswith("-") else None
        else:
            pip_indent = _indent(item) if body == "pip:" else None
            requirement = None if body == "pip:" else parse_conda_item(body, number)
        if requirement is not None:
            found.append(requirement)
    return found


def parser_for(name: str) -> Parser | None:
    lower = name.lower()
    if lower == "pyproject.toml":
        return parse_pyproject
    if lower == "environment.yml":
        return parse_environment_yml
    return parse_requirements_txt if is_dependency_file(lower) else None


def _read_bounded(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_DEP_FILE_BYTES:
            return None
        with path.open("rb") as handle:
            data = handle.read(MAX_DEP_FILE_BYTES + 1)
    except OSError:
        return None
    return None if len(data) > MAX_DEP_FILE_BYTES else data.decode("utf-8", errors="replace")


def parse_dependency_file(path: Path, parts: list[str]) -> list[Dependency]:
    """Every entry of one dependency file under the workspace, or `[]`."""
    parser = parser_for(parts[-1]) if parts else None
    if parser is None:
        return []
    text = _read_bounded(path)
    if text is None:
        return []
    try:
        requirements = parser(text)
    except Exception as exc:  # noqa: BLE001 - a hostile file yields nothing, never a crash
        logger.warning("dependency parse of %s failed: %s", "/".join(parts), type(exc).__name__)
        return []
    return [{"parts": list(parts), "ecosystem": ECOSYSTEM, **item} for item in requirements]


def collect_dependencies(
    root: Path, file_parts: Iterable[list[str]]
) -> tuple[list[Dependency], bool]:
    """`(dependencies, truncated)` over the scan's (sorted) file `parts`."""
    collected: list[Dependency] = []
    for parts in file_parts:
        if not parts or not is_dependency_file(parts[-1]):
            continue
        for dependency in parse_dependency_file(root.joinpath(*parts), parts):
            if len(collected) == MAX_DEPENDENCIES:
                return collected, True
            collected.append(dependency)
    return collected, False
