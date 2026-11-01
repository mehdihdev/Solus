"""Closed derived-signal grammar: lexer, bounded recursive-descent parser, frozen AST
and a tree-walking evaluator (docs/api/bench-view.md §4, architecture/bench-view.md §2).

This is the write-time authority: every stored expression is parsed and bounded here.
Pure module: no I/O, no globals mutated, no dynamic code path of any kind. Filter
state lives on an explicit per-evaluation object. The shared conformance vectors
(packages/shared-types/fixtures/bench-expression-vectors.json) pin every rule below,
including the clarifications recorded in their ``_doc``.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final

MAX_EXPRESSION_CHARS: Final = 512
MAX_NODES: Final = 64
MAX_DEPTH: Final = 12
MAX_REFS: Final = 8
MAX_LITERAL_CHARS: Final = 32
MAX_DEVICE_ID_CHARS: Final = 512
MAX_SIGNAL_CHARS: Final = 128
MAX_WINDOW_S: Final = 10.0
MAX_CUTOFF_HZ: Final = 1000.0
MAX_FILTER_SAMPLES: Final = 2000
HOLD_SECONDS: Final = 1.0
DERIV_RESET_S: Final = 1.0
LOWPASS_MAX_RESET_S: Final = 10.0
MAX_BUFFERED_SAMPLES: Final = 20000

ERROR_MESSAGES: Final[dict[str, str]] = {
    "too_long": "The expression is longer than 512 characters.",
    "too_many_nodes": "The expression has more than 64 terms.",
    "too_deep": "The expression nests more than 12 levels deep.",
    "too_many_refs": "The expression references more than 8 signals.",
    "no_signal": "The expression must reference at least one signal.",
    "non_finite_literal": "A number is longer than 32 characters or not finite.",
    "param_range": "A filter or scale parameter is out of range.",
    "bad_ref": "A signal reference is empty, too long or has unsupported characters.",
    "unknown_function": "Unknown function.",
    "arity": "A function has the wrong number of arguments.",
    "non_constant_param": "This parameter must be a constant number.",
    "syntax": "The expression does not match the grammar.",
}

_DIGITS: Final = frozenset("0123456789")
_IDENT_START: Final = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_")
_IDENT_CHARS: Final = _IDENT_START | _DIGITS
_WHITESPACE: Final = frozenset(" \t\n")
_PUNCTUATION: Final = frozenset("+-*/(),")
_ADDITIVE: Final = frozenset("+-")
_MULTIPLICATIVE: Final = frozenset("*/")
_FILTERS: Final = frozenset({"ma", "lowpass", "deriv", "integ"})
# name -> (min arity, max arity, indices of constant-only parameters)
_FUNCTIONS: Final[dict[str, tuple[int, int, tuple[int, ...]]]] = {
    "abs": (1, 1, ()),
    "min": (2, 8, ()),
    "max": (2, 8, ()),
    "clamp": (3, 3, ()),
    "scale": (5, 5, (1, 2, 3, 4)),
    "ma": (2, 2, (1,)),
    "lowpass": (2, 2, (1,)),
    "deriv": (1, 1, ()),
    "integ": (2, 2, (1,)),
}


class ExpressionError(Exception):
    """A parse or bound failure. ``message`` is a fixed sentence per code and never
    echoes the expression; ``position``/``length`` are code-point offsets."""

    def __init__(self, code: str, position: int, length: int) -> None:
        self.code = code
        self.position = position
        self.length = length
        self.message = ERROR_MESSAGES[code]
        super().__init__(f"{code} at {position}: {self.message}")

    def as_detail(self) -> dict[str, str | int]:
        return {
            "code": self.code,
            "position": self.position,
            "length": self.length,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class SignalRef:
    device_id: str
    signal: str

    def as_dict(self) -> dict[str, str]:
        return {"device_id": self.device_id, "signal": self.signal}


# ------------------------------------------------------------------------------ AST


@dataclass(frozen=True, slots=True)
class NumberNode:
    value: float
    position: int
    length: int
    height: int = 1


@dataclass(frozen=True, slots=True)
class RefNode:
    ref: SignalRef
    index: int  # into ParsedExpression.refs
    position: int
    length: int
    height: int = 1


@dataclass(frozen=True, slots=True)
class UnaryNode:
    operand: Node
    position: int
    length: int
    height: int


@dataclass(frozen=True, slots=True)
class BinaryNode:
    op: str
    left: Node
    right: Node
    position: int
    length: int
    height: int


@dataclass(frozen=True, slots=True)
class CallNode:
    name: str
    args: tuple[Node, ...]
    slot: int  # filter-state slot, -1 for stateless functions
    position: int
    length: int
    height: int


@dataclass(frozen=True, slots=True)
class GroupNode:
    """Parentheses: not counted as a node, but one depth level."""

    inner: Node
    position: int
    length: int
    height: int


Node = NumberNode | RefNode | UnaryNode | BinaryNode | CallNode | GroupNode


@dataclass(frozen=True, slots=True)
class ParsedExpression:
    root: Node
    node_count: int
    depth: int
    refs: tuple[SignalRef, ...]  # distinct, first-appearance order; refs[0] is the time base
    filter_count: int


# ---------------------------------------------------------------------------- lexer


@dataclass(frozen=True, slots=True)
class _Token:
    kind: str  # one of _PUNCTUATION, "num", "ident", "str", "eof"
    text: str
    position: int
    value: float = 0.0

    @property
    def length(self) -> int:
        return len(self.text)

    @property
    def end(self) -> int:
        return self.position + len(self.text)


def _scan_digits(text: str, i: int) -> int:
    while i < len(text) and text[i] in _DIGITS:
        i += 1
    return i


def _scan_number(text: str, start: int) -> int:
    end = _scan_digits(text, start)
    if end < len(text) and text[end] == ".":
        end = _scan_digits(text, end + 1)
    if end < len(text) and text[end] in "eE":
        k = end + 1
        if k < len(text) and text[k] in "+-":
            k += 1
        if k < len(text) and text[k] in _DIGITS:
            end = _scan_digits(text, k)
    return end


def _lex(text: str) -> list[_Token]:
    tokens: list[_Token] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in _WHITESPACE:
            i += 1
        elif c in _PUNCTUATION:
            tokens.append(_Token(c, c, i))
            i += 1
        elif c in _DIGITS or (c == "." and i + 1 < n and text[i + 1] in _DIGITS):
            end = _scan_number(text, i)
            literal = text[i:end]
            value = float(literal) if len(literal) <= MAX_LITERAL_CHARS else math.inf
            if not math.isfinite(value):
                raise ExpressionError("non_finite_literal", i, len(literal))
            tokens.append(_Token("num", literal, i, value))
            i = end
        elif c in _IDENT_START:
            end = i + 1
            while end < n and text[end] in _IDENT_CHARS:
                end += 1
            tokens.append(_Token("ident", text[i:end], i))
            i = end
        elif c == '"':
            close = text.find('"', i + 1)
            if close < 0:
                raise ExpressionError("syntax", i, n - i)
            tokens.append(_Token("str", text[i : close + 1], i))
            i = close + 1
        else:
            raise ExpressionError("syntax", i, 1)
    tokens.append(_Token("eof", "", n))
    return tokens


# --------------------------------------------------------------------------- parser


def _span_error(code: str, node: Node | _Token) -> ExpressionError:
    return ExpressionError(code, node.position, node.length)


def _end(node: Node | _Token) -> int:
    return node.position + node.length


def _ref_string_ok(content: str, limit: int) -> bool:
    return 1 <= len(content) <= limit and all(
        0x20 <= ord(c) <= 0x7E and c not in '"\\' for c in content
    )


def _constant_value(node: Node) -> float | None:
    if isinstance(node, NumberNode):
        return node.value
    if isinstance(node, UnaryNode) and isinstance(node.operand, NumberNode):
        return -node.operand.value
    return None


class _Parser:
    """Recursive descent over the token list. ``level`` is the nesting level (root = 1);
    descending past MAX_DEPTH fails before recursing, so stack use is bounded."""

    def __init__(self, tokens: list[_Token]) -> None:
        self._tokens = tokens
        self._i = 0
        self._nodes = 0
        self._slots = 0
        self.refs: list[SignalRef] = []

    @property
    def node_count(self) -> int:
        return self._nodes

    @property
    def slot_count(self) -> int:
        return self._slots

    def parse(self) -> Node:
        root = self._sum(1)
        if self._peek().kind != "eof":
            raise _span_error("syntax", self._peek())
        return root

    def _peek(self) -> _Token:
        return self._tokens[self._i]

    def _next(self) -> _Token:
        token = self._tokens[self._i]
        self._i += 1
        return token

    def _expect(self, kind: str) -> _Token:
        if self._peek().kind != kind:
            raise _span_error("syntax", self._peek())
        return self._next()

    @staticmethod
    def _descend(level: int, token: _Token) -> int:
        if level + 1 > MAX_DEPTH:
            raise _span_error("too_deep", token)
        return level + 1

    def _build[N: Node](self, node: N, counted: bool = True) -> N:
        if counted:
            self._nodes += 1
            if self._nodes > MAX_NODES:
                raise _span_error("too_many_nodes", node)
        if node.height > MAX_DEPTH:
            raise _span_error("too_deep", node)
        return node

    def _sum(self, level: int) -> Node:
        left = self._product(level)
        while self._peek().kind in _ADDITIVE:
            left = self._binary(left, self._next().kind, self._product(level))
        return left

    def _product(self, level: int) -> Node:
        left = self._unary(level)
        while self._peek().kind in _MULTIPLICATIVE:
            left = self._binary(left, self._next().kind, self._unary(level))
        return left

    def _binary(self, left: Node, op: str, right: Node) -> Node:
        height = 1 + max(left.height, right.height)
        span = _end(right) - left.position
        return self._build(BinaryNode(op, left, right, left.position, span, height))

    def _unary(self, level: int) -> Node:
        token = self._peek()
        if token.kind != "-":
            return self._primary(level)
        inner = self._descend(level, token)
        self._next()
        operand = self._unary(inner)
        span = _end(operand) - token.position
        return self._build(UnaryNode(operand, token.position, span, operand.height + 1))

    def _primary(self, level: int) -> Node:
        token = self._next()
        if token.kind == "num":
            return self._build(NumberNode(token.value, token.position, token.length))
        if token.kind == "(":
            inner = self._sum(self._descend(level, token))
            close = self._expect(")")
            span = close.end - token.position
            group = GroupNode(inner, token.position, span, inner.height + 1)
            return self._build(group, counted=False)
        if token.kind == "ident":
            if token.text == "sig":
                return self._reference(token)
            if token.text in _FUNCTIONS:
                return self._call(token, level)
            if self._peek().kind == "(":
                raise _span_error("unknown_function", token)
        raise _span_error("syntax", token)

    def _ref_string(self, limit: int) -> str:
        token = self._expect("str")
        content = token.text[1:-1]
        if not _ref_string_ok(content, limit):
            raise _span_error("bad_ref", token)
        return content

    def _reference(self, name: _Token) -> Node:
        self._expect("(")
        device_id = self._ref_string(MAX_DEVICE_ID_CHARS)
        self._expect(",")
        signal = self._ref_string(MAX_SIGNAL_CHARS)
        close = self._expect(")")
        ref = SignalRef(device_id, signal)
        index = self.refs.index(ref) if ref in self.refs else len(self.refs)
        node = self._build(RefNode(ref, index, name.position, close.end - name.position))
        if index == len(self.refs):
            if index == MAX_REFS:
                raise _span_error("too_many_refs", node)
            self.refs.append(ref)
        return node

    def _call(self, name: _Token, level: int) -> Node:
        self._expect("(")
        inner = self._descend(level, name)
        args = [self._sum(inner)]
        while self._peek().kind == ",":
            self._next()
            args.append(self._sum(inner))
        close = self._expect(")")
        span = close.end - name.position
        height = 1 + max(arg.height for arg in args)
        probe = CallNode(name.text, tuple(args), -1, name.position, span, height)
        _check_call(probe)
        slot = -1
        if name.text in _FILTERS:
            slot, self._slots = self._slots, self._slots + 1
        return self._build(CallNode(name.text, tuple(args), slot, name.position, span, height))


def _check_call(call: CallNode) -> None:
    low, high, constants = _FUNCTIONS[call.name]
    if not low <= len(call.args) <= high:
        raise _span_error("arity", call)
    values: dict[int, float] = {}
    for index in constants:
        value = _constant_value(call.args[index])
        if value is None:
            raise _span_error("non_constant_param", call.args[index])
        values[index] = value
    if call.name in ("ma", "integ") and not 0.0 < values[1] <= MAX_WINDOW_S:
        raise _span_error("param_range", call.args[1])
    if call.name == "lowpass" and not 0.0 < values[1] <= MAX_CUTOFF_HZ:
        raise _span_error("param_range", call.args[1])
    if call.name == "scale" and values[1] == values[2]:
        raise _span_error("param_range", call.args[2])


def parse_expression(text: str) -> ParsedExpression:
    """Parse and bound ``text``; raises ExpressionError (never anything else)."""
    if not isinstance(text, str):
        raise ExpressionError("syntax", 0, 0)
    if len(text) > MAX_EXPRESSION_CHARS:
        raise ExpressionError("too_long", MAX_EXPRESSION_CHARS, len(text) - MAX_EXPRESSION_CHARS)
    parser = _Parser(_lex(text))
    root = parser.parse()
    if not parser.refs:
        raise ExpressionError("no_signal", 0, len(text))
    return ParsedExpression(
        root=root,
        node_count=parser.node_count,
        depth=root.height,
        refs=tuple(parser.refs),
        filter_count=parser.slot_count,
    )


# ------------------------------------------------------------------------ evaluator


def _finite(value: float) -> float:
    return value if math.isfinite(value) else math.nan


def _fold_min(values: list[float]) -> float:
    if any(math.isnan(v) for v in values):
        return math.nan
    result = values[0]
    for v in values[1:]:
        if v < result:
            result = v
    return result


def _fold_max(values: list[float]) -> float:
    if any(math.isnan(v) for v in values):
        return math.nan
    result = values[0]
    for v in values[1:]:
        if v > result:
            result = v
    return result


class _FilterState:
    def update(self, t: float, x: float) -> float:
        raise NotImplementedError

    def size(self) -> int:
        return 0


class _WindowedFilter(_FilterState):
    """Finite samples in (t - w, t], newest MAX_FILTER_SAMPLES; recomputed per sample."""

    def __init__(self, window: float) -> None:
        self._window = window
        self._samples: deque[tuple[float, float]] = deque()
        self._last_t: float | None = None

    def update(self, t: float, x: float) -> float:
        if self._last_t is not None and t - self._last_t > self._window:
            self._samples.clear()
        self._last_t = t
        if math.isfinite(x):
            self._samples.append((t, x))
        cutoff = t - self._window
        while self._samples and self._samples[0][0] <= cutoff:
            self._samples.popleft()
        while len(self._samples) > MAX_FILTER_SAMPLES:
            self._samples.popleft()
        return _finite(self._reduce())

    def size(self) -> int:
        return len(self._samples)

    def _reduce(self) -> float:
        raise NotImplementedError


class _MovingAverage(_WindowedFilter):
    def _reduce(self) -> float:
        if not self._samples:
            return math.nan
        total = 0.0
        for _t, x in self._samples:
            total += x
        return total / len(self._samples)


class _Integral(_WindowedFilter):
    def _reduce(self) -> float:
        total = 0.0
        previous: tuple[float, float] | None = None
        for t, x in self._samples:
            if previous is not None:
                total += (t - previous[0]) * (x + previous[1]) / 2
            previous = (t, x)
        return total


class _LowPass(_FilterState):
    def __init__(self, cutoff_hz: float) -> None:
        self._rc = 1.0 / (2.0 * math.pi * cutoff_hz)
        self._reset = min(LOWPASS_MAX_RESET_S, 5.0 * self._rc)
        self._y: float | None = None
        self._t_finite = 0.0
        self._last_t: float | None = None

    def update(self, t: float, x: float) -> float:
        if self._last_t is not None and t - self._last_t > self._reset:
            self._y = None
        self._last_t = t
        if not math.isfinite(x):
            return math.nan
        if self._y is None:
            self._y = x
        else:
            dt = t - self._t_finite
            alpha = dt / (self._rc + dt)
            self._y = self._y + alpha * (x - self._y)
        self._t_finite = t
        return _finite(self._y)

    def size(self) -> int:
        return 0 if self._y is None else 1


class _Derivative(_FilterState):
    def __init__(self) -> None:
        self._previous: tuple[float, float] | None = None
        self._last_t: float | None = None

    def update(self, t: float, x: float) -> float:
        if self._last_t is not None and t - self._last_t > DERIV_RESET_S:
            self._previous = None
        self._last_t = t
        if not math.isfinite(x):
            return math.nan
        previous, self._previous = self._previous, (t, x)
        if previous is None:
            return math.nan
        return _finite((x - previous[1]) / (t - previous[0]))

    def size(self) -> int:
        return 0 if self._previous is None else 1


def _make_filter(call: CallNode) -> _FilterState:
    if call.name == "deriv":
        return _Derivative()
    parameter = _constant_value(call.args[1])
    assert parameter is not None  # guaranteed by _check_call
    if call.name == "lowpass":
        return _LowPass(parameter)
    return _MovingAverage(parameter) if call.name == "ma" else _Integral(parameter)


def _filter_calls(node: Node) -> list[CallNode]:
    if isinstance(node, CallNode):
        found = [call for arg in node.args for call in _filter_calls(arg)]
        return found + [node] if node.slot >= 0 else found
    if isinstance(node, BinaryNode):
        return _filter_calls(node.left) + _filter_calls(node.right)
    if isinstance(node, UnaryNode):
        return _filter_calls(node.operand)
    if isinstance(node, GroupNode):
        return _filter_calls(node.inner)
    return []


class _ReferenceBuffer:
    """One reference's accepted samples: strictly increasing finite timestamps."""

    def __init__(self) -> None:
        self.times: list[float] = []
        self.values: list[float] = []
        self._last_t: float | None = None

    def accept(self, t: float, value: float) -> bool:
        if not math.isfinite(t) or (self._last_t is not None and t <= self._last_t):
            return False
        self._last_t = t
        self.times.append(t)
        self.values.append(value if math.isfinite(value) else math.nan)
        if len(self.times) > MAX_BUFFERED_SAMPLES:
            del self.times[0], self.values[0]
        return True

    def held(self, t: float) -> float:
        i = bisect_right(self.times, t) - 1
        if i < 0 or t - self.times[i] > HOLD_SECONDS:
            return math.nan
        return self.values[i]

    def trim(self, t: float) -> None:
        """Keep the latest sample at or before ``t`` and everything after it."""
        i = bisect_right(self.times, t) - 1
        if i > 0:
            del self.times[:i], self.values[:i]


