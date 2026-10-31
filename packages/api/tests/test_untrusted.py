"""Unit tests for the shared untrusted-input gates (extracted from mcp_tool)."""

import pytest
from solus_api.agent.tools.untrusted import (
    REDACTED,
    SAFE_REMOTE_NAME,
    SCHEMA_BYTES_CAP,
    UNTRUSTED_TEXT_CAP,
    contains_ref,
    redact_text,
    redact_value,
    schema_oversized,
    unsafe_schema_reason,
)


def test_safe_remote_name_accepts_composed_names() -> None:
    assert SAFE_REMOTE_NAME.fullmatch("mock.echo")
    assert SAFE_REMOTE_NAME.fullmatch("kicad_export-v2")


def test_safe_remote_name_rejects_hostile_shapes() -> None:
    assert SAFE_REMOTE_NAME.fullmatch("") is None
    assert SAFE_REMOTE_NAME.fullmatch("rm -rf /") is None
    assert SAFE_REMOTE_NAME.fullmatch("a" * 129) is None


def test_contains_ref_finds_nested_refs() -> None:
    assert contains_ref({"properties": {"x": {"$ref": "#/defs/x"}}})
    assert contains_ref([{"anyOf": [{"$ref": "#"}]}])
    assert not contains_ref({"type": "object", "properties": {"x": {"type": "string"}}})


def test_schema_oversized_bounds_serialized_size() -> None:
    assert not schema_oversized({"type": "object"})
    assert schema_oversized({"blob": "x" * (SCHEMA_BYTES_CAP + 1)})
    assert schema_oversized({"bad": object()})  # unserializable ⇒ rejected


def test_unsafe_schema_reason_pass_and_fail_modes() -> None:
    assert unsafe_schema_reason({"type": "object"}) is None
    assert unsafe_schema_reason({"blob": "x" * (SCHEMA_BYTES_CAP + 1)}) == (
        "advertises an oversized schema"
    )
    assert unsafe_schema_reason({"$ref": "#/nope"}) == "advertises a $ref-bearing input schema"
    assert unsafe_schema_reason({"type": "not-a-real-type"}) == (
        "advertises a malformed input schema"
    )


def test_text_cap_is_the_mcp01_value() -> None:
    assert UNTRUSTED_TEXT_CAP == 500


# A long absolute path satisfies the entropy heuristic on every count — length,
# charset (`/` is in it), and distinct characters — so whole paths were being
# redacted. The consent card renders `cwd` and `path` rows from a companion
# dry-run plan, and a card that says the command runs in "[REDACTED]" is not
# consent (SOLUSDEV-252, found live on machine.run_command).
_LONG_PATH = "/home/beeboss/projects/solus/packages/companion/src/solus_companion/machine"


def test_a_filesystem_path_is_not_a_secret() -> None:
    assert redact_value({"cwd": _LONG_PATH}) == {"cwd": _LONG_PATH}
    assert redact_value(["C:\\Users\\pratham\\AppData\\Local\\Programs\\solus\\resources"]) == [
        "C:\\Users\\pratham\\AppData\\Local\\Programs\\solus\\resources"
    ]
    assert redact_text(f"running in {_LONG_PATH} now") == f"running in {_LONG_PATH} now"


def test_a_secret_inside_a_path_still_goes() -> None:
    """Per-segment, not blanket: one high-entropy component is still redacted."""
    secret = "sk-proj-Ab3Kd9Xz2Qw7Rt5Yu8Io1Pl4Mn6Bv0Cx9Zs3Ed7Fg2Hj5Kl8"
    assert redact_value({"path": f"/var/run/{secret}/socket"}) == {"path": REDACTED}


def test_a_bare_secret_is_still_redacted() -> None:
    assert redact_value("ghp_1a2B3c4D5e6F7g8H9i0JkLmNoPqRsTuVwXyZ01") == REDACTED
    assert redact_value({"api_key": "short"}) == {"api_key": REDACTED}


def test_a_base64_blob_that_starts_like_a_path_is_still_a_secret() -> None:
    """The per-segment relaxation must not become the way to smuggle one out.

    Every `/`-delimited run here is UNDER the 40-character bar, so the per-segment
    test alone would pass it; only the `+`/`=` guard catches it. A blob with one
    long run would be caught either way and would not test this at all.
    """
    blob = "/aB3kD9xZ2qW7rT5yU/8iO1pL4mN6bV0cX9zS3/eD7fG2hJ5kL8mP+q="
    assert max(len(part) for part in blob.split("/")) < 40  # the guard is what fires
    assert redact_value({"note": blob}) == {"note": REDACTED}


