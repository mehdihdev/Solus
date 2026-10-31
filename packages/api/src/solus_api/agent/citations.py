"""SOLUSDEV-321 P7 — the closing message of a model reply: its prose and the citations it keeps.

`reason.verified_citations` keeps a token of the reply only when a section of the turn's context
served it (CLAUDE.md §7: model output is untrusted), and the desktop makes pills of those tokens
alone. The findings section serves `[finding:<id>]` (P0-T6) and the `.solus` layers
`[solus:<section>:<id>]`. The graph context is ONE section whose entity lines carry no token, so the
turn's graph anchors serve `[entity:<id>]` here — only the ones the project-scoped pull returned
(`Context.scoped_anchors`, P7 fix 1, I1): a UUID pasted into the message is a `ref_match` anchor
whether or not the person can see it, and one that is another team's, deleted or never existed
is never served. Each served anchor becomes a citation-only section of the context the reply is
checked against; that copy is made after the prompt is built and is never rendered — it reaches
no prompt, manifest or layer count. The graph layer offers the same tokens in one line
(`context._anchor_tokens_line`), so the model knows what to cite.

A reply whose text was only a reasoning block, with an approval card waiting, closes with ONE
fixed Solus line instead of an empty message (P7 fix 1, M4) — never model text.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Sequence
from typing import TYPE_CHECKING, Final

from solus_api.agent import prompt, reason
from solus_api.agent.layers import ContextSection
from solus_api.agent.modes import ActionMode
from solus_api.agent.reasoning_frame import strip_reasoning
from solus_api.agent.tools.shapes import ToolErrorCode

if TYPE_CHECKING:
    from solus_api.agent.context import Context
    from solus_api.agent.tools.shapes import ToolDescriptor
    from solus_api.orchestration.providers import ToolOutcome, Turn

#: The closing message of a reply that was only a reasoning block while a card waits (M4).
PROPOSAL_ONLY_REPLY: Final = "See the proposal below."
#: What every park tells the model, and no refusal does.
_PARKED_WORDS: Final = "waiting for the person"


def with_anchor_citations(context: Context) -> Context:
    """`context` with `[entity:<id>]` served for each anchor the project-scoped pull returned:
    what a reply is checked against, never what a prompt is built from."""
    served = tuple(
        ContextSection(kind="graph", text="", tokens=0, score=1.0, citation=f"[entity:{a.id}]")
        for a in context.scoped_anchors()
    )
    return context.model_copy(update={"sections": (*context.sections, *served)})


def reply_parts(
    text: str, context: Context, *, waiting: bool = False
) -> tuple[str, tuple[str, ...]]:
    """A model reply's closing `message`: its prose and its verified citations, with its
    reasoning block taken out first (P7: raw JSON never reaches the chat). Prose that comes out
    empty while a card is `waiting` reads `PROPOSAL_ONLY_REPLY`."""
    prose, cited = reason.sanitize_reply(strip_reasoning(text), with_anchor_citations(context))
    return (PROPOSAL_ONLY_REPLY if waiting and not prose else prose), cited


def card_waiting(
    turns: Sequence[Turn],
    offered: Sequence[ToolDescriptor],
    executed: Collection[str],
    mode: ActionMode,
) -> bool:
    """Whether a call this turn made waits on an approval card: in Build, a call to a tool that
    requires confirmation, which the routine policy did not run, answered as a park. Guide refuses
    such a call and parks nothing, so it never counts. The runner reads it from the turn's own tool
    outcomes, so no card is ever claimed that the round did not park."""
    if mode is not ActionMode.DO:
        return False
    gated = {d.name for d in offered if d.requires_confirmation}
    called = {
        use.id: prompt.resolve_tool_name(use.name, offered)
        for turn in turns
        for use in turn.tool_uses
    }
    return any(
        called.get(outcome.id) in gated and outcome.id not in executed and _parked(outcome)
        for turn in turns
        for outcome in turn.tool_results
    )


def _parked(outcome: ToolOutcome) -> bool:
    """`prompt.contain_result`'s failure payload in a park's own words: `unauthorized`, saying a
    person has the call (`confirmations._parked_message`, the restored card, the route's repeat).
    The Build routine refuses with the same code (an action already attempted, a routine that
    changed), and so does the gate with no confirmation flow wired; neither parks anything.

    ponytail: the words are the signal; a parked-call-id set from the route's `park` hook is the
    upgrade if they are ever reworded (a reworded park closes with no line, as before M4)."""
    if not outcome.is_error:
        return False
    try:
        payload = json.loads(outcome.content)
    except ValueError:  # a cut payload is not a park's (a park's is a short sentence)
        return False
    return (
        isinstance(payload, dict)
        and payload.get("code") == ToolErrorCode.UNAUTHORIZED.value
        and _PARKED_WORDS in str(payload.get("message", ""))
    )
