"""Actual native routine facts must leave space for the cloud consent binding."""

import json
import struct
import sys
from pathlib import Path
from types import SimpleNamespace

from mcp.types import CallToolResult
from solus_api.agent.tools.untrusted import redact_value
from solus_companion.dispatch import map_result
from test_isaac_tools import SESSION, graph, tools

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from integrations.mcp.isaac.solus.actions import ActionEngine
from integrations.mcp.isaac.solus.models import Model
from integrations.mcp.isaac.solus.server import wire_result


def float32(value):
    return struct.unpack("f", struct.pack("f", value))[0]


async def test_actual_native_routine_survives_transport_and_cloud_binding(db, engine, tmp_path):
    project, root, _ = await graph(db)
    built, native, calls, state = tools(engine, project.id)
    tool = built["isaac.run_routine"]
    resolved = await tool.resolver.resolve(str(root.id))
    model = Model.model_validate(resolved.model.model_dump())
    state.update(loaded=True, model_entity_id=str(root.id), graph_digest=resolved.digest)

    class Scene:
        def status(self):
            return {
                "loaded": True,
                "positions_rad": {j.entity_id: 0.001234567890123 for j in model.joints},
                "limits_rad": {
                    j.entity_id: [float32(v) for v in (j.lower_rad, j.upper_rad)]
                    for j in model.joints
                },
                "link_bindings": {x.entity_id: "/World/" + x.name for x in model.links},
                "sensor_poses": {
                    model.sensors[0].entity_id: {
                        "translation_m": [-0.007, -0.073, 0.019],
                        "orientation_wxyz": [1.0, 0.0, 0.0, 0.0],
                    }
                },
            }

    action = ActionEngine(Scene(), tmp_path, tmp_path)
    action.model = model
    action.model_entity_id = str(root.id)
    action.graph_digest = resolved.digest
    action.revision_store = SimpleNamespace(
        relative_path=lambda generation: ".solus/isaac/revision.json"
    )
    captured = []

    async def native_preview(args):
        assert args["dry_run"] is True
        result = action.dispatch(
            "run_routine", {k: v for k, v in args.items() if k != "session_id"}
        )
        sdk = CallToolResult.model_validate_json(
            CallToolResult(content=[], structuredContent=wire_result(result)).model_dump_json()
        )
        value = redact_value(json.loads(map_result("owned", sdk))["data"]["value"])
        captured.extend(value["preview"])
        return value

    native["isaac.run_routine"].invoke = native_preview
    args = {
        "session_id": SESSION,
        "routine": "joint_trajectory",
        "duration_s": 30,
        "joints": [
            {
                "joint_entity_id": j.entity_id,
                "lower": (j.lower_rad, j.upper_rad)[0],
                "upper": (j.lower_rad, j.upper_rad)[1],
            }
            for j in model.joints
        ],
        "waypoints": [
            {
                "positions": [
                    {"joint_entity_id": j.entity_id, "position_rad": 0.05} for j in model.joints
                ],
            }
            for _ in range(3)
        ],
    }
    rows = await tool.preview(args)
    assert len(rows) <= 40
    assert rows[:-1] == captured
    timing = next(row for row in rows if row["label"] == "timing")
    assert json.loads(timing["after"]) == {
        "duration_s": 30.0,
        "physics_steps": 1800,
        "maximum_target_speed_rad_s": 0.25,
    }
    assert str(root.id) in rows[-1]["after"]
    text = str(rows)
    assert all(j.entity_id in text and j.name in text for j in model.joints)
    assert all(key in text for key in ("duration_s", "physics_steps", "maximum_target_speed_rad_s"))
    assert action.generation == 0
    assert not any(name == "run_routine" for name, _ in calls)
