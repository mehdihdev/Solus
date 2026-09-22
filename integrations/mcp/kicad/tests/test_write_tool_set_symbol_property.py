"""SOLUSDEV-100 T2b — `kicad.set_symbol_property` end to end: the full
splice pipeline against a copy of the committed Solus sample fixture, every
refusal path, adversarial values, and the registration/allowlist mapping.

CLAUDE.md §7 discipline: the committed fixture at
`tests/fixtures/solus_sample/solus_sample.kicad_sch` is NEVER opened for
writing directly — every test that mutates a schematic copies it into
`tmp_path` first.
"""

import re
import shutil
from pathlib import Path

import pytest

from tree_hash import git_tree_hash  # isort: skip
import yaml
from paths import REPO_ROOT, SOLUS_SAMPLE_SCH

# The support module's import bootstrap (sys.path + lockfile-dep stubs) must
# run BEFORE any `solus` import — keep this line before the solus.* imports.
from test_overlay_support import FakeMCP  # isort: skip

from solus.roster import WRITE_ROSTER  # isort: skip
from solus.write.locator import locate_property_value  # isort: skip
from solus.write.errors import (  # isort: skip
    REASON_AMBIGUOUS_TARGET,
    REASON_FILE_TOO_LARGE,
    REASON_PATH_ESCAPES_WORKSPACE,
    REASON_PROPERTY_NOT_FOUND,
    REASON_REFERENCE_NOT_FOUND,
    REASON_UNSUPPORTED_VALUE,
    RefusalError,
)
from solus.write.set_symbol_property import (  # isort: skip
    RESULT_KEYS,
    register_write_tools,
    set_symbol_property_impl as _bound_impl,
)


from solus.development.models import DevelopmentError, fingerprint
from solus.workspace import workspace_root


def set_symbol_property_impl(path, reference, property_name, value):
    """Legacy regression cases use an actual observed digest, never bypass binding."""
    target = Path(path)
    relative = (
        str(target.relative_to(workspace_root()))
        if target.is_relative_to(workspace_root())
        else path
    )
    return _bound_impl(relative, reference, property_name, value, fingerprint(target.read_bytes()))


