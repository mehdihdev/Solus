"""Unit tests for the shared untrusted-input gates (extracted from mcp_tool)."""

from solus_api.agent.tools.untrusted import (
    SAFE_REMOTE_NAME,
    SCHEMA_BYTES_CAP,
    UNTRUSTED_TEXT_CAP,
    contains_ref,
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
