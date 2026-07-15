"""Shared EDA (electrical) connector family — SOLUS-EDA (SOLUSDEV-102).

The electrical analogue of `code_host.py`: the pieces every committed-export EDA
connector (Altium here; KiCad / SPICE next) shares so the family mirrors itself
instead of drifting per tool.

Three layers:
  * the normalized netlist IR (`Component`/`Net`/`Node`/`Netlist`) each tool's
    parser produces — one shape for the whole family;
  * the electrical graph mapping (`build_graph`) — netlist IR → `EntityOut`
    (`component` + first-class `net` nodes) / `RelationOut` (`connected_to`),
    intra-source only (W0-05), with the pin carried in the edge `properties`
    (Decision B) and net name/class on the net entity;
  * `EdaExportConnector` — the Connector scaffold: it validates a synthetic
    identity (a committed export needs no tool credential of its own),
    reads the export CONTENT, parses it via the subclass's `parse`, and builds
    the graph. **v1 SCAFFOLD:** the export content is supplied on
    `SyncContext.config["export"]`; the live path (pull the committed file from
    the linked repo at a ref, or a proprietary tool integration) is stubbed for
    post-launch — see `_read_export`.

Everything mapping-side is pure (netlist in → entities out) per the analyzer
rule. Ingested netlist text is untrusted DATA, never instructions, and is parsed
without eval/exec/subprocess and under a size bound (CLAUDE.md §7).
"""

from __future__ import annotations

import abc
import hashlib
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

#: A committed export larger than this is refused rather than parsed (§7 — bound
#: message sizes; never let a malformed/huge artifact exhaust the worker).
MAX_EXPORT_BYTES: Final = 8 * 1024 * 1024

#: Cap on per-sync `SyncError`s (§7 — bound message sizes): an adversarial export
#: full of duplicates must not amplify into megabytes of error objects persisted
#: on one Sync row and echoed by every sync-history read. Overflow collapses
#: into a single truncation note.
MAX_SYNC_ERRORS: Final = 100

#: `net` entity keys are namespaced so a net named like a designator can't collide
#: with a component's key (source_keys must be unique within a sync — W0-05 §10).
NET_KEY_PREFIX: Final = "net:"

CONNECTED_TO: Final = "connected_to"


# --------------------------------------------------------------- netlist IR


@dataclass(frozen=True)
class Node:
    """One pin of a component sitting on a net (`Designator-Pin`)."""

    designator: str
    pin: str


@dataclass(frozen=True)
class Component:
    """A placed part. The three optional identity fields — `part_number`,
    `schematic_symbol_name`, `datasheet_ref` — are the W0-08 §5.2 fingerprint
    channels; a tool's parser fills whichever its format carries."""

    designator: str
    footprint: str | None = None
    value: str | None = None
    part_number: str | None = None
    schematic_symbol_name: str | None = None
    datasheet_ref: str | None = None
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Net:
    name: str
    nodes: tuple[Node, ...]
    net_class: str | None = None


@dataclass(frozen=True)
class Netlist:
    """The one IR the whole EDA family maps from. Tool parsers produce this.

    `warnings` carries human-readable notes about data a lenient parser dropped
    (unterminated/empty blocks, unparseable lines). `build_graph` folds them into
    `SyncResult.errors` so a partial parse is visible on the sync record rather
    than a silent smaller-than-expected graph.
    """

    components: tuple[Component, ...] = ()
    nets: tuple[Net, ...] = ()
    warnings: tuple[str, ...] = ()


# --------------------------------------------------------- graph mapping


def component_entity(component: Component) -> EntityOut:
    """A `component` node keyed by its reference designator (its stable per-source id)."""
    properties: dict[str, Any] = {
        "footprint": component.footprint,
        "value": component.value,
        **component.properties,
    }
    # Identity signals are the fingerprint's channel, kept out of properties.
    modality_hints = {
        hint: value
        for hint, value in (
            ("part_number", component.part_number),
            ("schematic_symbol_name", component.schematic_symbol_name),
            ("datasheet_ref", component.datasheet_ref),
        )
        if value
    }
    return EntityOut(
        source_key=component.designator,
        type="component",
        domain=Domain.ELECTRICAL,
        name=component.designator,
        properties=properties,
        modality_hints=modality_hints,
    )


