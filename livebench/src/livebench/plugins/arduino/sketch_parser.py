"""Sketch print-order repo-config parser (SOLUSDEV-250 Phase 2). A bare board that prints a
flat sequence of values in `loop()` (Arduino C++) or a top-level `while True:` (MicroPython)
names, by that order, the columns of the float stream the framing interrogator sees. The
parse is tree-sitter, nothing is executed (CLAUDE.md §7), and any print under a branch,
switch or nested loop makes the order data-dependent — that file is REFUSED, never guessed.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, Final

from tree_sitter import Node, Parser

from livebench.hardware.repo_config import RepoConfigMatch, RepoPartDecl
from livebench.recognition.firmware import CPP_LANGUAGE, PY_LANGUAGE, node_text

PARSER_ID: Final = "sketch-print-order"
MAX_SKETCH_BYTES: Final = 512 * 1024
MAX_CHANNELS: Final = 64
MAX_NAME_CHARS: Final = 128
MAX_CONFIG_ID_CHARS: Final = 256
_MAX_DEPTH: Final = 256
_CPP_SUFFIXES: Final = frozenset({".ino", ".cpp", ".c"})
_CPP_BRANCHES: Final = frozenset(
    {
        "if_statement",
        "switch_statement",
        "for_statement",
        "while_statement",
        "do_statement",
        "try_statement",
        "conditional_expression",
    }
)
_PY_BRANCHES: Final = frozenset(
    {
        "if_statement",
        "for_statement",
        "while_statement",
        "try_statement",
        "match_statement",
        "conditional_expression",
    }
)
_SEPARATORS: Final = frozenset({"string_literal", "char_literal", "string"})
_PUNCT: Final = frozenset({"(", ")", ","})
_LOOP_CONDITIONS: Final = frozenset({"True", "1"})


class _RefuseError(Exception):
    """The print order is not a flat, static sequence — no match for this file."""


#: What one hostile file may raise; it skips only itself (repo content is untrusted, §7).
_FILE_ERRORS: Final = (_RefuseError, OSError, RecursionError, ValueError, UnicodeDecodeError)


@dataclass
class _Sketch:
    channels: list[str] = field(default_factory=list)
    baud: int | None = None
    period_ms: float = 0.0

    def params(self) -> dict[str, float | int]:
        params: dict[str, float | int] = {}
        if self.baud:
            params["baud"] = self.baud
        if self.period_ms > 0:
            params["declared_hz"] = 1000.0 / self.period_ms
        return params

    def add(self, name: str) -> None:
        if len(name) > MAX_NAME_CHARS:
            raise _RefuseError
        self.channels.append(name)
        if len(self.channels) > MAX_CHANNELS:
            raise _RefuseError


def _args(call: Node) -> list[Node]:
    args = call.child_by_field_name("arguments")
    return [c for c in args.children if c.type not in _PUNCT] if args is not None else []


def _first_number(call: Node) -> float | None:
    try:
        return float(node_text(_args(call)[0]))
    except (IndexError, ValueError):
        return None


def _walk_flagged(node: Node, branches: frozenset[str]) -> Iterator[tuple[Node, bool]]:
    """Every descendant, pre-order, with whether a control-flow construct sits between it and
    the body. An explicit stack with a depth cap: a hostile file is refused, never walked
    to the bottom."""
    stack = [(child, child.type in branches, 1) for child in reversed(node.children)]
    while stack:
        current, inside, depth = stack.pop()
        if depth > _MAX_DEPTH:
            raise _RefuseError
        yield current, inside
        stack.extend(
            (child, inside or child.type in branches, depth + 1)
            for child in reversed(current.children)
        )


# ── C++ (Arduino) ──────────────────────────────────────────────────────────────


def _cpp_function_body(root: Node, name: str) -> Node | None:
    for node in root.children:
        if node.type != "function_definition":
            continue
        declarator = node.child_by_field_name("declarator")
        if (
            declarator is not None
            and node_text(declarator.child_by_field_name("declarator")) == name
        ):
            return node.child_by_field_name("body")
    return None


def _cpp_method(call: Node) -> tuple[str, str]:
    """(`Serial`, `println`) for `Serial.println(...)`; ("", name) for a plain call."""
    function = call.child_by_field_name("function")
    if function is None or function.type != "field_expression":
        return "", node_text(function)
    return node_text(function.child_by_field_name("argument")), node_text(
        function.child_by_field_name("field")
    )


def _cpp_print(sketch: _Sketch, method: str, args: list[Node]) -> None:
    if method == "printf":
        args = args[1:]  # the format string
    for index, arg in enumerate(args):
        if arg.type == "identifier":
            sketch.add(node_text(arg))
        elif arg.type in _SEPARATORS or (index > 0 and arg.type == "number_literal"):
            continue  # a separator, or `print(x, digits)`'s precision
        else:
            raise _RefuseError


def _cpp_sketch(source: bytes) -> _Sketch | None:
    root = Parser(CPP_LANGUAGE).parse(source).root_node
    loop = _cpp_function_body(root, "loop")
    if loop is None:
        return None
    sketch = _Sketch()
    setup = _cpp_function_body(root, "setup")
    for node, _ in _walk_flagged(setup, _CPP_BRANCHES) if setup is not None else ():
        if node.type != "call_expression":
            continue
        target, method = _cpp_method(node)  # only `Serial*.begin(rate)` sets the baud
        baud = _first_number(node) if target.startswith("Serial") and method == "begin" else None
        if baud:
            sketch.baud = int(baud)
    for node, nested in _walk_flagged(loop, _CPP_BRANCHES):
        if node.type != "call_expression":
            continue
        target, method = _cpp_method(node)
        if target.startswith("Serial") and method.startswith("print"):
            if nested:
                raise _RefuseError
            _cpp_print(sketch, method, _args(node))
        elif method == "delay" and not nested:
            sketch.period_ms += _first_number(node) or 0.0
    return sketch


# ── Python (MicroPython) ───────────────────────────────────────────────────────


def _py_loop_body(root: Node) -> Node | None:
    for node in root.children:
        if node.type == "while_statement":
            if node_text(node.child_by_field_name("condition")) in _LOOP_CONDITIONS:
                return node.child_by_field_name("body")
    return None


def _py_print(sketch: _Sketch, args: list[Node]) -> None:
    for arg in args:
        if arg.type == "identifier":
            sketch.add(node_text(arg))
        elif arg.type == "string":
            for part in arg.children:
                if part.type != "interpolation":
                    continue
                inner = next((c for c in part.children if c.type not in ("{", "}")), None)
                if inner is None or inner.type != "identifier":
                    raise _RefuseError
                sketch.add(node_text(inner))
        elif arg.type != "keyword_argument":
            raise _RefuseError


def _py_sketch(source: bytes) -> _Sketch | None:
    body = _py_loop_body(Parser(PY_LANGUAGE).parse(source).root_node)
    if body is None:
        return None
    sketch = _Sketch()
    for node, nested in _walk_flagged(body, _PY_BRANCHES):
        if node.type != "call":
            continue
        function = node_text(node.child_by_field_name("function"))
        if function == "print":
            if nested:
                raise _RefuseError
            _py_print(sketch, _args(node))
        elif function in ("time.sleep_ms", "time.sleep") and not nested:
            value = _first_number(node) or 0.0
            sketch.period_ms += value if function.endswith("_ms") else value * 1000.0
    return sketch


# ── the parser ─────────────────────────────────────────────────────────────────


class SketchConfigParser:
    """`.ino/.cpp/.c` → `loop()`; `.py` → top-level `while True:`; the print order names
    the channels `0..n-1` of a `raw-lines` stream."""

    parser_id: ClassVar[str] = PARSER_ID

    def scan(self, root: Path, files: list[Path]) -> list[RepoConfigMatch]:
        matches: list[RepoConfigMatch] = []
        for path in files:
            try:
                match = _match_file(root, path)
            except _FILE_ERRORS:
                continue  # one hostile file skips only itself
            if match is not None:
                matches.append(match)
        return matches


def _match_file(root: Path, path: Path) -> RepoConfigMatch | None:
    if path.suffix not in _CPP_SUFFIXES | {".py"} or path.stat().st_size > MAX_SKETCH_BYTES:
        return None
    relative = path.relative_to(root).as_posix()
    config_id = f"sketch:{relative}"
    if len(config_id) > MAX_CONFIG_ID_CHARS:
        return None  # refused, never truncated
    reader = _cpp_sketch if path.suffix in _CPP_SUFFIXES else _py_sketch
    sketch = reader(path.read_bytes())
    if sketch is None or not sketch.channels:
        return None
    return RepoConfigMatch(
        config_id=config_id,
        parser_id=PARSER_ID,
        label=relative,
        source=str(path),
        protocol_hint="raw-lines",
        parts=[
            RepoPartDecl(name=name, address=str(index))
            for index, name in enumerate(sketch.channels)
        ],
        params=dict(sketch.params()),
        names_by_print_order=True,
    )
