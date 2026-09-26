"""Repo config as a first-class source (R2). The user's own code names their parts: a motor
map, the addresses, the models, a calibration file. Parsers are plugins behind a registry; the
one generic reader here knows SHAPES (a `motors`/`parts` map in YAML, JSON or TOML), never a
vendor idiom. Everything a parser reports is provenance `repo` and a proposal input.

Repo content is untrusted (CLAUDE.md §7): bounded walk, bounded file sizes, no execution, a
parser that raises is skipped.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import stat
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, ClassVar, Final, Protocol

from solus_api.hardware.config import BusMapEntry, CalibrationMode

from livebench.recognition.firmware import decode_extraction_source

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

    def extract_bytes(
        self, source: bytes, *, suffix: str, source_ref: str
    ) -> list[RepoConfigMatch]:
        if suffix not in _STRUCTURED_SUFFIXES:
            return []
        return extract_repo_config_bytes(source, suffix=suffix, source_ref=source_ref)

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


def _yaml_bytes_document(text: str) -> Any:
    import yaml

    depth = events = 0
    for event in yaml.parse(text):
        events += 1
        if isinstance(event, yaml.events.CollectionStartEvent):
            depth += 1
        elif isinstance(event, yaml.events.CollectionEndEvent):
            depth -= 1
        if (
            events > 4096
            or depth > 32
            or isinstance(event, yaml.events.AliasEvent)
            or getattr(event, "anchor", None)
        ):
            raise ValueError("YAML aliases, anchors or excessive structure are not supported")
    return _unique_yaml_document(text)


def _unique_pairs(pairs: list[tuple[Any, Any]]) -> dict[Any, Any]:
    result: dict[Any, Any] = {}
    for key, value in pairs:
        try:
            if key in result:
                raise ValueError("duplicate configuration mapping key")
            result[key] = value
        except TypeError as exc:
            raise ValueError("unsupported configuration mapping key") from exc
    return result


def _unique_yaml_document(text: str) -> Any:
    import yaml

    loader: Any = yaml.SafeLoader(text)
    try:
        root = loader.get_single_node()
        nodes = [root] if root is not None else []
        while nodes:
            node = nodes.pop()
            if isinstance(node, yaml.nodes.MappingNode):
                _unique_pairs(
                    [(loader.construct_object(key, deep=True), None) for key, _ in node.value]
                )
                nodes.extend(child for pair in node.value for child in pair)
            elif isinstance(node, yaml.nodes.SequenceNode):
                nodes.extend(node.value)
        return loader.construct_document(root) if root is not None else None
    finally:
        loader.dispose()


def _check_document_budget(document: Any) -> None:
    stack = [(document, 0)]
    remaining = 4096
    while stack:
        value, depth = stack.pop()
        remaining -= 1
        if depth > 32 or remaining < 0:
            raise ValueError("configuration structure exceeds extraction budget")
        if isinstance(value, dict):
            if len(value) * 2 > remaining - len(stack):
                raise ValueError("configuration object exceeds extraction budget")
            stack.extend((item, depth + 1) for pair in value.items() for item in pair)
        elif isinstance(value, list):
            if len(value) > remaining - len(stack):
                raise ValueError("configuration array exceeds extraction budget")
            stack.extend((item, depth + 1) for item in value)
        else:
            _check_config_scalar(value)


def _check_config_scalar(value: Any) -> None:
    if value is not None and not isinstance(value, (str, int, float, bool)):
        raise ValueError("configuration supports only JSON-compatible scalars")
    if isinstance(value, str) and len(value) > 512:
        raise ValueError("configuration token exceeds extraction budget")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("configuration scalars must be finite")


def _decode_config_document(text: str, suffix: str) -> Any:
    import yaml

    try:
        if suffix == ".json":
            return json.loads(text, object_pairs_hook=_unique_pairs)
        if suffix == ".toml":
            return tomllib.loads(text)
        return _yaml_bytes_document(text)
    except (ValueError, RecursionError, yaml.YAMLError) as exc:
        raise ValueError("malformed or over-budget configuration") from exc


def _check_address_scalar(value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError("declared addresses must be strings or finite numbers")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("declared addresses must be finite")
    if isinstance(value, int) and value.bit_length() > 1701:
        raise ValueError("declared address exceeds field bounds")
    if not 1 <= len(str(value)) <= 512:
        raise ValueError("declared address exceeds field bounds")


def _check_address_aliases(spec: Mapping[str, Any]) -> None:
    addresses = [spec[key] for key in _ADDRESS_KEYS if key in spec]
    for address in addresses:
        _check_address_scalar(address)
    if len({str(address) for address in addresses}) > 1:
        raise ValueError("contradictory address aliases")


def _byte_config_parts(document: Mapping[str, Any]) -> list[RepoPartDecl]:
    """Visit every supported section; duplicate names are ambiguous, never silently overwritten."""
    parts: list[RepoPartDecl] = []
    names: set[str] = set()
    declared = 0
    for key in _PART_KEYS:
        section = document.get(key)
        if not isinstance(section, (Mapping, list)):
            continue
        declared += len(section)
        if declared > MAX_PARTS_PER_CONFIG:
            raise ValueError("declared parts exceed extraction budget")
        specs = section.values() if isinstance(section, Mapping) else section
        for spec in specs:
            if isinstance(spec, Mapping):
                _check_address_aliases(spec)
        for part in _parts_of({key: section}):
            if part.name in names:
                raise ValueError("ambiguous duplicate part name")
            names.add(part.name)
            parts.append(part)
    return parts


def extract_repo_config_bytes(
    source: bytes, *, suffix: str, source_ref: str
) -> list[RepoConfigMatch]:
    """Review supplied structured bytes with opaque provenance; never expose local path hints."""
    text = decode_extraction_source(source, source_ref)
    if not isinstance(suffix, str) or suffix not in _STRUCTURED_SUFFIXES:
        raise ValueError("unsupported configuration suffix")
    document = _decode_config_document(text, suffix)
    if not isinstance(document, Mapping):
        raise ValueError("configuration must be an object")
    _check_document_budget(document)
    parts = _byte_config_parts(document)
    if not parts:
        return []
    return [
        RepoConfigMatch(
            config_id=source_ref,
            parser_id=GenericStructuredParser.parser_id,
            label=source_ref,
            source=source_ref,
            protocol_hint=_string(document, "protocol", "driver", "driver_id"),
            parts=parts,
        )
    ]


def parse_repo_sources(
    sources: Sequence[Mapping[str, Any]], registry: RepoParserRegistry
) -> list[RepoConfigMatch]:
    """Private byte capability: selected files only, with content-bound portable IDs."""
    matches: list[RepoConfigMatch] = []
    for source in sources:
        content, ref, suffix = source["content"], source["source_ref"], source["suffix"]
        decode_extraction_source(content, ref)
        for parser in registry.all():
            extract = getattr(parser, "extract_bytes", None)
            if not callable(extract):
                continue
            parsed = extract(content, suffix=suffix, source_ref=ref)
            for match in parsed:
                identity = hashlib.sha256(
                    content + f"\0{ref}\0{parser.parser_id}\0{match.config_id}".encode()
                ).hexdigest()
                declared = {
                    part.address: part.calibration_mode.value
                    for part in match.parts
                    if part.calibration_mode is not None
                }
                # Source declarations do not establish this physical device's calibration.
                # Keep modes as evidence, never as units for uncalibrated position packets.
                parts = [replace(part, calibration_mode=None) for part in match.parts]
                params = (
                    {**match.params, "declared_calibration_modes": declared}
                    if declared
                    else match.params
                )
                matches.append(
                    replace(
                        match, config_id=f"repo:{identity}", source=ref, parts=parts, params=params
                    )
                )
    return sorted(matches, key=lambda match: (match.source, match.config_id))