def net_entity(net: Net) -> EntityOut:
    """A first-class `net` node — so high-fanout nets (power/GND) are one node,
    not O(n²) pairwise edges, and the net name/class has a home."""
    return EntityOut(
        source_key=f"{NET_KEY_PREFIX}{net.name}",
        type="net",
        domain=Domain.ELECTRICAL,
        name=net.name,
        properties={"net_class": net.net_class} if net.net_class else {},
    )


def build_graph(
    netlist: Netlist,
) -> tuple[list[EntityOut], list[RelationOut], list[SyncError]]:
    """Netlist IR → (entities, relations, errors).

    Components and nets become entities; a component gets ONE `connected_to` edge
    per net it touches, carrying ALL of its pins on that net in `properties.pins`.
    Emitting one edge per pin instead would collide at the reconciliation layer
    (edges are keyed by `(from, to, relation_type)`, pins only in properties), so
    a multi-pin part on a net — every multi-VCC/GND IC — would silently lose all
    but one connection. Duplicate designators/nets and nodes referencing an
    unknown component are dropped with a `SyncError`, and any parser `warnings`
    are surfaced too — so "why is this part/edge missing?" is answerable rather
    than a silent gap (keeping source_keys unique and relations intra-source,
    W0-05 §10). The errors list is capped at `MAX_SYNC_ERRORS` (§7).
    """
    recorder = _ErrorRecorder()
    for warning in netlist.warnings:
        recorder.record("parse", warning)

    components = _map_components(netlist, recorder)
    nets, relations = _map_nets(netlist, components, recorder)

    entities = [*components.values(), *nets.values()]
    return entities, relations, recorder.finish()


class _ErrorRecorder:
    """Collects SyncErrors under the `MAX_SYNC_ERRORS` cap (§7): overflow is
    counted and collapsed into one truncation note by `finish`."""

    def __init__(self) -> None:
        self._errors: list[SyncError] = []
        self._suppressed = 0

    def record(self, item: str, message: str) -> None:
        if len(self._errors) < MAX_SYNC_ERRORS:
            self._errors.append(SyncError(item=item, message=message))
        else:
            self._suppressed += 1

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


def _map_components(netlist: Netlist, recorder: _ErrorRecorder) -> dict[str, EntityOut]:
    components: dict[str, EntityOut] = {}
    for component in netlist.components:
        if component.designator in components:
            recorder.record(_label(component.designator), "duplicate component designator")
            continue
        try:
            # Adversarial exports can carry an over-long token (a designator up to
            # the byte cap) that overflows EntityOut's field bounds. Drop that one
            # item with a SyncError rather than letting the whole sync fail (§7 —
            # a compromised repo must not be able to break a team's every sync).
            components[component.designator] = component_entity(component)
        except ValidationError:
            recorder.record(_label(component.designator), "component exceeds field bounds; dropped")
    return components


def _map_nets(
    netlist: Netlist,
    components: dict[str, EntityOut],
    recorder: _ErrorRecorder,
) -> tuple[dict[str, EntityOut], list[RelationOut]]:
    nets: dict[str, EntityOut] = {}
    relations: list[RelationOut] = []
    for net in netlist.nets:
        net_key = f"{NET_KEY_PREFIX}{net.name}"
        if net_key in nets:
            recorder.record(_label(net.name), "duplicate net name")
            continue
        try:
            nets[net_key] = net_entity(net)
        except ValidationError:
            recorder.record(_label(net.name), "net name exceeds field bounds; dropped")
            continue
        # Group this net's nodes by component so a part gets one edge to the net
        # carrying all its pins (order-preserving), not one colliding edge per pin.
        pins_by_designator: dict[str, list[str]] = {}
        for node in net.nodes:
            if node.designator not in components:
                recorder.record(
                    f"{net.name}:{node.designator}", "net node references unknown component"
                )
                continue
            pins = pins_by_designator.setdefault(node.designator, [])
            if node.pin not in pins:
                pins.append(node.pin)
        relations.extend(
            RelationOut(
                from_key=designator,
                to_key=net_key,
                type=CONNECTED_TO,
                properties={"net": net.name, "pins": pins},
            )
            for designator, pins in pins_by_designator.items()
        )
    return nets, relations


