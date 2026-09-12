"""Gated `.solus` write tools (SOLUSDEV-252 S5, docs/api/solus.md §6.1).

`add_solus_entry` appends; these three CHANGE what a team already recorded, so each is
confirmation-gated (CLAUDE.md §7: mutating or deleting graph-backed data) with a
Solus-authored consent sentence and a `preview` that shows the exact edit as
`{label, before, after}` rows (docs/contracts/action-gate.md). Nothing runs before a
person approves the card; the gate re-runs `preview` at decision time, so a row that
moved underneath the card is STALE, not executed.

Scope is bound HERE by Solus code (the `get_entity` idiom): `project_id` and `user_id`
are closure variables, never arguments. An entry or robot in another project answers
NOT_FOUND — no existence oracle.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.agent.tools.registry import ToolRegistry
from solus_api.agent.tools.shapes import ToolDescriptor, ToolErrorCode
from solus_api.agent.tools.tool import InProcessTool, ToolException
from solus_api.core.errors import APIError
from solus_api.hardware.config import EntityHardwareConfig, FieldProvenance
from solus_api.hardware.ownership import current_parent
from solus_api.hardware.store import (
    hardware_entity,
    put_entity_config,
    read_entity_config,
    robot_root,
)
from solus_api.models import GraphEntity, SolusEntry
from solus_api.services.code_env import (
    CodeEnvironment,
    EnvironmentProvenance,
    upsert_code_environment,
)
from solus_api.services.code_environment_adapter import EnvironmentFetch
from solus_api.services.solus_config import MAX_TEXT_CHARS, delete_entry, get_entry, update_text
from solus_api.services.solus_graph import lock_project
from solus_api.storage import ArtifactStore

_PREVIEW_CAP = 500
_UNSET = "(unset)"
_SOL_SOURCE = "sol turn"
_MAX_FIELD_PREVIEWS = 16
#: Never model-settable: identity and the provenance ledger itself.
_RESERVED_ROOTS = frozenset({"schema_version", "robot_entity_id", "entity_id", "provenance"})
_PATH_PATTERN = r"^[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+)*$"
_UUID = {"type": "string", "format": "uuid"}
_OK = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}

Scalar = str | int | float | bool | None


def _api_error_to_tool(exc: APIError) -> ToolException:
    code = ToolErrorCode.NOT_FOUND if exc.status_code == 404 else ToolErrorCode.INVALID_ARGS
    return ToolException(exc.message, code=code)


def _shown(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value)
    return text[:_PREVIEW_CAP]


# --------------------------------------------------------------- dotted paths


def _descend(node: Any, segment: str, path: str) -> Any:
    if isinstance(node, dict):
        if segment not in node:
            raise ToolException(f"{path}: no such field", code=ToolErrorCode.INVALID_ARGS)
        return node[segment]
    if isinstance(node, list):
        if not segment.isdigit() or int(segment) >= len(node):
            raise ToolException(f"{path}: no such index", code=ToolErrorCode.INVALID_ARGS)
        return node[int(segment)]
    raise ToolException(f"{path}: cannot descend into a value", code=ToolErrorCode.INVALID_ARGS)


def _leaf_parent(document: dict[str, Any], path: str) -> tuple[Any, str]:
    """The container holding the leaf `path` names, and the leaf's own key. Only the LEAF
    may be new — intermediate containers must exist, so SOL cannot conjure a part or a bus."""
    segments = path.split(".")
    if segments[0] in _RESERVED_ROOTS:
        raise ToolException(f"{path}: not a settable field", code=ToolErrorCode.INVALID_ARGS)
    node: Any = document
    for segment in segments[:-1]:
        node = _descend(node, segment, path)
    if not isinstance(node, dict | list):
        raise ToolException(f"{path}: cannot descend into a value", code=ToolErrorCode.INVALID_ARGS)
    return node, segments[-1]


def _leaf_value(document: dict[str, Any], path: str) -> Any:
    parent, key = _leaf_parent(document, path)
    try:
        return _descend(parent, key, path)
    except ToolException:
        return _UNSET


def _set_leaf(document: dict[str, Any], path: str, value: Scalar) -> None:
    parent, key = _leaf_parent(document, path)
    if isinstance(parent, list):
        _descend(parent, key, path)  # the index must exist — a list is never grown here
        parent[int(key)] = value
        return
    if isinstance(parent.get(key), dict | list):
        raise ToolException(
            f"{path}: is a group of fields, not a value", code=ToolErrorCode.INVALID_ARGS
        )
    parent[key] = value


# --------------------------------------------------------------------- tools


@dataclass
class _FieldDocument:
    subject: GraphEntity
    document: dict[str, Any]
    path: str
    version: int
    entry_id: uuid.UUID

    def revision(self) -> tuple[uuid.UUID, int, uuid.UUID, int]:
        return self.subject.id, self.subject.version, self.entry_id, self.version


def _field_key(args: dict[str, Any]) -> str:
    return json.dumps(args, sort_keys=True, separators=(",", ":"), allow_nan=False)


async def _field_target(
    session: AsyncSession, project_id: uuid.UUID, robot: GraphEntity, path: str
) -> tuple[GraphEntity, str]:
    if path.startswith("parts."):
        segments = path.split(".", 2)
        if len(segments) != 3:
            raise ToolException("A part field is required", code=ToolErrorCode.INVALID_ARGS)
        try:
            part_id = uuid.UUID(segments[1])
        except ValueError:
            raise ToolException(
                "A part UUID is required", code=ToolErrorCode.INVALID_ARGS
            ) from None
        part = await hardware_entity(session, project_id, part_id)
        parent_id = await current_parent(session, project_id, part.id)
        parent = await session.get(GraphEntity, parent_id) if parent_id is not None else None
        if parent is None or (
            parent.id != robot.id and parent.attrs.get("robot_id") != str(robot.id)
        ):
            raise ToolException("Part is not owned by this robot", code=ToolErrorCode.INVALID_ARGS)
        return part, "component." + segments[2]
    return robot, "component." + path if path == "firmware" or path.startswith(
        "firmware."
    ) else path


class _SolusWriter:
    """The three handlers and their previews, bound to ONE project and user."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        store: ArtifactStore,
        project_id: uuid.UUID,
        user_id: uuid.UUID | None,
    ) -> None:
        self._sessions = session_factory
        self._store = store
        self._project_id = project_id
        self._user_id = user_id
        # Consistency snapshots only; approval authority remains in the confirmation gate.
        self._field_previews: dict[str, tuple[uuid.UUID, int, uuid.UUID, int]] = {}

    async def _entry(self, session: AsyncSession, args: dict[str, Any]) -> SolusEntry:
        try:
            return await get_entry(session, self._project_id, uuid.UUID(str(args["entry_id"])))
        except APIError as exc:
            raise _api_error_to_tool(exc) from None

    async def edit_preview(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        async with self._sessions() as session:
            entry = await self._entry(session, args)
        return [
            {"label": "Entry", "before": _shown(entry.text or ""), "after": _shown(args["text"])}
        ]

    async def edit(self, args: dict[str, Any]) -> dict[str, Any]:
        async with self._sessions() as session:
            entry = await self._entry(session, args)
            try:
                await update_text(session, entry, str(args["text"]))
            except APIError as exc:
                raise _api_error_to_tool(exc) from None
            await session.commit()
        return {"ok": True}

    async def delete_preview(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        async with self._sessions() as session:
            entry = await self._entry(session, args)
        return [{"label": "Entry", "before": _shown(entry.text or ""), "after": None}]

    async def delete(self, args: dict[str, Any]) -> dict[str, Any]:
        async with self._sessions() as session:
            entry = await self._entry(session, args)
            await delete_entry(session, self._store, entry)
            await session.commit()
        return {"ok": True}

    async def _document(self, session: AsyncSession, args: dict[str, Any]) -> _FieldDocument:
        try:
            robot = await robot_root(
                session, self._project_id, uuid.UUID(str(args["robot_entity_id"]))
            )
            subject, path = await _field_target(session, self._project_id, robot, str(args["path"]))
            entry, config = await read_entity_config(session, self._project_id, subject.id)
            if entry is None or config is None:
                raise APIError(404, "not_found", "Hardware config not found")
        except APIError as exc:
            raise _api_error_to_tool(exc) from None
        return _FieldDocument(
            subject, config.model_dump(mode="json"), path, entry.config_version, entry.id
        )

    async def field_preview(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        key = _field_key(args)
        self._field_previews.pop(key, None)
        async with self._sessions() as session:
            field = await self._document(session, args)
        before = _leaf_value(field.document, field.path)
        if len(self._field_previews) >= _MAX_FIELD_PREVIEWS:
            self._field_previews.pop(next(iter(self._field_previews)))
        self._field_previews[key] = field.revision()
        return [
            {
                "label": args["path"],
                "before": before if before == _UNSET else _shown(before),
                "after": _shown(args["value"]),
            },
            {
                "label": "Config version",
                "before": str(field.version),
                "after": str(field.version + 1),
            },
        ]

    async def set_field(self, args: dict[str, Any]) -> dict[str, Any]:
        revision = self._field_previews.pop(_field_key(args), None)
        if revision is None:
            raise ToolException(
                "A current field preview is required", code=ToolErrorCode.UNAUTHORIZED
            )
        async with self._sessions() as session:
            await lock_project(session, self._project_id)
            field = await self._document(session, args)
            if revision != field.revision():
                raise ToolException(
                    "Configuration changed; request a new preview", code=ToolErrorCode.UNAUTHORIZED
                )
            _set_leaf(field.document, field.path, args["value"])
            field.document["provenance"][field.path] = {
                "by": FieldProvenance.SOL.value,
                "source": _SOL_SOURCE,
            }
            try:
                config = EntityHardwareConfig.model_validate(field.document)
            except ValidationError:
                raise ToolException(
                    "Invalid hardware configuration value", code=ToolErrorCode.INVALID_ARGS
                ) from None
            try:
                await put_entity_config(
                    session,
                    self._project_id,
                    field.subject,
                    config,
                    expected_version=field.version,
                    created_by=self._user_id,
                )
            except APIError as exc:
                raise _api_error_to_tool(exc) from None
            await session.commit()
        return {
            "robot_entity_id": str(args["robot_entity_id"]),
            "path": str(args["path"]),
            "value": args["value"],
            "provenance": FieldProvenance.SOL.value,
        }


class _EnvironmentLinker:
    """`link_environment`: record a machine environment in this project's `.solus`.

    SOL creates environments and SOL links them (the S5 spec sentence), but the
    model's part is naming WHICH one. Every recorded fact — interpreter, path,
    packages, host — is read back from the companion's targeted I3 probe
    answer at link time, so an environment can never be filed with a package or
    a path nobody observed (`services/code_env.py`). A name the machine does not
    report is a refusal, not an empty entry: empty beats invented.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        project_id: uuid.UUID,
        user_id: uuid.UUID | None,
        fetch: EnvironmentFetch,
    ) -> None:
        self._sessions = session_factory
        self._project_id = project_id
        self._user_id = user_id
        self._fetch = fetch

    async def _observed(self, name: str) -> CodeEnvironment:
        try:
            answer = await self._fetch(name)
        except ToolException:
            raise
        except Exception as exc:  # noqa: BLE001 — the companion's answer is untrusted
            raise ToolException(
                "could not read the environments on this machine",
                code=ToolErrorCode.UNAVAILABLE,
                retryable=True,
            ) from exc
        found = answer.get("environments") if isinstance(answer, dict) else None
        matches = [
            candidate
            for candidate in (found if isinstance(found, list) else [])
            if isinstance(candidate, dict) and candidate.get("name") == name
        ]
        if len(matches) > 1:
            # A conda env and a workspace venv can share a name. First-wins would
            # link whichever the probe happened to see first, store it under a
            # DIFFERENT identity than the one meant, and then create a second row
            # on the next link. `resolve_environment` refuses the same collision.
            raise ToolException(
                f"several environments on this machine are named {name!r}; "
                "say which one by its path",
                code=ToolErrorCode.INVALID_ARGS,
            )
        for candidate in matches:
            try:
                observed = CodeEnvironment.model_validate(candidate)
            except ValidationError as exc:
                raise ToolException(
                    f"the machine's description of {name!r} is not a code environment",
                    code=ToolErrorCode.TOOL_ERROR,
                ) from exc
            # Provenance is SET here, never accepted: the companion is untrusted
            # and could claim `user` for something a person never typed. What
            # actually happened is that SOL filed a machine reading, and that is
            # the one value this path may record.
            return observed.model_copy(update={"provenance": EnvironmentProvenance.SOL})
        raise ToolException(
            f"no environment named {name!r} on this machine", code=ToolErrorCode.NOT_FOUND
        )

    async def preview(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        env = await self._observed(str(args["name"]))
        # The package IDENTITIES, not just a count: the rows are what the gate
        # compares at decision time, so a count alone let an install between
        # parking and approval rewrite every recorded version with no staleness
        # refusal. The 500-char row cap truncates a long list, which still moves
        # when the head of the list moves.
        listed = ", ".join(f"{pin.name} {pin.version or '?'}" for pin in env.packages)
        rows = [
            {"label": "type", "before": None, "after": env.type.value},
            {"label": "name", "before": None, "after": env.name},
            {
                "label": "packages",
                "before": None,
                "after": _shown(f"{len(env.packages)} recorded: {listed}" if listed else "none"),
            },
        ]
        for label, value in (
            ("interpreter", env.interpreter),
            ("path", env.path),
            ("image", env.image),
            ("python", env.version),
        ):
            if value:
                rows.append({"label": label, "before": None, "after": _shown(value)})
        return rows

    async def link(self, args: dict[str, Any]) -> dict[str, Any]:
        env = await self._observed(str(args["name"]))
        async with self._sessions() as session:
            try:
                entry = await upsert_code_environment(
                    session, self._project_id, env, created_by=self._user_id, author="sol"
                )
            except APIError as exc:
                raise _api_error_to_tool(exc) from None
            await session.commit()
            return {
                "entry_id": str(entry.id),
                "type": env.type.value,
                "name": env.name,
                "packages": len(env.packages),
            }


def register_solus_write_tools(
    registry: ToolRegistry,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    store: ArtifactStore,
    project_id: uuid.UUID,
    user_id: uuid.UUID | None,
    fetch_environments: EnvironmentFetch | None = None,
) -> None:
    """Register the gated `.solus` writers, bound to ONE project and user.

    `fetch_environments` adapts the live targeted `code.probe_environment` read, supplied by
    the runtime only when a companion is connected. Without it there is nothing
    to link and `link_environment` is not offered — a tool that could only ever
    answer "no machine" is worse than an absent one.
    """
    writer = _SolusWriter(session_factory, store, project_id, user_id)
    _register_gated(
        registry,
        name="edit_solus_entry",
        description=(
            "Replace the text of a note in this project's .solus (text or SOL-filed entries "
            "only; imported files and configs cannot be edited this way). The person approves "
            "the exact before/after first."
        ),
        consent="Edit a note in this project's .solus",
        params={
            "entry_id": _UUID,
            "text": {"type": "string", "minLength": 1, "maxLength": MAX_TEXT_CHARS},
        },
        returns=_OK,
        handler=writer.edit,
        preview=writer.edit_preview,
    )
    _register_gated(
        registry,
        name="delete_solus_entry",
        description=(
            "Remove an entry from this project's .solus — its graph node too, and for an "
            "imported file its stored bytes. Irreversible; the person approves first."
        ),
        consent="Remove an entry from this project's .solus (a file's stored bytes go too)",
        params={"entry_id": _UUID},
        returns=_OK,
        handler=writer.delete,
        preview=writer.delete_preview,
    )
    _register_gated(
        registry,
        name="set_hardware_config_field",
        description=(
            "Set ONE scalar field of a Physical Robot's hardware config by dotted path, e.g. "
            "'parts.<part entity id>.firmware.baud', 'parts.<id>.lifecycle', "
            "'bus_map.0.address', 'firmware.board_rev'. The containing group must already "
            "exist. These paths map to the owner or owned part’s independent v2 component. "
            "Schema/entity identity and provenance fields cannot be set. The field is recorded as "
            "set by SOL. Only set a value you have a source for."
        ),
        consent="Change one field of this robot's hardware config",
        params={
            "robot_entity_id": _UUID,
            "path": {"type": "string", "pattern": _PATH_PATTERN, "maxLength": 256},
            "value": {"type": ["string", "number", "integer", "boolean", "null"]},
        },
        returns={
            "type": "object",
            "properties": {
                "robot_entity_id": _UUID,
                "path": {"type": "string"},
                "value": {},
                "provenance": {"type": "string"},
            },
            "required": ["robot_entity_id", "path", "value", "provenance"],
        },
        handler=writer.set_field,
        preview=writer.field_preview,
    )
    if fetch_environments is None:
        return
    linker = _EnvironmentLinker(session_factory, project_id, user_id, fetch_environments)
    _register_gated(
        registry,
        name="link_environment",
        description=(
            "Record a workspace code environment in the project's .solus. Pass its relative "
            "path as name (for example sim); link time reads code.probe_environment with "
            "environment set to that target. Only observed interpreter, path and package "
            "facts are recorded; unavailable observations refuse the link. You cannot "
            "supply those facts. Linking the same environment updates its entry in place."
        ),
        consent="Record one of this machine's code environments in this project's .solus",
        params={"name": {"type": "string", "minLength": 1, "maxLength": 128}},
        returns={
            "type": "object",
            "properties": {
                "entry_id": _UUID,
                "type": {"type": "string"},
                "name": {"type": "string"},
                "packages": {"type": "integer"},
            },
            "required": ["entry_id", "type", "name", "packages"],
        },
        handler=linker.link,
        preview=linker.preview,
    )


def _register_gated(
    registry: ToolRegistry,
    *,
    name: str,
    description: str,
    consent: str,
    params: dict[str, Any],
    returns: dict[str, Any],
    handler: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
    preview: Callable[[dict[str, Any]], Awaitable[list[dict[str, Any]]]],
) -> None:
    descriptor = ToolDescriptor(
        name=name,
        description=description,
        params={
            "type": "object",
            "properties": params,
            "required": list(params),
            "additionalProperties": False,
        },
        returns=returns,
        requires_confirmation=True,
        consent_summary=consent,
    )
    registry.register(InProcessTool(descriptor, handler, preview))


__all__ = ["register_solus_write_tools"]
