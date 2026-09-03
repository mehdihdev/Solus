"""Rail-icon SVG reduction (SOLUSDEV-235 / ADR-035 §3).

An extension's page icon is rendered by the HOST, inside the desktop rail, so
it is reduced to a path-only, theme-aware subset before it is ever stored: a
closed element set, a closed attribute allowlist, plain colours only (rewritten
to ``currentColor``), no DOCTYPE / entities / processing instructions / scripts
/ external references. Parsing uses the stdlib expat parser directly with entity
declarations refused on sight (and again at parse time); nothing external.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from xml.parsers import expat

SVG_NAMESPACE = "http://www.w3.org/2000/svg"
ALLOWED_ELEMENTS = frozenset(
    {"svg", "g", "path", "circle", "rect", "line", "polyline", "polygon", "ellipse", "title"}
)
ALLOWED_ATTRIBUTES = frozenset(
    {
        "d", "cx", "cy", "r", "rx", "ry", "x", "y", "x1", "y1", "x2", "y2", "width", "height",
        "viewBox", "points", "fill", "stroke", "stroke-width", "stroke-linecap",
        "stroke-linejoin", "fill-rule", "opacity", "transform", "xmlns",
    }
)  # fmt: skip
COLOUR_ATTRIBUTES = frozenset({"fill", "stroke"})
#: `none`, `currentColor`, #rgb/#rgba/#rrggbb/#rrggbbaa, or a bare colour name. No url(), no rgb().
_COLOUR_RE = re.compile(
    r"^(none|currentColor|#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})|[A-Za-z]+)$"
)
_FORBIDDEN_MARKUP_RE = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)


class SvgError(ValueError):
    """Raised by :func:`sanitize_svg`; ``problems`` mirrors :func:`svg_problems`."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass
class _Node:
    name: str
    attrs: list[tuple[str, str]]
    children: list[_Node] = field(default_factory=list)
    text: str = ""


class _Reducer:
    """Expat handlers that build the reduced tree while collecting problems."""

    def __init__(self) -> None:
        self.problems: list[str] = []
        self.root: _Node | None = None
        self._stack: list[_Node] = []

    def start(self, name: str, attrs: dict[str, str]) -> None:
        if not self._stack and name != "svg":
            self.problems.append(f"root element must be <svg>, found <{name}>")
        if name not in ALLOWED_ELEMENTS:
            self.problems.append(f"element <{name}> is not allowed")
        node = _Node(name, self._reduce_attrs(name, attrs))
        if self._stack:
            self._stack[-1].children.append(node)
        else:
            self.root = node
        self._stack.append(node)

    def end(self, _name: str) -> None:
        self._stack.pop()

    def text(self, data: str) -> None:
        if self._stack and self._stack[-1].name == "title":
            self._stack[-1].text += data

    def instruction(self, target: str, _data: str) -> None:
        self.problems.append(f"processing instruction <?{target}?> is not allowed")

    def doctype(self, name: str, *_args: object) -> None:
        self.problems.append(f"DOCTYPE {name} is not allowed")

    def entity(self, name: str, *_args: object) -> None:
        self.problems.append(f"ENTITY {name} is not allowed")

    def _reduce_attrs(self, element: str, attrs: dict[str, str]) -> list[tuple[str, str]]:
        kept: list[tuple[str, str]] = []
        for key, value in attrs.items():
            if key.lower().startswith("on") or key not in ALLOWED_ATTRIBUTES:
                self.problems.append(f"attribute {key} on <{element}> is not allowed")
            elif key == "xmlns" and value != SVG_NAMESPACE:
                self.problems.append(f"xmlns on <{element}> must be {SVG_NAMESPACE}")
            elif key in COLOUR_ATTRIBUTES and not _COLOUR_RE.match(value):
                self.problems.append(
                    f"{key} on <{element}> must be none, currentColor, "
                    "a hex colour or a colour name"
                )
            else:
                kept.append((key, _rewrite_colour(key, value)))
        return kept


def _rewrite_colour(key: str, value: str) -> str:
    if key in COLOUR_ATTRIBUTES and value != "none":
        return "currentColor"
    return value


def _parse(data: bytes) -> _Reducer:
    reducer = _Reducer()
    parser = expat.ParserCreate()
    parser.StartElementHandler = reducer.start
    parser.EndElementHandler = reducer.end
    parser.CharacterDataHandler = reducer.text
    parser.ProcessingInstructionHandler = reducer.instruction
    parser.StartDoctypeDeclHandler = reducer.doctype
    parser.EntityDeclHandler = reducer.entity
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    try:
        parser.Parse(data, True)
    except expat.ExpatError as exc:
        reducer.problems.append(f"malformed XML: {exc}")
    return reducer


def _analyse(data: bytes, max_bytes: int) -> tuple[_Node | None, list[str]]:
    if len(data) > max_bytes:
        return None, [f"exceeds {max_bytes} bytes"]
    if (hit := _FORBIDDEN_MARKUP_RE.search(data)) is not None:
        return None, [f"{hit.group(1).decode().upper()} declarations are not allowed"]
    reducer = _parse(data)
    if reducer.root is None and not reducer.problems:
        reducer.problems.append("malformed XML: no root element")
    return reducer.root, reducer.problems


def _serialize(node: _Node) -> str:
    attrs = "".join(f' {k}="{html.escape(v, quote=True)}"' for k, v in node.attrs)
    inner = html.escape(node.text) + "".join(_serialize(c) for c in node.children)
    if not inner:
        return f"<{node.name}{attrs}/>"
    return f"<{node.name}{attrs}>{inner}</{node.name}>"


def svg_problems(data: bytes, max_bytes: int) -> list[str]:
    """Every reason `data` is not an acceptable rail icon; empty when it is."""
    return _analyse(data, max_bytes)[1]


def sanitize_svg(data: bytes, max_bytes: int) -> str:
    """The reduced SVG text (allowed elements/attributes only, colours → currentColor).

    Raises :class:`SvgError` with the problems when the icon is not acceptable.
    """
    root, problems = _analyse(data, max_bytes)
    if problems or root is None:
        raise SvgError(problems)
    attrs = [(k, v) for k, v in root.attrs if k != "xmlns"]
    rooted = _Node(root.name, [("xmlns", SVG_NAMESPACE), *attrs], root.children, root.text)
    return _serialize(rooted)
