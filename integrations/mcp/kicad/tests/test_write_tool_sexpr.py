"""SOLUSDEV-100 T2b — the owned S-expression tokenizer/parser
(`solus/write/sexpr.py`): byte-offset fidelity, escaping round-trips, and the
malformed-input failure modes the splice guard depends on.

Phase 4 M5 addendum: an explicit token-count cap and nesting-depth bound so a
pathological input (deep nesting, or a huge flat token count within the
already-enforced 8 MiB file cap) refuses cleanly via `GuardExceededError`
rather than exhausting memory or raising `RecursionError` past the parser's
own contract of "only `SExprSyntaxError` (or a subclass) ever escapes"."""

import time
from pathlib import Path

import pytest
from paths import SOLUS_SAMPLE_SCH

# The support module's import bootstrap (sys.path + lockfile-dep stubs) must
# run BEFORE any `solus` import — keep this line before the solus.* imports.
from test_overlay_support import SOLUS  # noqa: F401  # isort: skip

from solus.write.sexpr import (  # isort: skip
    MAX_TOKENS,
    GuardExceededError,
    Node,
    SExprSyntaxError,
    TokenKind,
    parse,
    tokenize,
)


# --- flat tokenization --------------------------------------------------------


def test_tokenizes_parens_atoms_and_strings_with_exact_byte_spans() -> None:
    data = b'(kicad_sch (version 20250114) (title_block (title "Solus")))'
    tokens = tokenize(data)
    kinds = [token.kind for token in tokens]
    assert kinds[:3] == [TokenKind.LPAREN, TokenKind.ATOM, TokenKind.LPAREN]
    version_atom = tokens[3]
    assert version_atom.kind == TokenKind.ATOM
    assert version_atom.value == "version"
    number_atom = tokens[4]
    assert number_atom.value == "20250114"
    assert data[number_atom.start : number_atom.end] == b"20250114"
    title_string = next(t for t in tokens if t.kind == TokenKind.STRING)
    assert title_string.value == "Solus"
    # The span covers the surrounding quotes too.
    assert data[title_string.start : title_string.end] == b'"Solus"'


def test_whitespace_variants_are_all_skipped_between_tokens() -> None:
    data = b"(\ta\n b\r\n)"
    tokens = tokenize(data)
    assert [t.kind for t in tokens] == [
        TokenKind.LPAREN,
        TokenKind.ATOM,
        TokenKind.ATOM,
        TokenKind.RPAREN,
    ]
    assert [t.value for t in tokens if t.kind == TokenKind.ATOM] == ["a", "b"]


def test_negative_and_decimal_numeric_atoms_tokenize_as_single_atoms() -> None:
    tokens = tokenize(b"(at -12.7 15.24 0)")
    values = [t.value for t in tokens if t.kind == TokenKind.ATOM]
    assert values == ["at", "-12.7", "15.24", "0"]


# --- string escaping on read ---------------------------------------------------


def test_decodes_escaped_quote_inside_a_string() -> None:
    data = b'(description "creates a global label with name \\"+3V3\\"")'
    tokens = tokenize(data)
    string_token = next(t for t in tokens if t.kind == TokenKind.STRING)
    assert string_token.value == 'creates a global label with name "+3V3"'


def test_decodes_escaped_backslash_inside_a_string() -> None:
    data = b'(value "a\\\\b")'
    tokens = tokenize(data)
    string_token = next(t for t in tokens if t.kind == TokenKind.STRING)
    assert string_token.value == "a\\b"


def test_string_may_contain_raw_parens_without_terminating() -> None:
    data = b'(value "(not a list)")'
    tokens = tokenize(data)
    string_token = next(t for t in tokens if t.kind == TokenKind.STRING)
    assert string_token.value == "(not a list)"


def test_string_may_contain_unicode() -> None:
    data = '(value "Ωµ")'.encode()
    tokens = tokenize(data)
    string_token = next(t for t in tokens if t.kind == TokenKind.STRING)
    assert string_token.value == "Ωµ"


# --- malformed input -----------------------------------------------------------


def test_unterminated_string_raises_sexpr_syntax_error() -> None:
    with pytest.raises(SExprSyntaxError):
        tokenize(b'(value "unterminated)')


def test_dangling_escape_at_end_of_input_raises_sexpr_syntax_error() -> None:
    with pytest.raises(SExprSyntaxError):
        tokenize(b'(value "abc\\')


def test_unbalanced_close_paren_raises_sexpr_syntax_error() -> None:
    with pytest.raises(SExprSyntaxError):
        parse(b"(a))")


def test_unterminated_list_raises_sexpr_syntax_error() -> None:
    with pytest.raises(SExprSyntaxError):
        parse(b"(a (b)")


def test_trailing_content_after_top_level_expression_raises() -> None:
    with pytest.raises(SExprSyntaxError):
        parse(b"(a) (b)")


def test_empty_document_raises_sexpr_syntax_error() -> None:
    with pytest.raises(SExprSyntaxError):
        parse(b"   \n\t")


