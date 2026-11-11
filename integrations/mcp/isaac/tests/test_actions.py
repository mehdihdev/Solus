import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parents[4]))
from integrations.mcp.isaac.solus.actions import ActionEngine
from integrations.mcp.isaac.tests.test_models import fixture


class Scene:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def status(self) -> dict[str, Any]:
        return {"loaded": False}

    def load(self, *args: Any) -> dict[str, Any]:
        self.calls.append("load")
        return {"loaded": True}


def test_load_preview_has_complete_bindings_and_no_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ActionEngine, "_copy_model", lambda *args: None)
    scene = Scene()
    engine = ActionEngine(scene, tmp_path, tmp_path)
    data: dict[str, Any] = {
        "model_entity_id": "00000000-0000-0000-0000-000000000063",
        "resolved_model": fixture(),
        "graph_digest": "b" * 64,
        "expected_scene_generation": 0,
        "dry_run": True,
    }
    result = engine.dispatch("load_model", data)
    assert result["dry_run"]
    assert all(
        binding["entity_id"] in str(result["preview"])
        for binding in data["resolved_model"]["links"] + data["resolved_model"]["joints"]
    )
    assert scene.calls == []


def test_stale_generation_and_extra_fields_refuse(tmp_path: Path) -> None:
    engine = ActionEngine(Scene(), tmp_path, tmp_path)
    for data in (
        {
            "model_entity_id": "00000000-0000-0000-0000-000000000063",
            "resolved_model": fixture(),
            "graph_digest": "b" * 64,
            "expected_scene_generation": 1,
            "dry_run": True,
        },
        {"script": "evil.py"},
    ):
        with pytest.raises(ValueError):
            engine.dispatch("load_model", data)


def test_unknown_action_refuses(tmp_path: Path) -> None:
    engine = ActionEngine(Scene(), tmp_path, tmp_path)
    with pytest.raises(ValueError):
        engine.dispatch("exec", {})


def test_preview_refuses_missing_asset_closure(tmp_path: Path) -> None:
    engine = ActionEngine(Scene(), tmp_path, tmp_path)
    data: dict[str, Any] = {
        "model_entity_id": "00000000-0000-0000-0000-000000000063",
        "resolved_model": fixture(),
        "graph_digest": "b" * 64,
        "expected_scene_generation": 0,
        "dry_run": True,
    }
    with pytest.raises(ValueError):
        engine.dispatch("load_model", data)


def test_partial_load_failure_invalidates_old_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ActionEngine, "_copy_model", lambda *args: None)

    class PartialScene(Scene):
        def load(self, *args: Any) -> dict[str, Any]:
            if self.calls:
                raise ValueError("partial stage replacement")
            return super().load(*args)

        def invalidate_loaded_state(self) -> None:
            self.calls.append("invalidated")

    engine = ActionEngine(PartialScene(), tmp_path, tmp_path)
    args: dict[str, Any] = {
        "model_entity_id": "00000000-0000-0000-0000-000000000063",
        "resolved_model": fixture(),
        "graph_digest": "b" * 64,
        "expected_scene_generation": 0,
        "dry_run": False,
    }
    engine.dispatch("load_model", args)
    args["expected_scene_generation"] = 1
    with pytest.raises(ValueError):
        engine.dispatch("load_model", args)
    assert engine.model is None
    assert engine.graph_digest is None
    assert engine.model_entity_id is None


def test_mutation_failure_retains_uncertain_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from integrations.mcp.isaac.solus.actions import MutationUnverifiedError

    monkeypatch.setattr(ActionEngine, "_copy_model", lambda *args: None)

    class FailedScene(Scene):
        def load(self, *args: Any) -> dict[str, Any]:
            raise ValueError("readback failed after scene change")

        def invalidate_loaded_state(self) -> None:
            pass

    engine = ActionEngine(FailedScene(), tmp_path, tmp_path)
    args: dict[str, Any] = {
        "model_entity_id": "00000000-0000-0000-0000-000000000063",
        "resolved_model": fixture(),
        "graph_digest": "b" * 64,
        "expected_scene_generation": 0,
        "dry_run": False,
    }
    with pytest.raises(MutationUnverifiedError) as error:
        engine.dispatch("load_model", args)
    assert error.value.result["execution_started"] is True
    assert error.value.result["uncertain"] is True
    assert error.value.result["reason"] == "mutation_unverified"