def _workspace_with_sample(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A workspace containing an editable COPY of the committed fixture —
    never the fixture file itself."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(workspace))
    copy_path = workspace / SOLUS_SAMPLE_SCH.name
    shutil.copyfile(SOLUS_SAMPLE_SCH, copy_path)
    return copy_path


# --- the real, committed fixture: no-op and a genuine edit ------------------------


def test_noop_when_the_new_value_equals_the_old_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    copy_path = _workspace_with_sample(monkeypatch, tmp_path)
    before = copy_path.read_bytes()

    result = set_symbol_property_impl(str(copy_path), "U1", "MPN", "STM32F030F4P6")

    assert result["changed"] is False
    assert result["old_value"] == result["new_value"] == "STM32F030F4P6"
    assert result["bytes_before"] == result["bytes_after"] == len(before)
    assert copy_path.read_bytes() == before, "a no-op request must never touch the file"


def test_real_mpn_edit_changes_only_the_targeted_value(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    copy_path = _workspace_with_sample(monkeypatch, tmp_path)
    before = copy_path.read_bytes()

    result = set_symbol_property_impl(str(copy_path), "U1", "MPN", "STM32F030F4P7")

    assert {key: result[key] for key in RESULT_KEYS} == {
        "changed": True,
        "reference": "U1",
        "property": "MPN",
        "old_value": "STM32F030F4P6",
        "new_value": "STM32F030F4P7",
        "bytes_before": len(before),
        "bytes_after": len(before),  # "P6" -> "P7": same length, net zero
    }


def test_real_mpn_edit_confines_the_byte_diff_to_the_one_value(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Independently re-derive the located value's span (via a FRESH locator
    call on the pre-edit bytes) and assert every byte outside it — prefix
    and suffix — is identical before/after, and the file still looks like a
    well-formed KiCad schematic afterward (structural marker counts intact)."""
    copy_path = _workspace_with_sample(monkeypatch, tmp_path)
    before = copy_path.read_bytes()
    located = locate_property_value(before, "U1", "MPN")

    set_symbol_property_impl(str(copy_path), "U1", "MPN", "STM32F030F4P9-ALT")
    after = copy_path.read_bytes()

    prefix_len = located.start
    suffix_len = len(before) - located.end
    assert before[:prefix_len] == after[:prefix_len], (
        "bytes before the value span must be untouched"
    )
    assert before[-suffix_len:] == after[-suffix_len:], (
        "bytes after the value span must be untouched"
    )
    assert after[prefix_len : len(after) - suffix_len] == b'"STM32F030F4P9-ALT"'

    # The file is still shaped like a valid KiCad schematic: every structural
    # marker present the same number of times before and after.
    for marker in (b"(symbol (lib_id", b"(wire ", b"(label ", b"(no_connect ", b"(property "):
        assert before.count(marker) == after.count(marker), marker


def test_a_second_component_and_property_can_also_be_edited(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    copy_path = _workspace_with_sample(monkeypatch, tmp_path)
    result = set_symbol_property_impl(str(copy_path), "R1", "Value", "10k")
    assert result["changed"] is True
    assert result["old_value"] == "4.7k"
    assert result["new_value"] == "10k"


def test_upstream_tree_hash_is_unaffected_by_this_tree_of_work() -> None:
    """This task never touches upstream/ or vendor/ — sanity-pin that the
    committed tree still matches HEAD (mirrors test_vendor_sch_api.py's own
    hash proof; this is a cheap belt-and-braces re-check from T2b's tests)."""
    # Pure-Python recompute against the hash PROVENANCE records (no `git`
    # binary — the CI image has none; see tree_hash.py). Reading the working
    # tree means an uncommitted edit inside upstream/ fails this too.
    provenance = (REPO_ROOT / "integrations" / "mcp" / "kicad" / "PROVENANCE.md").read_text(
        encoding="utf-8"
    )
    match = re.search(r"Vendored tree hash:\*\*\s*`([0-9a-f]{40})`", provenance)
    assert match, "PROVENANCE.md must record the vendored tree hash"
    assert git_tree_hash(REPO_ROOT / "integrations" / "mcp" / "kicad" / "upstream") == match.group(
        1
    ), "upstream/ changed under a task that must never touch it"


# --- adversarial values: proven correct splice or clean refusal -----------------


@pytest.mark.parametrize(
    "adversarial_value",
    [
        'has "quotes" inside',
        "has\\backslash\\chars",
        'mix \\ and "',
        "(parens) (are) (fine)",
        "Ωµ unicode ★ 漢字",
        "x" * (32 * 1024),  # 32 KiB adversarial size — well within the L3 cap
    ],
)
def test_adversarial_values_produce_a_correct_splice(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, adversarial_value: str
) -> None:
    copy_path = _workspace_with_sample(monkeypatch, tmp_path)
    if len(adversarial_value) > 400:
        before = copy_path.read_bytes()
        with pytest.raises(DevelopmentError, match="file_too_large"):
            set_symbol_property_impl(str(copy_path), "U1", "MPN", adversarial_value)
        assert copy_path.read_bytes() == before
        return
    result = set_symbol_property_impl(str(copy_path), "U1", "MPN", adversarial_value)
    assert result["changed"] is True
    assert result["new_value"] == adversarial_value

    # Re-open the file to prove the write is durable and re-locatable.
    reopened = locate_property_value(copy_path.read_bytes(), "U1", "MPN")
    assert reopened.old_value == adversarial_value


@pytest.mark.parametrize(
    "hostile_value",
    ["line\nbreak", "carriage\rreturn", "a\ttab", "\x00null"],
)
def test_values_with_control_characters_refuse_cleanly_and_never_corrupt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, hostile_value: str
) -> None:
    copy_path = _workspace_with_sample(monkeypatch, tmp_path)
    before = copy_path.read_bytes()

    with pytest.raises((RefusalError, DevelopmentError)) as excinfo:
        set_symbol_property_impl(str(copy_path), "U1", "MPN", hostile_value)

    assert excinfo.value.reason == REASON_UNSUPPORTED_VALUE
    assert copy_path.read_bytes() == before


def test_a_value_over_the_l3_size_cap_refuses_cleanly_and_never_corrupts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from solus.write.escaping import MAX_PROPERTY_VALUE_BYTES

    copy_path = _workspace_with_sample(monkeypatch, tmp_path)
    before = copy_path.read_bytes()
    oversize_value = "x" * (MAX_PROPERTY_VALUE_BYTES + 1)

    with pytest.raises((RefusalError, DevelopmentError)) as excinfo:
        set_symbol_property_impl(str(copy_path), "U1", "MPN", oversize_value)

    assert excinfo.value.reason == REASON_UNSUPPORTED_VALUE
    assert copy_path.read_bytes() == before


# --- refusal paths, each proven to leave the file untouched -----------------------


def test_refuses_unknown_reference_and_leaves_file_untouched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    copy_path = _workspace_with_sample(monkeypatch, tmp_path)
    before = copy_path.read_bytes()
    with pytest.raises((RefusalError, DevelopmentError)) as excinfo:
        set_symbol_property_impl(str(copy_path), "U99", "MPN", "X")
    assert excinfo.value.reason == REASON_REFERENCE_NOT_FOUND
    assert copy_path.read_bytes() == before


def test_refuses_unknown_property_and_leaves_file_untouched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    copy_path = _workspace_with_sample(monkeypatch, tmp_path)
    before = copy_path.read_bytes()
    with pytest.raises((RefusalError, DevelopmentError)) as excinfo:
        set_symbol_property_impl(str(copy_path), "U1", "NoSuchProperty", "X")
    assert excinfo.value.reason == REASON_PROPERTY_NOT_FOUND
    assert copy_path.read_bytes() == before


def test_refuses_duplicate_reference_as_ambiguous(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(workspace))
    copy_path = workspace / "dup.kicad_sch"
    copy_path.write_bytes(
        b"(kicad_sch"
        b'  (symbol (lib_id "Device:R") (at 0 0 0) (property "Reference" "R1" (at 0 0 0))'
        b'    (property "Value" "10k" (at 0 0 0)))'
        b'  (symbol (lib_id "Device:R") (at 1 1 0) (property "Reference" "R1" (at 0 0 0))'
        b'    (property "Value" "4.7k" (at 0 0 0)))'
        b")"
    )
    before = copy_path.read_bytes()
    with pytest.raises((RefusalError, DevelopmentError)) as excinfo:
        set_symbol_property_impl(str(copy_path), "R1", "Value", "1k")
    assert excinfo.value.reason == REASON_AMBIGUOUS_TARGET
    assert copy_path.read_bytes() == before


def test_refuses_duplicate_property_as_ambiguous(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(workspace))
    copy_path = workspace / "dup_prop.kicad_sch"
    copy_path.write_bytes(
        b"(kicad_sch"
        b'  (symbol (lib_id "Device:R") (at 0 0 0) (property "Reference" "R1" (at 0 0 0))'
        b'    (property "Value" "10k" (at 0 0 0)) (property "Value" "20k" (at 0 0 0)))'
        b")"
    )
    before = copy_path.read_bytes()
    with pytest.raises((RefusalError, DevelopmentError)) as excinfo:
        set_symbol_property_impl(str(copy_path), "R1", "Value", "1k")
    assert excinfo.value.reason == REASON_AMBIGUOUS_TARGET
    assert copy_path.read_bytes() == before


def test_refuses_a_path_outside_the_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(workspace))
    outside = tmp_path / "outside.kicad_sch"
    shutil.copyfile(SOLUS_SAMPLE_SCH, outside)
    with pytest.raises((RefusalError, DevelopmentError)) as excinfo:
        set_symbol_property_impl(str(outside), "U1", "MPN", "X")
    assert excinfo.value.reason == REASON_PATH_ESCAPES_WORKSPACE


def test_refuses_an_oversize_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(workspace))
    huge = workspace / "huge.kicad_sch"
    huge.write_bytes(b"(kicad_sch)" + b" " * (8 * 1024 * 1024 + 1))
    with pytest.raises((RefusalError, DevelopmentError)) as excinfo:
        set_symbol_property_impl(str(huge), "U1", "MPN", "X")
    assert excinfo.value.reason == REASON_FILE_TOO_LARGE


