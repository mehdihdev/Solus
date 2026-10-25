"""The relation vocabulary (SOLUSDEV-320; ADR-027 amendment pending in the completion report).

An edge says what kind of connection it is, which way it runs, what evidence made it and which
cell of the interaction matrix it belongs to. Everything that writes or reads `graph_edge`
spells these names from here; the TypeScript twin is `packages/shared-types/src/relations.ts`,
pinned by `packages/shared-types/fixtures/relations/_values.json`.
"""

from __future__ import annotations

import enum
from collections.abc import Iterable, Mapping
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field


class RelationClass(enum.StrEnum):
    IDENTITY = "identity"
    STRUCTURE = "structure"
    DEPENDENCY = "dependency"
    OUTCOME = "outcome"
    LEGACY = "legacy"


class RelationType(enum.StrEnum):
    """Every `graph_edge.relation_type` a Solus component writes. Direction in RELATION_DOCS."""

    # identity
    SAME_AS = "same_as"
    # structure
    CONTAINS = "contains"
    PART_OF = "part_of"
    # dependency
    COMMANDS = "commands"
    READS = "reads"
    WIRES = "wires"
    POWERS = "powers"
    DRIVES = "drives"
    MOUNTS = "mounts"
    MATES_WITH = "mates_with"
    LIMITS = "limits"
    DEPENDS_ON = "depends_on"
    REQUIRES = "requires"
    HOSTS = "hosts"
    PUBLISHES = "publishes"
    SUBSCRIBES = "subscribes"
    # outcome
    MEASURED_BY = "measured_by"
    OBSERVED = "observed"
    FIXED_BY = "fixed_by"
    VERIFIED_BY = "verified_by"
    # legacy (written before this vocabulary; kept readable, never emitted by inference)
    CONNECTED_TO = "connected_to"
    CONFIGURES = "configures"
    BINDS = "binds"
    HARDWARE_CONNECTED_TO = "hardware_connected_to"
    HARDWARE_TOPOLOGY_MEMBER = "hardware_topology_member"
    HARDWARE_EVIDENCE_FOR = "hardware_evidence_for"
    PRESENCE_PREPARED_FOR = "presence_prepared_for"
    WIRING_PROPOSED_FOR = "wiring_proposed_for"
    DEPLOYMENT_FOR_TARGET = "deployment_for_target"
    CAD_VISUAL_FOR = "cad_visual_for"
    CLONE_OF = "clone_of"
    REFERENCES = "references"
    READS_FROM = "reads_from"  # read by checkers/core.py; superseded by `reads`


#: One line per type: src → dst (or ↔ for symmetric edges).
RELATION_DOCS: Final[Mapping[str, str]] = {
    "same_as": "observation ↔ observation of one physical part (fingerprint identity)",
    "contains": "parent → child (ownership / containment)",
    "part_of": "child → parent (connector-emitted containment)",
    "commands": "code site → actuator part",
    "reads": "code site → sensor part",
    "wires": "component ↔ component on a net (attrs.nets)",
    "powers": "supply or rail → sink",
    "drives": "bus → device",
    "mounts": "structure → device",
    "mates_with": "part ↔ part with attrs.mate_type",
    "limits": "joint → code constant",
    "depends_on": "manifest owner → package",
    "requires": "hardware config → package",
    "hosts": "machine → robot",
    "publishes": "ROS node → topic",
    "subscribes": "ROS node → topic",
    "measured_by": "part → channel",
    "observed": "finding → subject",
    "fixed_by": "error entry → diff or artifact",
    "verified_by": "goal or claim → run or sim result",
    "connected_to": "component → net (EDA netlist; attrs.net, attrs.pins)",
    "configures": "config node → configured subject",
    "binds": "config node → bound part (attrs.device_ref, address)",
    "hardware_connected_to": "brain or bus → endpoint (topology overlay)",
    "hardware_topology_member": "robot → topology endpoint",
    "hardware_evidence_for": "brain → accepted extraction evidence",
    "presence_prepared_for": "presence plan → robot or brain",
    "wiring_proposed_for": "wiring proposal → brain",
    "deployment_for_target": "deployment plan → target",
    "cad_visual_for": "CAD entity → scene model",
    "clone_of": "local clone → code-host repository",
    "references": ".solus root or context entity → entry node",
    "reads_from": "code → sensor (pre-vocabulary name of `reads`)",
}

RELATION_CLASS: Final[Mapping[RelationType, RelationClass]] = {
    RelationType.SAME_AS: RelationClass.IDENTITY,
    RelationType.CONTAINS: RelationClass.STRUCTURE,
    RelationType.PART_OF: RelationClass.STRUCTURE,
    **{
        t: RelationClass.DEPENDENCY
        for t in (
            RelationType.COMMANDS,
            RelationType.READS,
            RelationType.WIRES,
            RelationType.POWERS,
            RelationType.DRIVES,
            RelationType.MOUNTS,
            RelationType.MATES_WITH,
            RelationType.LIMITS,
            RelationType.DEPENDS_ON,
            RelationType.REQUIRES,
            RelationType.HOSTS,
            RelationType.PUBLISHES,
            RelationType.SUBSCRIBES,
        )
    },
    **{
        t: RelationClass.OUTCOME
        for t in (
            RelationType.MEASURED_BY,
            RelationType.OBSERVED,
            RelationType.FIXED_BY,
            RelationType.VERIFIED_BY,
        )
    },
    **{
        t: RelationClass.LEGACY
        for t in (
            RelationType.CONNECTED_TO,
            RelationType.CONFIGURES,
            RelationType.BINDS,
            RelationType.HARDWARE_CONNECTED_TO,
            RelationType.HARDWARE_TOPOLOGY_MEMBER,
            RelationType.HARDWARE_EVIDENCE_FOR,
            RelationType.PRESENCE_PREPARED_FOR,
            RelationType.WIRING_PROPOSED_FOR,
            RelationType.DEPLOYMENT_FOR_TARGET,
            RelationType.CAD_VISUAL_FOR,
            RelationType.CLONE_OF,
            RelationType.REFERENCES,
            RelationType.READS_FROM,
        )
    },
}