def test_complete_joint_routine_preview_fits_card(tmp_path: Path) -> None:
    import numpy as np

    from integrations.mcp.isaac.solus.artifacts import RevisionStore
    from integrations.mcp.isaac.solus.models import Model
    from integrations.mcp.isaac.tests.test_models import routine

    model = Model.model_validate(fixture())

    class LoadedScene(Scene):
        def status(self) -> dict[str, Any]:
            return {
                "loaded": True,
                "positions_rad": {j.entity_id: 0.0 for j in model.joints},
                "limits_rad": {
                    j.entity_id: [float(np.float32(v)) for v in (j.lower_rad, j.upper_rad)]
                    for j in model.joints
                },
                "link_bindings": {x.entity_id: x.name for x in model.links},
                "sensor_poses": {},
            }

    engine = ActionEngine(LoadedScene(), tmp_path, tmp_path)
    engine.model = model
    engine.graph_digest = "b" * 64
    engine.revision_store = RevisionStore(-1, "00000000-0000-4000-8000-000000000001")
    result = engine.dispatch(
        "run_routine",
        {
            "graph_digest": "b" * 64,
            "expected_scene_generation": 0,
            "dry_run": True,
            "routine_spec": routine(model),
        },
    )
    assert len(result["preview"]) <= 39  # Reserve the required cloud binding row.
    text = str(result["preview"])
    assert all(j.entity_id in text and j.name in text for j in model.joints)
    assert all(f"waypoint_{index}_positions_rad" in text for index in range(1, 4))
    assert "segment_settling_fraction" in text and "0.2" in text
    assert "final_joint_error_rad" in text and "0.01" in text


def test_unchanged_inventory_fingerprint_is_display_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ActionEngine, "_copy_model", lambda *args: None)
    scene = Scene()
    monkeypatch.setattr(
        scene,
        "status",
        lambda: {"loaded": False, "link_bindings": {"id": "/robot/Geometry/base_link"}},
    )
    result = ActionEngine(scene, tmp_path, tmp_path).dispatch(
        "load_model",
        {
            "model_entity_id": "00000000-0000-0000-0000-000000000063",
            "resolved_model": fixture(),
            "graph_digest": "b" * 64,
            "expected_scene_generation": 0,
            "dry_run": True,
        },
    )
    row = next(row for row in result["preview"] if row["label"] == "Unchanged link inventory")
    assert [len(chunk) for chunk in row["before"].split(":")] == [16, 16, 16, 16]


# --- SOLUSDEV-322 P4-T1: the user's own stage, every action round-trips a frame -----------

import io  # noqa: E402
import json  # noqa: E402

from integrations.mcp.isaac.solus.worker import serve_frames  # noqa: E402
from integrations.mcp.isaac.tests.conftest import ARM, FakeScene  # noqa: E402
from integrations.mcp.isaac.tests.test_assets_runtime import URDF, push_all  # noqa: E402

TWOLINK_URDF = (
    b'<robot name="twolink"><link name="base"/><link name="arm"/><link name="tip"/>'
    b'<joint name="shoulder" type="revolute"><parent link="base"/><child link="arm"/>'
    b'<limit lower="-1.57" upper="1.57" effort="10" velocity="2"/></joint>'
    b'<joint name="elbow" type="revolute"><parent link="arm"/><child link="tip"/>'
    b'<limit lower="-1.57" upper="1.57" effort="10" velocity="2"/></joint></robot>'
)


Frames = list[tuple[str, dict[str, Any]]]
StageWorkspace = tuple[FakeScene, ActionEngine, Path, str]


def _complete(preview: object) -> bool:
    """The API's `_diff_rows` acceptance (bridge/tool.py), restated."""
    return (
        isinstance(preview, list)
        and 1 <= len(preview) <= 40
        and all(
            isinstance(row, dict)
            and set(row) == {"label", "before", "after"}
            and isinstance(row["label"], str)
            and row["label"].strip()
            and all(v is None or (isinstance(v, str) and len(v) <= 400) for v in row.values())
            for row in preview
        )
    )


def _frames(frames: Frames) -> list[bytes]:
    return [
        json.dumps(
            {"operation": op, "sequence": i + 1, "generation": "owned", "arguments": args}
        ).encode()
        + b"\n"
        for i, (op, args) in enumerate(frames)
    ]


