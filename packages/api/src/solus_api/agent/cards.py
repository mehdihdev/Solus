"""SOLUSDEV-326 — what a card shows: the card a parked call carries, and a tool's working line.

A tool may author the Hardware page's card for a call that parks through a duck-typed
`card(stored_args) -> Card | None`, say what a call is doing through `working(args) -> str | None`,
and declare `card_resumes: bool` (a class attribute, default False): whether SOL continues after
any decision on its card. None of them is on `ToolDescriptor` (frozen, and part of the
routine-authority dump) or on the `Tool` protocol; they are duck-typed like `preview`.

The gate computes the card ONCE, when the call parks, from the STORED arguments
(`confirmations.request_confirmation`), and stores it beside the row: presentation only, never
part of the consent or the stale check, never a `DiffRow` (docs/contracts/action-gate.md §Cards).
Whatever the tool wrote, the server sets `resumes` from the tool, keeps `more` only in Guide mode,
and makes every text one printable, masked line: a USB device's name and a model-written question
both reach a card. A value the tool puts in a text goes in a `chip`, and masking never moves a
chip's edge. A text past its bound is cut to it (`fitted`), never through a chip, so a
card tool's card always parks with its call. A card that still cannot be shown safely is not shown
(logged); the call still parks with its summary and rows.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.agent.dynamic_gate import registered_tool
from solus_api.agent.tools.registry import ToolRegistry
from solus_api.agent.tools.shapes import ToolCall
from solus_api.agent.tools.untrusted import REDACTED, redact_text
from solus_api.contracts.action_gate import Card, CardField
from solus_api.models import ConfirmationStatus, Conversation, ToolConfirmation, utcnow

logger = logging.getLogger("solus.agent.cards")

#: Whitespace that would break the row in two (or pad text off-screen).
_CONTROL_WHITESPACE = re.compile(r"\s")
_RUNS = re.compile(r" {2,}")


def single_line(value: object, cap: int) -> str:
    """A consent-card field, stripped to printable characters and capped.

    THE ONE PLACE THE `_sanitize` IDIOM APPLIES. SOL's prose is free-form English
    and cannot be charset-restricted, but a preview LABEL or VALUE is not prose —
    so the fingerprint escalator's "reject anything not shaped like the thing"
    gate works here, and it closes consent forgery.

    Without it, anyone who can name a CAD feature can write multi-line text onto
    the approval card ("Approve this, it is safe\n\nAll changes reverted") or
    reverse its rendering with U+202E. Capping length stops neither: `str.isprintable`
    is False for control characters, bidi overrides and zero-width joiners, and
    True for the ASCII space, which is exactly the distinction wanted.

    Line breaks collapse to ONE SPACE rather than vanishing. Deleting them fused
    the lines of a file the person was approving into words nobody wrote — a
    Dockerfile preview read `FROM python:3.12-slimWORKDIR /app` (SOLUSDEV-252,
    live) — which is a misrepresentation of the change, not a defence against
    one. The row still cannot become two rows, so the forgery is still closed.
    """
    spaced = _CONTROL_WHITESPACE.sub(" ", str(value))
    return _RUNS.sub(" ", "".join(ch for ch in spaced if ch.isprintable()))[:cap].strip()


def chip(value: object, cap: int) -> str:
    """`value` as ONE code chip in a card's text (backtick spans render as chips): one printable
    line of at most `cap` characters with every backtick of its own removed, between exactly one
    pair. Every value a tool puts on a card — a device's serial, a name — goes through here: with
    a backtick of its own it would close the chip, and its next words, spaced with a printable
    blank such as U+2800 (which `single_line` keeps), would read as Solus's own."""
    return f"`{single_line(str(value).replace('`', ''), cap)}`"


def _one_line_texts(value: Any) -> Any:
    """Every text of a card, its field's too, as one printable, masked line. Masking only ever
    removes backticks, so a changed count is a chip's edge eaten (a `token=` running into it) and
    the value's next words outside its chip: that text is masked whole."""
    if isinstance(value, str):
        line = single_line(value, len(value))
        masked = redact_text(line)
        return masked if masked.count("`") == line.count("`") else REDACTED
    if isinstance(value, dict):
        return {key: _one_line_texts(item) for key, item in value.items()}
    return value


def _bounds(model: type[BaseModel]) -> dict[str, int]:
    """Each text field's `max_length`, read from the contract's own model."""
    return {
        name: bound.max_length
        for name, field in model.model_fields.items()
        for bound in field.metadata
        if getattr(bound, "max_length", None)
    }


_CARD_BOUNDS = _bounds(Card)
_FIELD_BOUNDS = _bounds(CardField)


def _cut(value: Any, bound: int | None) -> Any:
    """A text cut to `bound`, ending "…". Never through a chip: an open one would take Solus's
    next words into it, so a chip that does not fit is left out whole."""
    if not isinstance(value, str) or bound is None or len(value) <= bound:
        return value
    kept = value[: bound - 1]
    if kept.count("`") % 2:
        kept = kept[: kept.rindex("`")]
    return kept.rstrip() + "…"


def fitted(fields: Mapping[str, Any]) -> dict[str, Any]:
    """A card's fields with each text cut to the contract's bound, its field's too. A card tool's
    card must always park with it: a call parked without one never reaches the Hardware slot."""
    fit = {key: _cut(value, _CARD_BOUNDS.get(key)) for key, value in fields.items()}
    if isinstance(shown := fit.get("field"), Mapping):
        fit["field"] = {key: _cut(value, _FIELD_BOUNDS.get(key)) for key, value in shown.items()}
    return fit


