"""The FeatureScript approval diff (SOLUSDEV-168).

`put_featurescript` overwrites an ENTIRE Feature Studio, so the approval card is
the last thing between SOL and a destroyed file. Two properties are load-bearing
and this file pins both:

* **Readable.** `confirmations._single_line` deletes every non-printable
  character — newlines and tabs included — and truncates at `_VALUE_CAP = 500`.
  A whole-file before/after would render as one glued run-on in which a `//`
  comment swallows the next statement.
* **Exact.** `confirmations._diverged` compares the RENDERED rows, so anything
  the cap hides is invisible to the R1 staleness check.
"""

from typing import Any

from solus_api.agent.confirmations import _build_preview, _diverged, _single_line
from solus_api.agent.tools.hosted_tools import (
    content_argument,
    featurescript_rows,
    read_arguments,
)

VALUE_CAP = 500

GET_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"documentId": {"type": "string"}, "elementId": {"type": "string"}},
}
PUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "documentId": {"type": "string"},
        "elementId": {"type": "string"},
        "contents": {"type": "string"},
    },
}


def _script(marker: str) -> str:
    """A realistic Feature Studio: a long identical prefix, then a difference.
    This is the exact shape that defeats a truncated comparison."""
    header = "\n".join(f"// boilerplate line {i} of the standard Onshape header" for i in range(40))
    return f"{header}\nannotation {{ 'Feature Type Name' : '{marker}' }}\nexport const x = 1;\n"


# ------------------------------------------------------------------ readability


def test_hunk_rows_survive_the_consent_card_renderer() -> None:
    """Every row must still say something after `_single_line` mangles it."""
    rows = featurescript_rows(target="doc=d el=e", before=_script("Alpha"), after=_script("Beta"))
    for row in rows:
        for field in ("before", "after"):
            value = row[field]
            if value is None:
                continue
            rendered = _single_line(value, VALUE_CAP)
            assert rendered, f"{row['label']}/{field} rendered empty"
            assert len(str(value)) <= VALUE_CAP, (
                f"{row['label']}/{field} would be truncated on the card"
            )


def test_a_whole_file_row_would_not_survive() -> None:
    """The counterfactual, so the reason for hunk rows is not folklore."""
    whole = _script("Alpha")
    assert len(whole) > VALUE_CAP
    assert "\n" not in _single_line(whole, VALUE_CAP), "newlines are deleted, not spaced"
    assert len(_single_line(whole, VALUE_CAP)) == VALUE_CAP  # silently truncated


# ----------------------------------------------------------------- exactness


def test_divergence_is_detected_past_the_render_cap() -> None:
    """THE R1 HOLE. Two scripts sharing their first 500 printable characters
    differ only after the cap; without the checksum row the gate would compare
    them equal and let a stale approval overwrite a teammate's edit."""
    shown = featurescript_rows(target="t", before=_script("Alpha"), after=_script("Beta"))
    later = featurescript_rows(target="t", before=_script("Gamma"), after=_script("Beta"))
    assert _script("Alpha")[:VALUE_CAP] == _script("Gamma")[:VALUE_CAP], "premise"
    assert _diverged(shown, later) is True


def test_identical_inputs_never_diverge() -> None:
    """The preview runs TWICE — once at park, once at decide under a row lock.
    Any non-determinism (a timestamp, a reordered label) would make every
    approval refuse as STALE, and STALE is terminal."""
    first = featurescript_rows(target="t", before=_script("A"), after=_script("B"))
    second = featurescript_rows(target="t", before=_script("A"), after=_script("B"))
    assert first == second
    assert _diverged(first, second) is False


def test_a_change_anywhere_in_a_long_file_diverges() -> None:
    big = "\n".join(f"const v{i} = {i};" for i in range(400))
    edited = big.replace("const v399 = 399;", "const v399 = 400;")
    a = featurescript_rows(target="t", before=big, after=big)
    b = featurescript_rows(target="t", before=edited, after=big)
    assert _diverged(a, b) is True


def test_row_count_stays_inside_the_gates_fifty_row_cap() -> None:
    """`_MAX_PREVIEW_ROWS = 50`; rows beyond it are dropped by the gate, which
    would silently weaken the diff."""
    before = "\n".join(f"line {i}" for i in range(500))
    after = "\n".join(f"changed {i}" for i in range(500))
    rows = featurescript_rows(target="t", before=before, after=after)
    assert len(rows) <= 50


