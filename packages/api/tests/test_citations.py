"""SOLUSDEV-321 P7 — the desktop's pills come only from citations the server verified.

A reply's token survives `reason.verified_citations` only when the turn's context served it: the
findings section serves `[finding:<id>]` (P0-T6), the `.solus` layers `[solus:<section>:<id>]`,
and the turn's graph anchors `[entity:<id>]` (`agent/citations.py`). Anything else a model writes
— a finding nobody raised, an entity that was never an anchor — is stripped. Built on a context
the real assembly produced (a finding raised on a part in scope, a constraint a person wrote),
never a hand-made one.
"""

from __future__ import annotations

import uuid

from solus_api.agent import prompt
from solus_api.agent.citations import reply_parts, with_anchor_citations
from solus_api.agent.reason import Anchor, verified_citations
from solus_api.checkers.interface import Severity
from solus_api.graph.findings import FindingSpec, raise_finding
from solus_api.models import Domain, SolusSection, utcnow
from solus_api.services.solus_config import add_text_entry
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from test_solus_layer import _context, _part, _project


async def test_finding_and_entity_citations_survive_verified_citations(
    engine: AsyncEngine,
) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    project_id = await _project(maker)
    async with maker() as db:
        part, bystander = await _part(db, project_id, "LM358"), await _part(db, project_id, "C1")
        finding = await raise_finding(
            db,
            project_id,
            FindingSpec(
                rule_id="thermal.hot",
                severity=Severity.WARNING,
                source="checker",
                headline="LM358 runs hot",
                subjects=[part.id],
                domain=Domain.ELECTRICAL,
            ),
        )
        rule = await add_text_entry(
            db,
            project_id,
            SolusSection.CONSTRAINTS,
            "keep the op-amp under 85 C",
            author="user",
            created_by=None,
        )
        await db.commit()
    built = await _context(maker, project_id, "why is the LM358 hot?", part)
    context = built.with_anchors((Anchor(id=part.id, reason="mentioned"),), ())

    cited_finding = f"[finding:{finding.id}]"
    cited_rule = f"[solus:constraints:{rule.id}]"
    cited_part = f"[entity:{part.id}]"
    reply = (
        f"It runs hot {cited_finding} past {cited_rule} on {cited_part}; "
        f"not [finding:{uuid.uuid4()}], not [entity:{bystander.id}], "
        f"not [entity:{uuid.uuid4()}]. Again {cited_part}."
    )
    served = with_anchor_citations(context)
    assert verified_citations(reply, served) == (cited_finding, cited_rule, cited_part)
    # Without the anchors' tokens the graph context serves no entity at all.
    assert verified_citations(reply, context) == (cited_finding, cited_rule)
    # The served copy is for the check alone: the context the prompt and manifest come from is
    # untouched, and the anchor tokens add no tokens to any layer.
    assert context.sections == built.sections
    assert served.tokens() == context.tokens()

    # The closing message: the reasoning block out of the prose, the same verified citations.
    prose, citations = reply_parts(f'<reasoning>{{"considered": []}}</reasoning>{reply}', context)
    assert citations == (cited_finding, cited_rule, cited_part)
    assert prose.startswith("It runs hot") and "reasoning" not in prose


async def test_a_pasted_id_the_pull_never_returned_is_never_served(engine: AsyncEngine) -> None:
    """SOLUSDEV-321 P7 fix 1 (I1): a UUID typed into the message becomes a `ref_match` anchor
    whether or not the person can see it, and the project-scoped pull returns only what exists in
    their project. Only the anchors the pull returned serve `[entity:<id>]`: another team's id, a
    deleted one and one that never existed stay plain text — never a verified citation, never a
    pill, and never offered to the model (`Context.scoped_anchors`)."""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    project_id, elsewhere = await _project(maker), await _project(maker)
    async with maker() as db:
        part, gone = await _part(db, project_id, "LM358"), await _part(db, project_id, "R9")
        foreign = await _part(db, elsewhere, "LM358")
        gone.deleted_at = utcnow()
        await db.commit()
    built = await _context(maker, project_id, "why is the LM358 hot?", part)
    pasted = (foreign.id, gone.id, uuid.uuid4())
    context = built.with_anchors(
        (
            Anchor(id=part.id, reason="mentioned"),
            *(Anchor(id=i, reason="ref_match") for i in pasted),
        ),
        (),
    )
    assert [a.id for a in context.scoped_anchors()] == [part.id]

    reply = "See " + ", ".join(f"[entity:{i}]" for i in (part.id, *pasted)) + "."
    assert verified_citations(reply, with_anchor_citations(context)) == (f"[entity:{part.id}]",)
    assert reply_parts(reply, context)[1] == (f"[entity:{part.id}]",)
    prefix = context.fenced_prefix(prompt.new_nonce())
    assert not any(str(i) in prefix for i in pasted)


