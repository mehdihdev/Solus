"""SOLUSDEV-102 ALT-7 — the confirmation-gated write tools register through
the hardened wrapper, with data-driven write guards refusing BEFORE the tool
body: oversize parameter values (> 4 KiB), shape-violating parameter names
(wire-format metacharacters, control chars, unbounded length), and unbounded
stamp batches. The cloud side keeps both tools `requires_confirmation: true`
(allowlist.yaml — human-ratified); these guards are the fork-side depth
behind that gate, not a substitute for it.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

# The bootstrap module must run before any overlay/upstream import — keep the
# support import first (it installs sys.path + the lockfile-dep stubs).
from .test_overlay_support import (  # isort: skip
    FakeMCP,
    call_tool,
    register_overlay,
)
from .altium_paths import FORK_DIR, overlay_module

_roster = overlay_module("roster")
_trimming = overlay_module("trimming")

WRITE_ROSTER: frozenset[str] = _roster.WRITE_ROSTER
REASON_WRITE_GUARD_REFUSED: str = _trimming.REASON_WRITE_GUARD_REFUSED
VALUE_MAX = int(_trimming.PARAMETER_VALUE_MAX_BYTES)
NAME_MAX = int(_trimming.PARAMETER_NAME_MAX_CHARS)
STAMPS_MAX = int(_trimming.STAMPS_MAX_COUNT)


class RecordingBridge:
    """Records every IPC command a write-tool body would send."""

    def __init__(self) -> None:
        self.commands: list[tuple[str, dict[str, Any]]] = []

    async def send_command_async(
        self, command: str, params: dict[str, Any] | None = None, timeout: float | None = None
    ) -> dict[str, Any]:
        self.commands.append((command, dict(params or {})))
        return {"ok": True}


def write_tool_setup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[dict[str, Any], RecordingBridge, Path]:
    """Register the real overlay with the workspace pinned and BOTH write
    modules' bridge seams routed at one recorder."""
    import eda_agent.tools.generic as generic_module
    import eda_agent.tools.project as project_module

    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(workspace))
    bridge = RecordingBridge()
    monkeypatch.setattr(project_module, "get_bridge", lambda: bridge)
    monkeypatch.setattr(generic_module, "get_bridge", lambda: bridge)
    fake = FakeMCP()
    register_overlay(fake)
    return fake.tools, bridge, workspace


# --- registration outcome: ALT-7 completes the roster ----------------------------


def test_the_full_roster_is_now_registered_and_nothing_is_pending() -> None:
    assert _roster.PENDING_TOOLS == frozenset()
    assert _roster.registered_roster() == _roster.FULL_ROSTER


def test_both_write_tools_are_registered_through_the_registrar() -> None:
    fake = FakeMCP()
    registrar = register_overlay(fake)
    for name in sorted(WRITE_ROSTER):
        assert name in fake.tools, f"{name} must be registered after ALT-7"
        assert name in registrar.registered
    assert set(fake.tools) == set(_roster.FULL_ROSTER)


def test_allowlist_still_pins_both_writes_confirmation_gated() -> None:
    data = yaml.safe_load((FORK_DIR / "allowlist.yaml").read_text())
    gated = {tool["name"] for tool in data["tools"] if tool.get("requires_confirmation")}
    assert gated == set(WRITE_ROSTER)


def test_write_guards_cover_exactly_the_write_roster() -> None:
    """Data-driven, not per-tool code: the guard table's keys are the write
    roster — a new write tool cannot register guardless without failing
    here."""
    assert set(_trimming.WRITE_GUARDS) == set(WRITE_ROSTER)


# --- proj_set_parameter guards ---------------------------------------------------


