"""Locates the exact byte span of one symbol property's value (T2b).

Only TOP-LEVEL `(symbol (lib_id ...) ...)` nodes are candidates — the
schematic's placed component instances, siblings of `wire`/`label`/
`no_connect` under the root `(kicad_sch ...)` node. This deliberately never
recurses into `(lib_symbols ...)`: that section holds DEFINITION templates
(`(symbol "Device:R" ...)`, keyed by library id, not a placed reference) one
level deeper, so a top-level-only walk excludes them by construction — no
special-case needed.

v1 limitation: only root-level symbol instances are searched (no
hierarchical-sheet nesting) — recorded in SECURITY_REVIEW.md.
"""

from dataclasses import dataclass

from solus.write.errors import (
    REASON_AMBIGUOUS_TARGET,
    REASON_FILE_TOO_LARGE,
    REASON_PROPERTY_NOT_FOUND,
    REASON_REFERENCE_NOT_FOUND,
    RefusalError,
)
from solus.write.sexpr import GuardExceededError, Node, SExprSyntaxError, TokenKind, parse

REFERENCE_PROPERTY_NAME = "Reference"


@dataclass(frozen=True)
class LocatedValue:
    """The byte span (in the ORIGINAL source) of one property's value
    string token, plus its decoded current value."""

    start: int
    end: int
    old_value: str


def _property_name(node: Node) -> str | None:
    """The property's name if *node* is a well-formed `(property "Name"
    "Value" ...)` list, else None. Requires at least a name AND a value
    child so a malformed `(property "Name")` never matches anything."""
    if node.kind != TokenKind.LPAREN or len(node.children) < 3:
        return None
    head, name_node = node.children[0], node.children[1]
    is_property_head = head.kind == TokenKind.ATOM and head.value == "property"
    if is_property_head and name_node.kind == TokenKind.STRING:
        return name_node.value
    return None


def _is_instance_symbol(node: Node) -> bool:
    """Whether *node* is a placed symbol instance: `(symbol (lib_id ...)
    ...)` — as opposed to a `lib_symbols` definition template, which is
    `(symbol "lib:part" ...)` (a bare string, not a `(lib_id ...)` list)."""
    if node.kind != TokenKind.LPAREN or len(node.children) < 2:
        return False
    head = node.children[0]
    if not (head.kind == TokenKind.ATOM and head.value == "symbol"):
        return False
    lib_id = node.children[1]
    return (
        lib_id.kind == TokenKind.LPAREN
        and bool(lib_id.children)
        and lib_id.children[0].kind == TokenKind.ATOM
        and lib_id.children[0].value == "lib_id"
    )


def _reference_of(symbol: Node) -> str | None:
    for child in symbol.children:
        if _property_name(child) == REFERENCE_PROPERTY_NAME:
            return child.children[2].value
    return None


def _find_symbol_instances(root: Node, reference: str) -> list[Node]:
    return [
        node
        for node in root.children
        if _is_instance_symbol(node) and _reference_of(node) == reference
    ]


def _find_named_properties(symbol: Node, property_name: str) -> list[Node]:
    return [child for child in symbol.children if _property_name(child) == property_name]


def locate_property_value(data: bytes, reference: str, property_name: str) -> LocatedValue:
    """Find the value token of `reference`'s `property_name` property.

    Raises `RefusalError` with one of: `reference_not_found` (no top-level
    symbol instance carries that Reference), `ambiguous_target` (more than
    one instance shares the reference, or the matched instance carries the
    named property more than once), `property_not_found` (the instance has
    no such property), `file_too_large` (M5: the sexpr resource guard —
    token count or nesting depth — tripped).
    """
    try:
        root = parse(data)
    except GuardExceededError as exc:
        # M5: a resource-guard trip is an honest, dedicated reason — never
        # folded into the generic malformed-input bucket below.
        raise RefusalError(REASON_FILE_TOO_LARGE) from exc
    except SExprSyntaxError as exc:
        # An unparseable input is not one of the seven stable reasons; the
        # closest honest bucket is that the requested target cannot be
        # found in it. Recorded as a v1 limitation in SECURITY_REVIEW.md.
        raise RefusalError(REASON_REFERENCE_NOT_FOUND) from exc

    matches = _find_symbol_instances(root, reference)
    if not matches:
        raise RefusalError(REASON_REFERENCE_NOT_FOUND)
    if len(matches) > 1:
        raise RefusalError(REASON_AMBIGUOUS_TARGET)

    properties = _find_named_properties(matches[0], property_name)
    if not properties:
        raise RefusalError(REASON_PROPERTY_NOT_FOUND)
    if len(properties) > 1:
        raise RefusalError(REASON_AMBIGUOUS_TARGET)

    value_node = properties[0].children[2]
    located = LocatedValue(
        start=value_node.start, end=value_node.end, old_value=value_node.value or ""
    )
    # M5: the parsed tree (and the tokenizer's flat list, already released
    # inside `parse()`) is no longer needed once the small result above is
    # extracted — drop the reference explicitly rather than relying on it
    # merely going out of scope at return.
    del root, matches, properties
    return located
