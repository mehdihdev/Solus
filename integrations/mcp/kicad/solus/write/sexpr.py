"""An owned S-expression tokenizer/parser over raw KiCad `.kicad_sch` bytes.

Deliberately NOT the vendored `kicad_sch_api`/`sexpdata` parsers: those decode
into Python values with no byte-offset trail, so there is nothing to splice
against. Every token here carries the exact BYTE span it occupies in the
source, which is the only thing `locator.py` and `guard.py` need.

Grammar covered (KiCad's schematic S-expression subset — no comments, no
block strings): parenthesized lists, bare atoms (numbers, keywords, bare
words), and double-quoted strings with backslash escaping of `"` and `\\`.

M5 hardening: the 8 MiB file-size cap (`solus/write/paths.py`) does not by
itself bound WORST-CASE token count — an 8 MiB file of alternating `(`/`)`
bytes tokenizes into ~8M single-byte `Token` objects (~1 GiB RSS). `tokenize`
therefore aborts as soon as the token count crosses `MAX_TOKENS`, so the
token list itself never grows past that bound regardless of input size.
Separately, `_parse_node` is an ITERATIVE tree-builder (an explicit stack
replaces the call stack) so pathological nesting depth can never raise
`RecursionError`; `MAX_NESTING_DEPTH` bounds the stack's own memory too, as
defense in depth. Both guards raise `GuardExceededError`, a distinguishable
`SExprSyntaxError` subclass callers can map to a dedicated stable refusal
reason (`solus/write/locator.py` maps it to `file_too_large`) rather than
folding it into the generic malformed-input bucket.
"""

from dataclasses import dataclass
from enum import Enum, auto

_LPAREN = ord("(")
_RPAREN = ord(")")
_QUOTE = ord('"')
_BACKSLASH = ord("\\")
_WHITESPACE = frozenset(b" \t\r\n")
_DELIMITERS = frozenset({_LPAREN, _RPAREN, _QUOTE}) | _WHITESPACE

# M5: worst-case token-object memory bound. At ~150-200 bytes per `Token`
# dataclass instance, 200,000 tokens costs tens of MB — generous for any
# legitimate KiCad schematic (the committed fixtures run to a few hundred
# tokens), while refusing well before the ~6M-token/~1GiB DoS shape an 8 MiB
# pathological input can otherwise reach.
MAX_TOKENS = 200_000

# M5: worst-case nesting-depth bound (also bounds the iterative parser's
# explicit stack). KiCad schematics nest at most a handful of levels deep
# even with hierarchical sheets; 200 is generous headroom.
MAX_NESTING_DEPTH = 200


class SExprSyntaxError(ValueError):
    """The bytes are not well-formed KiCad S-expression tokens."""


class GuardExceededError(SExprSyntaxError):
    """An explicit resource guard (token count or nesting depth) tripped —
    distinct from ordinary malformed syntax so callers can map it to its own
    stable refusal reason instead of the generic malformed-input bucket."""


class TokenKind(Enum):
    LPAREN = auto()
    RPAREN = auto()
    ATOM = auto()
    STRING = auto()


@dataclass(frozen=True)
class Token:
    """One lexical token. `start`/`end` are byte offsets into the source
    (end exclusive); `value` is the decoded text for ATOM/STRING, else None."""

    kind: TokenKind
    start: int
    end: int
    value: str | None = None


@dataclass(frozen=True)
class Node:
    """One parsed tree node. LPAREN nodes are lists (`children` populated);
    ATOM/STRING nodes are leaves. `start`/`end` span the whole node,
    including its parens for a list."""

    kind: TokenKind
    start: int
    end: int
    value: str | None = None
    children: tuple["Node", ...] = ()


def _decode_escapes(body: str) -> str:
    """Reverse of the escaping `encode_kicad_string` writes: `\\"` -> `"`,
    `\\\\` -> `\\`. An unrecognized escape is preserved literally (lenient on
    READ so an unusual existing file never fails to parse; `escaping.py`
    never itself produces such a sequence)."""
    out: list[str] = []
    i = 0
    n = len(body)
    while i < n:
        char = body[i]
        if char == "\\" and i + 1 < n and body[i + 1] in ('"', "\\"):
            out.append(body[i + 1])
            i += 2
            continue
        out.append(char)
        i += 1
    return "".join(out)