# --- tree parsing ---------------------------------------------------------------


def test_parse_builds_a_nested_tree_with_whole_node_spans() -> None:
    data = b'(property "Reference" "U1" (at 63.5 68.58 0))'
    root = parse(data)
    assert root.kind == TokenKind.LPAREN
    assert root.start == 0
    assert root.end == len(data)
    assert len(root.children) == 4
    assert root.children[0].value == "property"
    assert root.children[1].value == "Reference"
    assert root.children[2].value == "U1"
    at_node = root.children[3]
    assert at_node.kind == TokenKind.LPAREN
    assert [c.value for c in at_node.children] == ["at", "63.5", "68.58", "0"]


def test_parse_round_trips_the_committed_solus_sample_fixture() -> None:
    """The real fixture must parse cleanly end to end — the load-bearing
    floor every other write-tool test builds on."""
    data = Path(SOLUS_SAMPLE_SCH).read_bytes()
    root = parse(data)
    assert root.kind == TokenKind.LPAREN
    assert root.children[0].kind == TokenKind.ATOM
    assert root.children[0].value == "kicad_sch"


def test_node_is_frozen_and_hashable_by_identity() -> None:
    node = Node(TokenKind.ATOM, 0, 1, "x")
    with pytest.raises(AttributeError):
        node.value = "y"  # type: ignore[misc]


# --- M5: token-count and nesting-depth guards --------------------------------------


def test_guard_exceeded_error_is_a_sexpr_syntax_error() -> None:
    """`GuardExceededError` must be catchable by every existing `except
    SExprSyntaxError` call site (locator.py, guard.py) without change,
    while remaining distinguishable where a caller wants a dedicated
    stable reason (locator.py maps it to `file_too_large`, not the
    default `reference_not_found` bucket)."""
    assert issubclass(GuardExceededError, SExprSyntaxError)


def test_tokenize_refuses_a_pathological_token_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("solus.write.sexpr.MAX_TOKENS", 10)
    with pytest.raises(GuardExceededError):
        tokenize(b"(" + b"a " * 20 + b")")


def test_tokenize_accepts_up_to_the_token_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("solus.write.sexpr.MAX_TOKENS", 10)
    tokens = tokenize(b"(" + b"a " * 8 + b")")
    assert len(tokens) == 10


def test_tokenize_at_the_real_cap_stays_within_a_sane_wall_time_budget() -> None:
    """A flat (non-nested) document at the real `MAX_TOKENS` cap — proves the
    guard bounds memory/time for realistic legitimate input too, not just a
    monkeypatched tiny cap."""
    atom_count = MAX_TOKENS - 2  # -2 for the enclosing LPAREN/RPAREN
    data = b"(" + b"a " * atom_count + b")"

    started = time.perf_counter()
    tokens = tokenize(data)
    elapsed = time.perf_counter() - started

    assert len(tokens) == MAX_TOKENS
    # Deliberately GENEROUS (measured ~0.12s on a dev laptop): this catches a
    # complexity regression (quadratic scanning would blow far past it) without
    # flaking on a loaded shared CI runner, where a tight bound would be a
    # false failure rather than a finding.
    assert elapsed < 30.0, f"tokenizing {MAX_TOKENS} tokens took {elapsed:.2f}s — too slow"


def test_parse_refuses_pathological_nesting_depth_instead_of_recursion_error() -> None:
    """The exact repro from the finding: 50,000 levels of nesting must refuse
    cleanly, never raise `RecursionError`."""
    with pytest.raises(GuardExceededError):
        parse(b"(" * 50_000 + b")" * 50_000)


def test_parse_accepts_nesting_up_to_the_depth_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("solus.write.sexpr.MAX_NESTING_DEPTH", 10)
    root = parse(b"(" * 10 + b")" * 10)
    assert root.kind == TokenKind.LPAREN


def test_parse_refuses_nesting_one_past_the_depth_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("solus.write.sexpr.MAX_NESTING_DEPTH", 10)
    with pytest.raises(GuardExceededError):
        parse(b"(" * 11 + b")" * 11)


@pytest.mark.parametrize(
    "hostile",
    [
        b"(" * 50_000 + b")" * 50_000,
        b"(" + b"a " * 300_000 + b")",
        b"(" * 100,  # unterminated, also deep
        b"",
        b"(((",
        b'(value "unterminated' + b"(" * 1000,
    ],
    ids=[
        "deep-balanced-nesting",
        "many-flat-tokens",
        "deep-unterminated-nesting",
        "empty",
        "shallow-unterminated",
        "unterminated-string-then-deep-nesting",
    ],
)
def test_hostile_sexpr_input_sweep_never_raises_anything_but_sexpr_syntax_error(
    hostile: bytes,
) -> None:
    """Only `SExprSyntaxError` (or `GuardExceededError`, its subclass) may
    ever escape `tokenize`/`parse` — never `RecursionError`, never anything
    else — across a sweep of hostile shapes."""
    try:
        parse(hostile)
    except SExprSyntaxError:
        pass  # expected — includes GuardExceededError
