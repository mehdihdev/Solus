"""Prepare private, ephemeral driver input after authenticated graph resolution — and the ONE
opener every hardware session goes through (SOLUSDEV-326).

The bench route (`provider: robot|hardware`), the confirm-and-connect coordinator and the session
an accepted device suggestion starts all open a subject the same way: `plan_session` (graph half:
the host check, the config, its brains) then `prepare_session` (private half, no database: one v1
driver document per brain this host can open) then `SessionOpener.open` (inside the session
manager): each brain is opened; one that cannot be is reported as unreachable, never fatal unless
no brain opens. A robot is one session — one connection over its brains, one window evaluator.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.connectors.live import BatchCallback, LiveStatus
from solus_api.core.errors import APIError
from solus_api.hardware.config import (
    EntityHardwareConfig,
    HardwareConfig,
    TransportKind,
    is_private_source,
)
from solus_api.hardware.local_sources import LocalHardwareSources, LocalSourceError
from solus_api.hardware.runtime import RuntimeConfig, brains_of, resolve_runtime_config
from solus_api.hardware.store import ROBOT_KIND, read_entity_config
from solus_api.livebench.sessions import (
    AmbiguousDeviceError,
    DeviceBusyError,
    DeviceNotFoundError,
    TappableConnection,
)
from solus_api.models import GraphEntity

logger = logging.getLogger(__name__)

NO_BRAIN = (
    "The hardware's config has no transport identity or protocol yet — detect it or configure "
    "it before starting a session."
)
_UNBOUND = "No device is bound to this brain yet."
_NO_DRIVER = "This brain has no driver yet."
_REMOTE = "This brain is reached through another computer."


async def open_local_hardware(
    runner: Any, document: dict[str, Any], project_id: uuid.UUID, user_id: uuid.UUID
) -> Any:
    """Never let a driver echo private input into API errors or traceback logs. The device is
    claimed for `user_id`, the requesting member (SOLUSDEV-326 serial owner)."""
    try:
        return await runner.open_robot(document, project_id=project_id, user_id=user_id)
    except AmbiguousDeviceError:
        raise APIError(
            409, "device_ambiguous", "More than one device matches; select it again."
        ) from None
    except DeviceNotFoundError:
        raise APIError(404, "device_not_found", "The configured device is not connected.") from None
    except DeviceBusyError as exc:  # SOLUSDEV-326: busy is never "could not be started"
        raise APIError(409, "device_busy", str(exc), details=exc.details()) from None
    except ValueError:
        raise APIError(
            422, "validation_error", "The hardware configuration could not open this device."
        ) from None
    except Exception as exc:
        logger.warning("hardware open failed: project=%s error=%s", project_id, type(exc).__name__)
        raise APIError(
            503, "source_unavailable", "The hardware session could not be started."
        ) from None


def prepare_local_hardware(
    runner: object | None,
    config: HardwareConfig,
    project_id: uuid.UUID,
    account_id: uuid.UUID,
    entry_id: uuid.UUID,
    *,
    owner_config: EntityHardwareConfig | None = None,
    hint: bool = True,
) -> dict[str, Any]:
    """Verify file evidence without replacing stored values or authorizing a port.

    Run off-loop. Only the local driver receives the returned document; callers
    must construct response/session metadata from the original portable config.
    A last-seen hint is never a confirmed_device_path or reconnect permission.

    The driver gets ONE brain (SOLUSDEV-326): the first of `config`'s. The entry's one port hint
    belongs to its first brain; `hint=False` (brains 2..N) gets none.
    """
    config = brains_of(config)[0]
    try:
        reader = LocalHardwareSources.for_local_runner(runner)
        references: set[str] = set()
        components = list(config.parts.values())
        if owner_config is not None and owner_config.component is not None:
            components.append(owner_config.component)
        for part in components:
            source = part.calibration.source if part.calibration is not None else None
            if source is not None and is_private_source(source):
                raise LocalSourceError("relink_required")
            if source is not None and source.startswith("source:"):
                references.add(source)
        for reference in references:
            reader.read_source(project_id, account_id, reference)
        found = reader.binding_hint(project_id, account_id, entry_id) if hint else None
    except LocalSourceError as exc:
        if exc.code == "source_unavailable":
            raise APIError(503, exc.code, "The local hardware runner is unavailable.") from None
        if exc.code == "source_changed":
            raise APIError(
                409,
                exc.code,
                "A calibration source changed. Review and relink it before connecting.",
            ) from None
        raise APIError(
            422,
            "relink_required",
            "Relink the calibration source in this account before connecting.",
        ) from None
    document = config.model_dump(mode="json")
    if document["identity"] is not None:
        document["identity"]["last_seen_path"] = (
            found
            if config.identity is not None and config.identity.kind is TransportKind.USB_SERIAL
            else None
        )
    return document


@dataclass(frozen=True)
class SessionPlan:
    """What the graph says one hardware subject's session opens, read in the caller's session."""

    project_id: uuid.UUID
    subject_id: uuid.UUID
    name: str
    robot: bool
    entry_id: uuid.UUID
    config: RuntimeConfig
    owner: EntityHardwareConfig


async def plan_session(
    local: Any, session: AsyncSession, project_id: uuid.UUID, subject: GraphEntity
) -> SessionPlan:
    """The graph half of every start path: a robot confirmed on another machine opens only
    there, and a subject none of whose brains has a device and a driver opens nowhere."""
    bound = subject.attrs.get("host_machine_id")
    if bound is not None:
        from solus_api.hardware.host_topology import LocalHostProvider  # imports the route stack

        host = await LocalHostProvider(local).identity()
        if host is not None and host != bound:
            raise APIError(
                409,
                "host_mismatch",
                "This robot is bound to another host machine; start the session there",
                details=[{"host_machine_id": bound, "local_host_id": host}],
            )
    config = await resolve_runtime_config(session, project_id, subject.id)
    if not any(b.identity is not None and b.protocol is not None for b in config.per_brain()):
        raise APIError(422, "validation_error", NO_BRAIN)
    entry, owner = await read_entity_config(session, project_id, subject.id)
    if entry is None or owner is None:
        raise APIError(422, "validation_error", "Configure this hardware before connecting.")
    return SessionPlan(
        project_id, subject.id, subject.name, subject.kind == ROBOT_KIND, entry.id, config, owner
    )


def _with_own_channels(brain: HardwareConfig, owner: EntityHardwareConfig) -> HardwareConfig:
    """A part bound on its own streams its own channels: its component joins the driver input
    as a part keyed by itself (unrouted, so its signals go out under the device's own key)."""
    if owner.component is None:
        return brain
    key = str(owner.entity_id)
    document = brain.model_dump(mode="json")
    document["parts"][key] = owner.component.model_dump(mode="json")
    document["provenance"].update(
        {
            f"parts.{key}" + path.removeprefix("component"): record.model_dump(mode="json")
            for path, record in owner.provenance.items()
            if path == "component" or path.startswith("component.")
        }
    )
    return HardwareConfig.model_validate(document)


def _unopenable(brain: HardwareConfig, via: str | None) -> str | None:
    """Why this host does not open a brain, or None."""
    if brain.identity is None:
        return _UNBOUND
    if via is not None:
        return _REMOTE
    return _NO_DRIVER if brain.protocol is None else None


@dataclass
class SessionOpener:
    """One subject's session, prepared: the private driver document of each brain this host can
    open, and why each other brain is unreachable. `device` is the session's device record — the
    one the session manager keeps — and `open` completes it with the brains it could not reach,
    before the session is first read. Every brain is opened for `account_id`, the requesting
    member."""

    plan: SessionPlan
    local: Any
    account_id: uuid.UUID
    label: str
    device: dict[str, Any]
    documents: list[tuple[int, str, dict[str, Any]]]
    unreachable: dict[int, tuple[str | None, str]] = field(default_factory=dict)

    @property
    def evaluate(self) -> bool:
        """A robot's session runs its window evaluator; a part bound on its own judges nothing."""
        return self.plan.robot

    async def open(self) -> TappableConnection:
        """Open every prepared brain; one that fails is reported, and only all failing fails."""
        opened: list[TappableConnection] = []
        failures: list[APIError] = []
        for index, ref, document in self.documents:
            try:
                opened.append(
                    await open_local_hardware(
                        self.local, document, self.plan.project_id, self.account_id
                    )
                )
            except APIError as exc:
                failures.append(exc)
                self.unreachable[index] = (ref, exc.message)
        if not opened:
            raise failures[0]
        if self.unreachable:
            self.device["unreachable"] = [
                {"device_ref": ref, "error": error}
                for _, (ref, error) in sorted(self.unreachable.items())
            ]
        return opened[0] if len(opened) == 1 else BrainsConnection(opened)

    def brain_states(self) -> list[dict[str, Any]] | None:
        """Each brain's connection state once open, for a robot of several (None for one)."""
        brains = self.plan.config.per_brain()
        if len(brains) < 2:
            return None
        return [
            {
                "device_ref": brain.identity.device_ref if brain.identity else None,
                "status": "unreachable" if index in self.unreachable else "connected",
                "error": self.unreachable[index][1] if index in self.unreachable else None,
            }
            for index, brain in enumerate(brains)
        ]


async def prepare_session(local: Any, plan: SessionPlan, account_id: uuid.UUID) -> SessionOpener:
    """The private half (no database; files read off-loop): each brain's driver document.
    A brain that cannot be opened from here, or prepared, is reported; none left is fatal."""
    documents: list[tuple[int, str, dict[str, Any]]] = []
    unreachable: dict[int, tuple[str | None, str]] = {}
    failure: APIError | None = None
    for index, (brain, stored) in enumerate(
        zip(plan.config.per_brain(), plan.owner.identity, strict=True)
    ):
        ref = brain.identity.device_ref if brain.identity is not None else None
        reason = _unopenable(brain, stored.via)
        if reason is not None or ref is None:
            unreachable[index] = (ref, reason or _UNBOUND)
            continue
        driver_input = brain if plan.robot else _with_own_channels(brain, plan.owner)
        try:
            document = await asyncio.to_thread(
                prepare_local_hardware,
                local,
                driver_input,
                plan.project_id,
                account_id,
                plan.entry_id,
                owner_config=plan.owner,
                hint=index == 0,
            )
        except APIError as exc:
            failure = failure or exc
            unreachable[index] = (ref, exc.message)
            continue
        documents.append((index, ref, document))
    if not documents:  # `plan_session` saw a brain with a device and a driver: it is remote
        raise failure or APIError(422, "validation_error", min(unreachable.items())[1][1])
    first = plan.config.per_brain()[documents[0][0]]
    identity, protocol = first.identity, first.protocol
    assert identity is not None and protocol is not None  # only openable brains are prepared
    return SessionOpener(
        plan=plan,
        local=local,
        account_id=account_id,
        label=f"Robot {plan.name} ({', '.join(ref for _, ref, _ in documents)})",
        device={
            "device_ref": identity.device_ref,
            "driver_id": protocol.driver_id,
            "serial_number": identity.binding
            if identity.kind is TransportKind.USB_SERIAL
            else None,
            "device_path": identity.last_seen_path,
            "baud": protocol.params.get("baud"),
        },
        documents=documents,
        unreachable=unreachable,
    )


class BrainsConnection:
    """One session's connection over its brains' connections (SOLUSDEV-326): every brain feeds
    the one tap and the one batch callback; the link is its best brain's (one brain down is not
    the robot down); closing closes every brain.

    ponytail: each brain windows its own packets, so `last_summary` is the latest brain's window;
    merge the sources upstream if one summary across brains is ever needed."""

    def __init__(self, connections: Sequence[TappableConnection]) -> None:
        self._connections = tuple(connections)
        self._handles: list[str] = []

    @property
    def tap(self) -> Any:
        return self._connections[0].tap

    @tap.setter
    def tap(self, value: Any) -> None:
        for connection in self._connections:
            connection.tap = value

    @property
    def device_facts(self) -> dict[str, Any]:
        """Each brain's per-device tables, merged (their keys are per-brain device refs)."""
        merged: dict[str, Any] = {}
        for connection in self._connections:
            facts = getattr(connection, "device_facts", None)
            for name in ("channel_roles", "channel_display"):
                table = facts.get(name) if isinstance(facts, dict) else None
                if isinstance(table, dict):
                    merged.setdefault(name, {}).update(table)
        return merged

    async def subscribe(self, window: Any) -> str:
        self._handles = [await connection.subscribe(window) for connection in self._connections]
        return "brains"

    def on_batch(self, handle: str, callback: BatchCallback) -> None:
        for connection, inner in zip(self._connections, self._handles, strict=True):
            connection.on_batch(inner, callback)

    def status(self) -> LiveStatus:
        statuses = {connection.status() for connection in self._connections}
        for status in (LiveStatus.STREAMING, LiveStatus.CONNECTED):
            if status in statuses:
                return status
        return LiveStatus.DISCONNECTED

    async def aclose(self) -> None:
        results = await asyncio.gather(
            *(connection.aclose() for connection in self._connections), return_exceptions=True
        )
        for result in results:
            if isinstance(result, BaseException):
                raise result