async def test_oversize_parameter_value_is_refused_before_the_body(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tools, bridge, _ = write_tool_setup(monkeypatch, tmp_path)

    result = await call_tool(
        tools["proj_set_parameter"], name="Description", value="A" * (VALUE_MAX + 1)
    )

    assert result["reason"] == REASON_WRITE_GUARD_REFUSED
    assert bridge.commands == [], "the tool body must never run on a refused value"


async def test_boundary_parameter_value_reaches_the_bridge(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tools, bridge, _ = write_tool_setup(monkeypatch, tmp_path)

    result = await call_tool(tools["proj_set_parameter"], name="Description", value="A" * VALUE_MAX)

    assert result == {"ok": True}
    assert [command for command, _ in bridge.commands] == ["project.set_parameter"]
    assert bridge.commands[0][1]["name"] == "Description"


async def test_multibyte_value_is_bounded_by_bytes_not_characters(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tools, bridge, _ = write_tool_setup(monkeypatch, tmp_path)

    result = await call_tool(
        tools["proj_set_parameter"],
        name="Description",
        value="é" * ((VALUE_MAX // 2) + 1),  # 2 bytes each in UTF-8
    )

    assert result["reason"] == REASON_WRITE_GUARD_REFUSED
    assert bridge.commands == []


@pytest.mark.parametrize(
    "hostile_name",
    [
        "evil\nname",  # control character
        "name=inject",  # wire key/value metacharacter
        "a;b",  # wire field separator
        "x~~y",  # wire stamp separator
        "",  # empty
        "A" * 65,  # over the length bound
        123,  # not a string at all
    ],
)
async def test_hostile_parameter_name_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, hostile_name: Any
) -> None:
    tools, bridge, _ = write_tool_setup(monkeypatch, tmp_path)

    result = await call_tool(tools["proj_set_parameter"], name=hostile_name, value="v")

    assert result["reason"] == REASON_WRITE_GUARD_REFUSED
    assert bridge.commands == []


@pytest.mark.parametrize("benign_name", ["Revision", "Part Number", "Solus.SyncId", "MPN_2"])
async def test_benign_parameter_names_pass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, benign_name: str
) -> None:
    tools, bridge, _ = write_tool_setup(monkeypatch, tmp_path)

    result = await call_tool(tools["proj_set_parameter"], name=benign_name, value="v")

    assert result == {"ok": True}
    assert len(bridge.commands) == 1


async def test_project_path_confinement_still_applies_to_the_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tools, bridge, _ = write_tool_setup(monkeypatch, tmp_path)

    result = await call_tool(
        tools["proj_set_parameter"],
        name="Revision",
        value="B",
        project_path=str(tmp_path / "other-team" / "board.PrjPcb"),
    )

    assert result["reason"] == "path_escapes_workspace"
    assert bridge.commands == []


# --- sch_set_components_parameters guards ----------------------------------------


async def test_valid_stamps_reach_the_bridge(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tools, bridge, _ = write_tool_setup(monkeypatch, tmp_path)

    result = await call_tool(
        tools["sch_set_components_parameters"],
        stamps=[
            {"designator": "R1", "Value": "10k", "MPN": "RC0603FR-0710KL"},
            {"designator": "C5", "Value": "100nF"},
        ],
    )

    assert result == {"ok": True}
    assert [command for command, _ in bridge.commands] == ["generic.set_sch_components_parameters"]


@pytest.mark.parametrize(
    "hostile_stamps",
    [
        "not a list",
        [{"designator": "R1", "Value": 42}],  # non-string value
        [{"designator": "R1", "Val\nue": "10k"}],  # control char in key
        [{"designator": "R1", "k=v;x": "10k"}],  # wire metacharacters in key
        [["designator", "R1"]],  # stamp is not an object
    ],
)
async def test_hostile_stamps_are_refused_before_the_body(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, hostile_stamps: Any
) -> None:
    tools, bridge, _ = write_tool_setup(monkeypatch, tmp_path)

    result = await call_tool(tools["sch_set_components_parameters"], stamps=hostile_stamps)

    assert result["reason"] == REASON_WRITE_GUARD_REFUSED
    assert bridge.commands == []


async def test_oversize_stamp_value_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tools, bridge, _ = write_tool_setup(monkeypatch, tmp_path)

    result = await call_tool(
        tools["sch_set_components_parameters"],
        stamps=[{"designator": "R1", "Value": "A" * (VALUE_MAX + 1)}],
    )

    assert result["reason"] == REASON_WRITE_GUARD_REFUSED
    assert bridge.commands == []


async def test_unbounded_stamp_batches_are_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tools, bridge, _ = write_tool_setup(monkeypatch, tmp_path)

    stamps = [{"designator": f"R{index}", "Value": "1k"} for index in range(STAMPS_MAX + 1)]
    result = await call_tool(tools["sch_set_components_parameters"], stamps=stamps)

    assert result["reason"] == REASON_WRITE_GUARD_REFUSED
    assert bridge.commands == []


async def test_sheet_path_confinement_still_applies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tools, bridge, _ = write_tool_setup(monkeypatch, tmp_path)

    result = await call_tool(
        tools["sch_set_components_parameters"],
        stamps=[{"designator": "R1", "Value": "10k"}],
        sheet_path=str(tmp_path / "outside.SchDoc"),
    )

    assert result["reason"] == "path_escapes_workspace"
    assert bridge.commands == []


# --- the harvest stays surgical ---------------------------------------------------


def test_generic_modules_other_tools_stay_dead_and_off_the_audit_trail() -> None:
    """sch_set_components_parameters is harvested out of upstream's
    tools/generic.py by closure capture; the module's OTHER tools
    (obj_run_process, the object mutators) must neither register nor even
    appear on the registrar's blocked audit trail."""
    fake = FakeMCP()
    registrar = register_overlay(fake)
    seen = set(registrar.registered) | set(registrar.blocked)
    for name in ("obj_run_process", "obj_delete", "proj_run_erc"):
        assert name not in fake.tools
        assert name not in seen, f"{name} reached the registrar via the harvest"


# --- H4: model-controllable timeout + unbounded limit wedge the bridge ------------


def test_proj_get_component_info_timeout_is_pinned_none() -> None:
    """Upstream forwards `timeout` verbatim to send_command_async, whose
    commands all serialize through one bridge worker; a model-chosen timeout
    wedges that single worker. Pinned None → the bridge's own default."""
    assert dict(_trimming.PINNED_PARAMETERS)["proj_get_component_info"] == {"timeout": None}


def test_proj_get_component_info_advertised_schema_lacks_timeout() -> None:
    fake = FakeMCP()
    register_overlay(fake)
    import inspect

    wrapper = fake.tools["proj_get_component_info"]
    assert "timeout" not in inspect.signature(wrapper).parameters
    assert "timeout" not in getattr(wrapper, "__annotations__", {})


def test_numeric_bounds_cover_the_two_limit_bearing_reads() -> None:
    """Data-driven, not per-tool code: proj_get_nets and proj_get_bom carry a
    `limit` forwarded unbounded to the bridge; both are bounded here."""
    bounds = dict(_trimming.NUMERIC_BOUNDS)
    assert bounds["proj_get_nets"] == {"limit": 100_000}
    assert bounds["proj_get_bom"] == {"limit": 20_000}


@pytest.mark.parametrize(
    ("tool_name", "cap"),
    [("proj_get_nets", 100_000), ("proj_get_bom", 20_000)],
)
async def test_over_cap_limit_is_refused_before_the_body(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tool_name: str, cap: int
) -> None:
    tools, bridge, _ = write_tool_setup(monkeypatch, tmp_path)

    result = await call_tool(tools[tool_name], limit=cap + 1)

    assert result["reason"] == _trimming.REASON_NUMERIC_BOUND_REFUSED
    assert bridge.commands == [], "an over-cap limit must never reach the bridge"


@pytest.mark.parametrize(
    ("tool_name", "cap"),
    [("proj_get_nets", 100_000), ("proj_get_bom", 20_000)],
)
async def test_at_cap_limit_reaches_the_bridge(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tool_name: str, cap: int
) -> None:
    tools, bridge, _ = write_tool_setup(monkeypatch, tmp_path)

    result = await call_tool(tools[tool_name], limit=cap)

    assert result == {"ok": True}
    assert len(bridge.commands) == 1


async def test_absurd_limit_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tools, bridge, _ = write_tool_setup(monkeypatch, tmp_path)

    result = await call_tool(tools["proj_get_nets"], limit=10**12)

    assert result["reason"] == _trimming.REASON_NUMERIC_BOUND_REFUSED
    assert bridge.commands == []


# --- M2: stamp key-count and total-payload caps ----------------------------------


def test_stamp_bound_constants_are_exposed() -> None:
    assert _trimming.STAMP_MAX_KEYS > 0
    assert _trimming.STAMPS_TOTAL_MAX_BYTES > 0


async def test_a_stamp_with_too_many_keys_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tools, bridge, _ = write_tool_setup(monkeypatch, tmp_path)
    over = _trimming.STAMP_MAX_KEYS + 1
    stamp = {"designator": "R1", **{f"P{index}": "v" for index in range(over)}}

    result = await call_tool(tools["sch_set_components_parameters"], stamps=[stamp])

    assert result["reason"] == REASON_WRITE_GUARD_REFUSED
    assert bridge.commands == []


async def test_a_batch_over_the_total_payload_cap_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tools, bridge, _ = write_tool_setup(monkeypatch, tmp_path)
    # Each stamp is well under the per-value (4 KiB) and per-stamp key caps,
    # and the batch is under STAMPS_MAX_COUNT — only the TOTAL encoded size
    # trips the new cap.
    big_value = "A" * (VALUE_MAX - 16)
    per_stamp = {"designator": "R1", "Value": big_value}
    count = (_trimming.STAMPS_TOTAL_MAX_BYTES // VALUE_MAX) + 2
    assert count <= STAMPS_MAX
    stamps = [dict(per_stamp, designator=f"R{index}") for index in range(count)]

    result = await call_tool(tools["sch_set_components_parameters"], stamps=stamps)

    assert result["reason"] == REASON_WRITE_GUARD_REFUSED
    assert bridge.commands == []