def test_a_secret_next_to_punctuation_is_redacted() -> None:
    """Where secrets actually sit: quoted in a shell trace, on its own line."""
    line = "curl -H 'authorization: Bearer ghp_16C7e42F292c6912E7710c838347Ae178B4a'\nmake: Error 2"
    masked = redact_text(line)
    assert "ghp_16C7e42F292c6912E7710c838347Ae178B4a" not in masked
    assert "make: Error 2" in masked  # the useful part survives


def test_redaction_keeps_the_shape_of_the_text() -> None:
    assert redact_text("line one\nline two") == "line one\nline two"


def test_authorization_scheme_does_not_leave_credential_visible() -> None:
    assert "short-token" not in redact_text("Authorization: Bearer short-token")
    assert "short-token" not in redact_text("authorization=Basic short-token")


# One sample per provider shape, built at test time (a literal key-shaped string is a secret to
# every scanner) and kept under the 40-character entropy floor with few distinct characters, so
# only the provider-prefix denylist can be what masks it.
_PROVIDER_KEYS = {
    "aws access key": "AKIA" + "AB12" * 4,
    "aws session key": "ASIA" + "AB12" * 4,
    "openai": "sk-" + "ab12" * 6,
    "github": "ghp_" + "ab12" * 9,
    "gitlab": "glpat-" + "ab12" * 5,
    "slack": "xoxb-" + "12" * 6,
    "google": "AIza" + "ab12" * 8 + "abc",
    "stripe": "sk_live_" + "ab12" * 6,
    "pem": "-----BEGIN " + "RSA PRIVATE KEY-----",
}


@pytest.mark.parametrize("shape", _PROVIDER_KEYS)
def test_a_provider_prefixed_key_is_redacted_wherever_it_sits(shape: str) -> None:
    key = _PROVIDER_KEYS[shape]
    # Below the entropy heuristic's floor (40 characters, 16 distinct): only the denylist masks it.
    assert len(key) < 40 or len(set(key)) < 16
    assert redact_text(f"use {key} now") == f"use {REDACTED} now"
    assert redact_text(key) == REDACTED
    # A scalar inside a structure is judged whole, like an entropic one: prose that carries a key
    # is masked, not passed through because it has spaces in it.
    assert redact_value(f"rotate {key} soon") == REDACTED
    assert redact_value({"title": f"rotate {key} soon", "n": 1}) == {"title": REDACTED, "n": 1}


@pytest.mark.parametrize(
    "text",
    [
        "AKIA" + "AB12X",  # too short for an AWS access key id
        "disk-" + "ab12" * 6,  # `sk-` inside a word is not an OpenAI key
        "task_live_" + "ab12" * 6,  # nor is `sk_live_` inside one a Stripe key
        "ASIAN" + "ab12",  # a word that merely starts like an AWS prefix
        # Round 4: the same look-alikes behind an accent, which puts them on the folded path. The
        # word rule holds there too — anchored at a raw word start, never searched anywhere.
        "café" + "disk-" + "ab12" * 6,
        "café" + "x" + "AKIA" + "QZ7X" * 4,
    ],
)
def test_text_that_only_resembles_a_provider_key_is_left_alone(text: str) -> None:
    assert redact_text(f"see {text} here") == f"see {text} here"
    assert redact_value(text) == text


#: Code points that render as nothing (or blank) inside a token: a combining grapheme joiner, a
#: variation selector, a combining accent, two Hangul fillers, a blank braille cell, a zero-width
#: space (M35). Built at run time, so no key-shaped literal sits in the source.
_INVISIBLES = ("͏", "️", "́", "ㅤ", "ᅟ", "⠀", "​")
_OPENAI_SHAPED = "sk-" + "Zq9" * 8
_AWS_SHAPED = "AKIA" + "QZ7X" * 4


@pytest.mark.parametrize("mark", _INVISIBLES)
@pytest.mark.parametrize("key", [_OPENAI_SHAPED, _AWS_SHAPED])
def test_an_invisible_code_point_inside_a_key_does_not_hide_it(key: str, mark: str) -> None:
    hidden = key[:6] + mark + key[6:]
    assert REDACTED in redact_text(f"the key is {hidden} ok")
    assert redact_text(f"the key is {hidden} ok").startswith("the key is ")
    assert redact_value(hidden) == REDACTED
    assert redact_value({"note": f"use {hidden}"}) == {"note": REDACTED}