def _round_trip(engine: ActionEngine, frames: Frames) -> list[Any]:
    reader = io.BytesIO(b"".join(_frames(frames)))
    writer = io.BytesIO()
    serve_frames(reader, writer, "owned", engine)
    return [json.loads(row)["result"] for row in writer.getvalue().splitlines()[1:]]


@pytest.fixture
def stage_workspace(tmp_path: Path) -> StageWorkspace:
    from integrations.mcp.isaac.solus.assets import ModelStore, store_digest

    files = {"twolink.urdf": TWOLINK_URDF, "meshes/arm.stl": b"solid arm\nendsolid arm\n"}
    store = ModelStore(tmp_path)
    assert push_all(store, files)[-1]["promoted"] is True
    sha = store_digest({k: __import__("hashlib").sha256(v).hexdigest() for k, v in files.items()})
    stage = tmp_path / "bench.usda"
    stage.write_text("#usda 1.0\n")
    private = tmp_path / "private"
    private.mkdir()
    scene = FakeScene()
    return scene, ActionEngine(scene, tmp_path, private), stage, sha


def _open(stage: Path) -> tuple[str, dict[str, Any]]:
    return (
        "open_stage",
        {
            "expected_scene_generation": 0,
            "dry_run": False,
            "stage_path": str(stage),
            "stage_ref": stage.name,
        },
    )


def test_every_stage_action_round_trips_a_frame(stage_workspace: StageWorkspace) -> None:
    scene, engine, stage, sha = stage_workspace
    sweep = {
        "routine": "sweep",
        "duration_s": 2.0,
        "sweep": {
            "articulation": ARM,
            "joint": "elbow",
            "lower": -0.5,
            "upper": 0.5,
            "speed_rad_s": 0.25,
        },
    }
    results = _round_trip(
        engine,
        [
            _open(stage),
            ("find_articulations", {}),
            (
                "spawn_at",
                {
                    "expected_scene_generation": 1,
                    "dry_run": False,
                    "model_sha256": sha,
                    "name": "arm2",
                    "pose": {"xyz": [0.1, 0.0, 0.0], "rpy": [0.0, 0.0, 1.57]},
                },
            ),
            ("read_state", {"articulation": ARM}),
            ("control", {"expected_scene_generation": 2, "dry_run": False, "action": "pause"}),
            (
                "control",
                {"expected_scene_generation": 3, "dry_run": False, "action": "step", "steps": 5},
            ),
            (
                "run_routine",
                {"expected_scene_generation": 4, "dry_run": False, "routine_spec": sweep},
            ),
            (
                "save_stage",
                {"expected_scene_generation": 5, "dry_run": False, "dest": "out/bench2.usda"},
            ),
        ],
    )
    opened, found, spawned, state, paused, stepped, swept, saved = results
    assert opened["ok"] and opened["scene_generation"] == 1
    assert opened["readback"]["stage"] == "bench.usda" and opened["readback"]["articulations"]
    assert [a["path"] for a in found["articulations"]] == [ARM]
    assert spawned["ok"] and spawned["readback"]["prim_path"] == "/World/arm2"
    assert spawned["readback"]["model_file"] == "twolink.urdf"
    assert spawned["readback"]["urdf_joints"] == ["shoulder", "elbow"]
    assert ("spawn_at", "twolink.urdf", "arm2", [0.1, 0.0, 0.0], [0.0, 0.0, 1.57]) in scene.calls
    assert state["articulation"]["dofs"]["elbow"]["position_rad"] == 0.1
    assert paused["readback"]["paused"] is True and stepped["readback"]["steps"] == 5
    assert swept["ok"] and swept["readback"]["steps"] == 120
    assert -0.5 <= swept["readback"]["final_position_rad"] <= 0.5
    assert saved["ok"] and saved["readback"]["export"].endswith(".usda")
    assert saved["readback"]["bytes"] > 0
    assert engine.generation == 6
    # the private copy of the spawned model never leaves the engine's private directory
    assert (engine.private_dir / "spawn-2" / "twolink.urdf").read_bytes() == TWOLINK_URDF
    assert (engine.private_dir / saved["readback"]["export"]).is_file()


