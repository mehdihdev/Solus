"""The proposal the propose route just built, kept briefly so the confirm that follows does
not open the port and interrogate the same device again (docs/api/hardware.md §4).

Keyed by (project, account, device_ref, evidence digest): actors never share entries. An entry is
taken exactly once — a confirm consumes it whether or not it succeeds, so bound rows are never
served from memory — and only while every accepted row is in it and it is younger than the
TTL; anything else is a miss and the wire is asked, as before.
"""

from __future__ import annotations

import uuid
from collections import OrderedDict
from collections.abc import Callable, Iterable
from time import monotonic

from solus_api.hardware.detect import ProposalOut

MAX_ENTRIES = 64
TTL_S = 60.0
Key = tuple[uuid.UUID, uuid.UUID, str, str]


class ProposalCache:
    def __init__(
        self,
        *,
        max_entries: int = MAX_ENTRIES,
        ttl_s: float = TTL_S,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.clock = clock
        self._max_entries = max_entries
        self._ttl_s = ttl_s
        self._entries: OrderedDict[Key, tuple[float, ProposalOut]] = OrderedDict()

    def put(self, key: Key, proposal: ProposalOut) -> None:
        self._entries.pop(key, None)
        self._entries[key] = (self.clock(), proposal)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    def take(self, key: Key, row_ids: Iterable[str]) -> ProposalOut | None:
        """Pop the entry; hand it back only when fresh and covering every accepted row."""
        entry = self._entries.pop(key, None)
        if entry is None:
            return None
        at, proposal = entry
        if self.clock() - at > self._ttl_s:
            return None
        known = {row.id for row in proposal.rows}
        return proposal if all(row_id in known for row_id in row_ids) else None


# ponytail: one process-wide cache; the local API serves one machine, so no per-app instance.
PROPOSALS = ProposalCache()
