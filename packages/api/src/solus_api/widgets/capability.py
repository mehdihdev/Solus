"""The shape an in-repo capability package exports (SOLUSDEV-246).

``CAPABILITY = WidgetCapability(...)`` at a sub-package root is the whole
contract between a first-party bundle's manifest and the server code that backs
it. The manifest CLAIMS kinds, tools and routes; the publish gate checks the
claim against this object; the loader, the SOL registry and the widgets router
consume it. Scope discipline (CLAUDE.md §7): a tool builder receives a
:class:`BundleScope` bound by Solus code — the project and user come from the
authenticated request, never from model arguments.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from fastapi import APIRouter
from solus_contracts.extension_manifest import graph_kind_name
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.agent.tools.tool import Tool


@dataclass(frozen=True)
class BundleScope:
    """What a tool builder is handed: the request's project (and user) and a
    session factory. Nothing in here came from a model or a manifest."""

    session_factory: async_sessionmaker[AsyncSession]
    project_id: uuid.UUID
    user_id: uuid.UUID | None


#: Builds ONE tool bound to a scope. The returned descriptor's ``name`` must be
#: ``composed_tool_name(capability.id, <declared name>)``.
ToolBuilder = Callable[[BundleScope], Tool]


@dataclass(frozen=True)
class DeclaredKind:
    """A graph node type the package writes; lands as ``ext:<id>:<name>``."""

    name: str
    domain: str


@dataclass(frozen=True)
class WidgetCapability:
    id: str
    kinds: tuple[DeclaredKind, ...]
    tools: Mapping[str, ToolBuilder]
    router: APIRouter | None

    def kind_names(self) -> tuple[str, ...]:
        return tuple(graph_kind_name(self.id, kind.name) for kind in self.kinds)