class EdgeOrigin(enum.StrEnum):
    CONNECTOR = "connector"
    MANUAL = "manual"
    INFERRED = "inferred"
    FINGERPRINT = "fingerprint"
    SYSTEM = "system"


class MatrixCell(enum.StrEnum):
    """The nine cells of the interaction matrix; the direction is src → dst."""

    SOFTWARE_SOFTWARE = "software->software"
    SOFTWARE_ELECTRICAL = "software->electrical"
    SOFTWARE_MECHANICAL = "software->mechanical"
    ELECTRICAL_SOFTWARE = "electrical->software"
    ELECTRICAL_ELECTRICAL = "electrical->electrical"
    ELECTRICAL_MECHANICAL = "electrical->mechanical"
    MECHANICAL_SOFTWARE = "mechanical->software"
    MECHANICAL_ELECTRICAL = "mechanical->electrical"
    MECHANICAL_MECHANICAL = "mechanical->mechanical"


class EvidenceKind(enum.StrEnum):
    NETLIST = "netlist"
    FIRMWARE_SYMBOL = "firmware_symbol"
    BUS_ENUMERATION = "bus_enumeration"
    MATE = "mate"
    MANIFEST = "manifest"
    CONFIG = "config"
    FINGERPRINT = "fingerprint"
    USER_CONFIRMED = "user_confirmed"
    CHECKER = "checker"
    TELEMETRY_ROUTING = "telemetry_routing"
    RUN = "run"
    SIM = "sim"


class EdgeEvidence(BaseModel):
    """One piece of evidence behind an edge; deduped on (kind, ref) when merged."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: EvidenceKind
    ref: str = Field(min_length=1, max_length=512)
    detail: str | None = Field(default=None, max_length=1024)


#: `graph_entity.domain` values (`solus_api.models.Domain`), spelled here so the contract has no
#: application import. Kept in step by `test_contracts_package.py`.
GRAPH_DOMAINS: Final[tuple[str, ...]] = (
    "code",
    "electrical",
    "mechanical",
    "simulation",
    "runtime",
    "project",
    "workspace",
)

#: Inferred edges below this confidence are candidates: shown dashed, never facts.
CANDIDATE_THRESHOLD: Final = 0.8

_MATRIX_DOMAIN: Final[Mapping[str, str]] = {
    "code": "software",
    "electrical": "electrical",
    "mechanical": "mechanical",
}


def relation_class(relation_type: str) -> RelationClass:
    """The class of a relation type; unknown types are a programming error."""
    try:
        return RELATION_CLASS[RelationType(relation_type)]
    except ValueError as exc:
        raise ValueError(f"unknown relation_type {relation_type!r}") from exc


def is_legacy(relation_type: str) -> bool:
    return relation_class(relation_type) is RelationClass.LEGACY


def normalize_domain_pair(a: str, b: str) -> str:
    """`"a<->b"`, Domain values in alphabetical order; direction lives in matrix_cell."""
    for value in (a, b):
        if value not in GRAPH_DOMAINS:
            raise ValueError(f"unknown graph domain {value!r}")
    lo, hi = sorted((a, b))
    return f"{lo}<->{hi}"


def matrix_cell(src_domain: str, dst_domain: str) -> MatrixCell | None:
    """The matrix cell for src → dst, or None when either side is outside the three worlds."""
    src = _MATRIX_DOMAIN.get(src_domain)
    dst = _MATRIX_DOMAIN.get(dst_domain)
    if src is None or dst is None:
        return None
    return MatrixCell(f"{src}->{dst}")


def evidence_key(items: Iterable[Mapping[str, Any]]) -> set[tuple[str, str]]:
    """The `(kind, ref)` identity set of an evidence list (dumped or model form)."""
    return {(str(item["kind"]), str(item["ref"])) for item in items}


def values_manifest() -> dict[str, Any]:
    """What the TypeScript twin must agree on (written to shared-types fixtures by the tests)."""
    return {
        "RelationClass": [c.value for c in RelationClass],
        "RelationType": [t.value for t in RelationType],
        "RELATION_CLASS": {t.value: c.value for t, c in RELATION_CLASS.items()},
        "EdgeOrigin": [o.value for o in EdgeOrigin],
        "MatrixCell": [m.value for m in MatrixCell],
        "EvidenceKind": [k.value for k in EvidenceKind],
        "EdgeEvidence": sorted(EdgeEvidence.model_fields),
        "CANDIDATE_THRESHOLD": CANDIDATE_THRESHOLD,
    }
