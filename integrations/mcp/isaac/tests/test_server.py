import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[4]))
from integrations.mcp.isaac.solus.server import ToolService, tool_specs


def test_exact_roster_and_no_freeform_command():
    specs = tool_specs()
    assert {s.name for s in specs} == {
        "probe",
        "status",
        "start",
        "stop",
        "load_model",
        "set_joint_limits",
        "set_sensor_pose",
        "run_routine",
    }
    assert all(s.inputSchema["additionalProperties"] is False for s in specs)


def test_advertised_schema_inlines_only_closed_definitions_and_retains_constraints():
    from integrations.mcp.isaac.solus.server import _advertised_schema

    original = {
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


def test_read_only_service_does_not_launch(tmp_path):
    service = ToolService(tmp_path)
    assert service.call("status", {})["state"] == "stopped"
    assert isinstance(service.call("probe", {})["available"], bool)
    assert list(tmp_path.iterdir()) == []
    service.close()


@pytest.mark.parametrize(
    "args", [{"dry_run": "false"}, {"dry_run": 1}, {"dry_run": False, "command": "evil"}]
)
def test_start_rejects_coercion_before_controller(tmp_path, args):
    service = ToolService(tmp_path)
    with pytest.raises(ValueError):
        service.call("start", args)
    assert service.call("status", {})["state"] == "stopped"
    service.close()


def test_service_routes_owned_session_and_marks_transport_loss_uncertain(tmp_path, monkeypatch):
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

    def lost(*args, **kwargs):
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
