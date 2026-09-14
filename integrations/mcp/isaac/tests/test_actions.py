import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[4]))
from integrations.mcp.isaac.solus.actions import ActionEngine
from integrations.mcp.isaac.tests.test_models import fixture


class Scene:
    def __init__(self):
        self.calls = []

    def status(self):
        return {"loaded": False}

    def load(self, *args):
        self.calls.append("load")
        return {"loaded": True}


def test_load_preview_has_complete_bindings_and_no_mutation(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "integrations.mcp.isaac.solus.actions.verify_assets", lambda *args: "a" * 64
    )
    scene = Scene()
    engine = ActionEngine(scene, tmp_path, tmp_path)
    data = {
        "model_entity_id": "00000000-0000-0000-0000-000000000063",
        "resolved_model": fixture(),
        "graph_digest": "b" * 64,
        "expected_scene_generation": 0,
        "dry_run": True,
    }
    result = engine.dispatch("load_model", data)
    assert result["dry_run"]
    assert len(result["preview"]) >= 18
    assert scene.calls == []


def test_stale_generation_and_extra_fields_refuse(tmp_path):
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


def test_unknown_action_refuses(tmp_path):
    engine = ActionEngine(Scene(), tmp_path, tmp_path)
    with pytest.raises(ValueError):
        engine.dispatch("exec", {})


def test_preview_refuses_missing_asset_closure(tmp_path):
    engine = ActionEngine(Scene(), tmp_path, tmp_path)
    data = {
        "model_entity_id": "00000000-0000-0000-0000-000000000063",
        "resolved_model": fixture(),
        "graph_digest": "b" * 64,
        "expected_scene_generation": 0,
        "dry_run": True,
    }
    with pytest.raises(ValueError):
        engine.dispatch("load_model", data)


def test_partial_load_failure_invalidates_old_model(tmp_path, monkeypatch):
    module = "integrations.mcp.isaac.solus.actions"
    monkeypatch.setattr(module + ".verify_assets", lambda *args: "a" * 64)
    monkeypatch.setattr(module + ".copy_verified_assets", lambda *args: "a" * 64)

    class PartialScene(Scene):
        def load(self, *args):
            if self.calls:
                raise ValueError("partial stage replacement")
            return super().load(*args)

        def invalidate_loaded_state(self):
            self.calls.append("invalidated")

    engine = ActionEngine(PartialScene(), tmp_path, tmp_path)
    args = {
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


def test_mutation_failure_retains_uncertain_outcome(tmp_path, monkeypatch):
    from integrations.mcp.isaac.solus.actions import MutationUnverifiedError

    module = "integrations.mcp.isaac.solus.actions"
    monkeypatch.setattr(module + ".verify_assets", lambda *args: "a" * 64)
    monkeypatch.setattr(module + ".copy_verified_assets", lambda *args: "a" * 64)

    class FailedScene(Scene):
        def load(self, *args):
            raise ValueError("readback failed after scene change")

        def invalidate_loaded_state(self):
            pass

    engine = ActionEngine(FailedScene(), tmp_path, tmp_path)
    args = {
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


def test_complete_six_joint_routine_preview_fits_card(tmp_path):
    from types import SimpleNamespace

    import numpy as np

    from integrations.mcp.isaac.solus.models import LIMITS, Model
    from integrations.mcp.isaac.tests.test_models import routine

    model = Model.model_validate(fixture())

    class LoadedScene(Scene):
        def status(self):
            return {
                "loaded": True,
                "positions_rad": {j.entity_id: 0.0 for j in model.joints},
                "limits_rad": {
                    j.entity_id: [float(np.float32(v)) for v in LIMITS[j.name]]
                    for j in model.joints
                },
                "link_bindings": {x.entity_id: x.name for x in model.links},
                "sensor_poses": {},
                "bottle_position_m": [0.2, 0.0, 0.1],
            }

    engine = ActionEngine(LoadedScene(), tmp_path, tmp_path)
    engine.model = model
    engine.graph_digest = "b" * 64
    engine.revision_store = SimpleNamespace(
        relative_path=lambda generation: ".solus/isaac/revision.json"
    )
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
    assert all(phase in text for phase in ("approach", "close", "lift"))
    assert "phase_settling_fraction" in text and "0.2" in text
    assert "bottle_specific_contact" in text and "0.02" in text


def test_unchanged_inventory_fingerprint_is_display_safe(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "integrations.mcp.isaac.solus.actions.verify_assets", lambda *args: "a" * 64
    )
    scene = Scene()
    monkeypatch.setattr(
        scene,
        "status",
        lambda: {"loaded": False, "link_bindings": {"id": "/so101/Geometry/base_link"}},
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
