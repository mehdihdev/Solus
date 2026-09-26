"""Safe read-only projection of the authenticated application bridge."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from solus_api.agent.tools.tool import Tool
from solus_api.bridge.registry import BridgeSession, BridgeSessionRegistry, ScopeKey


class IsaacConnectionStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    bridge: Literal["connected", "unavailable"] = "unavailable"
    installation: Literal["installed", "unknown"] = "unknown"
    owned_session: Literal["running", "not_running", "unknown"] = "unknown"
    streaming: Literal["none"] = "none"
    reason: (
        Literal[
            "bridge_unavailable",
            "capability_unavailable",
            "observation_failed",
            "runtime_unverified",
        ]
        | None
    ) = "bridge_unavailable"


class IsaacConnectionEnvelope(BaseModel):
    data: IsaacConnectionStatus


async def observe_connection(
    registry: BridgeSessionRegistry,
    scope: ScopeKey,
    captured: BridgeSession,
    tools: Sequence[Tool],
    *,
    timeout: float = 6,
) -> IsaacConnectionStatus:
    if registry.get(*scope) is not captured:
        return IsaacConnectionStatus()
    reads = {
        tool.descriptor.name: tool
        for tool in tools
        if tool.descriptor.name in {"isaac.probe", "isaac.status"}
    }
    if set(reads) != {"isaac.probe", "isaac.status"}:
        return IsaacConnectionStatus(bridge="connected", reason="capability_unavailable")
    try:
        probe, status = await asyncio.wait_for(
            asyncio.gather(
                reads["isaac.probe"].invoke({}),
                reads["isaac.status"].invoke({}),
                return_exceptions=True,
            ),
            timeout,
        )
    except TimeoutError:
        probe = status = TimeoutError()
    if registry.get(*scope) is not captured:
        return IsaacConnectionStatus()
    return _project(probe, status)


def _project(probe: Any, status: Any) -> IsaacConnectionStatus:
    installation: Literal["installed", "unknown"] = "unknown"
    running: Literal["running", "not_running", "unknown"] = "unknown"
    if isinstance(probe, dict) and probe.get("available") is True:
        installation = "installed"
    if isinstance(status, dict):
        if status.get("state") == "running":
            running = "running"
        elif status.get("state") == "stopped":
            running = "not_running"
    observed = isinstance(probe, dict) and type(probe.get("available")) is bool
    reason: Literal["observation_failed", "runtime_unverified"] | None = None
    if not observed or running == "unknown":
        reason = "observation_failed"
    elif installation == "unknown":
        reason = "runtime_unverified"
    return IsaacConnectionStatus(
        bridge="connected", installation=installation, owned_session=running, reason=reason
    )
