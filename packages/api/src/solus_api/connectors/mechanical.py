"""Shared mechanical-CAD connector family — SOLUS-CAD-00.

The mechanical analogue of `eda.py`. `docs/contracts/metadata-extraction.md` §3
is explicit that this layer is written ONCE, not per tool:

    every CAD connector = {a way to obtain the export file} + {the SHARED
    geometry/assembly parser}

So Onshape, Fusion, SolidWorks and AutoCAD differ only in ACQUISITION; the STEP
they hand over flows through one parser and one mapping. Three layers, mirroring
the EDA family:

  * the normalized CAD IR (`CadNode` / `CadModel`) every format parser produces;
  * the mechanical graph mapping (`build_mechanical_graph`) — IR → `EntityOut`
    (`part`) / `RelationOut` (`part_of`), intra-source only (W0-05);
  * `CadExportConnector` — the Connector scaffold: validate a synthetic identity
    (a committed export needs no tool credential), read the export, parse it via
    the subclass, build the graph.

Vocabulary follows the CONTRACT, not the ticket text: §5.5 emits `part`, and the
assembly-hierarchy edge is `part_of` (both free strings per ADR-027).

**Identity linchpin (MCP-04 §2.1 invariant 2).** `source_key` is the OCCURRENCE
PATH derived from the design content (`Bracket/PegPair/Peg[0]`) — never a temp
path, `ArtifactRef` id, call id, or file hash. A byte-identical export acquired
from a committed file or from a live MCP export call therefore yields identical
entities, so the fingerprint receives identical canonical-part inputs either way.

Everything mapping-side is pure (IR in → records out) per the analyzer rule.
Ingested CAD text is untrusted DATA, never instructions, parsed without
eval/exec/subprocess and under a size bound (CLAUDE.md §7).
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, ClassVar, Final

from pydantic import ValidationError

from solus_api.connectors.contracts import (
    AccountInfo,
    AuthKind,
    Connector,
    ConnectorError,
    Credentials,
    Domain,
    EntityOut,
    RelationOut,
    SyncContext,
    SyncError,
    SyncResult,
)
from solus_api.connectors.export_common import ErrorRecorder, content_sha, label

#: CAD exports dwarf netlists — a real robot assembly's STEP runs to tens of MB,
#: so the EDA family's 8 MiB bound would refuse ordinary files. Larger than this
#: is refused rather than parsed (§7 — one artifact must not exhaust the worker).
MAX_CAD_EXPORT_BYTES: Final = 64 * 1024 * 1024

#: The assembly-hierarchy edge (§5.5 / ADR-027). `mounted_on` exists but means
#: something else; `part_of` is the value the contract names for hierarchy.
PART_OF: Final = "part_of"

#: The product-structure entity kind (§5.5). Geometry-only bodies carrying no
#: product identity (STL, §5.6) map to `cad_body` — deferred, since STL has no
#: assembly structure at all and STEP is the assembly source.
PART: Final = "part"


# --------------------------------------------------------------- the CAD IR


@dataclass(frozen=True)
class CadNode:
    """One node of the product structure.

    `key` is the occurrence path and becomes `EntityOut.source_key`. It must be
    deterministic across re-exports and unique within the model: when one
    product is instanced twice, each OCCURRENCE gets its own key
    (`.../Peg[0]`, `.../Peg[1]`) while `name` and `part_number` stay shared.
    That is the §6.1 instance-name-vs-product-name distinction, made explicit.
    """

    key: str
    name: str
    is_assembly: bool
    parent_key: str | None = None
    #: Translation of THIS occurrence within its parent. STEP yields geometric
    #: placements, not semantic mates (§5.5) — so it rides the edge, not the part.
    placement: tuple[float, float, float] | None = None
    #: The W0-08 §5.5 fingerprint channel. Only a REAL manufacturer part number
    #: belongs here — a CAD-internal id is not an MPN and is never invented.
    part_number: str | None = None
    material: str | None = None
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CadModel:
    """A parsed CAD export: the product structure plus non-fatal parse notes."""

    nodes: tuple[CadNode, ...] = ()
    warnings: tuple[str, ...] = ()


# --------------------------------------------------------------- mapping


def _scoped(key: str, scope: str) -> str:
    """Namespace an occurrence key under its scope. See `build_mechanical_graph`."""
    return f"{scope}:{key}" if scope else key


def _entity(node: CadNode, scope: str, provenance: dict[str, Any]) -> EntityOut:
    properties: dict[str, Any] = {
        **node.properties,
        **provenance,
        "is_assembly": node.is_assembly,
    }
    if node.material is not None:
        properties["material"] = node.material

    key = _scoped(node.key, scope)
    # Matcher key spellings ONLY (`_HINT_KEYS` in fingerprint/matcher.py):
    # `part_number` is the single channel that seeds a merge; `cad_model` carries
    # provenance and is v1-unscored. A hint under any other spelling is dead.
    hints: dict[str, Any] = {"cad_model": key}
    if node.part_number:
        hints["part_number"] = node.part_number

    return EntityOut(
        source_key=key,
        type=PART,
        domain=Domain.MECHANICAL,
        name=node.name,
        properties=properties,
        modality_hints=hints,
    )


def build_mechanical_graph(
    model: CadModel,
    recorder: ErrorRecorder | None = None,
    *,
    scope: str = "",
    provenance: dict[str, Any] | None = None,
) -> tuple[list[EntityOut], list[RelationOut], list[SyncError]]:
    """CAD IR → intra-source graph records.

    Pure: same model in, same records out. Relations point child → parent, so a
    tree of N nodes yields N-1 edges. A node whose `parent_key` names nothing in
    this model is recorded as a per-item error and its edge dropped — the
    conformance suite requires BOTH endpoints of every relation to be emitted
    entities, and a partial export must degrade rather than fail the sync.

    Pass `recorder` to share ONE `MAX_SYNC_ERRORS` budget with a caller that has
    already recorded errors of its own (the Onshape connector's metadata read) —
    otherwise two independently-capped lists would double the documented bound.

    `scope` namespaces every emitted key (`"{scope}:{occurrence_path}"`). A STEP
    occurrence path is only unique WITHIN one export, but an account-level source
    (Onshape) spans many documents, and the runtime upserts on
    `(source_id, external_ref)`. Two documents each holding a `Bracket` would
    therefore collapse onto one graph row — a false merge created at the
    ingestion key, upstream of every fingerprint guard. Callers that ingest one
    export per source leave `scope` empty and are unaffected.

    `provenance` is merged into every entity's properties (e.g. the document and
    element a part came from), so one source spanning many documents can still
    say where each entity originated.
    """
    recorder = recorder if recorder is not None else ErrorRecorder()
    provenance = provenance or {}
    for warning in model.warnings:
        recorder.record("parse", warning)

    entities: list[EntityOut] = []
    emitted: set[str] = set()
    # The nodes that actually produced an entity. The relation pass MUST iterate
    # these, not `model.nodes`: a node dropped as a duplicate shares its key with
    # the survivor, so `key in emitted` is true for it too and its edge would be
    # emitted under the survivor's key — two `part_of` records with the same
    # (from, to, type) but different placements. `_reconcile_relations` keys on
    # exactly that tuple, so one silently overwrote the other and a placement
    # could land on the wrong occurrence, with no SyncError anywhere.
    accepted: list[CadNode] = []
    for node in model.nodes:
        if node.key in emitted:
            recorder.record(label(node.key), "duplicate occurrence key; dropped")
            continue
        try:
            # An adversarial export can carry an over-long name or key that
            # overflows EntityOut's field bounds. Drop that one node with a
            # SyncError rather than failing the team's whole sync (§7).
            entities.append(_entity(node, scope, provenance))
        except ValidationError:
            recorder.record(label(node.key), "node exceeds field bounds; dropped")
            continue
        emitted.add(node.key)
        accepted.append(node)

    relations: list[RelationOut] = []
    for node in accepted:
        if node.parent_key is None:
            continue
        if node.parent_key not in emitted:
            recorder.record(
                label(node.key),
                f"parent {label(node.parent_key)!r} is not a node of this export",
            )
            continue
        properties: dict[str, Any] = {}
        if node.placement is not None:
            properties["placement"] = list(node.placement)
        relations.append(
            RelationOut(
                from_key=_scoped(node.key, scope),
                to_key=_scoped(node.parent_key, scope),
                type=PART_OF,
                properties=properties,
            )
        )

    return entities, relations, recorder.finish()


# --------------------------------------------------------------- connector


class CadExportConnector(Connector):
    """Scaffold for every mechanical-CAD connector.

    Subclasses supply `provider` and `parse`; ACQUISITION of the export is the
    only thing that differs per tool (§3). v1 takes the export CONTENT on
    `SyncContext.config["export"]`; the live paths — Onshape's REST translation
    fetch (CAD-01) and the MCP export call of §2.1 (CAD-02/03/04) — override
    `_read_export` and nothing else.
    """

    auth_kind: ClassVar[AuthKind] = AuthKind.NONE
    supports_token_connect: ClassVar[bool] = False
    config_fields: ClassVar[tuple[str, ...]] = ("export",)

    @abc.abstractmethod
    def parse(self, text: str) -> CadModel:
        """Format-specific parse of one export into the shared CAD IR."""

    async def validate_credentials(self, creds: Credentials) -> AccountInfo:
        """A committed export proves no tool identity — report a synthetic one so
        "whose source is this?" still has an answer on the Source row."""
        return AccountInfo(
            external_id=self.provider,
            login=f"{self.provider}-export",
            name=f"{self.provider.title()} CAD export",
        )

    async def sync(self, ctx: SyncContext) -> SyncResult:
        text = self._read_export(ctx)
        model = self.parse(text)
        entities, relations, errors = build_mechanical_graph(model)
        return SyncResult(
            entities=entities,
            relations=relations,
            cursor={"content_sha": content_sha(text)},
            errors=errors,
        )

    async def detect_changes(self, ctx: SyncContext) -> bool:
        """Fail SAFE: an export we cannot read counts as CHANGED, so a transient
        acquisition failure schedules a sync rather than silently skipping one."""
        try:
            text = self._read_export(ctx)
        except ConnectorError:
            return True
        return content_sha(text) != ctx.cursor.get("content_sha")

    def _read_export(self, ctx: SyncContext) -> str:
        """v1 SCAFFOLD: the export content arrives inline on config.

        Overrides MUST raise `ConnectorError` (never a raw network/IO exception)
        so `detect_changes`'s narrow catch keeps its fail-safe behaviour.
        """
        export = ctx.config.get("export")
        if export is None:
            raise ConnectorError(
                "export_unavailable",
                f"no {self.provider} export supplied — set config['export'] to the STEP content",
            )
        if not isinstance(export, str):
            raise ConnectorError("export_invalid", "export content must be text")
        if len(export.encode("utf-8", "surrogatepass")) > MAX_CAD_EXPORT_BYTES:
            raise ConnectorError(
                "export_too_large",
                f"export exceeds the {MAX_CAD_EXPORT_BYTES // (1024 * 1024)} MiB parse limit",
            )
        return export
