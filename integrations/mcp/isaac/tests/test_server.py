import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parents[4]))
from integrations.mcp.isaac.solus.server import ToolService, tool_specs


def test_allowlist_is_exposure_internal_with_the_api_loader() -> None:
    """SOLUSDEV-322 P10: the whole server is `exposure: internal` (bridge-protocol.md);
    only the owned `isaac.*` wrappers in the API are model-facing."""
    from solus_api.bridge.allowlist import load_allowlist

    loaded = load_allowlist(Path(__file__).parents[2])
    assert "isaac" in loaded.internal
    assert len(loaded.servers["isaac"]) == 16, "the ratified entries are untouched"


def test_exact_roster_and_no_freeform_command() -> None:
    import json

    import yaml

    specs = tool_specs()
    allowlisted = [
        t["name"]
        for t in yaml.safe_load((Path(__file__).parents[1] / "allowlist.yaml").read_text())["tools"]
    ]
    assert [s.name for s in specs] == allowlisted and len(specs) == 16
    assert set(allowlisted) >= {
        "probe",
        "status",
        "start",
        "stop",
        "load_model",
        "set_joint_limits",
        "set_sensor_pose",
        "run_routine",
        "list_stages",
        "open_stage",
        "find_articulations",
        "spawn_at",
        "read_state",
        "control",
        "save_stage",
        "put_asset",
    }
    for spec in specs:
        assert spec.inputSchema["additionalProperties"] is False, spec.name
        assert "$ref" not in json.dumps(spec.inputSchema) and "$defs" not in spec.inputSchema


def test_advertised_schema_inlines_only_closed_definitions_and_retains_constraints() -> None:
    from integrations.mcp.isaac.solus.server import _advertised_schema

    original: dict[str, Any] = {
        "$defs": {"Item": {"type": "number", "minimum": -1}},
        "type": "object",
        "properties": {"x": {"$ref": "#/$defs/Item", "maximum": 1}},
    }
    result = _advertised_schema(original)
    assert result["properties"]["x"] == {"type": "number", "minimum": -1, "maximum": 1}
    assert "$defs" not in result
    assert "$ref" in original["properties"]["x"]
    for invalid in (
        {"$ref": "https://example.test/schema"},
        {"$ref": "#/$defs/missing"},
        {"$defs": {"A": {"$ref": "#/$defs/A"}}, "$ref": "#/$defs/A"},
    ):
        with pytest.raises(ValueError):
            _advertised_schema(invalid)


def test_read_only_service_does_not_launch(tmp_path: Path) -> None:
    service = ToolService(tmp_path)
    assert service.call("status", {})["state"] == "stopped"
    assert isinstance(service.call("probe", {})["available"], bool)
    assert list(tmp_path.iterdir()) == []
    service.close()


@pytest.mark.parametrize(
    "args", [{"dry_run": "false"}, {"dry_run": 1}, {"dry_run": False, "command": "evil"}]
)
def test_start_rejects_coercion_before_controller(tmp_path: Path, args: dict[str, Any]) -> None:
    service = ToolService(tmp_path)
    with pytest.raises(ValueError):
        service.call("start", args)
    assert service.call("status", {})["state"] == "stopped"
    service.close()


