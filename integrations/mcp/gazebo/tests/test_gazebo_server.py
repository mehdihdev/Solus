"""The stdio server's tool surface (`GazeboToolService.call`) against the fixture CLIs and a
fake simulator process. Every result is a dict; no real simulator is ever started."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

import pytest
import yaml

from integrations.mcp.gazebo.solus.adapters.adapter_base import Completed, run_argv
from integrations.mcp.gazebo.solus.gazebo_server import (
    CAPABILITIES,
    GazeboToolService,
    gazebo_tool_specs,
)
from integrations.mcp.gazebo.solus.model_assets import SPAWN_PREFIX, manifest_digest
from integrations.mcp.gazebo.solus.world_sessions import SessionRefusedError
from integrations.mcp.gazebo.tests.conftest import NONFINITE_PARTITION, Children

FORK = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[4]
HINTED_WORLD = (
    '<sdf version="1.10">\n  <world name="empty">\n'
    '    <plugin filename="gz-sim-physics-system" name="gz::sim::systems::Physics"/>\n'
    "  </world>\n</sdf>\n"
)
PLAIN_WORLD = '<sdf version="1.6">\n  <world name="empty"/>\n</sdf>\n'
TWOLINK_URDF = (
    '<?xml version="1.0"?>\n<robot name="twolink">\n'
    '  <link name="base"/><link name="arm"/><link name="tip"/>\n'
    '  <joint name="shoulder" type="revolute"><parent link="base"/><child link="arm"/>'
    '<axis xyz="0 1 0"/><limit lower="-1.57" upper="1.57" effort="10" velocity="2"/></joint>\n'
    '  <joint name="elbow" type="revolute"><parent link="arm"/><child link="tip"/>'
    '<axis xyz="0 1 0"/><limit lower="-1.57" upper="1.57" effort="10" velocity="2"/></joint>\n'
    "</robot>\n"
)
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
Harness = tuple[GazeboToolService, list[list[str]], list[float]]
cold = pytest.mark.usefixtures("cold_simulator")


@pytest.fixture
def worlds_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "worlds"
    (root / "nested").mkdir(parents=True)
    (root / "empty.sdf").write_text(HINTED_WORLD)
    (root / "nested" / "plain.sdf").write_text(PLAIN_WORLD)
    monkeypatch.setenv("SOLUS_SIM_ROOTS", str(root))
    return root


@pytest.fixture
def service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fixture_bins: Path,
    worlds_root: Path,
    fake_children: Children,
) -> Harness:
    monkeypatch.setenv("SOLUS_GAZEBO_PATH", str(fixture_bins / "gz8"))
    workspace = tmp_path / "ws"
    workspace.mkdir()
    calls: list[list[str]] = []
    now = [100.0]

    def recording(argv: list[str], timeout: float) -> Completed:
        calls.append(list(argv))
        return run_argv(argv, timeout)

    def clock() -> float:
        return now[0]

    def sleep(seconds: float) -> None:
        now[0] += seconds

    return GazeboToolService(workspace, run=recording, clock=clock, sleep=sleep), calls, now


def _attached(service: GazeboToolService) -> str:
    result = service.call("attach", {"family": "gz", "world": "empty"})
    assert result["ok"], result
    return str(result["session_id"])


def _owned(service: GazeboToolService) -> str:
    result = service.call("open_world", {"world_ref": "empty.sdf"})
    assert result["ok"], result
    return str(result["session_id"])


def _push_twolink(service: GazeboToolService) -> str:
    files = {"twolink.urdf": TWOLINK_URDF.encode(), "meshes/arm.stl": b"solid arm\nendsolid\n"}
    manifest = {k: hashlib.sha256(v).hexdigest() for k, v in files.items()}
    sha = manifest_digest(manifest)
    for index, (path, data) in enumerate(files.items()):
        result = service.call(
            "put_asset",
            {
                "sha256": sha,
                "path": path,
                "index": index,
                "total": len(files),
                "data_b64": base64.b64encode(data).decode(),
                **({"manifest": manifest} if index == 0 else {}),
            },
        )
        assert result["ok"], result
    return sha


# --- roster and argument handling --------------------------------------------------------------


def test_exact_roster_matches_the_allowlist_and_schemas_are_closed() -> None:
    specs = gazebo_tool_specs()
    allowlisted = [
        t["name"] for t in yaml.safe_load((FORK / "allowlist.yaml").read_text())["tools"]
    ]
    assert [s.name for s in specs] == allowlisted and len(specs) == 13
    for spec in specs:
        assert spec.inputSchema["additionalProperties"] is False, spec.name
        assert "$ref" not in json.dumps(spec.inputSchema) and "$defs" not in spec.inputSchema
        assert spec.description and "Gazebo" in spec.description


def test_unknown_tool_and_invalid_arguments_are_results_not_exceptions(service: Harness) -> None:
    svc, _, _ = service
    assert svc.call("nope", {}) == {
        "ok": False,
        "code": "unknown_tool",
        "reason": "no such tool",
    }
    bad = svc.call("spawn", {"session_id": "x", "model_sha256": "zz", "name": "-rf"})
    assert bad["ok"] is False and bad["code"] == "invalid_arguments"
    assert isinstance(bad["reason"], str) and 0 < len(bad["reason"]) <= 200
    assert "-rf" not in bad["reason"], "inputs are never echoed"
    coerced = svc.call("control", {"session_id": "x", "action": "step", "steps": "3"})
    assert coerced["code"] == "invalid_arguments"


@pytest.mark.parametrize("name", [s.name for s in gazebo_tool_specs()])
def test_service_never_raises_for_any_tool_with_garbage(service: Harness, name: str) -> None:
    svc, _, _ = service
    for arguments in ({}, {"session_id": "bogus"}, {"session_id": "bogus", "dry_run": True}):
        result = svc.call(name, arguments)
        assert isinstance(result, dict) and isinstance(result["ok"], bool)
        if not result["ok"]:
            assert isinstance(result["code"], str) and isinstance(result["reason"], str)


# --- discovery -------------------------------------------------------------------------------


def test_probe_reports_families_capabilities_and_gui_attach(service: Harness) -> None:
    svc, _, _ = service
    result = svc.call("probe", {})
    assert result["ok"] is True
    assert result["families"] == [{"name": "gz", "version": "8.15.0", "distro": "Harmonic"}]
    assert result["capabilities"] == CAPABILITIES["gz"]
    assert result["gui_attach"] is True and result["running_worlds"] == ["empty"]
    assert result["sessions"] == [] and result["roots"] == 1
    assert "bin_dir" not in json.dumps(result)


def test_probe_without_search_path_reports_no_family(
    tmp_path: Path, worlds_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SOLUS_GAZEBO_PATH", raising=False)
    result = GazeboToolService(tmp_path).call("probe", {})
    assert result["ok"] is True
    assert result["families"] == [] and result["capabilities"] is None
    assert result["gui_attach"] is False and result["running_worlds"] == []


def test_list_worlds_scans_roots_and_running_worlds(service: Harness) -> None:
    svc, _, _ = service
    result = svc.call("list_worlds", {})
    assert result["ok"] is True
    assert result["worlds"] == [
        {"path": "empty.sdf", "family_hint": "gz"},
        {"path": "nested/plain.sdf", "family_hint": None},
    ]
    assert result["running"] == [{"family": "gz", "version": "8.15.0", "world": "empty"}]


# --- sessions --------------------------------------------------------------------------------


@cold
def test_open_world_dry_run_then_real_registers_an_owned_session(
    service: Harness, fake_children: Children, worlds_root: Path
) -> None:
    svc, _, _ = service
    created, signals = fake_children
    preview = svc.call("open_world", {"world_ref": "empty.sdf", "dry_run": True})
    assert preview["ok"] and preview["dry_run"] is True
    assert [row["label"] for row in preview["preview"]] == [
        "Simulator",
        "World file",
        "World",
        "Mode",
        "Family choice",
        "Lifetime",
    ]
    assert re.fullmatch(r"[0-9a-f]{64}", preview["fingerprint"])
    assert created == [], "a dry run started a simulator"
    result = svc.call("open_world", {"world_ref": "empty.sdf"})
    assert result["ok"] and result["owned"] is True and UUID.match(result["session_id"])
    assert result["family"] == "gz" and result["world"] == "empty"
    assert result["family_reason"].startswith("hinted")
    assert created[0].argv[1:] == ["sim", "-s", "-r", str(worlds_root / "empty.sdf")]
    probe = svc.call("probe", {})
    assert [s["session_id"] for s in probe["sessions"]] == [result["session_id"]]
    assert probe["sessions"][0]["alive"] is True
    busy = svc.call("open_world", {"world_ref": "nested/plain.sdf"})
    assert busy["ok"] is False and busy["code"] == "busy"
    assert len(created) == 1
    stopped = svc.call("stop", {"session_id": result["session_id"]})
    assert stopped["ok"] and stopped["state"] == "stopped"
    assert [sig for _, sig in signals] == [15]


@cold
def test_open_world_plain_sdf_picks_newest_family_and_says_so(service: Harness) -> None:
    svc, _, _ = service
    result = svc.call("open_world", {"world_ref": "nested/plain.sdf", "gui": True})
    assert result["ok"] and result["family"] == "gz"
    assert "newest" in result["family_reason"] and "no" in result["family_reason"]
    assert result["gui"] is True


def test_open_world_refuses_a_world_the_user_already_runs(
    service: Harness, fake_children: Children
) -> None:
    svc, _, _ = service
    created, _ = fake_children
    attached = _attached(svc)
    result = svc.call("open_world", {"world_ref": "empty.sdf"})
    assert result["ok"] is False and result["code"] == "world_already_running"
    assert created == [], "a simulator was started over the user's world"
    probe = svc.call("probe", {})
    assert [s["session_id"] for s in probe["sessions"]] == [attached]


def test_open_world_refuses_missing_files_and_uninstalled_families(service: Harness) -> None:
    svc, _, _ = service
    missing = svc.call("open_world", {"world_ref": "missing.sdf"})
    assert missing["ok"] is False and missing["code"] == "refused"
    classic = svc.call("open_world", {"world_ref": "empty.sdf", "family": "classic"})
    assert classic["ok"] is False and classic["code"] == "family_not_installed"
    no_world = svc.call("open_world", {"world_ref": "nested"})
    assert no_world["ok"] is False


def test_attach_then_list_models_and_joint_state(service: Harness) -> None:
    svc, _, _ = service
    attached = svc.call("attach", {"family": "gz", "world": "empty"})
    assert attached["ok"] and attached["owned"] is False
    assert attached["session_id"].startswith("attached-")
    sid = attached["session_id"]
    models = svc.call("list_models", {"session_id": sid})
    assert models["ok"] and models["world"] == "empty"
    twolink = next(m for m in models["models"] if m["name"] == "twolink")
    assert twolink["links"] == ["base", "arm", "tip"]
    assert [j["name"] for j in twolink["joints"]] == ["shoulder", "elbow"]
    state = svc.call(
        "joint_state", {"session_id": sid, "model": "twolink", "joints": ["elbow"], "window_s": 0.5}
    )
    assert state["ok"] and state["paused"] is False and state["count"] == len(state["samples"])
    assert {s["joint"] for s in state["samples"]} == {"elbow"}
    assert all(isinstance(s["position"], float) for s in state["samples"])
    nowhere = svc.call("attach", {"family": "gz", "world": "nowhere"})
    assert nowhere["code"] == "world_not_running"
    gone = svc.call("list_models", {"session_id": "attached-00000000-0000-4000-8000-000000000000"})
    assert gone["code"] == "session_unavailable"


def test_stop_refuses_attached_session(service: Harness, fake_children: Children) -> None:
    svc, _, _ = service
    _, signals = fake_children
    sid = _attached(svc)
    for dry_run in (True, False):
        result = svc.call("stop", {"session_id": sid, "dry_run": dry_run})
        assert result["ok"] is False and result["code"] == "not_owned"
    assert signals == []
    assert svc.call("list_models", {"session_id": sid})["ok"], "the attached session survives"


# --- actions ---------------------------------------------------------------------------------


def test_set_joint_targets_and_control_run_the_recorded_argv(service: Harness) -> None:
    svc, calls, _ = service
    sid = _attached(svc)
    calls.clear()
    targets = svc.call(
        "set_joint_targets",
        {
            "session_id": sid,
            "model": "twolink",
            "targets": [{"joint": "shoulder", "position_rad": 0.5}],
        },
    )
    assert targets["ok"] and targets["targets"] == {"shoulder": 0.5}
    assert [c[1:] for c in calls] == [
        [
            "topic", "-t", "/model/twolink/joint/shoulder/0/cmd_pos",
            "-m", "gz.msgs.Double", "-p", "data: 0.5",
        ]
    ]  # fmt: skip
    calls.clear()
    stepped = svc.call("control", {"session_id": sid, "action": "step", "steps": 3})
    assert stepped["ok"] and stepped["action"] == "step" and stepped["steps"] == 3
    assert calls[0][1:4] == ["service", "-s", "/world/empty/control"]
    assert calls[0][-1] == "pause: true multi_step: 3"
    reset = svc.call(
        "control", {"session_id": sid, "action": "reset", "reset_scope": "time", "dry_run": True}
    )
    assert reset["dry_run"] and "time" in reset["preview"][0]["after"]


def test_run_routine_sweep_and_trajectory_stay_inside_the_wall_time(service: Harness) -> None:
    svc, calls, now = service
    sid = _attached(svc)
    started = now[0]
    sweep = svc.call(
        "run_routine",
        {
            "session_id": sid,
            "model": "twolink",
            "routine": "sweep",
            "duration_s": 4.0,
            "sweep": {"joint": "elbow", "lower": -1.0, "upper": 1.0, "speed_rad_s": 1.0},
        },
    )
    assert sweep["ok"] and sweep["routine"] == "sweep"
    assert sweep["targets_sent"] >= 4
    assert set(sweep["per_joint"]) == {"elbow"}
    row = sweep["per_joint"]["elbow"]
    assert set(row) == {"target", "final", "error"} and row["error"] >= 0
    assert sweep["max_abs_error_rad"] == row["error"]
    assert now[0] - started <= 4.0 + 10.0
    assert sum("cmd_pos" in " ".join(c) for c in calls) == sweep["targets_sent"]
    started = now[0]
    trajectory = svc.call(
        "run_routine",
        {
            "session_id": sid,
            "model": "twolink",
            "routine": "joint_trajectory",
            "duration_s": 2.0,
            "waypoints": [
                {"t_s": 0.0, "positions": {"shoulder": 0.0, "elbow": 0.0}},
                {"t_s": 1.0, "positions": {"shoulder": 0.9, "elbow": 0.0}},
            ],
        },
    )
    assert trajectory["ok"] and trajectory["targets_sent"] == 2
    assert set(trajectory["per_joint"]) == {"shoulder", "elbow"}
    assert trajectory["per_joint"]["shoulder"]["target"] == 0.9
    assert now[0] - started <= 2.0 + 10.0
    missing = svc.call(
        "run_routine",
        {"session_id": sid, "model": "twolink", "routine": "sweep", "duration_s": 2.0},
    )
    assert missing["ok"] is False and missing["code"] == "refused"


def test_spawn_refuses_unverified_model_dir(service: Harness, tmp_path: Path) -> None:
    svc, calls, _ = service
    sid = _attached(svc)
    sha = "a" * 64
    args = {"session_id": sid, "model_sha256": sha, "name": "arm1"}
    absent = svc.call("spawn", args)
    assert absent["ok"] is False and "not verified" in absent["reason"]
    # The API wrapper keys its chunk push on this one code, never on the reason text.
    assert absent["code"] == "model_not_verified"
    preview = svc.call("spawn", {**args, "dry_run": True})
    assert preview["ok"] is False and preview["code"] == "model_not_verified"
    # A hand-made directory with the final name but no verified manifest is not trusted either.
    forged = tmp_path / "ws" / ".solus" / "sim" / "models" / sha
    forged.mkdir(parents=True)
    (forged / "twolink.urdf").write_text(TWOLINK_URDF)
    forged_result = svc.call("spawn", args)
    assert forged_result["ok"] is False and "not verified" in forged_result["reason"]
    assert not any("create" in c for c in calls), "the server was asked to spawn"
    assert str(tmp_path) not in json.dumps(forged_result)


def test_spawn_wraps_the_verified_model_and_asks_the_server_to_create_it(
    service: Harness, tmp_path: Path
) -> None:
    svc, calls, _ = service
    sid = _attached(svc)
    sha = _push_twolink(svc)
    args = {
        "session_id": sid,
        "model_sha256": sha,
        "name": "arm1",
        "pose": {"xyz": [1.0, 0.0, 0.5], "rpy": [0.0, 0.0, 0.0]},
    }
    preview = svc.call("spawn", {**args, "dry_run": True})
    assert preview["ok"] and preview["dry_run"]
    labels = [row["label"] for row in preview["preview"]]
    assert labels == ["Model", "Name in world", "Pose", "Joints controlled", "World"]
    assert preview["preview"][3]["after"] == "shoulder, elbow"
    model_dir = tmp_path / "ws" / ".solus" / "sim" / "models" / sha
    assert not list(model_dir.glob(f"{SPAWN_PREFIX}*")), "a dry run wrote the spawn file"
    calls.clear()
    result = svc.call("spawn", args)
    assert result["ok"], result
    assert result["name"] == "arm1" and result["joints"] == ["shoulder", "elbow"]
    spawn_file = model_dir / f"{SPAWN_PREFIX}arm1.sdf"
    assert spawn_file.is_file()
    text = spawn_file.read_text()
    assert text.count("joint-position-controller-system") == 2
    assert "/model/arm1/joint/elbow/0/cmd_pos" in text
    create = next(c for c in calls if "/world/empty/create" in c)
    assert f'sdf_filename: "{spawn_file}"' in create[-1] and 'name: "arm1"' in create[-1]
    assert str(tmp_path) not in json.dumps(result)
    assert svc.call("spawn", args)["ok"], "the model stays verified after a spawn"


def test_spawn_of_a_verified_but_malformed_model_keeps_its_own_code(
    service: Harness, tmp_path: Path
) -> None:
    """Only the asset store's verdict is `model_not_verified` (the API's "push it again" key);
    a verified model whose XML the spawn guard refuses reports that refusal, not a re-push."""
    svc, calls, _ = service
    sid = _attached(svc)
    broken = b'<?xml version="1.0"?>\n<robot name="broken"><link name="base">\n'
    manifest = {"broken.urdf": hashlib.sha256(broken).hexdigest()}
    sha = manifest_digest(manifest)
    pushed = svc.call(
        "put_asset",
        {
            "sha256": sha,
            "path": "broken.urdf",
            "index": 0,
            "total": 1,
            "data_b64": base64.b64encode(broken).decode(),
            "manifest": manifest,
        },
    )
    assert pushed["ok"] and pushed["promoted"], pushed
    calls.clear()
    result = svc.call("spawn", {"session_id": sid, "model_sha256": sha, "name": "arm1"})
    assert result["ok"] is False, result
    assert result["code"] != "model_not_verified", result
    assert result["code"] == "refused" and "well-formed" in result["reason"]
    assert not any("create" in c for c in calls), "the server was asked to spawn"
    assert str(tmp_path) not in json.dumps(result)


def test_spawn_refusal_from_the_adapter_keeps_its_code(
    service: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc, calls, _ = service
    sid = _attached(svc)
    sha = _push_twolink(svc)
    adapter = svc.sessions.get(sid).adapter

    def refusing_spawn(*_args: object, **_kwargs: object) -> None:
        raise SessionRefusedError("name_taken", "a model named arm1 already exists")

    monkeypatch.setattr(adapter, "spawn", refusing_spawn)
    result = svc.call("spawn", {"session_id": sid, "model_sha256": sha, "name": "arm1"})
    assert result == {
        "ok": False,
        "code": "name_taken",
        "reason": "a model named arm1 already exists",
    }


def test_spawn_refuses_a_model_store_behind_a_symlinked_ancestor(
    service: Harness, tmp_path: Path
) -> None:
    """A repo that ships `.solus/sim/models -> <anywhere>` must not move the store: spawn
    refuses the (otherwise verified) model and writes no spawn file at the link's target."""
    svc, calls, _ = service
    sid = _attached(svc)
    sha = _push_twolink(svc)
    models = tmp_path / "ws" / ".solus" / "sim" / "models"
    outside = tmp_path / "outside-models"
    shutil.move(str(models), str(outside))
    os.symlink(outside, models)
    before = sorted(outside.rglob("*"))
    calls.clear()
    result = svc.call("spawn", {"session_id": sid, "model_sha256": sha, "name": "arm1"})
    assert result["ok"] is False and "not verified" in result["reason"], result
    assert not any("create" in c for c in calls), "the server was asked to spawn"
    pushed = svc.call(
        "put_asset",
        {
            "sha256": sha,
            "path": "twolink.urdf",
            "index": 0,
            "total": 1,
            "data_b64": base64.b64encode(TWOLINK_URDF.encode()).decode(),
            "manifest": {"twolink.urdf": hashlib.sha256(TWOLINK_URDF.encode()).hexdigest()},
        },
    )
    assert pushed["ok"] is False and pushed["code"] == "store_unsafe", pushed
    assert sorted(outside.rglob("*")) == before, "something was written through the symlink"
    assert str(tmp_path) not in json.dumps([result, pushed])