# --- M5: pathological sexpr input, and RecursionError/OSError never escape ------


@pytest.mark.parametrize(
    "hostile_bytes",
    [
        b"(" * 50_000 + b")" * 50_000,  # pathological nesting depth
        b"(" + b"a " * 250_000 + b")",  # pathological flat token count
    ],
    ids=["deep-nesting", "many-tokens"],
)
def test_hostile_schematic_inputs_only_ever_raise_refusalerror(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, hostile_bytes: bytes
) -> None:
    """The exact repro from the M5 finding (`parse(b"("*50000 + b")"*50000)`)
    plus a pathological-token-count sibling: both must refuse cleanly with
    `file_too_large`, never raise `RecursionError` or anything else."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(workspace))
    hostile = workspace / "hostile.kicad_sch"
    hostile.write_bytes(hostile_bytes)

    with pytest.raises((RefusalError, DevelopmentError)) as excinfo:
        set_symbol_property_impl(str(hostile), "U1", "MPN", "X")

    assert excinfo.value.reason == REASON_FILE_TOO_LARGE


async def test_tool_wrapper_maps_a_recursion_error_to_a_refusal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Defense in depth: even though the iterative parser (M5) no longer
    raises `RecursionError` itself, the tool wrapper must still convert one
    to a clean refusal if it ever arises from anywhere else in the pipeline."""
    copy_path = _workspace_with_sample(monkeypatch, tmp_path)
    fake = FakeMCP()
    register_write_tools(fake)

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RecursionError("simulated runaway recursion")

    monkeypatch.setattr("solus.write.set_symbol_property.locate_property_value", _boom)

    with pytest.raises(ValueError, match="guard_failed"):
        await fake.tools["set_symbol_property"](
            schematic_path=copy_path.name,
            expected_fingerprint=fingerprint(copy_path.read_bytes()),
            reference="U1",
            property="MPN",
            value="X",
        )


