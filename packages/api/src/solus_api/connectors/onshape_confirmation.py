"""Single-use, task-local observations for confirmed native CAD authoring."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from solus_api.agent.tools.tool import InProcessTool
from solus_api.connectors.contracts import ConnectorError

_active: ContextVar[str | None] = ContextVar("onshape_approved_observation", default=None)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def stable_spec(value: Any) -> Any:
    """Vendor spec nodeIds are freshly generated per GET, not CAD identity."""
    if isinstance(value, dict):
        return {k: stable_spec(v) for k, v in value.items() if k != "nodeId"}
    if isinstance(value, list):
        return [stable_spec(v) for v in value]
    return value


def _stale() -> ConnectorError:
    return ConnectorError("stale_state", "The approved CAD observation changed or is unavailable.")


@dataclass
class _Ticket:
    args: str
    rows: str
    consumed: bool = False


class PreviewBinding:
    """One tool instance; child-task dispatch consumes the parent's ticket too."""

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled
        self._ticket: ContextVar[_Ticket | None] = ContextVar("onshape_preview", default=None)

    def clear(self) -> None:
        ticket = self._ticket.get()
        if ticket is not None:
            ticket.consumed = True
        self._ticket.set(None)

    def remember(self, args: dict[str, Any], rows: list[dict[str, Any]]) -> None:
        self.clear()
        if self.enabled:
            self._ticket.set(_Ticket(_canonical(args), _canonical(rows)))

    @contextmanager
    def execution(self, args: dict[str, Any]) -> Iterator[None]:
        if not self.enabled:
            yield
            return
        ticket = self._ticket.get()
        if ticket is None or ticket.consumed:
            raise _stale()
        ticket.consumed = True
        if ticket.args != _canonical(args):
            raise _stale()
        token = _active.set(ticket.rows)
        try:
            yield
        finally:
            _active.reset(token)


def require_matching_preview(rows: list[dict[str, Any]]) -> None:
    if _active.get() != _canonical(rows):
        raise _stale()


class ConfirmedOnshapeTool(InProcessTool):
    requires_complete_preview = True
