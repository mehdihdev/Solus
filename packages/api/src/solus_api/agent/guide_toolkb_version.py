"""SOLUSDEV-321 P7 — tool knowledge for the release on the person's own machine.

The route hangs each mapped write tool's vendor note on its descriptor, read without a version
(`agent/tools/knowledge.py`). A GUI tool whose release the asker's machine reports — through the
project card's machine block, which only the machine's owner gets (`project_card.machine_block`
reads `tool_versions` behind `owns_machine`, never `machine.attrs` here) — is read again for that
release, its own family's mapped controls alone: a trusted note covering it stands, and none puts
the Solus sentence "not sure where that is in <tool> <release>" in its place, so a Guide answer
from the knowledge base never points at a control from another release. A read that failed says
the vendor notes were unavailable, never that no documentation covers the release (P7 fix 1). With
no release reported, a tool the knowledge base has nothing for gets the same sentence without one.
No model call; the release is the digits of the reported line, so nothing else from the machine's
report reaches the prompt.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Final

from solus_api.agent.tools.knowledge import (
    TOOL_CONTROLS,
    KnowledgeNote,
    family_notes,
    with_knowledge_notes,
)
from solus_api.contracts.tool_knowledge import ToolFamily

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from solus_api.agent.project_card import CardInputs, MachineBlock
    from solus_api.agent.tools.shapes import ToolDescriptor

#: The GUI tools whose release a machine reports: the binary the companion asks
#: (`routers/machines.py TOOL_VERSION_BINARIES`) and the name the person knows the tool by.
#: ponytail: KiCad is the one the companion reports today; a row per tool when it reports another.
MACHINE_TOOLS: Final[Mapping[ToolFamily, tuple[str, str]]] = {
    ToolFamily.KICAD: ("kicad-cli", "KiCad"),
}
#: Guide's sentence when the knowledge base cannot place a control in the person's release.
UNPLACED_NOTE: Final = "No vendor documentation covers {tool}: not sure where that is in {tool}."
#: …and when the read for that release failed: a note nobody could read is not one nobody wrote.
UNAVAILABLE_NOTE: Final = "Vendor notes unavailable for {tool}: not sure where that is in {tool}."
_RELEASE: Final = re.compile(r"\d{1,4}(?:\.\d{1,4}){0,2}")


def machine_release(machine: MachineBlock | None, binary: str) -> str | None:
    """The release digits the asker's machine reports for `binary`, or None."""
    line = dict(machine.tool_versions).get(binary, "") if machine is not None else ""
    match = _RELEASE.search(line)
    return match.group(0) if match else None


async def placed_tools(
    descriptors: Sequence[ToolDescriptor],
    card: CardInputs | None,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> tuple[ToolDescriptor, ...]:
    """`descriptors` with each mapped GUI tool's note read for the release the card's machine
    reports: the covering note, else the sentence naming that release; with no release, a tool
    without a note gets the sentence naming the tool alone. Every other descriptor is returned as
    it was."""
    machine = card.machine if card is not None else None
    notes: dict[str, KnowledgeNote] = {}
    for family, (binary, label) in MACHINE_TOOLS.items():
        mapped = [d for d in descriptors if TOOL_CONTROLS.get(d.name, (None,))[0] is family]
        if not mapped:
            continue
        release = machine_release(machine, binary)
        found, failed = (
            await _release_notes(sessionmaker, family, release) if release else ({}, frozenset())
        )
        tool = f"{label} {release}" if release else label
        notes |= {
            d.name: found.get(d.name) or _unplaced(d.name, tool, failed)
            for d in mapped
            if release or not d.knowledge_note
        }
    return with_knowledge_notes(descriptors, notes) if notes else tuple(descriptors)


def _unplaced(name: str, tool: str, failed: frozenset[str]) -> KnowledgeNote:
    """The Solus sentence for a mapped tool the read did not place in `tool`."""
    sentence = UNAVAILABLE_NOTE if name in failed else UNPLACED_NOTE
    return KnowledgeNote(TOOL_CONTROLS[name][1], sentence.format(tool=tool))


async def _release_notes(
    sessionmaker: async_sessionmaker[AsyncSession], family: ToolFamily, release: str
) -> tuple[dict[str, KnowledgeNote], frozenset[str]]:
    """`family`'s mapped tools' trusted notes read for `release`, and the tools whose read
    failed (never raises)."""
    async with sessionmaker() as session:
        return await family_notes(session, family, version=release)