def test_non_finite_simulator_angles_never_break_a_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fixture_bins: Path
) -> None:
    """Diverged physics prints `angle: nan` / `angle: inf`; every result stays a dict that
    `json.dumps(allow_nan=False)` accepts (the wire's encoder), never a raised ValueError."""
    monkeypatch.setenv("SOLUS_GAZEBO_PATH", str(fixture_bins / "classic11"))
    monkeypatch.setenv("GZ_PARTITION", NONFINITE_PARTITION)
    now = [100.0]
    svc = GazeboToolService(
        tmp_path, clock=lambda: now[0], sleep=lambda s: now.__setitem__(0, now[0] + s)
    )
    sid = svc.call("attach", {"family": "classic", "world": "default"})["session_id"]
    state = svc.call(
        "joint_state", {"session_id": sid, "model": "twolink", "joints": ["shoulder", "elbow"]}
    )
    routine = svc.call(
        "run_routine",
        {
            "session_id": sid,
            "model": "twolink",
            "routine": "joint_trajectory",
            "duration_s": 1.0,
            "waypoints": [{"t_s": 0.0, "positions": {"shoulder": 0.5}}],
        },
    )
    preview = svc.call(
        "set_joint_targets",
        {
            "session_id": sid,
            "model": "twolink",
            "targets": [{"joint": "shoulder", "position_rad": 0.1}],
            "dry_run": True,
        },
    )
    for result in (state, routine, preview):
        json.dumps(result, allow_nan=False)
        assert isinstance(result, dict) and "ok" in result
    assert state["ok"] is False and state["code"] == "cli_failed"
    assert preview["ok"] and preview["preview"][0]["before"] is None


