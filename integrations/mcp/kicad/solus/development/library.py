"""Read real installed symbol definitions without loading/resaving schematics."""

import math
import os
import platform
import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

from solus.development.models import DevelopmentError, fingerprint
from solus.development.structural import children, value
from solus.write.sexpr import Node, SExprSyntaxError, parse, tokenize

MAX_LIBRARY_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True)
class LibraryPin:
    number: str
    name: str
    electrical_type: str
    x_mm: float
    y_mm: float
    angle: int
    unit: int


@dataclass(frozen=True)
class SymbolDefinition:
    library_id: str
    library_fingerprint: str
    definitions: tuple[bytes, ...]
    pins: tuple[LibraryPin, ...]
    default_reference: str
    default_value: str
    footprint: str


def installed_library_root() -> Path:
    """Fixed installation roots or package-manager query; no caller search path."""
    for native in _native_library_roots():
        if native.is_dir():
            return native.resolve()
    try:
        result = subprocess.run(
            ["/usr/bin/flatpak", "info", "--show-location", "org.kicad.KiCad.Library.Symbols"],
            capture_output=True,
            timeout=5,
            check=True,
        )
        location = Path(result.stdout.decode().strip())
        trusted = (Path("/var/lib/flatpak/runtime"), Path.home() / ".local/share/flatpak/runtime")
        if not location.is_absolute() or not any(
            location.resolve().is_relative_to(p.resolve()) for p in trusted
        ):
            raise DevelopmentError("library_unavailable")
        root = location / "files/symbols"
        if not root.is_dir():
            raise DevelopmentError("library_unavailable")
        return root.resolve()
    except (OSError, UnicodeError, subprocess.SubprocessError) as exc:
        raise DevelopmentError("library_unavailable") from exc


class _LibraryScan:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.depth = 0
        self.start = 0
        self.roots = 0
        self.end = 0
        self.quoted = False
        self.escaped = False
        self.found: dict[str, bytes] = {}

    def consume(self, index: int, byte: int) -> None:
        if self.quoted:
            if self.escaped:
                self.escaped = False
            elif byte == 92:
                self.escaped = True
            elif byte == 34:
                self.quoted = False
        elif byte == 34:
            self.quoted = True
        else:
            self.parenthesis(index, byte)

    def parenthesis(self, index: int, byte: int) -> None:
        if byte == 40:
            self.depth += 1
            if self.depth > 200:
                raise DevelopmentError("file_too_large")
            if self.depth == 1:
                self.roots += 1
            if self.depth == 2:
                self.start = index
        elif byte == 41:
            if self.depth == 2:
                self.block(index)
            self.depth -= 1
            if self.depth < 0:
                raise DevelopmentError("guard_failed")
            if self.depth == 0:
                self.end = index + 1

    def block(self, index: int) -> None:
        if not re.match(rb"\(symbol\s", self.data[self.start : self.start + 16]):
            return
        block = self.data[self.start : index + 1]
        if len(block) > 512 * 1024:
            raise DevelopmentError("file_too_large")
        name = value(parse(block))
        if name in self.found:
            raise DevelopmentError("ambiguous_target")
        self.found[name] = block


def _symbol_blocks(data: bytes) -> dict[str, bytes]:
    """One bounded byte scan; tokenize only individual symbol definitions."""
    scan = _LibraryScan(data)
    for index, byte in enumerate(data):
        scan.consume(index, byte)
    if (
        scan.depth
        or scan.quoted
        or scan.roots != 1
        or data[scan.end :].strip()
        or not re.match(rb"\s*\(kicad_symbol_lib\s", data)
    ):
        raise DevelopmentError("guard_failed")
    return scan.found