def test_a_truncated_diff_says_so_out_loud() -> None:
    """No silent caps: a card that hides changes must admit it."""
    before = "\n".join(f"line {i}" for i in range(400))
    after = "\n".join(f"x{i}" if i % 2 else f"line {i}" for i in range(400))
    rows = featurescript_rows(target="t", before=before, after=after)
    assert any("not shown" in row["label"] for row in rows)


def test_no_change_is_stated_rather_than_rendered_as_an_empty_card() -> None:
    rows = featurescript_rows(target="t", before="same", after="same")
    assert any("no change" in row["label"] for row in rows)
    assert _diverged(rows, featurescript_rows(target="t", before="same", after="same")) is False


# -------------------------------------------------- argument resolution (no guessing)


def test_the_content_argument_is_derived_from_the_two_schemas() -> None:
    """The spike captured schema SIZES, not field names. The content argument is
    the one the WRITE tool declares and the READ tool does not — so this never
    depends on the vendor's naming."""
    args = {"documentId": "d", "elementId": "e", "contents": "export const x = 1;"}
    assert content_argument(PUT_SCHEMA, GET_SCHEMA, args) == "contents"


def test_the_read_call_reuses_exactly_the_identifying_arguments() -> None:
    args = {"documentId": "d", "elementId": "e", "contents": "src"}
    assert read_arguments(GET_SCHEMA, args) == {"documentId": "d", "elementId": "e"}


def test_a_renamed_content_field_still_resolves() -> None:
    put: dict[str, Any] = {
        "type": "object",
        "properties": {**GET_SCHEMA["properties"], "code": {"type": "string"}},
    }
    args = {"documentId": "d", "elementId": "e", "code": "src"}
    assert content_argument(put, GET_SCHEMA, args) == "code"


def test_an_unresolvable_content_argument_returns_none_rather_than_guessing() -> None:
    """Fail closed: the caller refuses the call rather than previewing the wrong
    thing or degrading to argument rows."""
    assert content_argument(GET_SCHEMA, GET_SCHEMA, {"documentId": "d"}) is None


async def test_the_gate_accepts_these_rows_from_a_real_tool_object() -> None:
    """End to end through the gate's own duck-typed hook, so a shape change in
    `_build_preview` breaks here rather than in production."""

    class _Tool:
        async def preview(self, args: dict[str, object]) -> list[dict[str, object]]:
            return featurescript_rows(
                target="doc=d", before=_script("Alpha"), after=str(args["contents"])
            )

    rows = await _build_preview(_Tool(), {"contents": _script("Beta")})
    assert len(rows) >= 2
    assert all({"label", "before", "after"} == set(row) for row in rows)
    assert any("checksum" in row["label"] for row in rows)


async def test_the_checksum_row_is_what_catches_a_difference_past_the_cap() -> None:
    """Isolates the checksum's contribution, through the REAL path.

    Truncation happens in `_build_preview` (`_single_line(value, _VALUE_CAP)`),
    not in `_diverged` — so the comparison at decide time is between rows that
    have ALREADY been capped. A single line longer than the cap, differing only
    after character 500, therefore renders identically in its hunk row. Without
    the checksum row the gate sees no divergence and applies an overwrite built
    against a document that has since changed.
    """
    prefix = "const config = { " + "padding, " * 80  # > 500 chars, identical
    old_line = prefix + "tolerance: 0.1 };"
    new_line = prefix + "tolerance: 0.9 };"
    assert len(prefix) > VALUE_CAP
    assert _single_line(old_line, VALUE_CAP) == _single_line(new_line, VALUE_CAP), "premise"

    class _Tool:
        def __init__(self, current: str) -> None:
            self._current = current

        async def preview(self, args: dict[str, object]) -> list[dict[str, object]]:
            return featurescript_rows(target="t", before=self._current, after=str(args["contents"]))

    args = {"contents": "replacement"}
    shown = await _build_preview(_Tool(old_line), args)  # park time
    later = await _build_preview(_Tool(new_line), args)  # decide time, doc changed

    hunks_only = [[r for r in rows if "checksum" not in r["label"]] for rows in (shown, later)]
    assert _diverged(*hunks_only) is False, "hunk rows alone cannot see past the cap"
    assert _diverged(shown, later) is True, "the checksum row must catch it"