@cold
def test_save_world_writes_into_the_world_root(
    service: Harness, worlds_root: Path, fake_children: Children
) -> None:
    svc, _, _ = service
    sid = _owned(svc)
    preview = svc.call(
        "save_world", {"session_id": sid, "dest": "saved/empty-copy.sdf", "dry_run": True}
    )
    assert preview["ok"] and preview["dry_run"]
    assert preview["preview"][0] == {
        "label": "Destination",
        "before": "absent",
        "after": "saved/empty-copy.sdf",
    }
    assert not (worlds_root / "saved").exists()
    (worlds_root / "saved").mkdir()
    result = svc.call("save_world", {"session_id": sid, "dest": "saved/empty-copy.sdf"})
    assert result["ok"] and result["dest"] == "saved/empty-copy.sdf"
    assert (worlds_root / "saved" / "empty-copy.sdf").read_text().lstrip().startswith("<sdf")
    again = svc.call(
        "save_world", {"session_id": sid, "dest": "saved/empty-copy.sdf", "dry_run": True}
    )
    assert again["preview"][0]["before"].startswith("exists")


def test_put_asset_through_the_tool_surface(service: Harness) -> None:
    svc, _, _ = service
    sha = _push_twolink(svc)
    again = svc.call(
        "put_asset",
        {"sha256": sha, "path": "twolink.urdf", "index": 0, "total": 1, "data_b64": "AA=="},
    )
    assert again["ok"] and again["already"] is True, (
        "a verified model is acknowledged, not rewritten"
    )
    mismatch = svc.call(
        "put_asset",
        {
            "sha256": "c" * 64,
            "path": "twolink.urdf",
            "index": 0,
            "total": 2,
            "data_b64": "AA==",
            "manifest": {"twolink.urdf": "0" * 64, "meshes/arm.stl": "1" * 64},
        },
    )
    assert mismatch["ok"] is False and mismatch["code"] == "manifest_digest_mismatch"


