"""SOLUSDEV-100 T2b — `solus/write/escaping.py`: the KiCad string escape/
unescape round trip and the provable-round-trip refusal boundary."""

import pytest

# The support module's import bootstrap (sys.path + lockfile-dep stubs) must
# run BEFORE any `solus` import — keep this line before the solus.* imports.
from test_overlay_support import SOLUS  # noqa: F401  # isort: skip

from solus.write.escaping import (  # isort: skip
    MAX_PROPERTY_VALUE_BYTES,
    encode_kicad_string,
    is_round_trippable,
)
from solus.write.sexpr import TokenKind, tokenize  # isort: skip


def _decode_via_tokenizer(literal: bytes) -> str:
    """Round-trip *literal* (a full quoted-string token) back through OUR
    tokenizer, exactly as the splice guard does."""
    tokens = tokenize(literal)
    assert len(tokens) == 1
    assert tokens[0].kind == TokenKind.STRING
    return tokens[0].value or ""


# --- round trip: encode then decode gets the original value back --------------


@pytest.mark.parametrize(
    "value",
    [
        "plain",
        "",
        "STM32F030F4P6",
        'has "quotes" inside',
        "has\\backslash",
        'both \\ and "',
        "(parens) (are) (fine)",
        "Ωµ unicode ★ 漢字",
        "x" * (32 * 1024),  # 32 KiB adversarial size — well within the L3 cap
    ],
)
def test_encode_then_tokenize_round_trips_the_original_value(value: str) -> None:
    literal = encode_kicad_string(value)
    assert _decode_via_tokenizer(literal) == value


def test_encode_wraps_the_value_in_double_quotes() -> None:
    literal = encode_kicad_string("abc")
    assert literal == b'"abc"'


def test_encode_escapes_backslash_before_quote() -> None:
    literal = encode_kicad_string('a\\"b')
    assert literal == b'"a\\\\\\"b"'
    assert _decode_via_tokenizer(literal) == 'a\\"b'


def test_encode_handles_unicode_as_utf8_bytes() -> None:
    literal = encode_kicad_string("Ω")
    assert literal == '"Ω"'.encode()


# --- refusal boundary: characters that cannot be provably round-tripped -------


@pytest.mark.parametrize(
    "hostile",
    [
        "line\nbreak",
        "carriage\rreturn",
        "a\ttab",
        "\x00null",
        "\x7fdel",
        "\x1fc0-control",
        "\x85c1-control",
    ],
)
def test_control_characters_are_not_round_trippable(hostile: str) -> None:
    assert is_round_trippable(hostile) is False
    with pytest.raises(ValueError):
        encode_kicad_string(hostile)


@pytest.mark.parametrize("benign", ["plain text", "", "Ω", '"quoted"', "\\", "(parens)"])
def test_ordinary_values_are_round_trippable(benign: str) -> None:
    assert is_round_trippable(benign) is True


# --- L3: bound on spliced property value size ----------------------------------


def test_encodes_a_value_exactly_at_the_size_cap() -> None:
    # -2: the cap is on the FULL literal, quotes included.
    value = "x" * (MAX_PROPERTY_VALUE_BYTES - 2)
    literal = encode_kicad_string(value)
    assert len(literal) == MAX_PROPERTY_VALUE_BYTES
    assert _decode_via_tokenizer(literal) == value


def test_refuses_a_value_one_byte_over_the_size_cap() -> None:
    value = "x" * (MAX_PROPERTY_VALUE_BYTES - 1)  # literal would be cap + 1
    with pytest.raises(ValueError, match="unsupported"):
        encode_kicad_string(value)


def test_refuses_a_value_over_the_size_cap_measured_in_utf8_bytes() -> None:
    """The cap is on ENCODED byte length, not character count — a multibyte
    string near the cap in characters could still exceed it in bytes."""
    # "Ω" encodes to 2 UTF-8 bytes; MAX_PROPERTY_VALUE_BYTES chars of it is
    # 2x the byte cap.
    value = "Ω" * MAX_PROPERTY_VALUE_BYTES
    with pytest.raises(ValueError, match="unsupported"):
        encode_kicad_string(value)
