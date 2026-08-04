"""KiCad string escaping for values `set_symbol_property` writes (T2b).

Only backslash and double-quote need escaping to sit inside a KiCad
S-expression string literal (mirrors `sexpr.py::_decode_escapes`, the read
side). Values containing a character this module cannot PROVABLY round-trip
— any C0/C1 control character (raw newlines, tabs, carriage returns, NUL,
...) — are refused outright rather than risk writing a file KiCad itself
cannot re-open. Printable Unicode, quotes, backslashes, and raw parentheses
are all safe: none of them need special handling beyond the two escapes.

L3: a spliced value has no upper bound otherwise — `MAX_PROPERTY_VALUE_BYTES`
caps the ENCODED (UTF-8, post-escaping) size, refused as `unsupported_value`
(the same reason a non-round-trippable character gets) rather than minting a
new reason for what is, from the caller's perspective, the same "we will not
write this value" refusal.
"""

# C0 controls (0x00-0x1F) plus DEL (0x7F) plus C1 controls (0x80-0x9F).
_UNSUPPORTED_CODEPOINTS = frozenset({*range(0x00, 0x20), 0x7F, *range(0x80, 0xA0)})

# 64 KiB: a KiCad symbol property value (Reference, Value, MPN, ...) is a
# short field in practice — a few dozen to a few hundred bytes. 64 KiB is
# generous headroom over any legitimate use while bounding the worst-case
# splice size a single confirmed write can inject into a schematic file.
MAX_PROPERTY_VALUE_BYTES = 64 * 1024


def is_round_trippable(value: str) -> bool:
    """Whether *value* contains only characters this escaper can provably
    write and later read back byte-for-byte identical."""
    return not any(ord(char) in _UNSUPPORTED_CODEPOINTS for char in value)


def encode_kicad_string(value: str) -> bytes:
    """The full quoted-string literal (including surrounding quotes), ready
    to splice into KiCad S-expression bytes.

    Raises `ValueError` — never silently corrupts — if *value* is not
    `is_round_trippable`, or if its encoded size exceeds
    `MAX_PROPERTY_VALUE_BYTES` (L3).
    """
    if not is_round_trippable(value):
        raise ValueError(f"value contains a character that cannot be round-tripped: {value!r}")
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    encoded = f'"{escaped}"'.encode()
    if len(encoded) > MAX_PROPERTY_VALUE_BYTES:
        raise ValueError(
            f"unsupported value: encoded size {len(encoded)} bytes exceeds the "
            f"{MAX_PROPERTY_VALUE_BYTES}-byte cap"
        )
    return encoded
