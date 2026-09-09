"""Owned S-expression reader for KiCad files (SOLUSDEV-252, W0-08 §6.3).

The substrate the S-expression netlist parser (`kicad_netlist_sexpr`) and the
board parser (`kicad_pcb`) share. Stdlib only, no eval, no third-party
dependency — the contract's "owned S-expression reader: bounded token count and
nesting depth, scoped traversal, no eval".

Grammar (KiCad's subset — no comments, no block strings): parenthesized lists,
bare atoms, and double-quoted strings with backslash escapes. Atoms and strings
both decode to `str`; lists become nested tuples. Exactly one root list.

Ingested text is untrusted DATA (CLAUDE.md §7), so the reader is built to fail
safely on hostile shape, not just hostile content:

* It is ITERATIVE — an explicit stack replaces the call stack, so pathological
  nesting can never raise `RecursionError`.
* `MAX_SEXPR_DEPTH` bounds that stack (KiCad files nest a handful of levels;
  64 is generous headroom).
* `MAX_SEXPR_NODES` bounds MEMORY: the 8 MiB export cap upstream
  (`eda.MAX_EXPORT_BYTES`) bounds bytes, not node count — 8 MiB of `()` pairs
  is ~4M tuples. Nodes are counted as they are materialized and the read aborts
  the moment the count crosses the bound, so the tree never grows past it.
* `prune(head, depth)` lets a caller declare which lists it does not need
  (`design`/`libparts` in a netlist; copper, zones and graphics in a board).
  A pruned list is SKIPPED WITHOUT MATERIALIZING — a forward scan with paren
  balancing that respects quoted strings — so it costs no memory and is not
  counted. Pruned regions must still be well-formed; an unterminated one is a
  syntax error like any other.

Modeled on `integrations/mcp/kicad/solus/write/sexpr.py` (which additionally
carries byte offsets for splicing — not needed here) but deliberately not
imported from it: different package, different job.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from typing import Final

type Sexp = str | tuple[Sexp, ...]

#: Nesting-depth guard (root list = depth 0). Bounds the reader's explicit stack.
#: `Final` is a static annotation only — tests still lower these with
#: `monkeypatch.setattr`, and both are read at call time.
MAX_SEXPR_DEPTH: Final = 64

#: Materialized-node guard (atoms, strings and lists). Bounds worst-case memory
#: independently of the byte cap, which bounds BYTES and not node count: 8 MiB
#: of tiny atoms allocates far more than 8 MiB of Python objects.
#:
#: Calibrated by measurement (2026-09-09), between two hard requirements:
#:   * the densest LEGITIMATE input must still parse — an 8 MiB `kicad-cli`
#:     netlist at the committed fixture's density is 677k nodes / 33 MB peak
#:     (a components+nets document with nothing prunable is the dense case);
#:   * an ADVERSARIAL 8 MiB of tiny atoms at a legal unpruned position must
#:     trip this guard early: it does, at 49 MB peak.
#: The budget that matters is `worker.py`'s `max_jobs = 4` × 2 parses per KiCad
#: sync (netlist + board), so one team's worst case stays a few hundred MB
#: rather than the ~800 MB a 2M-node cap allowed.
MAX_SEXPR_NODES: Final = 1_000_000

#: C0 control characters that may never appear in a KiCad file. NUL survives
#: this reader but is rejected by Postgres deep inside the sync, where it
#: surfaces as an opaque internal error AND logs the failing statement's bound
#: parameters — i.e. ingested design content (§7). Refuse up front instead.
#: `\t`, `\n` and `\r` stay legal.
_CONTROL_CHARS: Final = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

#: One token at the current position. Every character is covered by exactly one
#: alternative, so `match` never returns None on in-range positions.
_TOKEN: Final = re.compile(
    r"\s+"
    r"|(?P<open>\()"
    r"|(?P<close>\))"
    r'|"(?P<string>(?:[^"\\]|\\.)*)"'
    r'|(?P<atom>[^\s()"]+)'
    r'|(?P<stray>")',
    re.DOTALL,
)

#: Forward scan used to skip a pruned list: bulk runs of non-structural text,
#: parens, whole quoted strings (escapes included), or a stray unterminated quote.
_SKIP: Final = re.compile(
    r'[^()"]+' r"|(?P<open>\()" r"|(?P<close>\))" r'|"(?:[^"\\]|\\.)*"' r'|(?P<stray>")',
    re.DOTALL,
)

_ESCAPE: Final = re.compile(r"\\(.)", re.DOTALL)
_ESCAPES: Final = {'"': '"', "\\": "\\", "n": "\n", "t": "\t", "r": "\r"}


class SExprSyntaxError(ValueError):
    """The text is not one well-formed S-expression document."""


class SExprLimitError(SExprSyntaxError):
    """A resource guard (nesting depth or node count) tripped — distinguishable
    from ordinary malformed syntax so callers can name the reason."""


def parse_sexpr(text: str, *, prune: Callable[[str, int], bool] | None = None) -> tuple[Sexp, ...]:
    """Parse *text* into its single root list as nested tuples.

    `prune(head, depth)` is consulted for every list whose first item is a
    STRING (`head`) — bare atom or quoted alike, because `children()` matches
    both, so consulting only atoms would let `("components" …)` bypass pruning
    yet still parse as real data — at nesting `depth` (root = 0, its children =
    1); returning True skips that list without materializing it. Raises `SExprSyntaxError`
    on malformed input (empty, unterminated, trailing content, multiple
    roots, a C0 control character) and `SExprLimitError` when a resource guard
    trips.
    """
    control = _CONTROL_CHARS.search(text)
    if control is not None:
        raise SExprSyntaxError(f"control character at offset {control.start()}")
    return _Reader(text, prune).read()


def children(node: Sexp | None, head: str) -> Iterator[tuple[Sexp, ...]]:
    """DIRECT child lists of *node* whose first item is *head* — scoped
    traversal, never a subtree walk (anti-smuggling, §7)."""
    if not isinstance(node, tuple):
        return
    for item in node:
        if isinstance(item, tuple) and item and item[0] == head:
            yield item


def child(node: Sexp | None, head: str) -> tuple[Sexp, ...] | None:
    """The first direct child list headed *head*, or None."""
    return next(children(node, head), None)


def string_at(node: Sexp | None, index: int) -> str | None:
    """The string (atom or quoted) at *index* of list *node*; None when *node*
    is not a list, the index is out of range, or the item is itself a list."""
    if not isinstance(node, tuple) or index < 0 or index >= len(node):
        return None
    item = node[index]
    return item if isinstance(item, str) else None


def _decode(body: str) -> str:
    """Decode backslash escapes; an unknown escape is preserved literally
    (lenient on read so an unusual existing file never fails to parse)."""
    if "\\" not in body:
        return body
    return _ESCAPE.sub(lambda m: _ESCAPES.get(m.group(1), m.group(0)), body)


class _Reader:
    """One iterative read of one document. `_stack` holds the open lists'
    children (innermost last); `_root` is set when the outermost list closes."""

    def __init__(self, text: str, prune: Callable[[str, int], bool] | None) -> None:
        self._text = text
        self._prune = prune
        self._pos = 0
        self._nodes = 0
        self._stack: list[list[Sexp]] = []
        self._root: tuple[Sexp, ...] | None = None

    def read(self) -> tuple[Sexp, ...]:
        text = self._text
        while self._pos < len(text):
            match = _TOKEN.match(text, self._pos)
            if match is None:
                raise SExprSyntaxError(f"unexpected character at offset {self._pos}")
            self._pos = match.end()
            kind = match.lastgroup
            if kind == "open":
                self._open(match.start())
            elif kind == "close":
                self._close(match.start())
            elif kind == "atom":
                self._leaf(match.group("atom"), match.start())
            elif kind == "string":
                self._leaf(_decode(match.group("string")), match.start())
            elif kind == "stray":
                raise SExprSyntaxError(f"unterminated string at offset {match.start()}")
        if self._stack:
            raise SExprSyntaxError("unterminated list at end of input")
        if self._root is None:
            raise SExprSyntaxError("empty document")
        return self._root

    def _open(self, offset: int) -> None:
        if not self._stack and self._root is not None:
            raise SExprSyntaxError(f"trailing content after the root list at offset {offset}")
        if len(self._stack) >= MAX_SEXPR_DEPTH:
            raise SExprLimitError(f"nesting exceeds the guarded depth ({MAX_SEXPR_DEPTH})")
        self._stack.append([])

    def _close(self, offset: int) -> None:
        if not self._stack:
            raise SExprSyntaxError(f"unexpected ')' at offset {offset}")
        node = tuple(self._stack.pop())
        self._count()
        if self._stack:
            self._stack[-1].append(node)
        else:
            self._root = node

    def _leaf(self, value: str, offset: int) -> None:
        if not self._stack:
            raise SExprSyntaxError(f"content outside the root list at offset {offset}")
        frame = self._stack[-1]
        # A head is a head whether it was written bare or quoted: `children()`
        # compares decoded strings, so both must face `prune` (S3).
        if not frame and self._prune is not None:
            depth = len(self._stack) - 1
            if self._prune(value, depth):
                self._stack.pop()
                self._skip_list()
                if not self._stack:
                    self._root = ()
                return
        self._count()
        frame.append(value)

    def _count(self) -> None:
        self._nodes += 1
        if self._nodes > MAX_SEXPR_NODES:
            raise SExprLimitError(f"node count exceeds the guarded limit ({MAX_SEXPR_NODES})")

    def _skip_list(self) -> None:
        """Advance past the close paren matching the list already opened at
        `_pos` (its head consumed), allocating nothing."""
        text, pos, depth = self._text, self._pos, 1
        while depth:
            match = _SKIP.match(text, pos)
            if match is None:
                raise SExprSyntaxError("unterminated list at end of input")
            pos = match.end()
            kind = match.lastgroup
            if kind == "open":
                depth += 1
            elif kind == "close":
                depth -= 1
            elif kind == "stray":
                raise SExprSyntaxError(f"unterminated string at offset {match.start()}")
        self._pos = pos
