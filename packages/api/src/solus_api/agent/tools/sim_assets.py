"""The shared model push (SOLUSDEV-322 P4-T2, factored out of the P3-T4 `gazebo.spawn` path).

A graph-bound `simulation_model` (v2) lives in the artifact store; a companion simulator spawns
it from its own verified store (`.solus/sim/models/<sha256>/`). When the companion reports the
model absent (`{ok: false, code: "model_not_verified"}` from its dry run) the owning wrapper
streams the files across the bridge as `put_asset` chunks: ≤ 64 KiB raw (≤ 96 KiB base64, under
the bridge call cap), chunk 0 carrying the manifest, every byte verified against the manifest
digest before it leaves. The fork promotes the directory only when everything matches.

Vendor-neutral by construction: the wrapper hands in the sender (its own raw `put_asset`
capability's invoke) so this module never touches a tool object or names a simulator.
Companion results are data: :func:`without_claims` drops any ownership field a fork returns and
makes every refusal say why in one sentence SOL can repeat (P7-T2); :func:`reaching` turns the
bridge's bare "bridge offline" into that same kind of sentence.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import uuid
from collections.abc import Awaitable, Callable, Iterator, Mapping
from typing import Any, Final, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.agent.tools.isaac_models import SimulationModel
from solus_api.agent.tools.shapes import ToolErrorCode
from solus_api.agent.tools.tool import ToolException
from solus_api.models import Artifact, GraphEntity
from solus_api.storage.artifact_store import ArtifactNotFoundError, ArtifactStore

#: One `put_asset` chunk: ≤ 64 KiB raw, which base64 keeps under the 96 KiB field bound.
CHUNK_BYTES: Final = 64 * 1024
MAX_DATA_B64: Final = 96 * 1024
MAX_FILE_BYTES: Final = 20_000_000
MAX_TOTAL_BYTES: Final = 32_000_000
MODEL_NOT_VERIFIED: Final = "model_not_verified"
#: Companion ownership claims: dropped from every result (reads included) before SOL sees it.
CLAIMS: Final = frozenset({"owned", "owner", "owned_by"})
#: A companion refusal `code` is quoted to SOL only in this shape; anything else reads "refused".
_REFUSAL_CODE = re.compile(r"[a-z_]{1,48}")
#: An absolute path inside companion text: never repeated to SOL, whatever the fork redacted.
_ABSOLUTE_PATH = re.compile(r"(?<![\w.])/[\w./-]+")
_REASON_CAP: Final = 200
#: What SOL repeats when the companion has no live bridge session (contract §3: "bridge offline").
OFFLINE: Final = "The companion is offline (bridge offline); reconnect it and try again."

#: The wrapper's own `put_asset` capability, as a plain awaitable: chunk args → the fork's ack.
SendChunk = Callable[[dict[str, Any]], Awaitable[Any]]


class BoundModel(Protocol):
    """What the push needs from a resolved graph model (`isaac_tools._Graph` satisfies it)."""

    @property
    def model_id(self) -> str: ...

    @property
    def model(self) -> SimulationModel: ...


def _push_refuse(message: str) -> ToolException:
    return ToolException(message, code=ToolErrorCode.TOOL_ERROR, retryable=False)


def refusal_code(ack: Any) -> str:
    code = ack.get("code") if isinstance(ack, dict) else None
    return code if isinstance(code, str) and _REFUSAL_CODE.fullmatch(code) else "refused"


def refusal_sentence(result: Mapping[str, Any]) -> str:
    """One SOL-repeatable sentence for a companion refusal: its own `reason` on one line, with
    no absolute path, capped and ended with a period; a bare code (or no reason) names the code."""
    reason = result.get("reason")
    text = " ".join(str(reason).split()) if isinstance(reason, str) else ""
    text = _ABSOLUTE_PATH.sub("<path>", text)[:_REASON_CAP].rstrip(" .")
    if not text or _REFUSAL_CODE.fullmatch(text):
        return f"The companion refused the action ({text or refusal_code(result)})."
    return text[0].upper() + text[1:] + "."


def without_claims(result: dict[str, Any]) -> dict[str, Any]:
    """Companion results are data: whatever a fork says about ownership never reaches SOL (the
    bridge already guarantees a dict — `ToolResult.value`), and a refusal always says why."""
    cleaned = {key: value for key, value in result.items() if key not in CLAIMS}
    if cleaned.get("ok") is False:
        cleaned["reason"] = refusal_sentence(cleaned)
    return cleaned


async def reaching[T](call: Awaitable[T]) -> T:
    """Await a companion-backed call; a dead bridge answers :data:`OFFLINE` instead of the
    contract's bare "bridge offline", same code and retryability."""
    try:
        return await call
    except ToolException as exc:
        if exc.code is not ToolErrorCode.UNAVAILABLE:
            raise
        raise ToolException(OFFLINE, code=exc.code, retryable=exc.retryable) from None


def consent_row(label: str, after: str) -> dict[str, Any]:
    return {"label": label, "before": None, "after": after[:400]}


def model_not_verified(plan: Any) -> bool:
    return (
        isinstance(plan, dict)
        and plan.get("ok") is False
        and plan.get("code") == MODEL_NOT_VERIFIED
    )


def chunk_count(size: int) -> int:
    return max(1, math.ceil(size / CHUNK_BYTES))


def pieces(data: bytes) -> Iterator[bytes]:
    if not data:
        yield b""
    for offset in range(0, len(data), CHUNK_BYTES):
        yield data[offset : offset + CHUNK_BYTES]