def shown_card(drafted: object, *, resumes: bool, guide: bool, fit: bool = False) -> dict[str, Any]:
    """`drafted` (a `Card`, or its fields) as it is stored and shown: each text one printable,
    masked line; `more` only in Guide mode; `resumes` the server's. Raises `ValidationError` when
    it is no card, or when masking pushes a text past its bound — unless `fit` (a tool's own
    card), which cuts each text to its bound before validating, as drafted and as masked."""
    if fit and isinstance(drafted, Mapping):
        drafted = fitted(drafted)
    shown = _one_line_texts(Card.model_validate(drafted).model_dump())
    shown.update(more=shown["more"] if guide else None, resumes=resumes)
    return Card.model_validate(fitted(shown) if fit else shown).model_dump(mode="json")


def authored_card(
    tool: object,
    stored_args: Mapping[str, Any],
    *,
    guide: bool,
    parked_for: Mapping[str, object] | None = None,
) -> dict[str, Any] | None:
    """The card `tool` authors for a call parked with `stored_args`, as `shown_card` makes it,
    each text cut to its bound; None when it authors none, or when its card fails or still
    cannot be shown safely (logged with `parked_for`, the ids of who it was parked for)."""
    author = getattr(tool, "card", None)
    if author is None:
        return None
    try:
        drafted = author(dict(stored_args))
        if drafted is None:
            return None
        resumes = getattr(tool, "card_resumes", False) is True
        return shown_card(drafted, resumes=resumes, guide=guide, fit=True)
    except Exception:  # noqa: BLE001 — presentation never refuses the park it describes
        name = getattr(getattr(tool, "descriptor", None), "name", None)
        ids = " ".join(f"{key}={value}" for key, value in (parked_for or {}).items())
        logger.warning("card for %.128r could not be shown; parked without one (%s)", name, ids)
        return None


def working_line(registry: ToolRegistry, call: ToolCall) -> str | None:
    """The tool's own line for what `call` is doing, for the `tool_call` frame's `working`: one
    printable line, UNCUT; None when the tool has none or it fails (logged), and when the model's
    arguments fail the tool's schema — that call is refused before it runs, so there is nothing to
    describe, and `working` never reads a value its schema would not admit. It fails to no line,
    never to a refusal. A model value a tool puts in its line goes in a `chip`.
    `AgentEvent.tool_call` masks the line like the arguments and only then cuts it to the frame's
    bound: cut first, a secret crossing the cut loses the length its shape needs and its first
    part would go out, and be stored, in the clear."""
    from solus_api.agent.confirmations import validate_tool_arguments  # it imports this module

    tool = registered_tool(registry, call.tool)
    author = getattr(tool, "working", None)
    if tool is None or author is None:
        return None
    try:
        if validate_tool_arguments(tool.descriptor, call.args):
            return None
        line = author(dict(call.args))
    except Exception:  # noqa: BLE001 — a status line never stops the call it describes
        logger.warning("working line for %.128r failed; framed without one", call.tool)
        return None
    return (single_line(line, len(line)) or None) if isinstance(line, str) else None


def open_card_rows(project_id: uuid.UUID, user_id: uuid.UUID) -> tuple[ColumnElement[bool], ...]:
    """A member's pending, unexpired rows with a card in a project, in their live conversations
    (docs/contracts/action-gate.md §Cards 3). Joined to `Conversation` by the reader."""
    return (
        ToolConfirmation.project_id == project_id,
        ToolConfirmation.user_id == user_id,
        ToolConfirmation.status == ConfirmationStatus.PENDING,
        ToolConfirmation.expires_at > utcnow(),
        ToolConfirmation.card.is_not(None),
        Conversation.project_id == project_id,
        Conversation.created_by == user_id,
        Conversation.deleted_at.is_(None),
    )


async def oldest_open_card(
    session: AsyncSession,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    *also: ColumnElement[bool],
) -> tuple[ToolConfirmation, int] | None:
    """The member's oldest open card here, and how many are open in all; None when none is."""
    found = (
        await session.execute(
            select(ToolConfirmation, func.count().over())
            .join(Conversation, Conversation.id == ToolConfirmation.conversation_id)
            .where(*open_card_rows(project_id, user_id), *also)
            .order_by(ToolConfirmation.created_at, ToolConfirmation.id)
            .limit(1)
        )
    ).first()
    return None if found is None else (found[0], found[1])


async def oldest_showable_card(
    session: AsyncSession,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    *also: ColumnElement[bool],
) -> tuple[ToolConfirmation, Card, int] | None:
    """`oldest_open_card`, past every stored card that no longer validates (one stored under
    older bounds): the row, its card, and how many showable-or-untried cards are open in all. The
    slot and SOL's turn card both read this, so SOL is told about the card the slot shows."""
    unshowable: list[uuid.UUID] = []
    # ponytail: one query per unshowable row; they are rare and gone within the 30-minute TTL.
    while (
        found := await oldest_open_card(
            session, project_id, user_id, *also, ToolConfirmation.id.not_in(unshowable)
        )
    ) is not None:
        row, total = found
        try:
            return row, Card.model_validate(row.card), total
        except ValidationError:
            logger.warning(
                "open card %s (project %s) no longer validates; skipped", row.id, project_id
            )
            unshowable.append(row.id)
    return None


__all__ = [
    "authored_card",
    "chip",
    "fitted",
    "oldest_open_card",
    "oldest_showable_card",
    "open_card_rows",
    "shown_card",
    "single_line",
    "working_line",
]
