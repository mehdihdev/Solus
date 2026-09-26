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
    the graph. The export content comes either from an injected
    `ExportAcquirer` (a live acquisition mechanism — SOLUSDEV-100 T4a;
    docs/contracts/metadata-extraction.md §2.1) or, when no acquirer is
    configured or it declines/fails, inline on `SyncContext.config["export"]`
    — see `_read_export`.

Everything mapping-side is pure (netlist in → entities out) per the analyzer
rule. Ingested netlist text is untrusted DATA, never instructions, and is parsed
without eval/exec/subprocess and under a size bound (CLAUDE.md §7).
"""

from __future__ import annotations

import abc
import logging
from dataclasses import dataclass, field
from typing import Any, ClassVar, Final

from pydantic import ValidationError

from solus_api.connectors.acquisition import ExportAcquirer
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
from solus_api.connectors.export_common import MAX_SYNC_ERRORS as _MAX_SYNC_ERRORS
from solus_api.connectors.export_common import ErrorRecorder as _ErrorRecorder
from solus_api.connectors.export_common import content_sha as _content_sha
from solus_api.connectors.export_common import label as _label

#: Structured-logging channel for acquisition degradation (§2.1 invariant 3):
#: "why did this user's sync degrade?" must be answerable from here.
_LOGGER: Final = logging.getLogger("solus.connectors.eda")

#: The `SyncContext.config` key an inline committed export arrives on, and the
#: key named in a degradation log line's `config_key=`.
EXPORT_CONFIG_KEY: Final = "export"

#: A committed export larger than this is refused rather than parsed (§7 — bound
#: message sizes; never let a malformed/huge artifact exhaust the worker).
MAX_EXPORT_BYTES: Final = 8 * 1024 * 1024

#: Cap on per-sync `SyncError`s (§7 — bound message sizes): an adversarial export
#: full of duplicates must not amplify into megabytes of error objects persisted
#: on one Sync row and echoed by every sync-history read. Overflow collapses
#: into a single truncation note. Shared with the mechanical family so the two
#: cannot drift (`export_common`, SOLUS-CAD-00).
MAX_SYNC_ERRORS: Final = _MAX_SYNC_ERRORS

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
    pin_function: str | None = None


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
        functions: dict[str, dict[str, set[str]]] = {}
        for node in net.nodes:
            if node.designator not in components:
                recorder.record(
                    _label(f"{net.name}:{node.designator}"),
                    "net node references unknown component",
                )
                continue
            pins = pins_by_designator.setdefault(node.designator, [])
            if node.pin not in pins:
                pins.append(node.pin)
            if node.pin_function:
                functions.setdefault(node.designator, {}).setdefault(node.pin, set()).add(
                    node.pin_function
                )
        relations.extend(
            RelationOut(
                from_key=designator,
                to_key=net_key,
                type=CONNECTED_TO,
                properties={
                    "net": net.name,
                    "pins": pins,
                    **_pin_functions(functions.get(designator, {})),
                },
            )
            for designator, pins in pins_by_designator.items()
        )
    return nets, relations


def _pin_functions(functions: dict[str, set[str]]) -> dict[str, Any]:
    known = {pin: next(iter(names)) for pin, names in functions.items() if len(names) == 1}
    return {"pin_functions": known} if known else {}


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
    #: A live `ExportAcquirer` (below) is tried first when one is injected.
    config_fields: ClassVar[tuple[str, ...]] = ("export",)

    def __init__(self, *, acquirer: ExportAcquirer | None = None) -> None:
        """`acquirer` is the optional live-acquisition seam (docs/contracts/
        metadata-extraction.md §2.1). `None` (the default) keeps every subclass
        zero-arg constructible and preserves the v1 inline-export-only
        behavior; registry factories inject a concrete acquirer per source once
        one exists (a later ticket) — this base never constructs one itself.
        """
        self._acquirer = acquirer

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
        text = await self._read_export(ctx)
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
            text = await self._read_export(ctx)
        except ConnectorError:
            return True
        return _content_sha(text) != ctx.cursor.get("content_sha")

    async def _read_export(self, ctx: SyncContext) -> str:
        """Obtain the committed export content, or fail the sync.

        `_select_export` runs the acquisition chain; only when BOTH sources are
        exhausted (no acquirer/decline, AND no inline export) does this raise
        `ConnectorError('export_unavailable')`. Only `ConnectorError` ever
        escapes, so `detect_changes`'s narrow catch keeps its fail-safe behavior.
        """
        export = await self._select_export(ctx)
        if export is None:
            raise ConnectorError(
                "export_unavailable",
                (
                    f"{self.provider}: no export available — the live acquirer (if any) "
                    f"declined/failed and config['{EXPORT_CONFIG_KEY}'] was not supplied."
                ),
            )
        return export

    async def _select_export(self, ctx: SyncContext) -> str | None:
        """Run the acquisition chain; `None` means "no export anywhere".

        Chain (docs/contracts/metadata-extraction.md §2.1): try the injected
        `ExportAcquirer` first — success wins outright; decline (`None`) or any
        raised exception logs a degradation and falls through to the inline
        `ctx.config['export']` path, exactly as if no acquirer were configured.
        The type and size bounds apply to whichever text was ultimately
        selected — acquired or inline — identically (§2.1 invariant 4:
        untrusted either way). Whether an absent export is fatal is the
        caller's call: `_read_export` says yes; a subclass with a second design
        input (KiCad's board, §5.2a) may not.
        """
        acquired = await self._acquire_export(ctx)
        if acquired is None:
            return self._inline_text(ctx, EXPORT_CONFIG_KEY)
        return _validated_text(acquired, EXPORT_CONFIG_KEY)

    def _inline_text(self, ctx: SyncContext, key: str) -> str | None:
        """The inline text on `ctx.config[key]`, bounds-checked; `None` when absent."""
        value = ctx.config.get(key)
        if value is None:
            return None
        return _validated_text(value, key)

    async def _acquire_export(self, ctx: SyncContext) -> str | None:
        """Try the injected `ExportAcquirer`, if any. Returns `None` for "fall
        through to inline" — whether because there is no acquirer, it declined,
        or it raised; all three are indistinguishable to the caller and, except
        for "no acquirer", are logged as a degradation (§2.1 invariant 3).
        """
        if self._acquirer is None:
            return None
        try:
            text = await self._acquirer.acquire(ctx)
        except Exception as exc:
            self._log_degradation(f"acquirer raised {type(exc).__name__}: {exc}")
            return None
        if text is None:
            self._log_degradation("acquirer returned None (declined/unavailable)")
            return None
        return text

    def _log_degradation(self, reason: str) -> None:
        _LOGGER.warning(
            "eda export acquisition degraded; falling back to inline export "
            "provider=%s config_key=%s reason=%s",
            self.provider,
            EXPORT_CONFIG_KEY,
            reason,
        )


def _validated_text(value: object, key: str) -> str:
    """Enforce the family's input bounds on one design text (§7): text only,
    at most `MAX_EXPORT_BYTES`. `key` names the input in the stable messages."""
    if not isinstance(value, str):
        raise ConnectorError("export_invalid", f"{key} content must be text")
    if _byte_len(value) > MAX_EXPORT_BYTES:
        raise ConnectorError("export_too_large", f"{key} exceeds the size limit")
    return value


def _byte_len(text: str) -> int:
    # surrogatepass (not "ignore") so a surrogate-heavy adversarial string can't
    # under-count its way past the size bound; never raises on lone surrogates.
    return len(text.encode("utf-8", "surrogatepass"))