_ACCENTED_E, _ZWSP = chr(0xE9), chr(0x200B)


@pytest.mark.parametrize(
    "hidden",
    [
        _ACCENTED_E + _AWS_SHAPED,  # stripping the accent's mark would merge `e` into `AKIA…`
        _ZWSP + _AWS_SHAPED,
        "x" + _ZWSP + _AWS_SHAPED,
        _OPENAI_SHAPED[:6] + _ACCENTED_E + _OPENAI_SHAPED[6:],
        _OPENAI_SHAPED[:6] + _ZWSP + _OPENAI_SHAPED[6:],
        # Round 2, new issue 6: a merge on one side AND a split inside, in one token.
        _ACCENTED_E + _AWS_SHAPED[:6] + _ZWSP + _AWS_SHAPED[6:],
        # Round 3 (R160): an invisible NFKC keeps out of every letter, before a key that also
        # hides one inside it — deleting merges the `x`/`q`, separating splits the key.
        "x" + _ZWSP + _AWS_SHAPED[:6] + _ZWSP + _AWS_SHAPED[6:],
        "x" + _ZWSP + _OPENAI_SHAPED[:6] + _ZWSP + _OPENAI_SHAPED[6:],
        "q" + chr(0x301) + _AWS_SHAPED,
        "q" + chr(0x301) + _AWS_SHAPED[:6] + _ZWSP + _AWS_SHAPED[6:],
        # Round 4: a symbol whose compatibility fold is ASCII letters (™ → TM, № → No, ｘ → x)
        # before a key split by an invisible — the fold must not merge the symbol into the key.
        chr(0x2122) + _AWS_SHAPED[:6] + _ZWSP + _AWS_SHAPED[6:],
        chr(0x2116) + _AWS_SHAPED[:6] + _ZWSP + _AWS_SHAPED[6:],
        chr(0xFF58) + _AWS_SHAPED[:6] + _ZWSP + _AWS_SHAPED[6:],
        chr(0x2122) + _OPENAI_SHAPED[:6] + _ZWSP + _OPENAI_SHAPED[6:],
        # Round 5 (R164): a key that starts partway through ONE code point's fold — U+33B2 folds
        # to `μs`, U+3382 to `μA` — so the folded text reads `μsk-…` / `μAKIA…`, split or not.
        chr(0x33B2) + _OPENAI_SHAPED[1:],
        chr(0x33B2) + _OPENAI_SHAPED[1:6] + _ZWSP + _OPENAI_SHAPED[6:],
        chr(0x3382) + _AWS_SHAPED[1:],
        chr(0x3382) + _AWS_SHAPED[1:6] + _ZWSP + _AWS_SHAPED[6:],
    ],
)
def test_a_mark_next_to_or_inside_a_key_never_hides_it(hidden: str) -> None:
    """R154: the detectors judge the raw text AND the stripped forms (a stripped mark is never
    allowed to merge its neighbours), so a key that matched before the fix still matches."""
    assert redact_value(hidden) == REDACTED
    assert REDACTED in redact_text(f"key {hidden} end")


def test_an_invisible_inside_a_pem_header_does_not_hide_it() -> None:
    """R162: the PEM header has no word rule, so it is searched in the folded form, not anchored.
    Judged whole: `redact_text` splits on the header's own spaces before the folded pass runs."""
    hidden = "-----BEGIN " + _ZWSP + "PRIVATE KEY-----"
    assert redact_value(hidden) == REDACTED
    assert redact_value({"pem": hidden}) == {"pem": REDACTED}
    # Round 5, item 3: straight after a letter, so no raw word start falls on the header — only a
    # whole-form SEARCH of the folded text finds it (a `\n` between them would be a start itself).
    assert redact_value("x" + hidden) == REDACTED
    assert redact_value(_PROVIDER_KEYS["pem"]) == REDACTED


def test_ordinary_accented_text_is_left_alone() -> None:
    for text in (
        "café naïve résumé",
        "café résumé",
        "the e" + chr(0x301) + "lan of AKIA-free prose",
    ):
        assert redact_text(text) == text and redact_value(text) == text
