"""What SOL's `hardware.inspect_device` learned about one device, kept for the member who asked
(SOLUSDEV-326 P2; docs/api/hardware.md "SOL's hardware tools").

An inspection listens to and pings one device through the local runner — the serial owner's open,
or the caller's own session's port — with the caller's authorized repo sources as evidence. It
writes nothing to the graph and files no link suggestion: the whole proposal is kept here, under a
fresh `inspection_id`, for the member in the project who asked; the model is answered a compact
summary and a card tool later stamps the snapshot it shows (P2-T5). Each inspection is one
`hardware.inspected` data event.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, replace
from time import monotonic
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.hardware.detect import (
    ProposalOut,
    bound_repo_config_ids,
    exclude_bound,
    propose_via_local,
)
from solus_api.hardware.local_sources import LocalHardwareSources, LocalSourceError
from solus_api.models import Project, User
from solus_api.services.events import emit_event

#: The listen budget (spec decision 6): a passive listen and a ping, never a write.
LISTEN_BUDGET_S: Final = 0.5
MAX_INSPECTIONS: Final = 64
#: As long as a parked card stays approvable, so a card tool can still stamp what it shows.
INSPECTION_TTL_S: Final = 30 * 60.0
#: How long a plug-in's inspection may answer the first `hardware.inspect_device` call after it in
#: place of a listen: long enough for the turn its notice starts. It answers once; every later
#: call listens.
INSPECTION_FRESH_S: Final = 120.0
EVENT: Final = "hardware.inspected"


@dataclass(frozen=True)
class Inspection:
    id: str
    project_id: uuid.UUID
    user_id: uuid.UUID
    device_ref: str
    proposal: ProposalOut
    at: float
    #: Made before anyone asked (a plug-in's) and not yet answered to its member.
    unasked: bool = False


class InspectionStore:
    """Inspections by id, each its member's in its project alone; the oldest go first past
    `max_entries`, and none is served past its TTL."""

    def __init__(
        self,
        *,
        max_entries: int = MAX_INSPECTIONS,
        ttl_s: float = INSPECTION_TTL_S,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._max_entries, self._ttl_s, self._clock = max_entries, ttl_s, clock
        self._entries: OrderedDict[str, Inspection] = OrderedDict()

    def put(
        self,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        proposal: ProposalOut,
        *,
        unasked: bool = False,
    ) -> Inspection:
        inspection = Inspection(
            str(uuid.uuid4()),
            project_id,
            user_id,
            proposal.device_ref,
            proposal,
            self._clock(),
            unasked,
        )
        self._entries[inspection.id] = inspection
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)
        return inspection

    def get(
        self, project_id: uuid.UUID, user_id: uuid.UUID, inspection_id: str
    ) -> Inspection | None:
        found = self._entries.get(inspection_id)
        return found if found is not None and self._theirs(found, project_id, user_id) else None

    def latest(
        self,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        device_ref: str,
        *,
        within_s: float | None = None,
    ) -> Inspection | None:
        """The member's newest inspection of `device_ref` here, while it lasts — with
        `within_s`, only one made that recently."""
        found = next(
            (
                found
                for found in reversed(self._entries.values())
                if found.device_ref == device_ref and self._theirs(found, project_id, user_id)
            ),
            None,
        )
        if found is None or (within_s is not None and self._clock() - found.at > within_s):
            return None
        return found

    def unasked(
        self,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        device_ref: str,
        *,
        within_s: float,
        take: bool = False,
    ) -> Inspection | None:
        """The member's newest inspection of `device_ref` when it is one nobody asked for, made
        within `within_s` and not yet answered. `take` answers it: it is kept for a card to
        stamp, and never handed out here again."""
        found = self.latest(project_id, user_id, device_ref, within_s=within_s)
        if found is None or not found.unasked:
            return None
        if take:
            self._entries[found.id] = replace(found, unasked=False)
        return found

    def age_s(self, inspection: Inspection) -> int:
        """Whole seconds since `inspection` was heard."""
        return int(self._clock() - inspection.at)

    def _theirs(self, found: Inspection, project_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        return (found.project_id, found.user_id) == (
            project_id,
            user_id,
        ) and self._clock() - found.at <= self._ttl_s


# ponytail: one process-wide store; the local API serves one machine (`proposal_cache.PROPOSALS`).
INSPECTIONS = InspectionStore()


def authorized_sources(
    local: object, project_id: uuid.UUID, user_id: uuid.UUID
) -> list[dict[str, Any]]:
    """Every source the member authorized here, read and verified; one that moved, changed or
    cannot be read is left out — it never stops a listen. The runner leaves out, before its port
    opens, one its parsers reject (livebench `propose_device` with a member)."""
    try:
        reader = LocalHardwareSources.for_local_runner(local)
        refs = reader.source_refs(project_id, user_id)
    except LocalSourceError:
        return []
    sources: list[dict[str, Any]] = []
    for ref in refs:
        try:
            source = reader.read_source(project_id, user_id, ref)
        except LocalSourceError:
            continue
        sources.append(
            {"source_ref": source.source_ref, "suffix": source.suffix, "content": source.content}
        )
    return sources


async def inspect_device(
    session: AsyncSession,
    local: Any,
    *,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    device_ref: str,
    unasked: bool = False,
    store: InspectionStore = INSPECTIONS,
) -> Inspection:
    """Listen to `device_ref` for `user_id` in `project_id` and keep what was found for them —
    `unasked` when no one asked (a plug-in): it then answers their first `inspect_device` call.
    Raises the proposal's `APIError`s (404 not here, 409 `device_busy`, 422, 503). Adds the data
    event; the caller commits."""
    sources = await asyncio.to_thread(authorized_sources, local, project_id, user_id)
    proposal = await propose_via_local(
        local,
        device_ref,
        repo_root=None,
        budget_s=LISTEN_BUDGET_S,
        repo_sources=sources,
        listener=(project_id, user_id),
    )
    bound = await bound_repo_config_ids(session, project_id)
    inspection = store.put(project_id, user_id, exclude_bound(proposal, bound), unasked=unasked)
    user = await session.get(User, user_id)
    project = await session.get(Project, project_id)
    if user is not None and project is not None:
        emit_event(
            session,
            user=user,
            event_type=EVENT,
            team_id=project.team_id,
            project_id=project_id,
            payload={
                "device_ref": inspection.device_ref,
                "inspection_id": inspection.id,
                "level": inspection.proposal.level,
                "rows": len(inspection.proposal.rows),
                "repo_matches": len(inspection.proposal.repo_matches),
            },
        )
    return inspection