def test_a_reply_that_was_only_a_block_says_so_in_solus_words_when_a_card_waits() -> None:
    """P7 fix 1 (M4): a reply whose text was only a reasoning block closed with an empty message.
    When a card waits — in Build, a call to a confirmation-requiring tool that the routine policy
    did not run, answered `unauthorized` in a park's own words — the message is ONE fixed Solus
    line, never model text; with no card waiting nothing is invented. A refusal parks nothing,
    whatever its code: the Build routine's own and the gate's with no confirmation flow wired are
    `unauthorized` too."""
    from typing import Any

    from solus_api.agent.citations import PROPOSAL_ONLY_REPLY, card_waiting
    from solus_api.agent.confirmations import _parked_message
    from solus_api.agent.context import Context
    from solus_api.agent.modes import ActionMode
    from solus_api.agent.runtime import confirmation_refusal
    from solus_api.agent.tools import (
        InProcessTool,
        ToolCall,
        ToolDescriptor,
        ToolError,
        ToolErrorCode,
        ToolRegistry,
        ToolResult,
    )
    from solus_api.orchestration.providers import ToolUse, Turn

    write = ToolDescriptor(
        name="onshape.set_variable",
        description="Sets a variable.",
        params={"type": "object"},
        returns={"type": "object"},
        requires_confirmation=True,
    )
    read = ToolDescriptor(
        name="onshape.get_variables",
        description="Reads variables.",
        params={"type": "object"},
        returns={"type": "object"},
    )
    offered = (write, read)
    names = prompt.provider_tool_names(offered)

    def gated_round(*results: tuple[ToolDescriptor, ToolResult]) -> tuple[Turn, ...]:
        uses = tuple(ToolUse(id=r.call_id, name=names[d.name]) for d, r in results)
        outcomes = tuple(
            prompt.contain_result(ToolCall(tool=d.name, args={}, call_id=r.call_id), r)
            for d, r in results
        )
        return (
            Turn(role="assistant", text="x", tool_uses=uses),
            Turn(role="user", tool_results=outcomes),
        )

    call = ToolCall(tool=write.name, args={}, call_id="c1")
    words = _parked_message(call, "Set WIDTH to 120 mm.")
    parked = ToolResult.failure("c1", ToolError(code=ToolErrorCode.UNAUTHORIZED, message=words))
    turns = gated_round((write, parked), (read, ToolResult.success("c2", {"variables": []})))
    assert card_waiting(turns, offered, set(), ActionMode.DO) is True
    assert card_waiting(turns, offered, {"c1"}, ActionMode.DO) is False  # Build ran it
    assert card_waiting(turns, offered, set(), ActionMode.GUIDE) is False  # Guide parks nothing
    assert card_waiting((), offered, set(), ActionMode.DO) is False

    async def run(args: dict[str, Any]) -> dict[str, Any]:
        return {}

    registry = ToolRegistry()
    registry.register(InProcessTool(write, run))
    attempted = "This Build action was already attempted. Inspect its outcome; do not retry."
    refusals = (
        ToolResult.failure("c1", ToolError(code=ToolErrorCode.INVALID_ARGS, message=words)),
        ToolResult.failure("c1", ToolError(code=ToolErrorCode.UNAUTHORIZED, message=attempted)),
        confirmation_refusal(registry, call),
    )
    for refused in refusals:
        assert refused is not None
        assert card_waiting(gated_round((write, refused)), offered, set(), ActionMode.DO) is False

    context = Context(query="q", project_id=uuid.uuid4(), sections=())
    block = '<reasoning>{"considered": [], "ruled_out": [], "proposing": "Widen it."}</reasoning>'
    assert reply_parts(block, context, waiting=True) == (PROPOSAL_ONLY_REPLY, ())
    assert PROPOSAL_ONLY_REPLY == "See the proposal below."
    assert reply_parts(block, context) == ("", ())
    assert reply_parts(f"{block}It is widened.", context, waiting=True)[0] == "It is widened."