def test_open_stage_does_not_write_the_file(stage_workspace: StageWorkspace) -> None:
    scene, engine, stage, _ = stage_workspace
    before = (stage.read_bytes(), stage.stat().st_mtime_ns)
    [opened] = _round_trip(engine, [_open(stage)])
    assert opened["ok"] and ("open_stage", str(stage)) in scene.calls
    assert (stage.read_bytes(), stage.stat().st_mtime_ns) == before
    assert sorted(p.name for p in stage.parent.iterdir() if p.is_file()) == ["bench.usda"]
    assert engine.model is None and engine.graph_digest is None


def test_every_stage_mutation_dry_runs_to_a_complete_preview(
    stage_workspace: StageWorkspace,
) -> None:
    scene, engine, stage, sha = stage_workspace
    _round_trip(engine, [_open(stage)])
    dry_runs: dict[str, dict[str, Any]] = {
        "spawn_at": {"model_sha256": sha, "name": "arm2"},
        "control": {"action": "reset"},
        "run_routine": {
            "routine_spec": {
                "routine": "sweep",
                "duration_s": 3.0,
                "sweep": {
                    "articulation": ARM,
                    "joint": "shoulder",
                    "lower": -1.0,
                    "upper": 1.0,
                    "speed_rad_s": 0.1,
                },
            }
        },
        "save_stage": {"dest": "bench.usda"},
    }
    for operation, arguments in dry_runs.items():
        result = engine.dispatch(
            operation, {"expected_scene_generation": 1, "dry_run": True, **arguments}
        )
        assert result["dry_run"] is True and result["ok"] is True, operation
        assert _complete(result["preview"]), operation
        assert len(result["fingerprint"]) == 64
    assert engine.generation == 1, "no dry run bumps the generation"
    assert not any(call[0] in ("spawn_at", "control", "run_sweep") for call in scene.calls)
    text = str(
        engine.dispatch(
            "spawn_at", {"expected_scene_generation": 1, "dry_run": True, **dry_runs["spawn_at"]}
        )["preview"]
    )
    assert "shoulder" in text and "elbow" in text and "arm2" in text


def test_save_stage_dry_run_previews_dest_and_bytes(stage_workspace: StageWorkspace) -> None:
    scene, engine, stage, _ = stage_workspace
    _round_trip(engine, [_open(stage)])
    result = engine.dispatch(
        "save_stage",
        {
            "expected_scene_generation": 1,
            "dry_run": True,
            "dest": "copies/bench.usda",
            "dest_state": "exists (12 bytes)",
        },
    )
    rows = {row["label"]: row for row in result["preview"]}
    assert rows["Destination"]["before"] == "exists (12 bytes)"
    assert rows["Destination"]["after"] == "copies/bench.usda"
    exported = next(call for call in scene.calls if call[0] == "export_stage")
    size = len(b'#usda 1.0\n(doc = "bench.usda")\n')
    assert rows["Bytes"]["after"] == f"{size} bytes (.usda)"
    assert exported[1].endswith(".usda")
    assert stage.read_text() == "#usda 1.0\n", "the user's file is never touched by a preview"


def test_sweep_outside_the_articulation_limits_or_unknown_joint_is_refused(
    stage_workspace: StageWorkspace,
) -> None:
    scene, engine, stage, _ = stage_workspace
    _round_trip(engine, [_open(stage)])
    for sweep in (
        {"articulation": ARM, "joint": "elbow", "lower": -2.0, "upper": 0.5, "speed_rad_s": 0.1},
        {"articulation": ARM, "joint": "wrist", "lower": -0.5, "upper": 0.5, "speed_rad_s": 0.1},
        {
            "articulation": "/World/ghost",
            "joint": "elbow",
            "lower": -0.5,
            "upper": 0.5,
            "speed_rad_s": 0.1,
        },
    ):
        with pytest.raises(ValueError):
            engine.dispatch(
                "run_routine",
                {
                    "expected_scene_generation": 1,
                    "dry_run": True,
                    "routine_spec": {"routine": "sweep", "duration_s": 2.0, "sweep": sweep},
                },
            )
    assert not any(call[0] == "run_sweep" for call in scene.calls)


