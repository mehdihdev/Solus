"""Fixed Isaac child entrypoint and bounded private pipe protocol."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, BinaryIO

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "solus"
from .actions import MutationUnverifiedError
from .runtime import MAX_FRAME, RUNTIME, validate_frame


def serve_frames(reader: BinaryIO, writer: BinaryIO, generation: str, engine: Any) -> None:
    sequence = 0

    def reply(value: dict[str, Any]) -> None:
        data = json.dumps(value, allow_nan=False, separators=(",", ":")).encode() + b"\n"
        if len(data) > MAX_FRAME:
            raise ValueError("reply too large")
        writer.write(data)

    reply({"ready": True, "generation": generation})
    while True:
        line = reader.readline(MAX_FRAME + 1)
        if not line:
            break
        request = validate_frame(line)
        if request["generation"] != generation or request["sequence"] != sequence + 1:
            raise ValueError("stale request")
        sequence = request["sequence"]
        operation = request["operation"]
        arguments = request["arguments"]
        if operation == "status" and not arguments:
            result = engine.status()
        elif operation == "stop" and not arguments:
            reply({"generation": generation, "sequence": sequence, "ok": True})
            break
        else:
            try:
                result = engine.dispatch(operation, arguments)
            except MutationUnverifiedError as error:
                result = error.result
            except (ValueError, OSError, TimeoutError):
                result = {
                    "ok": False,
                    "reason": "action_refused",
                    "scene_generation": engine.generation,
                }
        reply({"generation": generation, "sequence": sequence, "result": result})


def main() -> None:
    # These descriptors and generation are created by Controller, never a tool input.
    request_fd, reply_fd = int(sys.argv[1]), int(sys.argv[2])
    generation = sys.argv[3]
    workspace_fd = int(sys.argv[4])
    del sys.argv[1:5]
    from isaacsim import SimulationApp

    app = SimulationApp(
        {"headless": True, "disable_viewport_updates": True},
        experience=str(RUNTIME / "apps/isaacsim.exp.base.python.kit"),
    )
    from .actions import ActionEngine
    from .artifacts import RevisionStore
    from .scene import NativeScene

    scene = NativeScene(app)
    engine = ActionEngine(
        scene,
        Path(__file__).resolve().parents[1] / ".venv/assets/so101",
        Path.cwd(),
        revision_store=RevisionStore(workspace_fd, generation),
    )
    reader = os.fdopen(request_fd, "rb", buffering=0)
    writer = os.fdopen(reply_fd, "wb", buffering=0)
    try:
        serve_frames(reader, writer, generation, engine)
    finally:
        reader.close()
        writer.close()
        os.close(workspace_fd)
        app.close()


if __name__ == "__main__":
    main()
