"""SOLUSDEV-251: private hardware paths/hints share one strict TS/Python contract."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from solus_contracts.hardware_local_state import HardwareLocalState

ACCOUNT = "00000000-0000-4000-8000-000000000001"
SOURCE = "00000000-0000-4000-8000-000000000002"
CONFIG = "00000000-0000-4000-8000-000000000003"
FIXTURE = (
    Path(__file__).resolve().parents[2] / "shared-types/fixtures/hardware-local-state/valid.json"
)


def _with_source(**overrides: object) -> dict[str, object]:
    source = {"path": "/workspace/config.json", "contentSha256": "a" * 64, **overrides}
    return {
        "schema_version": 1,
        "accounts": {ACCOUNT: {"sources": {SOURCE: source}, "bindings": {}}},
    }


def test_shared_fixture_round_trip() -> None:
    raw = json.loads(FIXTURE.read_text())
    result = HardwareLocalState.model_validate(raw)
    assert result.model_dump(mode="json", by_alias=True, exclude_none=True) == raw


def test_equivalent_json_integer_encodings() -> None:
    HardwareLocalState.model_validate_json('{"schema_version":1.0,"accounts":{}}')


@pytest.mark.parametrize("hint", [None, "", "\u0085", "\ud800"])
def test_null_empty_control_or_surrogate_hint_rejected(hint: object) -> None:
    with pytest.raises(ValidationError):
        HardwareLocalState.model_validate(
            {
                "schema_version": 1,
                "accounts": {
                    ACCOUNT: {"sources": {}, "bindings": {CONFIG: {"lastSeenPath": hint}}}
                },
            }
        )


def test_map_bounds_and_newline_suffixes() -> None:
    for map_name in ("sources", "bindings"):
        entry = (
            {"path": "/workspace/config.json", "contentSha256": "a" * 64}
            if map_name == "sources"
            else {}
        )
        account: dict[str, dict[str, object]] = {"sources": {}, "bindings": {}}
        account[map_name] = {f"00000000-0000-4000-8000-{i:012d}": entry for i in range(257)}
        with pytest.raises(ValidationError):
            HardwareLocalState.model_validate({"schema_version": 1, "accounts": {ACCOUNT: account}})
    with pytest.raises(ValidationError):
        HardwareLocalState.model_validate(
            {"schema_version": 1, "accounts": {ACCOUNT + "\n": {"sources": {}, "bindings": {}}}}
        )
    with pytest.raises(ValidationError):
        HardwareLocalState.model_validate(_with_source(contentSha256="a" * 64 + "\n"))


@pytest.mark.parametrize("path", ["/workspace/config.json", "C:\\work\\config.json"])
def test_absolute_paths_are_host_independent(path: str) -> None:
    HardwareLocalState.model_validate(_with_source(path=path))


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        {},
        {"schema_version": True, "accounts": {}},
        {"schema_version": 0, "accounts": {}},
        {"schema_version": 2, "accounts": {}},
        {"schema_version": 1, "accounts": {}, "extra": True},
        {"schema_version": 1, "accounts": {"../other": {"sources": {}, "bindings": {}}}},
        _with_source(path="relative/config.json"),
        _with_source(path="/workspace/unsafe\x00.json"),
        _with_source(path="/" + "x" * 4096),
        _with_source(path=12),
        _with_source(contentSha256="A" * 64),
        _with_source(contentSha256="a" * 63),
        _with_source(credentials="not-allowed"),
        {
            "schema_version": 1,
            "accounts": {ACCOUNT: {"sources": {}, "bindings": {CONFIG: {"confirmed": True}}}},
        },
    ],
)
def test_rejects_invalid_input(value: object) -> None:
    with pytest.raises(ValidationError):
        HardwareLocalState.model_validate(value)


def test_account_map_and_document_size_are_bounded() -> None:
    accounts: dict[str, dict[str, dict[str, object]]] = {
        f"00000000-0000-4000-8000-{i:012d}": {"sources": {}, "bindings": {}} for i in range(17)
    }
    with pytest.raises(ValidationError):
        HardwareLocalState.model_validate({"schema_version": 1, "accounts": accounts})
    sources = {
        f"00000000-0000-4000-8000-{i:012d}": {"path": "/" + "é" * 2048, "contentSha256": "a" * 64}
        for i in range(100)
    }
    with pytest.raises(ValidationError):
        HardwareLocalState.model_validate(
            {"schema_version": 1, "accounts": {ACCOUNT: {"sources": sources, "bindings": {}}}}
        )
