"""Shared pieces of the SOL bench tools (SOLUSDEV-319): tool names, the per-call caller and
scope, card-row and error helpers. docs/api/bench-view.md §6."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from typing import Any, Final

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.agent.preview_refusal import PreviewRefusal
from solus_api.agent.tools.shapes import ToolErrorCode
from solus_api.agent.tools.tool import ToolException
from solus_api.bridge.service import ConnectRateLimiter
from solus_api.core.errors import APIError
from solus_api.deps import live_membership
from solus_api.models import ROLE_RANK, Project, Role, User

READ, DISPLAY, UPSERT, DELETE = (
    "bench_view.read",
    "bench_view.update_display",
    "bench_view.upsert_derived",
    "bench_view.delete_derived",
)
SESSION_START, SESSION_STOP, SETPOINT = (
    "bench.session_start",
    "bench.session_stop",
    "bench.setpoint",
)

CELL_CAP: Final = 200


def cell(value: object, cap: int = CELL_CAP) -> str:
    """One printable line, capped: a card row value from team- or device-authored text."""
    text = "".join(c if c.isprintable() else " " for c in str(value))
    text = " ".join(text.split())
    return text if len(text) <= cap else text[: cap - 1] + "…"


def as_uuid(value: object) -> uuid.UUID:
    """A model-supplied id (JSON Schema `format` is not enforced by the registry)."""
    try:
        return uuid.UUID(str(value))
    except ValueError:
        raise ToolException("id must be a UUID", code=ToolErrorCode.INVALID_ARGS) from None


def row(label: str, after: str | None, before: str | None = None) -> dict[str, Any]:
    return {"label": label, "before": before, "after": after}


def invalid(exc: ValidationError) -> ToolException:
    """Field paths and pydantic's fixed messages only — never the rejected input."""
    parts = [
        f"{'.'.join(str(p) for p in error['loc'])}: {error['msg']}"
        for error in exc.errors(include_input=False, include_url=False)[:3]
    ]
    return ToolException("; ".join(parts) or "invalid arguments", code=ToolErrorCode.INVALID_ARGS)


def api_tool_error(exc: APIError) -> ToolException:
    """A service APIError as a tool error (route doc §6). Details are Solus-composed (codes,
    positions, fixed sentences) and never echo the expression."""
    if exc.status_code == 403:
        return ToolException("Requires member role on this team.", code=ToolErrorCode.UNAUTHORIZED)
    if exc.status_code == 404:
        return ToolException(exc.message, code=ToolErrorCode.NOT_FOUND)
    if exc.status_code == 409:
        return ToolException(exc.message, code=ToolErrorCode.TOOL_ERROR, retryable=True)
    if exc.code == "expression_error":
        spans = [
            f"{d['code']} at {d['position']} (length {d['length']}): {d['message']}"
            for d in (exc.details or [])
        ]
        return ToolException(
            "expression_error: " + "; ".join(spans), code=ToolErrorCode.INVALID_ARGS
        )
    if exc.status_code == 422:
        return ToolException(f"{exc.code}: {exc.message}", code=ToolErrorCode.INVALID_ARGS)
    return ToolException(f"{exc.code}: {exc.message}", code=ToolErrorCode.UNAVAILABLE)


def refusal(exc: ToolException) -> PreviewRefusal:
    return PreviewRefusal(exc.message, code=exc.code)


def rate_limited(limiter: ConnectRateLimiter, key: str, message: str) -> None:
    """Raise the retryable `rate_limited` tool error when `limiter` refuses `key`."""
    if not limiter.allow(key):
        raise ToolException(
            f"rate_limited: {message}", code=ToolErrorCode.UNAVAILABLE, retryable=True
        )


def number(value: float | None, unit: str) -> str:
    if value is None or not math.isfinite(value):
        return "unknown"
    return f"{value:.1f} {unit}".strip()


@dataclass(frozen=True)
class BenchScope:
    project_id: uuid.UUID
    team_id: uuid.UUID
    user_id: uuid.UUID


class Caller:
    """The requesting user inside one tool call: their user row and current team role."""

    def __init__(self, session: AsyncSession, scope: BenchScope) -> None:
        self.session, self.scope = session, scope

    async def user(self) -> User:
        user = await self.session.get(User, self.scope.user_id)
        if user is None:
            raise ToolException("User not found.", code=ToolErrorCode.UNAUTHORIZED)
        return user

    async def role(self) -> Role | None:
        project = await self.session.scalar(
            select(Project.id).where(
                Project.id == self.scope.project_id,
                Project.team_id == self.scope.team_id,
                Project.deleted_at.is_(None),
            )
        )
        if project is None:
            raise ToolException("Project not found.", code=ToolErrorCode.NOT_FOUND)
        membership = await live_membership(self.session, self.scope.team_id, self.scope.user_id)
        return membership.role if membership is not None else None

    async def require_role(self) -> Role:
        """Any live membership (viewers included); none is `unauthorized`."""
        role = await self.role()
        if role is None:
            raise ToolException("Not a member of this team.", code=ToolErrorCode.UNAUTHORIZED)
        return role

    async def require_member(self) -> Role:
        role = await self.role()
        if role is None or ROLE_RANK[role] < ROLE_RANK[Role.MEMBER]:
            raise ToolException(
                "Requires member role on this team; viewers can read the bench only.",
                code=ToolErrorCode.UNAUTHORIZED,
            )
        return role
