"""Helpers shared by the committed-export connector families (EDA + mechanical).

Both families face the same two problems: an adversarial export must not be
able to amplify one sync into megabytes of persisted error objects (CLAUDE.md
§7 — bound message sizes), and change detection needs a stable content hash
(W0-05 §7 re-parse-and-diff). Extracted from `eda.py` when `mechanical.py`
(SOLUS-CAD-00) needed identical behaviour, so the two families cannot drift.
"""

from __future__ import annotations

import hashlib
from typing import Final

from solus_api.connectors.contracts import SyncError

#: Cap on per-sync `SyncError`s. Overflow collapses into one truncation note
#: rather than being persisted item by item on the Sync row.
MAX_SYNC_ERRORS: Final = 100

#: Longest `SyncError.item` label kept verbatim before truncation.
LABEL_LIMIT: Final = 64

#: Longest `SyncError.message` kept verbatim. The count cap above bounds HOW
#: MANY errors persist; this bounds how BIG each one is. Without it a connector
#: that interpolates ingested content into a message (KiCad's netlist/board
#: reconciliation, SOLUSDEV-252) lets one adversarial file persist megabytes of
#: JSON on the Sync row and replay it on every sync-history read (§7 — bound
#: message sizes).
MESSAGE_LIMIT: Final = 512

#: Ceiling on the TOTAL bytes (`item` + `message`) one sync may persist. The
#: two caps above are per-item; an adversarial export that maximises both still
#: has to fit under this, so the worst case is bounded end to end.
TOTAL_BYTES_LIMIT: Final = 64 * 1024


class ErrorRecorder:
    """Collects `SyncError`s under the `MAX_SYNC_ERRORS` cap: overflow is
    counted and collapsed into one truncation note by `finish`."""

    def __init__(self) -> None:
        self._errors: list[SyncError] = []
        self._suppressed = 0
        self._bytes = 0

    def record(self, item: str, message: str) -> None:
        """Record one non-fatal failure, subject to all three bounds: the count
        cap, the per-message clip, and the aggregate byte budget. Anything the
        budgets refuse is COUNTED and collapsed into one note by `finish`, so a
        hostile export can never amplify a sync into megabytes of JSON."""
        clipped = _clip_message(message)
        cost = len(item) + len(clipped)
        if len(self._errors) >= MAX_SYNC_ERRORS or self._bytes + cost > TOTAL_BYTES_LIMIT:
            self._suppressed += 1
            return
        self._errors.append(SyncError(item=item, message=clipped))
        self._bytes += cost

    def finish(self) -> list[SyncError]:
        if self._suppressed:
            return [
                *self._errors,
                SyncError(
                    item="parse",
                    message=f"{self._suppressed} further issue(s) truncated",
                ),
            ]
        return self._errors


def content_sha(text: str) -> str:
    """Stable digest of an export's content, used as the change-detection
    cursor. `surrogatepass` so a malformed export hashes instead of raising."""
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def _clip_message(message: str) -> str:
    """A `SyncError.message` bounded to exactly `MESSAGE_LIMIT` characters."""
    if len(message) <= MESSAGE_LIMIT:
        return message
    return f"{message[: MESSAGE_LIMIT - 1]}…"


def label(token: str, limit: int = LABEL_LIMIT) -> str:
    """A short, safe label for a `SyncError` item — an over-long adversarial
    token is truncated rather than persisted whole."""
    return token if len(token) <= limit else f"{token[:limit]}…"
