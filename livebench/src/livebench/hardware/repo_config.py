"""Repo config as a first-class source (R2). The user's own code names their parts: a motor
map, the addresses, the models, a calibration file. Parsers are plugins behind a registry; the
one generic reader here knows SHAPES (a `motors`/`parts` map in YAML, JSON or TOML), never a
vendor idiom. Everything a parser reports is provenance `repo` and a proposal input.

Repo content is untrusted (CLAUDE.md §7): bounded walk, bounded file sizes, no execution, a
parser that raises is skipped.
"""

from __future__ import annotations

import json
import logging
import os
import re
import stat
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Final, Protocol

from solus_api.hardware.config import BusMapEntry, CalibrationMode

logger = logging.getLogger(__name__)

MAX_SCAN_FILES: Final = 5000
MAX_STRUCTURED_BYTES: Final = 256 * 1024
MAX_PARTS_PER_CONFIG: Final = 256
SKIP_DIRS: Final = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        "build",
        "dist",
        ".mypy_cache",
        ".pytest_cache",
        "site-packages",
        ".cache",
    }
)
_STRUCTURED_SUFFIXES: Final = frozenset({".yaml", ".yml", ".json", ".toml"})
_PART_KEYS: Final = ("motors", "parts", "actuators", "servos", "sensors", "joints")
_ADDRESS_KEYS: Final = ("id", "address", "node", "addr")
_ALNUM: Final = re.compile(r"[^a-z0-9]")


@dataclass(frozen=True)
class RepoPartDecl:
    """One part the repo declares: its function name, bus address, model and calibration."""

    name: str
    address: str
    model: str | None = None
    calibration_mode: CalibrationMode | None = None
    calibration: dict[str, float | int] | None = None
    calibration_source: str | None = None


@dataclass(frozen=True)
class RepoConfigMatch:
    """One configuration the repo describes, as a parser understood it."""

    config_id: str
    parser_id: str
    label: str
    source: str
    protocol_hint: str | None = None
    parts: list[RepoPartDecl] = field(default_factory=list)
    port_hint: str | None = None  # a tty path the config binds — informational, never identity
    calibration_source: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    #: The parts are the columns of a print order (a sketch), not a keyed map — the proposal
    #: words it as "your sketch names them …".
    names_by_print_order: bool = False


class RepoConfigParser(Protocol):
    parser_id: ClassVar[str]

    def scan(self, root: Path, files: list[Path]) -> list[RepoConfigMatch]: ...


def _regular_file_inside(path: Path, root: Path) -> bool:
    """A regular file by lstat (so neither a symlink nor a FIFO) that resolves inside `root`."""
    # ponytail: one lstat answers "symlink?" and "regular?" at once — no separate is_symlink()
    try:
        return stat.S_ISREG(os.lstat(path).st_mode) and path.resolve().is_relative_to(root)
    except OSError:
        return False


def iter_repo_files(root: Path, *, max_files: int = MAX_SCAN_FILES) -> list[Path]:
    """A bounded, sorted walk that never enters vendor/VCS/virtualenv directories, never
    follows a symlink, and keeps regular files inside `root` only (repo content is untrusted,
    CLAUDE.md §7). Every entry walked — kept or skipped — is charged to the budget, so junk
    cannot exhaust memory before the cap bites."""
    resolved = root.resolve()
    budget = max_files * 8
    walked = 0
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            walked += 1
            if walked > budget or len(files) >= max_files:
                logger.info("repo scan stopped at %d files under %s", len(files), root)
                return files
            path = Path(dirpath) / name
            if _regular_file_inside(path, resolved):
                files.append(path)
    return files


class RepoParserRegistry:
    def __init__(self) -> None:
        self._parsers: dict[str, RepoConfigParser] = {}

    def register(self, parser_cls: type[RepoConfigParser]) -> None:
        parser = parser_cls()
        if parser.parser_id in self._parsers:
            raise ValueError(f"repo parser {parser.parser_id} is already registered")
        self._parsers[parser.parser_id] = parser

    def get(self, parser_id: str) -> RepoConfigParser:
        return self._parsers[parser_id]

    def all(self) -> list[RepoConfigParser]:
        return list(self._parsers.values())

    @classmethod
    def with_generic(cls) -> RepoParserRegistry:
        registry = cls()
        registry.register(GenericStructuredParser)
        return registry