def _pins(node: Node) -> list[LibraryPin]:
    pins = []
    for unit_node in children(node, "symbol"):
        match = re.search(r"_(\d+)_([01])$", value(unit_node))
        if match is None:
            raise DevelopmentError("unsupported_symbol")
        unit = int(match[1])
        for pin in children(unit_node, "pin"):
            attrs = {name: children(pin, name) for name in ("at", "number", "name")}
            if any(len(nodes) != 1 for nodes in attrs.values()):
                raise DevelopmentError("unsupported_symbol")
            at = attrs["at"][0]
            try:
                x, y, angle = (float(value(at, index)) for index in (1, 2, 3))
                if not all(math.isfinite(v) for v in (x, y, angle)) or angle not in (
                    0,
                    90,
                    180,
                    270,
                ):
                    raise ValueError
            except ValueError as exc:
                raise DevelopmentError("unsupported_symbol") from exc
            pins.append(
                LibraryPin(
                    value(attrs["number"][0]),
                    value(attrs["name"][0]),
                    value(pin),
                    x,
                    y,
                    int(angle),
                    unit,
                )
            )
    return pins


class LibraryResolver:
    """Root is trusted launch configuration, never a tool argument."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def resolve(self, library_id: str) -> SymbolDefinition:
        if not isinstance(library_id, str) or library_id.count(":") != 1:
            raise DevelopmentError("library_unavailable")
        library, name = library_id.split(":")
        if any(
            not part
            or len(part) > 128
            or any(c in "/\\:" or ord(c) < 32 for c in part)
            or part in (".", "..")
            for part in (library, name)
        ):
            raise DevelopmentError("library_unavailable")
        path = self.root / (library + ".kicad_sym")
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as handle:
                if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                    raise DevelopmentError("library_unavailable")
                data = handle.read(MAX_LIBRARY_BYTES + 1)
            if len(data) > MAX_LIBRARY_BYTES:
                raise DevelopmentError("file_too_large")
            blocks = _symbol_blocks(data)
            chain = _inheritance(blocks, name)
            properties: dict[str, str] = {}
            pins: list[LibraryPin] = []
            for block in reversed(chain):
                node = parse(block)
                for prop in children(node, "property"):
                    properties[value(prop)] = value(prop, 2)
                local = _pins(node)
                if local:
                    pins = local
            identities = [(p.unit, p.number) for p in pins]
            if len(identities) != len(set(identities)) or any(not p.number for p in pins):
                raise DevelopmentError("ambiguous_target")
            return SymbolDefinition(
                library_id,
                fingerprint(b"".join(chain)),
                tuple(reversed(chain)),
                tuple(pins),
                properties.get("Reference", ""),
                properties.get("Value", ""),
                properties.get("Footprint", ""),
            )
        except (OSError, SExprSyntaxError, UnicodeError) as exc:
            raise DevelopmentError("library_unavailable") from exc


def _inheritance(blocks: dict[str, bytes], name: str) -> list[bytes]:
    chain: list[bytes] = []
    visited: set[str] = set()
    current = name
    while True:
        if current in visited or len(visited) >= 32 or current not in blocks:
            raise DevelopmentError("unsupported_symbol")
        visited.add(current)
        block = blocks[current]
        chain.append(block)
        if sum(map(len, chain)) > 512 * 1024 or sum(len(tokenize(item)) for item in chain) > 20_000:
            raise DevelopmentError("file_too_large")
        parent = children(parse(block), "extends")
        if not parent:
            break
        if len(parent) != 1:
            raise DevelopmentError("unsupported_symbol")
        current = value(parent[0])
    return chain


def _native_library_roots() -> list[Path]:
    system = platform.system()
    if system == "Linux":
        return [Path("/usr/share/kicad/symbols"), Path("/usr/local/share/kicad/symbols")]
    if system == "Darwin":
        return [
            Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols"),
            Path("/Library/Application Support/kicad/symbols"),
        ]
    if system == "Windows":
        root = Path("C:/Program Files/KiCad")
        if root.is_dir():
            versions = sorted(
                (p for p in root.iterdir() if re.fullmatch(r"[0-9]+\.[0-9]+", p.name)),
                key=lambda p: tuple(int(v) for v in p.name.split(".")),
                reverse=True,
            )
            return [path / "share/kicad/symbols" for path in versions[:32]]
    return []