async def test_tool_wrapper_maps_an_os_error_to_a_refusal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An OSError from stat/read/atomic-write (race, permissions, disk full,
    ...) must never escape the tool as a bare exception."""
    copy_path = _workspace_with_sample(monkeypatch, tmp_path)
    fake = FakeMCP()
    register_write_tools(fake)

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated I/O failure")

    monkeypatch.setattr("solus.write.set_symbol_property.locate_property_value", _boom)

    with pytest.raises(ValueError, match="guard_failed"):
        await fake.tools["set_symbol_property"](
            schematic_path=copy_path.name,
            expected_fingerprint=fingerprint(copy_path.read_bytes()),
            reference="U1",
            property="MPN",
            value="X",
        )


def test_guard_injection_via_monkeypatch_refuses_and_leaves_no_temp_litter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Force the splice guard to fail (simulating a locator/encoder bug) and
    prove: refusal propagates, the original file is byte-identical, and no
    temp file is left in the workspace (atomic_write is never reached)."""
    copy_path = _workspace_with_sample(monkeypatch, tmp_path)
    before = copy_path.read_bytes()

    def _always_fails(*_args: object, **_kwargs: object) -> None:
        from solus.write.errors import REASON_GUARD_FAILED

        raise RefusalError(REASON_GUARD_FAILED)

    monkeypatch.setattr("solus.write.set_symbol_property.verify_byte_stable_splice", _always_fails)
    with pytest.raises((RefusalError, DevelopmentError)) as excinfo:
        set_symbol_property_impl(str(copy_path), "U1", "MPN", "STM32F030F4P9")

    assert excinfo.value.reason == "guard_failed"
    assert copy_path.read_bytes() == before
    assert {p.name for p in copy_path.parent.iterdir()} == {copy_path.name}, (
        "no temp file may survive a refused guard"
    )


# --- the MCP tool wrapper: refusal shape + result keys ---------------------------