class IncrementalEvaluator:
    """Streaming evaluation with bounded state. Output samples are produced at the
    primary reference's timestamps. ``drain`` gives the same results as a batch run
    provided every secondary sample with timestamp <= t was fed before t is drained."""

    def __init__(self, parsed: ParsedExpression) -> None:
        self._parsed = parsed
        self._index = {ref: i for i, ref in enumerate(parsed.refs)}
        self._buffers = [_ReferenceBuffer() for _ in parsed.refs]
        self._pending: deque[float] = deque(maxlen=MAX_BUFFERED_SAMPLES)
        calls = sorted(_filter_calls(parsed.root), key=lambda call: call.slot)
        self._filters = [_make_filter(call) for call in calls]

    def feed(self, ref: SignalRef, samples: Iterable[tuple[float, float]]) -> None:
        index = self._index.get(ref)
        if index is None:
            return
        buffer = self._buffers[index]
        for t, value in samples:
            if buffer.accept(float(t), float(value)) and index == 0:
                self._pending.append(float(t))

    def drain(self, until: float | None = None) -> list[tuple[float, float]]:
        out: list[tuple[float, float]] = []
        while self._pending and (until is None or self._pending[0] <= until):
            t = self._pending.popleft()
            held = [buffer.held(t) for buffer in self._buffers]
            out.append((t, self._value(self._parsed.root, t, held)))
        if out:
            for buffer in self._buffers:
                buffer.trim(out[-1][0])
        return out

    def filter_state_sizes(self) -> list[int]:
        return [state.size() for state in self._filters]

    def buffer_sizes(self) -> list[int]:
        return [len(buffer.times) for buffer in self._buffers]

    def _value(self, node: Node, t: float, held: list[float]) -> float:
        if isinstance(node, NumberNode):
            return node.value
        if isinstance(node, RefNode):
            return held[node.index]
        if isinstance(node, GroupNode):
            return self._value(node.inner, t, held)
        if isinstance(node, UnaryNode):
            return _finite(-self._value(node.operand, t, held))
        if isinstance(node, BinaryNode):
            return _binary(
                node.op, self._value(node.left, t, held), self._value(node.right, t, held)
            )
        # Every argument is evaluated (no short-circuit) so nested filters advance.
        args = [self._value(arg, t, held) for arg in node.args]
        if node.slot >= 0:
            return self._filters[node.slot].update(t, args[0])
        return _apply(node.name, args)


def _binary(op: str, a: float, b: float) -> float:
    if op == "+":
        return _finite(a + b)
    if op == "-":
        return _finite(a - b)
    if op == "*":
        return _finite(a * b)
    return math.nan if b == 0 else _finite(a / b)


def _apply(name: str, args: list[float]) -> float:
    if name == "abs":
        return _finite(abs(args[0]))
    if name == "min":
        return _fold_min(args)
    if name == "max":
        return _fold_max(args)
    if name == "clamp":
        x, low, high = args
        if math.isnan(low) or math.isnan(high) or low > high:
            return math.nan
        return _fold_min([_fold_max([x, low]), high])
    x, in_lo, in_hi, out_lo, out_hi = args  # scale
    span = in_hi - in_lo
    return math.nan if span == 0 else _finite(out_lo + (x - in_lo) * (out_hi - out_lo) / span)


def evaluate(
    parsed: ParsedExpression, series: Mapping[SignalRef, Iterable[tuple[float, float]]]
) -> list[tuple[float, float]]:
    """Batch evaluation: ``[(t, value)]`` at the primary timestamps; NaN marks a gap."""
    stream = IncrementalEvaluator(parsed)
    for ref, samples in series.items():
        stream.feed(ref, samples)
    return stream.drain()