# --- the real stdio transport -----------------------------------------------------------------


async def test_stdio_server_answers_initialize_and_advertises_the_allowlisted_roster(
    tmp_path: Path,
) -> None:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from solus_api.bridge.allowlist import load_allowlist, validate_inventory
    from solus_api.bridge.frames import HelloData, HelloServer, HelloTool

    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "integrations.mcp.gazebo.solus.gazebo_server"],
        cwd=str(REPO_ROOT),
        env={"SOLUS_MCP_WORKSPACE": str(tmp_path), "PATH": "/usr/bin:/bin"},
    )
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            advertised = await session.list_tools()
            probe = await session.call_tool("probe", {})
            refused = await session.call_tool("spawn", {"bogus": 1})
    hello = HelloData(
        protocol_version=1,
        companion_version="test",
        companion_instance_id="gazebo-boundary-test",
        servers=(
            HelloServer(
                server="gazebo",
                tools=tuple(
                    HelloTool(name=tool.name, input_schema=tool.inputSchema)
                    for tool in advertised.tools
                ),
            ),
        ),
    )
    inventory = validate_inventory(hello, load_allowlist(REPO_ROOT / "integrations/mcp"))
    assert {spec.descriptor.name for spec in inventory} == {
        "gazebo." + tool.name for tool in advertised.tools
    }
    assert len(inventory) == 13
    assert not probe.isError and probe.structuredContent is not None
    assert probe.structuredContent["ok"] is True and probe.structuredContent["families"] == []
    assert not refused.isError and refused.structuredContent is not None
    assert refused.structuredContent["ok"] is False
    assert refused.structuredContent["code"] == "invalid_arguments"
    assert list(tmp_path.iterdir()) == []