class ModelPush:
    """Streams a graph-bound model's files to the companion store, verified before they leave."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        project_id: uuid.UUID,
        artifacts: ArtifactStore | None,
    ) -> None:
        self.sessions = sessions
        self.project_id = project_id
        self.artifacts = artifacts

    async def _artifact_ids(self, graph: BoundModel) -> dict[str, Any]:
        """`attrs.artifacts = {urdf: <artifact id>, meshes: {<path>: <artifact id>}}` written by
        the model generation job (plan P6-T2), keyed back by manifest path."""
        async with self.sessions() as session:
            attrs = await session.scalar(
                select(GraphEntity.attrs).where(
                    GraphEntity.id == uuid.UUID(graph.model_id),
                    GraphEntity.project_id == self.project_id,
                    GraphEntity.deleted_at.is_(None),
                )
            )
        artifacts = attrs.get("artifacts") if isinstance(attrs, dict) else None
        if not isinstance(artifacts, dict):
            return {}
        meshes = artifacts.get("meshes")
        ids = dict(meshes) if isinstance(meshes, dict) else {}
        ids[graph.model.asset.urdf_path] = artifacts.get("urdf")
        return ids

    async def rows(self, graph: BoundModel) -> list[tuple[str, Artifact]]:
        """One live, project-scoped artifact row per manifest file, or a refusal."""
        asset = graph.model.asset
        if "/" in asset.urdf_path:
            raise _push_refuse(
                "The simulator needs the model file at the top level of its manifest; "
                "regenerate it."
            )
        if self.artifacts is None:
            raise _push_refuse("The artifact store is unavailable; the model cannot be pushed.")
        ids = await self._artifact_ids(graph)
        rows: list[tuple[str, Artifact]] = []
        async with self.sessions() as session:
            for path in sorted(asset.files):
                try:
                    artifact_id = uuid.UUID(str(ids.get(path)))
                except ValueError:
                    raise _push_refuse(
                        f"No stored file for {path}; regenerate the model."
                    ) from None
                row = await session.scalar(
                    select(Artifact).where(
                        Artifact.id == artifact_id,
                        Artifact.project_id == self.project_id,
                        Artifact.deleted_at.is_(None),
                    )
                )
                if row is None:
                    raise _push_refuse(f"No stored file for {path}; regenerate the model.")
                if (row.size_bytes or 0) > MAX_FILE_BYTES:
                    raise _push_refuse("A model file exceeds the companion store's size bound.")
                rows.append((path, row))
        # Checked here, before any preview: the refusal comes before the card, never after it.
        if sum(row.size_bytes or 0 for _, row in rows) > MAX_TOTAL_BYTES:
            raise _push_refuse("The model exceeds the companion store's size bound.")
        return rows

    async def preview(
        self, graph: BoundModel, native: Mapping[str, Any]
    ) -> tuple[list[dict[str, Any]], str]:
        """The card body when the companion lacks the model: what spawns, and what is pushed
        first. The fork's own preview runs after the push, right before the native call."""
        rows = await self.rows(graph)
        sizes = [row.size_bytes or 0 for _, row in rows]
        asset = graph.model.asset
        chunks = sum(chunk_count(size) for size in sizes)
        preview = [
            consent_row(
                "Model", f"{asset.urdf_path} ({asset.sha256[:16]}…, {len(asset.files)} files)"
            ),
            consent_row("Name in world", str(native["name"])),
            consent_row("Pose", f"xyz={native['pose']['xyz']} rpy={native['pose']['rpy']}"),
            consent_row("Session", str(native["session_id"])),
            consent_row(
                "Model push",
                f"{chunks} chunk(s), {sum(sizes)} bytes into the companion's "
                f".solus/sim/models/{asset.sha256[:16]}…, verified by manifest before use",
            ),
        ]
        canonical = json.dumps(["push", dict(native), sizes], sort_keys=True, separators=(",", ":"))
        return preview, hashlib.sha256(canonical.encode()).hexdigest()

    async def _fetch(
        self, rows: list[tuple[str, Artifact]], manifest: Mapping[str, str]
    ) -> list[tuple[str, bytes]]:
        assert self.artifacts is not None  # `rows` refused already
        files: list[tuple[str, bytes]] = []
        total = 0
        for path, row in rows:
            try:
                data = await self.artifacts.get(str(row.id))
            except ArtifactNotFoundError:
                raise _push_refuse(f"No stored file for {path}; regenerate the model.") from None
            if hashlib.sha256(data).hexdigest() != manifest[path]:
                raise _push_refuse("A stored model file no longer matches its manifest digest.")
            total += len(data)
            if len(data) > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
                raise _push_refuse("The model exceeds the companion store's size bound.")
            files.append((path, data))
        return files

    async def send(self, graph: BoundModel, put: SendChunk | None) -> None:
        if put is None:
            raise _push_refuse("The companion offers no put_asset; the model cannot be pushed.")
        asset = graph.model.asset
        files = await self._fetch(await self.rows(graph), asset.files)
        total = sum(chunk_count(len(data)) for _, data in files)
        index = 0
        ack: Any = None
        for path, data in files:
            for piece in pieces(data):
                args: dict[str, Any] = {
                    "sha256": asset.sha256,
                    "path": path,
                    "index": index,
                    "total": total,
                    "data_b64": base64.b64encode(piece).decode("ascii"),
                }
                if index == 0:
                    args["manifest"] = dict(asset.files)
                ack = await put(args)
                if not isinstance(ack, dict) or ack.get("ok") is not True:
                    raise _push_refuse(
                        f"The companion refused model chunk {index}: {refusal_code(ack)}."
                    )
                index += 1
        if not isinstance(ack, dict) or ack.get("promoted") is not True:
            raise _push_refuse("The companion did not verify the pushed model.")