def test_service_routes_owned_session_and_marks_transport_loss_uncertain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from integrations.mcp.isaac.solus.actions import MutationUnverifiedError

    service = ToolService(tmp_path)
    controller = service.controller
    session = "00000000-0000-4000-8000-000000000001"
    controller.session = session
    monkeypatch.setattr(controller, "status", lambda: {"state": "running"})
    monkeypatch.setattr(
        controller, "exchange", lambda *args, **kwargs: {"result": {"loaded": True}}
    )
    assert service.call("status", {})["loaded"] is True
    monkeypatch.setattr(controller, "start", lambda **kwargs: kwargs)
    assert service.call("start", {"dry_run": True}) == {"dry_run": True}
    monkeypatch.setattr(controller, "stop", lambda value, **kwargs: {"session": value})
    assert service.call("stop", {"session_id": session, "dry_run": True})["session"] == session
    args = {
        "session_id": session,
        "entity_id": session,
        "lower": -0.1,
        "upper": 0.1,
        "graph_digest": "a" * 64,
        "expected_scene_generation": 1,
        "dry_run": True,
    }
    assert service.call("set_joint_limits", args)["loaded"] is True
    with pytest.raises(ValueError):
        service.call("unknown", {})
    with pytest.raises(ValueError):
        service.call(
            "set_joint_limits", {**args, "session_id": "00000000-0000-4000-8000-000000000002"}
        )

    def lost(*args: Any, **kwargs: Any) -> None:
        raise TimeoutError("private")

    monkeypatch.setattr(controller, "exchange", lost)
    with pytest.raises(TimeoutError):
        service.call("set_joint_limits", args)
    with pytest.raises(MutationUnverifiedError):
        service.call("set_joint_limits", {**args, "dry_run": False})
    monkeypatch.setattr(controller, "exchange", lambda *args, **kwargs: {"result": []})
    with pytest.raises(ValueError):
        service.call("set_joint_limits", args)
    service.close()


# --- SOLUSDEV-322 P4-T1: the user's own stage through the tool surface -----------------------

from integrations.mcp.isaac.tests.conftest import ARM, Children, FakeScene  # noqa: E402
from integrations.mcp.isaac.tests.test_actions import TWOLINK_URDF, _complete  # noqa: E402
from integrations.mcp.isaac.tests.test_assets_runtime import push_all  # noqa: E402


@pytest.fixture
def stage_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "stages"
    (root / "nested").mkdir(parents=True)
    (root / "bench.usda").write_text("#usda 1.0\n")
    (root / "nested" / "arm.usd").write_bytes(b"PXR-USDC")
    (root / "notes.txt").write_text("x")
    monkeypatch.setenv("SOLUS_SIM_ROOTS", str(root))
    return root


@pytest.fixture
def service(tmp_path: Path) -> Iterator[ToolService]:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    svc = ToolService(workspace)
    yield svc
    svc.close()


def test_probe_reports_gui_attach_unsupported(service: ToolService) -> None:
    probe = service.call("probe", {})
    assert probe["gui_attach"] == "unsupported"
    assert probe["available"] is True  # the fixture runtime
    assert service.controller.probe()["gui_attach"] == "unsupported"


def test_list_stages_scans_the_sim_roots_without_launching(
    service: ToolService, stage_root: Path
) -> None:
    result = service.call("list_stages", {})
    assert result == {
        "ok": True,
        "roots": 1,
        "stages": [{"path": "bench.usda"}, {"path": "nested/arm.usd"}],
    }
    assert service.call("status", {})["state"] == "stopped"
    assert list(service.controller.workspace.iterdir()) == []