def _scan_string(data: bytes, start: int) -> Token:
    """Scan one double-quoted string starting at the opening `"` (*start*).
    Backslash escapes the following byte from terminating the string —
    covers both `\\"` (embedded quote) and `\\\\` (literal backslash)."""
    n = len(data)
    i = start + 1
    while True:
        if i >= n:
            raise SExprSyntaxError(f"unterminated string starting at byte {start}")
        current = data[i]
        if current == _BACKSLASH:
            if i + 1 >= n:
                raise SExprSyntaxError(f"dangling escape at byte {i}")
            i += 2
            continue
        i += 1
        if current == _QUOTE:
            break
    end = i
    body = data[start + 1 : end - 1].decode("utf-8")
    return Token(TokenKind.STRING, start, end, _decode_escapes(body))


def _scan_atom(data: bytes, start: int) -> Token:
    """Scan one bare atom: everything up to the next delimiter or whitespace."""
    n = len(data)
    i = start
    while i < n and data[i] not in _DELIMITERS:
        i += 1
    return Token(TokenKind.ATOM, start, i, data[start:i].decode("utf-8"))


def tokenize(data: bytes) -> list[Token]:
    """Flat left-to-right token stream over *data*. Raises
    `SExprSyntaxError` on an unterminated string or a dangling escape —
    never silently drops bytes. Raises `GuardExceededError` (M5) the moment
    the token count would cross `MAX_TOKENS`, so the list itself never grows
    past that bound."""
    tokens: list[Token] = []
    i = 0
    n = len(data)
    while i < n:
        byte = data[i]
        if byte in _WHITESPACE:
            i += 1
            continue
        if byte == _LPAREN:
            tokens.append(Token(TokenKind.LPAREN, i, i + 1))
            i += 1
        elif byte == _RPAREN:
            tokens.append(Token(TokenKind.RPAREN, i, i + 1))
            i += 1
        else:
            token = _scan_string(data, i) if byte == _QUOTE else _scan_atom(data, i)
            tokens.append(token)
            i = token.end
        if len(tokens) > MAX_TOKENS:
            raise GuardExceededError(f"token count exceeds the guarded limit ({MAX_TOKENS})")
    return tokens


def _parse_node(tokens: list[Token], index: int) -> tuple[Node, int]:
    """Iterative tree-builder (M5): an explicit stack of open list frames
    replaces the call stack, so pathological nesting can never raise
    `RecursionError`. `MAX_NESTING_DEPTH` bounds the stack itself too, as
    defense in depth against unbounded frame-stack memory."""
    first = tokens[index]
    if first.kind == TokenKind.RPAREN:
        raise SExprSyntaxError(f"unexpected ')' at byte {first.start}")
    if first.kind in (TokenKind.ATOM, TokenKind.STRING):
        return Node(first.kind, first.start, first.end, first.value), index + 1

    stack: list[tuple[Token, list[Node]]] = [(first, [])]
    cursor = index + 1
    while stack:
        if len(stack) > MAX_NESTING_DEPTH:
            raise GuardExceededError(
                f"nesting depth exceeds the guarded limit ({MAX_NESTING_DEPTH})"
            )
        if cursor >= len(tokens):
            open_token, _ = stack[-1]
            raise SExprSyntaxError(f"unterminated list starting at byte {open_token.start}")
        token = tokens[cursor]
        if token.kind == TokenKind.RPAREN:
            open_token, children = stack.pop()
            node = Node(TokenKind.LPAREN, open_token.start, token.end, None, tuple(children))
            cursor += 1
            if not stack:
                return node, cursor
            stack[-1][1].append(node)
        elif token.kind == TokenKind.LPAREN:
            stack.append((token, []))
            cursor += 1
        else:
            stack[-1][1].append(Node(token.kind, token.start, token.end, token.value))
            cursor += 1
    raise SExprSyntaxError("unexpected end of parse")  # pragma: no cover — unreachable


def parse(data: bytes) -> Node:
    """The single top-level node (`(kicad_sch ...)`) parsed from *data*.
    Raises `SExprSyntaxError` on malformed or multi-root input."""
    tokens = tokenize(data)
    if not tokens:
        raise SExprSyntaxError("empty document")
    root, index = _parse_node(tokens, 0)
    if index != len(tokens):
        raise SExprSyntaxError("trailing content after the top-level expression")
    return root
