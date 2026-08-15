"""The Python half of the LB-06 cross-runtime drift gate (SOLUSDEV-126).

The checked-in fixture corpus is what the TypeScript decoder tests against. If the packet model
or the codec changes and the corpus is not regenerated, the two runtimes have silently drifted —
so this test fails loudly and tells you the one command that fixes it.
"""

from pathlib import Path

import pytest
from solus_api.graph.codec import PacketDecodeError, decode, decode_json
from solus_api.graph.packet import SCHEMA_VERSION
from telemetry_corpus import CORPUS, FIXTURE_DIR, HOSTILE, LIMITS, build_files

_REGENERATE = "cd packages/api && uv run python tests/telemetry_corpus.py"


def test_every_fixture_file_is_checked_in() -> None:
    missing = [name for name in build_files() if not (FIXTURE_DIR / name).exists()]
    assert not missing, f"missing fixtures {missing} — regenerate: {_REGENERATE}"


@pytest.mark.parametrize("name", sorted(build_files()))
def test_checked_in_fixture_matches_the_current_model(name: str) -> None:
    """Byte-for-byte. Changing the packet without regenerating fails HERE, in Python, rather
    than as a mystery in the TypeScript suite."""
    on_disk = (FIXTURE_DIR / name).read_bytes()
    assert on_disk == build_files()[name], f"{name} is stale — regenerate: {_REGENERATE}"


@pytest.mark.parametrize("name", sorted(CORPUS))
def test_fixtures_round_trip_through_both_encodings(name: str) -> None:
    expected = CORPUS[name]
    assert decode((FIXTURE_DIR / f"{name}.msgpack").read_bytes()) == expected
    assert decode_json((FIXTURE_DIR / f"{name}.json").read_bytes()) == expected


def test_future_fixture_decodes_on_this_build() -> None:
    """The forward-compatibility fixture the TS suite also reads: a newer producer's packet,
    decoded by a decoder that predates it."""
    for suffix in ("msgpack", "json"):
        raw = (FIXTURE_DIR / f"future.{suffix}").read_bytes()
        packet = decode(raw) if suffix == "msgpack" else decode_json(raw)
        assert packet.schema_version == SCHEMA_VERSION + 1
        assert packet.values == CORPUS["full"].values
        assert packet.units == CORPUS["full"].units


@pytest.mark.parametrize("name", sorted(HOSTILE))
def test_hostile_fixtures_are_rejected(name: str) -> None:
    """The parity that matters for security: every payload here must be refused by BOTH runtimes.
    The happy-path corpus cannot catch a case Python rejects and TypeScript quietly accepts —
    exactly the drift that produced the `toString` unit and `ts_us: 1e300` bugs."""
    raw = (FIXTURE_DIR / f"hostile.{name}.msgpack").read_bytes()
    with pytest.raises(PacketDecodeError):
        decode(raw)


def test_limits_file_reflects_the_python_constants() -> None:
    """`limits.json` is how the TypeScript decoder learns the bounds without hand-copying them."""
    import json

    assert json.loads((FIXTURE_DIR / "limits.json").read_text()) == LIMITS


def test_fixture_dir_has_no_orphans() -> None:
    """A renamed case must not leave its old files behind for the TS suite to read forever."""
    on_disk = {p.name for p in Path(FIXTURE_DIR).iterdir() if p.is_file()}
    assert on_disk == set(build_files()), f"orphaned fixtures — regenerate: {_REGENERATE}"
