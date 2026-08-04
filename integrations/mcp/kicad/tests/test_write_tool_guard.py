"""SOLUSDEV-100 T2b — `solus/write/guard.py`: the byte-stability guard is the
last check before any disk write. Exercises both the legitimate splice path
and injected-corruption scenarios that must all refuse with guard_failed."""

import pytest

# The support module's import bootstrap (sys.path + lockfile-dep stubs) must
# run BEFORE any `solus` import — keep this line before the solus.* imports.
from test_overlay_support import SOLUS  # noqa: F401  # isort: skip

from solus.write.errors import REASON_GUARD_FAILED, RefusalError  # isort: skip
from solus.write.guard import verify_byte_stable_splice  # isort: skip

_ORIGINAL = b'(kicad_sch (symbol (lib_id "Device:R") (property "Value" "10k" (at 0 0 0))))'


def _splice(original: bytes, old_literal: bytes, new_literal: bytes) -> tuple[bytes, int, int]:
    start = original.index(old_literal)
    end = start + len(old_literal)
    spliced = original[:start] + new_literal + original[end:]
    return spliced, start, end


# --- the legitimate path: a clean single-value splice passes --------------------


def test_a_clean_single_value_splice_passes() -> None:
    spliced, start, end = _splice(_ORIGINAL, b'"10k"', b'"4.7k"')
    verify_byte_stable_splice(_ORIGINAL, spliced, start, end, "10k", "4.7k")


def test_passes_when_the_new_value_is_longer_than_the_old_one() -> None:
    spliced, start, end = _splice(_ORIGINAL, b'"10k"', b'"1000000000000k"')
    verify_byte_stable_splice(_ORIGINAL, spliced, start, end, "10k", "1000000000000k")


def test_passes_when_the_new_value_is_shorter_than_the_old_one() -> None:
    spliced, start, end = _splice(_ORIGINAL, b'"10k"', b'"1"')
    verify_byte_stable_splice(_ORIGINAL, spliced, start, end, "10k", "1")


def test_passes_with_an_escaped_new_value() -> None:
    spliced, start, end = _splice(_ORIGINAL, b'"10k"', b'"has \\"quotes\\""')
    verify_byte_stable_splice(_ORIGINAL, spliced, start, end, "10k", 'has "quotes"')


# --- injected corruption: every variant refuses with guard_failed ---------------


def test_refuses_when_a_second_token_is_also_altered() -> None:
    """Simulates a locator/splice bug that touched more than the one span:
    the guard must catch it even though the caller claims a single span."""
    spliced, start, end = _splice(_ORIGINAL, b'"10k"', b'"4.7k"')
    corrupted = spliced.replace(b"Device:R", b"Device:C", 1)
    with pytest.raises(RefusalError) as excinfo:
        verify_byte_stable_splice(_ORIGINAL, corrupted, start, end, "10k", "4.7k")
    assert excinfo.value.reason == REASON_GUARD_FAILED


def test_refuses_when_a_byte_outside_the_span_changes() -> None:
    """A change outside the claimed span must fail the prefix/suffix check
    even when the token stream happens to still line up in length."""
    spliced, start, end = _splice(_ORIGINAL, b'"10k"', b'"10k"')  # no-op splice, same length
    corrupted = bytearray(spliced)
    corrupted[0:1] = b"X"  # corrupt a byte before the span
    with pytest.raises(RefusalError) as excinfo:
        verify_byte_stable_splice(_ORIGINAL, bytes(corrupted), start, end, "10k", "10k")
    assert excinfo.value.reason == REASON_GUARD_FAILED


def test_refuses_when_token_count_changes() -> None:
    """An extra/missing paren in the spliced bytes must be caught even
    though it lands inside the claimed span."""
    spliced, start, end = _splice(_ORIGINAL, b'"10k"', b'"4.7k") (extra "oops"')
    with pytest.raises(RefusalError) as excinfo:
        verify_byte_stable_splice(_ORIGINAL, spliced, start, end, "10k", "4.7k")
    assert excinfo.value.reason == REASON_GUARD_FAILED


def test_refuses_when_the_changed_token_is_not_a_string() -> None:
    original = b"(kicad_sch (at 0 0 0))"
    spliced = original.replace(b"(at 0 0 0)", b"(at 1 0 0)")
    start, end = original.index(b"0 0 0"), original.index(b"0 0 0") + len(b"0 0 0")
    with pytest.raises(RefusalError) as excinfo:
        verify_byte_stable_splice(original, spliced, start, end, "old", "new")
    assert excinfo.value.reason == REASON_GUARD_FAILED


def test_refuses_when_the_decoded_old_value_does_not_match_the_claim() -> None:
    spliced, start, end = _splice(_ORIGINAL, b'"10k"', b'"4.7k"')
    with pytest.raises(RefusalError) as excinfo:
        verify_byte_stable_splice(_ORIGINAL, spliced, start, end, "WRONG_OLD", "4.7k")
    assert excinfo.value.reason == REASON_GUARD_FAILED


def test_refuses_when_the_decoded_new_value_does_not_match_the_claim() -> None:
    spliced, start, end = _splice(_ORIGINAL, b'"10k"', b'"4.7k"')
    with pytest.raises(RefusalError) as excinfo:
        verify_byte_stable_splice(_ORIGINAL, spliced, start, end, "10k", "WRONG_NEW")
    assert excinfo.value.reason == REASON_GUARD_FAILED


def test_refuses_when_spliced_bytes_are_unparseable() -> None:
    spliced, start, end = _splice(_ORIGINAL, b'"10k"', b'"4.7k"" extra unterminated')
    with pytest.raises(RefusalError) as excinfo:
        verify_byte_stable_splice(_ORIGINAL, spliced, start, end, "10k", "4.7k")
    assert excinfo.value.reason == REASON_GUARD_FAILED


def test_refuses_a_no_op_splice_where_the_claimed_values_are_identical_but_wrong() -> None:
    """Guards against a caller claiming a change happened when it did not —
    same bytes in and out, but old==new claimed differs from the token."""
    with pytest.raises(RefusalError) as excinfo:
        verify_byte_stable_splice(_ORIGINAL, _ORIGINAL, 0, 0, "old", "new")
    assert excinfo.value.reason == REASON_GUARD_FAILED