def test_sweep_range_that_excludes_the_observed_position_is_refused_at_dry_run(
    stage_workspace: StageWorkspace,
) -> None:
    scene, engine, stage, _ = stage_workspace
    _round_trip(engine, [_open(stage)])
    sweep = {"articulation": ARM, "joint": "elbow", "lower": 0.5, "upper": 1.0, "speed_rad_s": 0.1}
    with pytest.raises(ValueError, match="observed position"):
        engine.dispatch(
            "run_routine",
            {
                "expected_scene_generation": 1,
                "dry_run": True,
                "routine_spec": {"routine": "sweep", "duration_s": 2.0, "sweep": sweep},
            },
        )
    assert not any(call[0] == "run_sweep" for call in scene.calls)
    assert engine.generation == 1, "a refused preview burns no scene generation"


def test_spawn_at_refuses_an_unverified_or_tampered_model(
    stage_workspace: StageWorkspace, tmp_path: Path
) -> None:
    scene, engine, stage, sha = stage_workspace
    _round_trip(engine, [_open(stage)])
    args = {"expected_scene_generation": 1, "dry_run": True, "model_sha256": "f" * 64, "name": "x"}
    with pytest.raises(ValueError, match="put_asset"):
        engine.dispatch("spawn_at", args)
    (tmp_path / ".solus" / "sim" / "models" / sha / "twolink.urdf").write_bytes(URDF)
    with pytest.raises(ValueError):
        engine.dispatch("spawn_at", {**args, "model_sha256": sha})
    assert not any(call[0] == "spawn_at" for call in scene.calls)


def test_stage_actions_guard_the_scene_generation_and_reject_extra_fields(
    stage_workspace: StageWorkspace,
) -> None:
    scene, engine, stage, _ = stage_workspace
    _round_trip(engine, [_open(stage)])
    with pytest.raises(ValueError, match="stale"):
        engine.dispatch(
            "control", {"expected_scene_generation": 0, "dry_run": True, "action": "play"}
        )
    with pytest.raises(ValueError):
        engine.dispatch(
            "control",
            {"expected_scene_generation": 1, "dry_run": True, "action": "play", "cmd": "rm"},
        )
    with pytest.raises(ValueError):
        engine.dispatch(
            "save_stage", {"expected_scene_generation": 1, "dry_run": True, "dest": "../x.usda"}
        )
    with pytest.raises(ValueError):
        engine.dispatch(
            "save_stage", {"expected_scene_generation": 1, "dry_run": True, "dest": "pack.usdz"}
        )


def test_spawn_at_refuses_a_stored_usd_model(tmp_path: Path) -> None:
    """P5-FIX: Solus spawns only the URDF models it generated. A verified store entry whose model
    file is USD is refused as `unsupported_model_type` at dry run and at the write alike, before
    any scene call — it is never handed to `AddReference`; the user's own USD is opened through
    `open_stage`."""
    import hashlib

    from integrations.mcp.isaac.solus.actions import RefusedError
    from integrations.mcp.isaac.solus.assets import ModelStore, store_digest

    files = {"model.usd": b"#usda 1.0\n"}
    store = ModelStore(tmp_path)
    assert push_all(store, files)[-1]["promoted"] is True
    sha = store_digest({k: hashlib.sha256(v).hexdigest() for k, v in files.items()})
    stage = tmp_path / "bench.usda"
    stage.write_text("#usda 1.0\n")
    private = tmp_path / "private"
    private.mkdir()
    scene = FakeScene()
    engine = ActionEngine(scene, tmp_path, private)
    _round_trip(engine, [_open(stage)])
    spawn = {"expected_scene_generation": 1, "model_sha256": sha, "name": "arm2"}
    refusal = {
        "ok": False,
        "code": "unsupported_model_type",
        "reason": (
            "Solus spawns only the URDF models it generated; open the user's own USD through "
            "open_stage instead"
        ),
    }

    for dry_run in (True, False):
        with pytest.raises(RefusedError) as error:
            engine.dispatch("spawn_at", {**spawn, "dry_run": dry_run})
        assert error.value.result == refusal
    (wire,) = _round_trip(engine, [("spawn_at", {**spawn, "dry_run": False})])

    assert wire == refusal, "the worker answers the typed refusal; nothing raises across the wire"
    assert not any(call[0] == "spawn_at" for call in scene.calls)
    assert engine.generation == 1, "a refused spawn burns no scene generation"
