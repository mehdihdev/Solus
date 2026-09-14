"""Unit tests for the shared untrusted-input gates (extracted from mcp_tool)."""

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
    assert 'short-token' not in redact_text('Authorization: Bearer short-token')
    assert 'short-token' not in redact_text('authorization=Basic short-token')
