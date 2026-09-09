"""Owned S-expression reader tests (SOLUSDEV-252, W0-08 §6.3).

The reader is the shared substrate for the S-expression netlist and the board
parser: stdlib-only, no eval, ITERATIVE (never recursion), with explicit
resource guards (nesting depth, materialized node count) and a `prune` hook
that skips whole subtrees WITHOUT materializing them. Pure unit — no DB.
"""

from __future__ import annotations

import pytest
from solus_api.connectors import kicad_sexpr
from solus_api.connectors.kicad_sexpr import (
    MAX_SEXPR_DEPTH,
    SExprLimitError,
    SExprSyntaxError,
    child,
    children,
    parse_sexpr,
    string_at,
)

# ------------------------------------------------------------- grammar


def test_atoms_and_strings_both_become_str() -> None:
    assert parse_sexpr('(net 1 "VCC" 2.5 yes)') == ("net", "1", "VCC", "2.5", "yes")


def test_nested_lists_become_nested_tuples() -> None:
    tree = parse_sexpr('(comp (ref "U1") (fields (field (name "MPN") "LM358DR")))')
    assert tree == ("comp", ("ref", "U1"), ("fields", ("field", ("name", "MPN"), "LM358DR")))


def test_empty_list_and_whitespace_variants() -> None:
    assert parse_sexpr("  \n\t( a\r\n(  )\tb )\n") == ("a", (), "b")


def test_known_escapes_are_decoded() -> None:
    tree = parse_sexpr(r'(s "a\"b" "c\\d" "e\nf" "g\th" "i\rj")')
    assert tree == ("s", 'a"b', "c\\d", "e\nf", "g\th", "i\rj")


def test_unknown_escape_is_preserved_literally() -> None:
    # Lenient on read: an unusual existing file never fails to parse.
    assert parse_sexpr(r'(s "x\qy")') == ("s", r"x\qy")


def test_string_may_contain_parens_and_newlines() -> None:
    assert parse_sexpr('(s "a (b) c\nd")') == ("s", "a (b) c\nd")


def test_adjacent_tokens_without_whitespace() -> None:
    assert parse_sexpr('(a"b"(c)d)') == ("a", "b", ("c",), "d")


# ------------------------------------------------------------- syntax errors


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   \n",
        "(a",
        "(a (b)",
        '(a "unterminated)',
        '(a "dangling\\',
        "(a) b",
        "(a) (b)",
        ")",
        "atom",
        '"string"',
    ],
)
def test_malformed_input_is_a_syntax_error(text: str) -> None:
    with pytest.raises(SExprSyntaxError):
        parse_sexpr(text)


def test_limit_error_is_a_syntax_error_subclass() -> None:
    assert issubclass(SExprLimitError, SExprSyntaxError)


# ------------------------------------------------------------- resource guards


def test_depth_at_the_limit_parses_and_one_deeper_is_refused() -> None:
    assert parse_sexpr("(" * MAX_SEXPR_DEPTH + ")" * MAX_SEXPR_DEPTH) is not None
    deeper = MAX_SEXPR_DEPTH + 1
    with pytest.raises(SExprLimitError):
        parse_sexpr("(" * deeper + ")" * deeper)


def test_node_limit_is_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(kicad_sexpr, "MAX_SEXPR_NODES", 10)
    assert parse_sexpr("(a b c)") == ("a", "b", "c")
    with pytest.raises(SExprLimitError):
        parse_sexpr("(" + " ".join(["x"] * 20) + ")")


def test_pathological_flat_input_is_refused_without_recursion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Alternating "()" pairs are the worst-case node/byte ratio; the node guard
    # must trip long before memory does and never hit a RecursionError.
    monkeypatch.setattr(kicad_sexpr, "MAX_SEXPR_NODES", 1_000)
    with pytest.raises(SExprLimitError):
        parse_sexpr("(" + "()" * 5_000 + ")")


# ------------------------------------------------------------- pruning


def test_prune_skips_the_subtree_and_reports_head_and_depth() -> None:
    seen: list[tuple[str, int]] = []

    def prune(head: str, depth: int) -> bool:
        seen.append((head, depth))
        return head == "design"

    tree = parse_sexpr(
        '(export (version "E") (design (source "x") (sheet (n 1))) (nets (net (code 1))))',
        prune=prune,
    )
    assert tree == ("export", ("version", "E"), ("nets", ("net", ("code", "1"))))
    assert ("export", 0) in seen
    assert ("design", 1) in seen
    # Nothing under the pruned list was ever offered for materialization.
    assert ("source", 2) not in seen
    assert ("sheet", 2) not in seen


def test_pruned_regions_are_not_materialized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(kicad_sexpr, "MAX_SEXPR_NODES", 10)
    noise = "(noise " + " ".join(['"x"'] * 500) + " (deep (deeper (deepest))))"
    text = f"(root {noise} (keep 1))"
    with pytest.raises(SExprLimitError):
        parse_sexpr(text)
    assert parse_sexpr(text, prune=lambda head, _d: head == "noise") == ("root", ("keep", "1"))


def test_pruning_respects_parens_inside_strings() -> None:
    text = '(root (skip "a ) b" "c \\" ( d") (keep "ok"))'
    assert parse_sexpr(text, prune=lambda head, _d: head == "skip") == ("root", ("keep", "ok"))


def test_unterminated_pruned_list_is_still_a_syntax_error() -> None:
    with pytest.raises(SExprSyntaxError):
        parse_sexpr("(root (skip (a (b)", prune=lambda head, _d: head == "skip")
    with pytest.raises(SExprSyntaxError):
        parse_sexpr('(root (skip "never closed) (keep))', prune=lambda head, _d: head == "skip")


def test_prune_is_not_consulted_for_headless_lists() -> None:
    calls: list[str] = []

    def prune(head: str, _depth: int) -> bool:
        calls.append(head)
        return False

    assert parse_sexpr('(root ("str" 1) ((x)) ())', prune=prune) == (
        "root",
        ("str", "1"),
        (("x",),),
        (),
    )
    assert calls == ["root", "x"]


# ------------------------------------------------------------- helpers


def test_children_yields_direct_matches_only() -> None:
    tree = parse_sexpr("(a (b 1) (c (b 2)) (b 3))")
    assert list(children(tree, "b")) == [("b", "1"), ("b", "3")]
    assert list(children(tree, "zzz")) == []
    assert list(children("atom", "b")) == []


def test_child_returns_first_match_or_none() -> None:
    tree = parse_sexpr("(a (b 1) (b 2))")
    assert child(tree, "b") == ("b", "1")
    assert child(tree, "c") is None


def test_string_at_returns_only_string_items_in_range() -> None:
    tree = parse_sexpr('(pad "1" smd (net 3 "SIGNAL"))')
    assert string_at(tree, 1) == "1"
    assert string_at(tree, 2) == "smd"
    assert string_at(tree, 3) is None  # a list, not a string
    assert string_at(tree, 99) is None
    assert string_at(None, 0) is None