# --------------------------------------------------------- family connector


class EdaExportConnector(Connector):
    """Base for committed-export EDA connectors (Altium/KiCad/SPICE mirror this).

    A committed export carries no tool credential of its own — repo auth belongs
    to the code host — so `auth_kind` is NONE and identity is synthetic. Subclasses
    supply `provider` and `parse`.
    """

    auth_kind: ClassVar[AuthKind] = AuthKind.NONE
    supports_token_connect: ClassVar[bool] = False
    #: v1 scaffold: the committed export CONTENT is handed in on this config key.
    #: When live acquisition lands this becomes the repo path/ref (see _read_export).
    config_fields: ClassVar[tuple[str, ...]] = ("export",)

    @abc.abstractmethod
    def parse(self, text: str) -> Netlist:
        """Parse this tool's export format into the shared netlist IR."""

    async def validate_credentials(self, creds: Credentials) -> AccountInfo:
        # No external identity to prove for a committed export; report a stable
        # synthetic one so the source has a "whose export is this?" label.
        return AccountInfo(
            external_id=self.provider,
            login=f"{self.provider}-export",
            name=f"{self.provider.title()} committed export",
        )

    async def sync(self, ctx: SyncContext) -> SyncResult:
        text = self._read_export(ctx)
        netlist = self.parse(text)
        entities, relations, errors = build_graph(netlist)
        return SyncResult(
            entities=entities,
            relations=relations,
            cursor={"content_sha": _content_sha(text)},
            errors=errors,
        )

    async def detect_changes(self, ctx: SyncContext) -> bool:
        # Re-parse-and-diff (W0-05 §7): the export's content hash vs the cursor.
        # On any acquisition failure, be safe and let a full sync decide.
        try:
            text = self._read_export(ctx)
        except ConnectorError:
            return True
        return _content_sha(text) != ctx.cursor.get("content_sha")

    def _read_export(self, ctx: SyncContext) -> str:
        """Obtain the committed export content.

        **v1 SCAFFOLD (post-launch completion):** the content is supplied inline
        on `ctx.config["export"]`. The LIVE path — resolving the configured repo
        path/ref and fetching the committed file's bytes (or a proprietary
        Altium tool integration) — is intentionally NOT built here; it depends on
        the shared file-acquisition seam (a later ticket). Until then, a config
        without inline `export` raises a clear, stable error.

        When the live path lands, it MUST raise `ConnectorError` (not raw
        network/IO exceptions) on failure, so `detect_changes`'s narrow catch
        keeps its fail-safe behavior.
        """
        export = ctx.config.get("export")
        if export is None:
            raise ConnectorError(
                "export_unavailable",
                (
                    f"{self.provider}: v1 parses a committed export supplied via "
                    "config['export']; live repo/tool acquisition is not yet implemented."
                ),
            )
        if not isinstance(export, str):
            raise ConnectorError("export_invalid", "export content must be text")
        if _byte_len(export) > MAX_EXPORT_BYTES:
            raise ConnectorError("export_too_large", "export exceeds the size limit")
        return export


def _byte_len(text: str) -> int:
    # surrogatepass (not "ignore") so a surrogate-heavy adversarial string can't
    # under-count its way past the size bound; never raises on lone surrogates.
    return len(text.encode("utf-8", "surrogatepass"))


def _content_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def _label(token: str, limit: int = 64) -> str:
    """A short, safe label for a SyncError item — an over-long adversarial token
    never bloats the error record."""
    return token if len(token) <= limit else f"{token[:limit]}…"
