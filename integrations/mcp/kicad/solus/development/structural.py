"""Insertion-only structural edits: existing byte spans are never reserialized."""

from collections.abc import Sequence

from solus.development.models import MAX_SCHEMATIC_BYTES, DevelopmentError
from solus.write.sexpr import Node, SExprSyntaxError, parse


def head(node: Node) -> str | None:
    return node.children[0].value if node.children else None


def children(node: Node, name: str) -> list[Node]:
    return [child for child in node.children if head(child) == name]


def value(node: Node, index: int = 1) -> str:
    if index >= len(node.children) or node.children[index].value is None:
        raise DevelopmentError("guard_failed")
    return str(node.children[index].value)


def document(data: bytes) -> Node:
    if len(data) > MAX_SCHEMATIC_BYTES:
        raise DevelopmentError("file_too_large")
    try:
        root = parse(data)
    except (SExprSyntaxError, UnicodeError) as exc:
        raise DevelopmentError("guard_failed") from exc
    if head(root) != "kicad_sch":
        raise DevelopmentError("guard_failed")
    _unique_uuids(root)
    _unique_instances(root)
    return root


def _unique_uuids(root: Node) -> None:
    seen: set[str] = set()
    stack = [root]
    while stack:
        node = stack.pop()
        if head(node) == "uuid":
            identity = value(node)
            if not identity or identity in seen:
                raise DevelopmentError("ambiguous_target")
            seen.add(identity)
        stack.extend(node.children)


def _unique_instances(root: Node) -> None:
    libraries = children(root, "lib_symbols")
    if len(libraries) > 1:
        raise DevelopmentError("ambiguous_target")
    if libraries:
        identities = [value(node) for node in children(libraries[0], "symbol")]
        if len(identities) != len(set(identities)):
            raise DevelopmentError("ambiguous_target")
    references: set[str] = set()
    for symbol in children(root, "symbol"):
        matches = [p for p in children(symbol, "property") if value(p) == "Reference"]
        if len(matches) != 1 or not value(matches[0], 2):
            raise DevelopmentError("ambiguous_target")
        reference = value(matches[0], 2)
        if reference in references:
            raise DevelopmentError("ambiguous_target")
        references.add(reference)


def insert_nodes(
    original: bytes, *, root_nodes: Sequence[bytes] = (), library_nodes: Sequence[bytes] = ()
) -> bytes:
    root = document(original)
    edits: list[tuple[int, bytes]] = []
    groups = [(root, root_nodes, {"symbol", "wire", "label", "no_connect", "junction"})]
    if library_nodes:
        libraries = children(root, "lib_symbols")
        if len(libraries) != 1:
            raise DevelopmentError("guard_failed")
        groups.append((libraries[0], library_nodes, {"symbol"}))
    for parent, additions, allowed in groups:
        for addition in additions:
            try:
                node = parse(addition)
            except (SExprSyntaxError, UnicodeError) as exc:
                raise DevelopmentError("guard_failed") from exc
            if head(node) not in allowed:
                raise DevelopmentError("guard_failed")
        if additions:
            edits.append((parent.end - 1, b"".join(b"\n" + item for item in additions)))
    result = original
    for offset, addition in sorted(edits, reverse=True):
        result = result[:offset] + addition + result[offset:]
    document(result)
    _verify_insertions(original, result, edits)
    return result


def _verify_insertions(original: bytes, result: bytes, edits: list[tuple[int, bytes]]) -> None:
    # Removing precisely our insertions must recover every original byte.
    recovered = result
    shift = 0
    for offset, addition in sorted(edits):
        start = offset + shift
        if result[start : start + len(addition)] != addition:
            raise DevelopmentError("guard_failed")
        shift += len(addition)
    for offset, addition in sorted(edits):
        recovered = recovered[:offset] + recovered[offset + len(addition) :]
    if recovered != original:
        raise DevelopmentError("guard_failed")