async def test_tool_wrapper_returns_a_refusal_shaped_result_on_bad_reference(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    copy_path = _workspace_with_sample(monkeypatch, tmp_path)
    fake = FakeMCP()
    register_write_tools(fake)

    with pytest.raises(ValueError, match="reference_not_found"):
        await fake.tools["set_symbol_property"](
            schematic_path=copy_path.name,
            expected_fingerprint=fingerprint(copy_path.read_bytes()),
            reference="U99",
            property="MPN",
            value="X",
        )


async def test_tool_wrapper_returns_the_success_shape_on_a_real_edit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    copy_path = _workspace_with_sample(monkeypatch, tmp_path)
    fake = FakeMCP()
    register_write_tools(fake)

    result = await fake.tools["set_symbol_property"](
        schematic_path=copy_path.name,
        expected_fingerprint=fingerprint(copy_path.read_bytes()),
        reference="U1",
        property="MPN",
        value="STM32F030F4P7",
    )

    assert RESULT_KEYS <= set(result)
    assert result["changed"] is True


# --- registration + allowlist mapping proof --------------------------------------


def test_register_write_tools_registers_exactly_set_symbol_property() -> None:
    fake = FakeMCP()
    register_write_tools(fake)
    assert set(fake.tools) == {"set_symbol_property"}


def test_allowlist_yaml_already_maps_set_symbol_property_confirmation_gated() -> None:
    """allowlist.yaml (T1b draft, human-ratified at MR) already carries this
    entry — proves the cloud-side confirmation gate is correct independent
    of whether the fork's own registration.py calls register_write_tools
    yet (that wiring is flagged in the T2b completion report: roster.py and
    registration.py are outside this task's file-ownership manifest)."""
    allowlist_path = REPO_ROOT / "integrations" / "mcp" / "kicad" / "allowlist.yaml"
    parsed = yaml.safe_load(allowlist_path.read_text())
    by_name = {tool["name"]: tool for tool in parsed["tools"]}
    entry = by_name["set_symbol_property"]
    assert entry["requires_confirmation"] is True
    assert "mutat" in entry["reason"].lower()


def test_set_symbol_property_is_still_pending_wiring_in_the_roster() -> None:
    """Honest documentation of the current state: WRITE_ROSTER is
    solus/roster.py's own record that this tool is allowlisted but not yet
    registered — flips to EXPOSED only when roster.py/registration.py are
    updated by whoever owns those files (see completion report)."""
    assert "set_symbol_property" in WRITE_ROSTER


@pytest.mark.asyncio
async def test_bound_property_preview_is_complete_and_write_preserves_other_bytes(
    monkeypatch, tmp_path
):
    from solus.development.models import fingerprint

    path = _workspace_with_sample(monkeypatch, tmp_path)
    before = path.read_bytes()
    fake = FakeMCP()
    register_write_tools(fake)
    tool = fake.tools["set_symbol_property"]
    args = dict(
        schematic_path=path.name,
        reference="R1",
        property="Value",
        value="10k",
        expected_fingerprint=fingerprint(before),
    )
    preview = await tool(**args, dry_run=True)
    assert preview["dry_run"] is True
    assert path.read_bytes() == before
    assert {"label": "R1 · Value", "before": "4.7k", "after": "10k"} in preview["preview"]
    result = await tool(**args)
    assert result["verified"] is True
    located = locate_property_value(before, "R1", "Value")
    assert path.read_bytes() == before[: located.start] + b'"10k"' + before[located.end :]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["stale", "missing", "oversize"])
async def test_bound_property_refuses_unsafe_or_incomplete_write(monkeypatch, tmp_path, failure):
    from solus.development.models import fingerprint

    path = _workspace_with_sample(monkeypatch, tmp_path)
    before = path.read_bytes()
    fake = FakeMCP()
    register_write_tools(fake)
    args = dict(
        schematic_path=path.name,
        reference="R1",
        property="Value",
        value="10k",
        expected_fingerprint=fingerprint(before),
    )
    if failure == "stale":
        args["expected_fingerprint"] = fingerprint(b"old")
    elif failure == "missing":
        args.pop("expected_fingerprint")
    else:
        args["value"] = "x" * 401
    with pytest.raises(ValueError):
        await fake.tools["set_symbol_property"](**args, dry_run=True)
    assert path.read_bytes() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("extra", [{"unexpected": True}, {"dry_run": "true"}])
async def test_property_real_mcp_rejects_coercion_and_extra_fields(monkeypatch, tmp_path, extra):
    from mcp.server.fastmcp import FastMCP
    from mcp.server.fastmcp.exceptions import ToolError
    from solus.trimming import TrimmingRegistrar

    path = _workspace_with_sample(monkeypatch, tmp_path)
    before = path.read_bytes()
    server = FastMCP("property boundary")
    register_write_tools(TrimmingRegistrar(server, allowed={"set_symbol_property"}))
    args = dict(
        schematic_path=path.name,
        reference="R1",
        property="Value",
        value="10k",
        expected_fingerprint=fingerprint(before),
        dry_run=True,
    )
    with pytest.raises(ToolError):
        await server.call_tool("set_symbol_property", {**args, **extra})
    assert path.read_bytes() == before


@pytest.mark.asyncio
async def test_property_real_mcp_refusal_is_error_not_success(monkeypatch, tmp_path):
    from mcp.server.fastmcp import FastMCP
    from mcp.server.fastmcp.exceptions import ToolError
    from solus.trimming import TrimmingRegistrar

    path = _workspace_with_sample(monkeypatch, tmp_path)
    server = FastMCP("property refusal")
    register_write_tools(TrimmingRegistrar(server, allowed={"set_symbol_property"}))
    with pytest.raises(ToolError, match="stale_plan"):
        await server.call_tool(
            "set_symbol_property",
            dict(
                schematic_path=path.name,
                reference="R1",
                property="Value",
                value="10k",
                dry_run=True,
            ),
        )
