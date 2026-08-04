"""The byte-stability guard (F10): the last check before any disk write.

Re-parses BOTH the original and the spliced bytes with the owned tokenizer
and asserts:

1. the raw byte diff is confined to the located value span (bytes outside
   `[span_start, span_end)` are identical, by construction of the splice —
   asserted here as defense in depth against a locator bug); and
2. the two flat token streams are identical except for exactly ONE token,
   which must be a STRING token whose old/new decoded values match what the
   caller expected.

Any violation raises `RefusalError(REASON_GUARD_FAILED)` — the caller must
not have written *spliced* to disk yet, so the original file is guaranteed
untouched.
"""

from solus.write.errors import REASON_GUARD_FAILED, RefusalError
from solus.write.sexpr import SExprSyntaxError, Token, TokenKind, tokenize


def _flatten(tokens: list[Token]) -> list[tuple[TokenKind, str | None]]:
    return [(token.kind, token.value) for token in tokens]


def _assert_diff_confined_to_span(
    original: bytes, spliced: bytes, span_start: int, span_end: int
) -> None:
    prefix_len = span_start
    if original[:prefix_len] != spliced[:prefix_len]:
        raise RefusalError(REASON_GUARD_FAILED)
    suffix_len = len(original) - span_end
    if suffix_len and original[-suffix_len:] != spliced[-suffix_len:]:
        raise RefusalError(REASON_GUARD_FAILED)


def _tokenize_both(original: bytes, spliced: bytes) -> tuple[list[Token], list[Token]]:
    try:
        return tokenize(original), tokenize(spliced)
    except SExprSyntaxError as exc:
        raise RefusalError(REASON_GUARD_FAILED) from exc


def verify_byte_stable_splice(
    original: bytes,
    spliced: bytes,
    span_start: int,
    span_end: int,
    old_value: str,
    new_value: str,
) -> None:
    """Verify *spliced* differs from *original* by exactly the one property
    value, confined to `[span_start, span_end)`. Raises `RefusalError` on
    any deviation; returns None (no exception) when the splice is proven
    safe to write."""
    _assert_diff_confined_to_span(original, spliced, span_start, span_end)

    before_tokens, after_tokens = _tokenize_both(original, spliced)
    before, after = _flatten(before_tokens), _flatten(after_tokens)
    if len(before) != len(after):
        raise RefusalError(REASON_GUARD_FAILED)

    changed = [
        index for index, pair in enumerate(zip(before, after, strict=True)) if pair[0] != pair[1]
    ]
    if len(changed) != 1:
        raise RefusalError(REASON_GUARD_FAILED)

    (before_kind, before_value), (after_kind, after_value) = before[changed[0]], after[changed[0]]
    if before_kind != TokenKind.STRING or after_kind != TokenKind.STRING:
        raise RefusalError(REASON_GUARD_FAILED)
    if before_value != old_value or after_value != new_value:
        raise RefusalError(REASON_GUARD_FAILED)