def scan_repo(
    root: Path, registry: RepoParserRegistry, *, max_files: int = MAX_SCAN_FILES
) -> list[RepoConfigMatch]:
    """Every configuration any registered parser can read. A parser that raises is skipped."""
    files = iter_repo_files(root, max_files=max_files)
    matches: list[RepoConfigMatch] = []
    for parser in registry.all():
        try:
            matches.extend(parser.scan(root, files))
        except Exception as exc:
            logger.warning("repo parser %s failed: %s", parser.parser_id, type(exc).__name__)
    return sorted(matches, key=lambda m: (m.source, m.config_id))


# ── the generic structured reader ─────────────────────────────────────────────


def _load_structured(path: Path) -> Any:
    if path.stat().st_size > MAX_STRUCTURED_BYTES:
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        if path.suffix == ".json":
            return json.loads(text)
        if path.suffix == ".toml":
            return tomllib.loads(text)
        import yaml

        return yaml.safe_load(text)
    except Exception:
        return None


def _mode(value: object) -> CalibrationMode | None:
    if not isinstance(value, str):
        return None
    try:
        return CalibrationMode(value.lower())
    except ValueError:
        return None


def _part_from(name: str, spec: object) -> RepoPartDecl | None:
    if not isinstance(spec, Mapping):
        return None
    address = next((spec[key] for key in _ADDRESS_KEYS if key in spec), None)
    if address is None or isinstance(address, bool):
        return None
    model = spec.get("model")
    return RepoPartDecl(
        name=name,
        address=str(address),
        model=str(model) if isinstance(model, str) and model else None,
        calibration_mode=_mode(spec.get("mode")),
    )


def _parts_of(document: Mapping[str, Any]) -> list[RepoPartDecl]:
    for key in _PART_KEYS:
        section = document.get(key)
        parts: list[RepoPartDecl] = []
        if isinstance(section, Mapping):
            for name, spec in section.items():
                part = _part_from(str(name), spec)
                if part is not None:
                    parts.append(part)
        elif isinstance(section, list):
            for spec in section:
                if isinstance(spec, Mapping) and isinstance(spec.get("name"), str):
                    part = _part_from(spec["name"], spec)
                    if part is not None:
                        parts.append(part)
        if parts:
            return parts[:MAX_PARTS_PER_CONFIG]
    return []


def _string(document: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = document.get(key)
        if isinstance(value, str) and value:
            return value
    return None


class GenericStructuredParser:
    """YAML/JSON/TOML documents with a `motors`/`parts`/… map of `{id|address, model?, mode?}`."""

    parser_id: ClassVar[str] = "generic-structured"

    def scan(self, root: Path, files: list[Path]) -> list[RepoConfigMatch]:
        matches: list[RepoConfigMatch] = []
        for path in files:
            if path.suffix not in _STRUCTURED_SUFFIXES:
                continue
            document = _load_structured(path)
            if not isinstance(document, Mapping):
                continue
            parts = _parts_of(document)
            if not parts:
                continue
            relative = str(path.relative_to(root))
            matches.append(
                RepoConfigMatch(
                    config_id=f"generic:{relative}",
                    parser_id=self.parser_id,
                    label=relative,
                    source=str(path),
                    protocol_hint=_string(document, "protocol", "driver", "driver_id"),
                    parts=parts,
                    port_hint=_string(document, "port", "device"),
                    calibration_source=_string(document, "calibration", "calibration_file"),
                )
            )
        return matches


# ── matching a config against what the wire said ───────────────────────────────


def _model_key(model: str) -> str:
    return _ALNUM.sub("", model.lower())


def match_configs(
    bus_map: Sequence[BusMapEntry], configs: Sequence[RepoConfigMatch]
) -> list[RepoConfigMatch]:
    """Configs whose declared address set equals the bus map's, with compatible models where
    both sides know one. Every plausible config is returned — ambiguity is a question."""
    observed = {entry.address: entry.model for entry in bus_map}
    matched: list[RepoConfigMatch] = []
    for config in configs:
        declared = {part.address: part.model for part in config.parts}
        if set(declared) != set(observed):
            continue
        compatible = all(
            declared[address] is None
            or observed[address] is None
            or _model_key(declared[address] or "") == _model_key(observed[address] or "")
            for address in observed
        )
        if compatible:
            matched.append(config)
    return matched
