"""SOLUSDEV-321 P5 (R103, R104, R127, D6, D10) — `render_view`: SOL looks at one view of the design.

One call answers how something looks with ONE labelled render, read once and cached:

- **Inside a turn only**, like `label_motifs`: with no turn bound the tool is unavailable. When the
  scope planner took renders off the turn (connectivity and counts come from the graph:
  `PerceptionTurn.renders_refused`), it says so and draws nothing.
- **The subject** is read through the scoped graph reader, in this project only and in the
  requesting person's own graph scope (`bind_scope(resolve_scope(...))`, the read every other tool
  makes). Another project's entity, an unknown id or a workspace node is not found, with no
  existence oracle.
- **Who draws it** is `Renderers.plan`, read in the same scope: a scene model, else a source that
  renders. Neither is an honest "nothing draws this", never an invented picture.
- **The view** is the question's (`choose_view`). On a sheet renderer it is the board when the
  question names the board, else the sheet. Otherwise it is the face the question names (looked
  at along its inward normal), a part's bounds when it asks about size, else the isometric view.
- **The cache** (D6, R127) is consulted only after that read, so a cached look is reachable only by
  someone who may read the subject at that moment. It is keyed `(project_id, asker, entity_id,
  change_signal, view_id)`: the renderer's revision and the labelled entities' graph state. The
  asker is set only for a companion-drawn view, a person's own working copy (M5); scene and
  connector views are shared. It holds values only (the annotated picture, the checked read, the
  lengths the graph won), never an artifact or a finding. A hit costs no render, no model call
  and no finding. Only a look a model read is kept.
- **A look** is the picture with the graph's labels and extents burned in (`annotate_render`),
  read by ONE vision call counted against the turn (`vision_extract`). Every length the graph
  states differently is replaced by the graph's value, and each difference files ONE info
  finding (`vision_postcheck`).
- **Shown only when asked** (`show`): every `show`, a cached look's included, stores a FRESH TTL
  artifact for the requesting person, and the result carries its reference, never pixels
  (W0-04). The chat shows it as a card.

The tool is ungated: it draws and reads, and its one write is an info finding. ponytail: the cache
is per process (at most `MAX_CACHED` looks, each one checked picture); share it through Redis
when the API runs as several instances.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from solus_api.agent.tools.read_document import DEFAULT_ARTIFACT_TTL_SECONDS
from solus_api.agent.tools.shapes import ToolDescriptor, ToolErrorCode
from solus_api.agent.tools.tool import InProcessTool, ToolException
from solus_api.agent.turn_context import current_perception, current_turn_id
from solus_api.agent.vision.render_annotate import Box, RenderLabel, annotate_render
from solus_api.agent.vision.renderers import Renderers, RenderPlan, RenderRefusedError, ViewSpec
from solus_api.agent.vision.vision_extract import vision_extract
from solus_api.agent.vision.vision_postcheck import (
    LENGTH_UNITS_MM,
    Disagreement,
    LengthFact,
    file_disagreements,
    length_fact,
    vision_postcheck,
)
from solus_api.graph import kinds
from solus_api.graph.neighborhood import load_neighborhood, to_graph_context
from solus_api.graph.read_scope import bind_scope, resolve_scope
from solus_api.livebench.scene.service import digest
from solus_api.models import Domain
from solus_api.services.artifacts import create_artifact

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from solus_api.agent.interfaces import EntityRead
    from solus_api.agent.tools.registry import ToolRegistry
    from solus_api.bridge.registry import BridgeSessionRegistry
    from solus_api.connectors.registry import ConnectorRegistry
    from solus_api.connectors.secrets import SecretStore
    from solus_api.storage import ArtifactStore

MAX_QUESTION_CHARS: Final = 300
RENDER_TIMEOUT_SECONDS: Final = 120.0
#: Room for the read (at most `MAX_READ_CHARS`, plus the graph's values written into it).
RESULT_CAP: Final = 6_000
MAX_CACHED: Final = 32
TITLE_CHARS: Final = 120
NOTHING_DRAWS: Final = (
    "nothing draws this entity: it has no scene model and no source that renders it"
)
READ_NOTE: Final = (
    "A vision model read this labelled render: describe it with hedges. Counts and connections "
    "come from the graph, never from a picture. Where the read gave a length the graph states "
    "differently, the graph's value is written in and an info finding was filed."
)
#: A word naming a face → the side it names.
_FACES: Final = MappingProxyType(
    {
        "front": "front",
        "back": "back",
        "rear": "back",
        "behind": "back",
        "left": "left",
        "right": "right",
        "top": "top",
        "above": "top",
        "overhead": "top",
        "bottom": "bottom",
        "underside": "bottom",
        "below": "bottom",
        "beneath": "bottom",
    }
)
_BOUNDS_WORDS: Final = frozenset(
    {"big", "bounds", "dimension", "dimensions", "extent", "extents", "large", "long", "size"}
)
_BOARD_WORDS: Final = frozenset(
    {"board", "copper", "footprint", "footprints", "layout", "pcb", "silkscreen", "traces"}
)

RENDER_VIEW_DESCRIPTOR: Final = ToolDescriptor(
    name="render_view",
    description=(
        "Look at one view of the design: a labelled render of an entity (a part, the robot or "
        "its scene model; a net's schematic sheet or the board), read once by a vision model. "
        "Use it for how something looks, where parts sit or what a face shows; never for counts "
        "or connections, which come from the graph. The view follows the question: a named face, "
        "a part's size, the board, else an overview. The graph's lengths win over the read. Set "
        "show only when the person asked to see the picture; otherwise report the read in text."
    ),
    params={
        "type": "object",
        "properties": {
            "entity_id": {"type": "string", "format": "uuid"},
            "question": {"type": "string", "minLength": 1, "maxLength": MAX_QUESTION_CHARS},
            "show": {
                "type": "boolean",
                "description": (
                    "true only when the person asked to see the picture; otherwise the read is "
                    "reported in text"
                ),
            },
        },
        "required": ["entity_id", "question"],
        "additionalProperties": False,
    },
    returns={
        "type": "object",
        "properties": {
            "rendered": {"type": "boolean"},
            "view": {"type": "string"},
            "renderer": {"type": "string"},
            "cached": {"type": "boolean"},
            "read": {"type": "string"},
            "graph_wins": {"type": "array", "items": {"type": "object"}},
            "findings": {"type": "array", "items": {"type": "string"}},
            "reason": {"type": "string"},
            "artifact_id": {"type": "string", "format": "uuid"},
        },
        "required": ["rendered"],
    },
    timeout_seconds=RENDER_TIMEOUT_SECONDS,
    result_cap=RESULT_CAP,
)

#: (project, asker, entity, change signal, view): what a cached look is a look at (R127). The asker
#: is set only for a companion-drawn view, which is its person's own working copy (M5).
type _LookKey = tuple[uuid.UUID, uuid.UUID | None, uuid.UUID, str, str]


@dataclass(frozen=True, slots=True)
class RenderView:
    """A look as the cache keeps it (R127): the annotated picture, the read with the graph's values
    in, and each length the graph won. Values only: never an artifact or a finding, nothing a
    later reader might not be allowed to see."""

    png: bytes
    text: str
    disagreements: tuple[Disagreement, ...]


_LOOKS: Final[OrderedDict[_LookKey, RenderView]] = OrderedDict()


def choose_view(question: str, *, sheets: bool) -> ViewSpec:
    """The one view a question asks for (module docstring)."""
    words = re.findall(r"[a-z]+", question.casefold())
    if sheets:
        return ViewSpec("board") if _BOARD_WORDS.intersection(words) else ViewSpec("sheet")
    side = next((_FACES[word] for word in words if word in _FACES), None)
    if side is not None:
        return ViewSpec("face", side)
    return ViewSpec("bounds") if _BOUNDS_WORDS.intersection(words) else ViewSpec("iso")


def change_signal(plan: RenderPlan) -> str:
    """What a picture of `plan` is drawn from: the renderer's revision and the labelled entities'
    graph state, as one digest (D6)."""
    return digest([plan.revision, [[str(e.id), e.name, e.attrs] for e in plan.labelled]])


class _RenderViewTool:
    """The tool, bound to ONE project and the requesting person by Solus code (`Renderers`)."""

    def __init__(self, renderers: Renderers, *, redis: Any, enqueue: Any) -> None:
        self._renderers = renderers
        self._redis = redis
        self._enqueue = enqueue

    async def look(self, args: dict[str, Any]) -> dict[str, Any]:
        perception = current_perception()
        if perception is None or current_turn_id() is None:
            raise ToolException(
                "render_view runs only inside a SOL turn", code=ToolErrorCode.UNAVAILABLE
            )
        if perception.renders_refused:
            return {"rendered": False, "reason": perception.renders_refused}
        subject, plan = await self._subject_and_plan(args["entity_id"])
        if plan is None:
            return {"rendered": False, "reason": NOTHING_DRAWS}
        view = choose_view(str(args["question"]), sheets=plan.sheets)
        # P5 fix 1 (M5): a companion draws its own person's working copy, so that look is theirs.
        asker = self._renderers.user_id if plan.sheets else None
        key = (self._renderers.project_id, asker, subject.id, change_signal(plan), view.view_id)
        looked = _LOOKS.get(key)
        if looked is not None:
            _LOOKS.move_to_end(key)
            result = _looked_result(looked, plan, view, cached=True, findings=())
        else:
            try:
                looked, read, findings = await self._look(plan, view)
            except RenderRefusedError as exc:
                return {"rendered": False, "view": view.view_id, "reason": str(exc)}
            if read:
                _remember(key, looked)
            result = _looked_result(looked, plan, view, cached=False, findings=findings)
        if args.get("show") is True:
            result.update(await self._shown(looked.png, subject, view, plan.renderer))
        return result

    async def _subject_and_plan(self, raw: object) -> tuple[EntityRead, RenderPlan | None]:
        """The subject and what draws it, read in the requesting person's own graph scope before
        the cache is consulted, so a cached look is reachable only by someone who may read the
        subject at that moment (R127)."""
        renderers = self._renderers
        async with renderers.sessions() as session:
            scope = await resolve_scope(session, renderers.project_id, renderers.user_id)
            with bind_scope(scope):
                subject = await _subject_of(session, renderers.project_id, raw)
                return subject, await renderers.plan(session, subject)

    async def _look(
        self, plan: RenderPlan, view: ViewSpec
    ) -> tuple[RenderView, bool, tuple[str, ...]]:
        """Draw, label, read and check one view (module docstring): the look, whether a model read
        it, and the findings it filed."""
        renderers = self._renderers
        drawn = await renderers.render(plan, view)
        facts = [fact for entity in plan.labelled if (fact := length_fact(entity)) is not None]
        png = await asyncio.to_thread(
            annotate_render,
            drawn.png,
            _render_labels(plan, drawn.boxes),
            _render_captions(view, facts),
        )
        async with renderers.sessions() as session:
            read = await vision_extract(
                png,
                secret_store=renderers.secret_store,
                user_id=renderers.user_id,
                session=session,
                redis=self._redis,
                enqueue=self._enqueue,
            )
            checked = vision_postcheck(read.text, facts if read.read else ())
            findings = await file_disagreements(
                session, renderers.project_id, checked.disagreements, view_id=view.view_id
            )
            await session.commit()
        looked = RenderView(png, checked.text, checked.disagreements)
        return looked, read.read, tuple(str(finding) for finding in findings)

    async def _shown(
        self, png: bytes, subject: EntityRead, view: ViewSpec, renderer: str
    ) -> dict[str, Any]:
        """The picture as a fresh TTL artifact of the requesting person, for the chat to show: a
        reference, never pixels (R127: never a cached artifact)."""
        renderers = self._renderers
        async with renderers.sessions() as session:
            artifact = await create_artifact(
                session,
                renderers.artifact_store,
                project_id=renderers.project_id,
                created_by=renderers.user_id,
                data=png,
                media_type="image/png",
                source_tool=RENDER_VIEW_DESCRIPTOR.name,
                # ponytail: as make_diagram's, the handler has no call id to correlate it with.
                tool_call_id=None,
            )
            await session.commit()
        return {
            "artifact_id": str(artifact.id),
            "uri": artifact.uri,
            "media_type": artifact.media_type,
            "title": f"{subject.name} ({view.view_id})"[:TITLE_CHARS],
            "summary": f"A labelled {view.view_id} render by the {renderer} renderer.",
        }


def register_render_view_tool(
    registry: ToolRegistry,
    sessions: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    *,
    user_id: uuid.UUID | None,
    team_id: uuid.UUID | None,
    secret_store: SecretStore | None,
    artifact_store: ArtifactStore | None,
    artifact_ttl_seconds: int | None = None,
    connectors: ConnectorRegistry | None = None,
    bridge: BridgeSessionRegistry | None = None,
    bridge_call_cap_bytes: int = 262_144,
    artifact_max_bytes: int | None = None,
    redis: Any = None,
    enqueue: Any = None,
) -> None:
    """Add `render_view`, bound by Solus code to ONE project and the requesting person (D10): no
    argument names either. It reads as the person (the secret store meters the one vision read;
    their team finds their companion) and draws from and into the artifact store, so without all
    four it is absent."""
    if user_id is None or team_id is None or secret_store is None or artifact_store is None:
        return
    renderers = Renderers(
        sessions=sessions,
        project_id=project_id,
        user_id=user_id,
        team_id=team_id,
        secret_store=secret_store,
        artifact_store=artifact_store,
        artifact_ttl_seconds=artifact_ttl_seconds or DEFAULT_ARTIFACT_TTL_SECONDS,
        connectors=connectors,
        bridge=bridge,
        call_cap_bytes=bridge_call_cap_bytes,
        artifact_max_bytes=artifact_max_bytes,
    )
    tool = _RenderViewTool(renderers, redis=redis, enqueue=enqueue)
    registry.register(InProcessTool(RENDER_VIEW_DESCRIPTOR, tool.look))


async def _subject_of(session: AsyncSession, project_id: uuid.UUID, raw: object) -> EntityRead:
    """The entity asked about, read through the scoped graph reader in this project only."""
    try:
        entity_id = uuid.UUID(str(raw))
    except ValueError:
        raise ToolException(
            "No such entity in this project", code=ToolErrorCode.NOT_FOUND
        ) from None
    hood = await load_neighborhood(session, project_id, roots=[entity_id], depth=0)
    for entity in to_graph_context(hood).entities:
        if entity.id == entity_id and entity.domain != Domain.WORKSPACE:
            return entity
    raise ToolException("No such entity in this project", code=ToolErrorCode.NOT_FOUND)


def _remember(key: _LookKey, looked: RenderView) -> None:
    """Keep a look, evicting the least recently used past `MAX_CACHED`."""
    _LOOKS[key] = looked
    while len(_LOOKS) > MAX_CACHED:
        _LOOKS.popitem(last=False)


def _render_labels(plan: RenderPlan, boxes: Mapping[uuid.UUID, Box]) -> list[RenderLabel]:
    """Each labelled entity where the renderer drew it; the subject, when it was not placed, named
    in the caption band (a net as the net the sheet is about)."""
    subject = plan.labelled[0]
    placed = [RenderLabel(e.name, boxes[e.id]) for e in plan.labelled if e.id in boxes]
    if subject.id in boxes:
        return placed
    noun = "net" if subject.kind == kinds.NET else "subject"
    return [RenderLabel(f"{noun}: {subject.name}"), *placed]


def _render_captions(view: ViewSpec, facts: Sequence[LengthFact]) -> list[str]:
    """The view, then each labelled part's extents as the graph states them."""
    return [
        f"view: {view.view_id}",
        *(f"{fact.label}: {_extents_text(fact)} (graph)" for fact in facts),
    ]


def _extents_text(fact: LengthFact) -> str:
    scale = LENGTH_UNITS_MM[fact.unit]
    return " x ".join(f"{extent / scale:g}" for extent in fact.extents_mm) + f" {fact.unit}"


def _looked_result(
    looked: RenderView,
    plan: RenderPlan,
    view: ViewSpec,
    *,
    cached: bool,
    findings: Sequence[str],
) -> dict[str, Any]:
    return {
        "rendered": True,
        "view": view.view_id,
        "renderer": plan.renderer,
        "cached": cached,
        "read": looked.text,
        "graph_wins": [_graph_win(disagreement) for disagreement in looked.disagreements],
        "findings": list(findings),
        "note": READ_NOTE,
    }


def _graph_win(disagreement: Disagreement) -> dict[str, Any]:
    fact = disagreement.fact
    return {
        "entity_id": str(fact.entity_id),
        "label": fact.label,
        "graph": {"value": disagreement.graph_value, "unit": fact.unit},
        "render": {"value": disagreement.render_value, "unit": disagreement.render_unit},
    }