def test_list_stages_without_roots_is_empty_not_an_error(
    service: ToolService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SOLUS_SIM_ROOTS", raising=False)
    assert service.call("list_stages", {}) == {"ok": True, "roots": 0, "stages": []}


def test_put_asset_through_the_tool_surface(service: ToolService) -> None:
    import base64
    import hashlib

    from integrations.mcp.isaac.solus.assets import store_digest

    files = {"twolink.urdf": TWOLINK_URDF}
    manifest = {k: hashlib.sha256(v).hexdigest() for k, v in files.items()}
    sha = store_digest(manifest)
    result = service.call(
        "put_asset",
        {
            "sha256": sha,
            "path": "twolink.urdf",
            "index": 0,
            "total": 1,
            "data_b64": base64.b64encode(TWOLINK_URDF).decode(),
            "manifest": manifest,
        },
    )
    assert result["ok"] and result["promoted"] is True
    assert (service.controller.workspace / ".solus/sim/models" / sha / "twolink.urdf").is_file()
    with pytest.raises(ValueError):
        service.call(
            "put_asset",
            {
                "sha256": sha,
                "path": "../x",
                "index": 0,
                "total": 1,
                "data_b64": "",
                "manifest": manifest,
            },
        )


def test_open_stage_dry_run_previews_without_launching(
    service: ToolService, stage_root: Path, children: Children
) -> None:
    created, _, _ = children
    result = service.call("open_stage", {"stage_ref": "bench.usda", "dry_run": True})
    assert result["ok"] is True and result["dry_run"] is True
    assert _complete(result["preview"]) and len(result["fingerprint"]) == 64
    labels = [row["label"] for row in result["preview"]]
    assert labels[:2] == ["Stage", "Stage file"] and "Runtime" in labels
    assert result["preview"][0]["after"] == "bench.usda"
    assert created == [] and service.call("status", {})["state"] == "stopped"


@pytest.mark.parametrize(
    "stage_ref", ["../secret.usda", "/etc/passwd", "notes.txt", "missing.usda", "-x.usda"]
)
def test_stage_paths_confined_to_sim_roots(
    service: ToolService, stage_root: Path, children: Children, tmp_path: Path, stage_ref: str
) -> None:
    created, _, _ = children
    (tmp_path / "secret.usda").write_text("#usda 1.0\n")
    for dry_run in (True, False):
        with pytest.raises(ValueError):
            service.call("open_stage", {"stage_ref": stage_ref, "dry_run": dry_run})
    assert created == [] and service.call("status", {})["state"] == "stopped"


def test_open_stage_starts_one_owned_session_and_refuses_a_second(
    service: ToolService, stage_root: Path, fake_worker: list[FakeScene]
) -> None:
    opened = service.call("open_stage", {"stage_ref": "bench.usda", "dry_run": False})
    assert opened["ok"] is True and opened["state"] == "running"
    assert opened["stage_ref"] == "bench.usda" and opened["stage"]["stage"] == "bench.usda"
    assert len(opened["runtime_fingerprint"]) == 64
    sid = opened["session_id"]
    assert ("open_stage", str(stage_root / "bench.usda")) in fake_worker[0].calls
    status = service.call("status", {})
    assert status["state"] == "running" and status["stage_ref"] == "bench.usda"
    assert status["scene_generation"] == 1 and status["loaded"] is False
    with pytest.raises(ValueError, match="busy"):
        service.call("open_stage", {"stage_ref": "nested/arm.usd", "dry_run": False})
    assert (stage_root / "bench.usda").read_text() == "#usda 1.0\n"
    service.call("stop", {"session_id": sid, "dry_run": False})
    assert service.call("status", {})["state"] == "stopped"


def test_spawn_at_without_the_model_says_model_not_verified(
    service: ToolService, stage_root: Path, fake_worker: list[FakeScene]
) -> None:
    """P4-T2: the API wrapper pushes the model only when the fork names the gap; a dry run of a
    `spawn_at` whose digest the store does not hold is `{ok: false, code: "model_not_verified"}`
    and never reaches the worker."""
    sid = service.call("open_stage", {"stage_ref": "bench.usda", "dry_run": False})["session_id"]
    spawn = {"session_id": sid, "model_sha256": "f" * 64, "name": "arm2"}
    for dry_run in (True, False):
        answer = service.call(
            "spawn_at", {**spawn, "expected_scene_generation": 1, "dry_run": dry_run}
        )
        assert answer == {
            "ok": False,
            "code": "model_not_verified",
            "reason": "model is not verified: push it with put_asset first",
        }
    assert not [c for c in fake_worker[0].calls if c[0] == "spawn_at"]
    assert service.call("status", {})["scene_generation"] == 1, "nothing was invalidated"


def test_stage_actions_round_trip_through_the_service(
    service: ToolService, stage_root: Path, fake_worker: list[FakeScene]
) -> None:
    from integrations.mcp.isaac.solus.assets import ModelStore, store_digest

    files = {"twolink.urdf": TWOLINK_URDF}
    push_all(ModelStore(service.controller.workspace), files)
    sha = store_digest({k: __import__("hashlib").sha256(v).hexdigest() for k, v in files.items()})
    sid = service.call("open_stage", {"stage_ref": "bench.usda", "dry_run": False})["session_id"]
    found = service.call("find_articulations", {"session_id": sid})
    assert [a["path"] for a in found["articulations"]] == [ARM]
    spawn = {"session_id": sid, "model_sha256": sha, "name": "arm2"}
    preview = service.call("spawn_at", {**spawn, "expected_scene_generation": 1, "dry_run": True})
    assert preview["dry_run"] is True and _complete(preview["preview"])
    spawned = service.call("spawn_at", {**spawn, "expected_scene_generation": 1, "dry_run": False})
    assert spawned["ok"] and spawned["readback"]["prim_path"] == "/World/arm2"
    stale = service.call("spawn_at", {**spawn, "expected_scene_generation": 1, "dry_run": False})
    assert stale["ok"] is False and stale["reason"] == "action_refused", "a stale plan never runs"
    assert len([c for c in fake_worker[0].calls if c[0] == "spawn_at"]) == 1
    state = service.call(
        "read_state", {"session_id": sid, "articulation": ARM, "camera_frame": True}
    )
    assert state["ok"] and set(state["articulation"]["dofs"]) == {"shoulder", "elbow"}
    assert state["camera"]["frame_sha256"]
    paused = service.call(
        "control",
        {"session_id": sid, "expected_scene_generation": 2, "action": "pause", "dry_run": False},
    )
    assert paused["readback"]["paused"] is True
    swept = service.call(
        "run_routine",
        {
            "session_id": sid,
            "expected_scene_generation": 3,
            "dry_run": False,
            "routine_spec": {
                "routine": "sweep",
                "duration_s": 1.0,
                "sweep": {
                    "articulation": ARM,
                    "joint": "elbow",
                    "lower": -0.5,
                    "upper": 0.5,
                    "speed_rad_s": 0.25,
                },
            },
        },
    )
    assert swept["ok"] and swept["readback"]["steps"] == 60
    save = {"session_id": sid, "dest": "nested/bench-copy.usda", "expected_scene_generation": 4}
    saved = service.call("save_stage", {**save, "dry_run": True})
    rows = {row["label"]: row for row in saved["preview"]}
    assert rows["Destination"] == {
        "label": "Destination",
        "before": "absent",
        "after": "nested/bench-copy.usda",
    }
    assert rows["Bytes"]["after"].endswith("bytes (.usda)")
    assert not (stage_root / "nested" / "bench-copy.usda").exists()
    written = service.call("save_stage", {**save, "dry_run": False})
    assert written["ok"] and written["dest"] == "nested/bench-copy.usda"
    data = (stage_root / "nested" / "bench-copy.usda").read_bytes()
    assert data.startswith(b"#usda 1.0") and written["bytes"] == len(data)
    again = service.call("save_stage", {**save, "expected_scene_generation": 5, "dry_run": True})
    assert {r["label"]: r["before"] for r in again["preview"]}["Destination"] == (
        f"exists ({len(data)} bytes)"
    )
    for name, args in (
        ("find_articulations", {"session_id": "00000000-0000-4000-8000-000000000002"}),
        (
            "save_stage",
            {**save, "expected_scene_generation": 5, "dest": "../x.usda", "dry_run": True},
        ),
        (
            "save_stage",
            {**save, "expected_scene_generation": 5, "dest": "pack.usdz", "dry_run": True},
        ),
        (
            "control",
            {
                "session_id": sid,
                "expected_scene_generation": 5,
                "action": "step",
                "steps": "3",
                "dry_run": False,
            },
        ),
    ):
        with pytest.raises(ValueError):
            service.call(name, args)


def test_save_stage_refuses_a_symlinked_destination_and_leaves_the_target_alone(
    service: ToolService, stage_root: Path, fake_worker: list[FakeScene], tmp_path: Path
) -> None:
    import os

    from integrations.mcp.isaac.solus.actions import MutationUnverifiedError

    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside / "victim.usda", stage_root / "link.usda")
    sid = service.call("open_stage", {"stage_ref": "bench.usda", "dry_run": False})["session_id"]
    with pytest.raises((ValueError, MutationUnverifiedError)):
        service.call(
            "save_stage",
            {
                "session_id": sid,
                "expected_scene_generation": 1,
                "dest": "link.usda",
                "dry_run": False,
            },
        )
    assert list(outside.iterdir()) == []
