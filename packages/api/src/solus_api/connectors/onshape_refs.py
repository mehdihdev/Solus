"""Geometry references and surgical edits — SOLUS-ONS-A4.

Two problems, one answer.

**The stale-id problem.** Onshape's face and edge ids are deterministic but
*microversion-scoped*: the same id can name a different face after the model
changes. A model that saw an id in a previous turn will happily reuse it, and the
edit lands somewhere nobody asked for — silently, because the write succeeds.
Community MCP servers hand these ids to the model and inherit exactly that bug.

So a deterministic id is **never a tool argument here**. The model names geometry
with a declarative selector ("the largest planar face", "the plane nearest
z=50mm"), and the selector is evaluated against the live document at the moment
the write happens. Ids exist inside one request and nowhere else. Staleness
becomes structurally impossible rather than merely unlikely.

**The unpublished-payload problem.** `BTMParameterQueryList-148` is a
`btType`-only stub in Onshape's OpenAPI spec, so the shape of a query object is
not knowable from any machine-readable source. Rather than guess, an edit CLONES
the query object the feature already carries and swaps only its id list. A
feature with no example to copy is refused. A refused edit is recoverable; a
corrupted model is not.

An ambiguous selector is also refused. Picking the first of three equal
candidates is how an edit lands on the wrong face, and the caller can always
narrow it.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Final

import httpx

from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.onshape import OnshapeConnector
from solus_api.connectors.onshape_confirmation import require_matching_preview, stable_spec
from solus_api.connectors.onshape_cut import _healthy
from solus_api.connectors.onshape_ops import (
    OnshapeOperation,
    element_base_path,
    parameter_value_field,
    schema,
    validated_id,
    workspace_for,
)

#: Entity kinds a selector can name, and where each lives in `bodydetails`.
_ENTITY_KINDS: Final[dict[str, tuple[str, str, str]]] = {
    # kind -> (bodydetails key, geometry key, size key)
    "face": ("faces", "surface", "area"),
    "edge": ("edges", "geometry", "length"),
}

#: How many candidates a refusal will name before it stops listing them.
_MAX_LISTED: Final = 8

# Feature IDs include underscores, unlike document/workspace IDs.
_FEATURE_ID_RE: Final = re.compile(r"[A-Za-z0-9_-]{1,64}")


class _Candidate:
    """One resolved entity: its id, kept server-side, and how to describe it."""

    __slots__ = ("entity_id", "kind", "geometry_type", "size", "origin")

    def __init__(self, entity: dict[str, Any], kind: str) -> None:
        _key, geometry_key, size_key = _ENTITY_KINDS[kind]
        geometry = entity.get(geometry_key)
        geometry = geometry if isinstance(geometry, dict) else {}
        self.entity_id: str = str(entity.get("id", ""))
        self.kind = kind
        self.geometry_type = str(geometry.get("type", "")) or "unknown"
        raw_size = entity.get(size_key, geometry.get(size_key))
        self.size: float | None = float(raw_size) if isinstance(raw_size, int | float) else None
        self.origin: list[float] | None = _point(geometry.get("origin"))

    def describe(self) -> str:
        """Human-readable, and deliberately id-free — this text reaches a
        confirmation card, where an opaque handle would be meaningless."""
        parts = [f"{self.kind}: {self.geometry_type}"]
        if self.size is not None:
            unit = "m²" if self.kind == "face" else "m"
            parts.append(f"{self.size:g} {unit}")
        if self.origin is not None:
            parts.append("at (" + ", ".join(f"{v:g}" for v in self.origin) + ")")
        return ", ".join(parts)


def _point(value: Any) -> list[float] | None:
    if not isinstance(value, list) or len(value) != 3:
        return None
    if not all(isinstance(v, int | float) for v in value):
        return None
    return [float(v) for v in value]


def _distance(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b, strict=True)))


def _selector(args: dict[str, Any], key: str = "selector") -> dict[str, Any]:
    value = args.get(key)
    if not isinstance(value, dict):
        raise ConnectorError("config_invalid", f"{key} must be an object describing the geometry")
    kind = value.get("entity")
    if kind not in _ENTITY_KINDS:
        raise ConnectorError(
            "config_invalid", f"selector.entity must be one of {sorted(_ENTITY_KINDS)}"
        )
    return value


def _candidates(bodies: Any, selector: dict[str, Any]) -> list[_Candidate]:
    """Every entity in the document matching the selector's filters."""
    kind = str(selector["entity"])
    collection_key, _geometry_key, _size_key = _ENTITY_KINDS[kind]
    wanted_body = selector.get("body")
    wanted_type = selector.get("surface") or selector.get("geometry")

    found: list[_Candidate] = []
    for body in bodies if isinstance(bodies, list) else []:
        if not isinstance(body, dict):
            continue
        if wanted_body is not None and body.get("id") != wanted_body:
            continue
        for entity in body.get(collection_key) or []:
            if not isinstance(entity, dict) or not entity.get("id"):
                continue
            candidate = _Candidate(entity, kind)
            if wanted_type is not None and candidate.geometry_type != wanted_type:
                continue
            found.append(candidate)
    return found


def _narrow(found: list[_Candidate], selector: dict[str, Any]) -> list[_Candidate]:
    """Apply the selector's ranking rules. Each keeps only outright winners, so
    a genuine tie stays a tie and is refused rather than resolved by luck."""
    near = _point(selector.get("nearest_to"))
    if near is not None:
        placed = [c for c in found if c.origin is not None]
        if placed:
            best = min(_distance(c.origin or [], near) for c in placed)
            found = [
                c
                for c in placed
                if math.isclose(_distance(c.origin or [], near), best, rel_tol=1e-9, abs_tol=1e-12)
            ]
    for flag, pick in (("largest", max), ("smallest", min)):
        if not selector.get(flag):
            continue
        sized = [c for c in found if c.size is not None]
        if not sized:
            continue
        best = pick(c.size or 0.0 for c in sized)
        found = [c for c in sized if math.isclose(c.size or 0.0, best, rel_tol=1e-9, abs_tol=1e-15)]
    return found


async def _resolve(
    connector: OnshapeConnector,
    client: httpx.AsyncClient,
    base: str,
    selector: dict[str, Any],
) -> _Candidate:
    """The ONE reference primitive. Exactly one match, or an honest failure."""
    body = await connector.get_json(
        client,
        f"{base}/bodydetails",
        what="body details",
        params={"includeGeometricData": "true"},
    )
    bodies = body.get("bodies") if isinstance(body, dict) else None
    found = _narrow(_candidates(bodies, selector), selector)
    if not found:
        raise ConnectorError("not_found", "nothing in this part studio matches that description")
    if len(found) > 1:
        listed = "; ".join(c.describe() for c in found[:_MAX_LISTED])
        raise ConnectorError(
            "config_invalid",
            f"{len(found)} entities match that description — narrow it "
            f"(add nearest_to, largest or a surface type). Candidates: {listed}",
        )
    return found[0]


async def _resolve_reference(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> dict[str, Any]:
    document_id = validated_id(args, "document_id")
    element_id = validated_id(args, "element_id")
    workspace_id = await workspace_for(connector, client, args)
    base = element_base_path("partstudios", document_id, workspace_id, element_id)
    candidate = await _resolve(connector, client, base, _selector(args))
    # No id in the response, deliberately: see the module docstring.
    return {"matched": 1, "description": candidate.describe(), "entity": candidate.kind}


# ------------------------------------------------------------ surgical edit


def _feature(tree: Any, feature_id: str) -> dict[str, Any]:
    items = tree.get("features") if isinstance(tree, dict) else None
    if not isinstance(items, list):
        raise ConnectorError("api_error", "Onshape returned a malformed feature collection")
    features: dict[str, dict[str, Any]] = {}
    for item in items:
        message = item.get("message", item) if isinstance(item, dict) else None
        identity = message.get("featureId") if isinstance(message, dict) else None
        if (
            not isinstance(identity, str)
            or not _FEATURE_ID_RE.fullmatch(identity)
            or identity in features
        ):
            raise ConnectorError("api_error", "Onshape returned malformed feature identities")
        assert isinstance(message, dict)
        features[identity] = message
    if feature_id in features:
        return features[feature_id]
    raise ConnectorError(
        "not_found",
        f"no feature '{feature_id}' in this part studio — "
        "call onshape.get_feature_tree to list them",
    )


def _is_query(parameter: dict[str, Any]) -> bool:
    return "Query" in str(parameter.get("btType", ""))


def _id_field(query: dict[str, Any]) -> str | None:
    """Which key on a query object holds its id list, read off a live example.

    Same rule as A3's value field: exactly one list-of-strings key means we know
    where the ids go; anything else means we do not, and the caller refuses.
    """
    candidates = [
        key
        for key, value in query.items()
        if isinstance(value, list) and all(isinstance(v, str) for v in value)
    ]
    return candidates[0] if len(candidates) == 1 else None


def _repointed(parameter: dict[str, Any], entity_id: str, parameter_id: str) -> dict[str, Any]:
    """The feature's own query parameter, aimed at a different entity."""
    queries = parameter.get("queries")
    example = queries[0] if isinstance(queries, list) and queries else None
    if not isinstance(example, dict):
        raise ConnectorError(
            "config_invalid",
            f"'{parameter_id}' has no existing selection to model the edit on, and the "
            "query payload shape is not published — set it in Onshape once, then edits "
            "can follow it",
        )
    field = _id_field(example)
    if field is None:
        raise ConnectorError(
            "config_invalid", f"'{parameter_id}' has an ambiguous query shape; refusing to guess"
        )
    return {**parameter, "queries": [{**example, field: [entity_id]}]}


def _editable_value_field(parameter: dict[str, Any]) -> str | None:
    # Live quantity values include derived fields beside their authored
    # expression. Recognize only this observed type and bounded field set.
    if parameter.get("btType") == "BTMParameterQuantity-147":
        allowed = {
            "btType",
            "parameterId",
            "parameterName",
            "nodeId",
            "libraryRelationType",
            "expression",
            "value",
            "units",
            "isInteger",
            "importMicroversion",
            "valueString",
        }
        if set(parameter) <= allowed and isinstance(parameter.get("expression"), str):
            return "expression"
        return None
    return parameter_value_field(parameter)


def _rewritten_value(parameter: dict[str, Any], value: Any, parameter_id: str) -> dict[str, Any]:
    """A non-geometry parameter with its value replaced, shape untouched."""
    if not isinstance(value, str | int | float | bool):
        raise ConnectorError("config_invalid", f"'{parameter_id}' must be a single value")
    field = _editable_value_field(parameter)
    if field is None:
        raise ConnectorError(
            "config_invalid", f"'{parameter_id}' has an ambiguous payload shape; refusing to guess"
        )
    return {**parameter, field: value}


def _current(parameter: dict[str, Any]) -> str | None:
    """What a parameter reads as today, for the diff."""
    if _is_query(parameter):
        queries = parameter.get("queries")
        return "a selection" if isinstance(queries, list) and queries else None
    field = _editable_value_field(parameter)
    return None if field is None else str(parameter.get(field))


async def _edited_parameters(
    connector: OnshapeConnector,
    client: httpx.AsyncClient,
    base: str,
    feature: dict[str, Any],
    supplied: Any,
) -> tuple[list[dict[str, Any]], list[tuple[str, str | None, str]]]:
    """The feature's full parameter list with the requested changes applied, plus
    the diff rows describing them."""
    if supplied is None:
        supplied = {}
    if not isinstance(supplied, dict):
        raise ConnectorError("config_invalid", "parameters must be an object")
    existing = feature.get("parameters", [])
    if not isinstance(existing, list):
        raise ConnectorError("api_error", "Onshape returned a malformed parameter collection")
    by_id: dict[str, dict[str, Any]] = {}
    for parameter in existing:
        identity = parameter.get("parameterId") if isinstance(parameter, dict) else None
        if not isinstance(identity, str) or not identity or identity in by_id:
            raise ConnectorError("api_error", "Onshape returned malformed parameter identities")
        by_id[identity] = parameter
    for parameter_id in supplied:
        if parameter_id not in by_id:
            raise ConnectorError(
                "config_invalid",
                f"'{feature.get('name', '?')}' has no parameter '{parameter_id}'",
            )

    changed: dict[str, dict[str, Any]] = {}
    rows: list[tuple[str, str | None, str]] = []
    for parameter_id, value in supplied.items():
        parameter = by_id[parameter_id]
        before = _current(parameter)
        if _is_query(parameter):
            candidate = await _resolve(
                connector, client, base, _value_selector(value, parameter_id)
            )
            changed[parameter_id] = _repointed(parameter, candidate.entity_id, parameter_id)
            rows.append((parameter_id, before, candidate.describe()))
        else:
            changed[parameter_id] = _rewritten_value(parameter, value, parameter_id)
            rows.append((parameter_id, before, str(value)))
    return [changed.get(identity, parameter) for identity, parameter in by_id.items()], rows


def _value_selector(value: Any, parameter_id: str) -> dict[str, Any]:
    """A geometry parameter takes a SELECTOR, never an id.

    Refusing a bare string closes the obvious loophole: a model that learned an
    id elsewhere must not be able to smuggle it through as a plain value.
    """
    if not isinstance(value, dict):
        raise ConnectorError(
            "config_invalid",
            f"'{parameter_id}' points at geometry, so it takes a selector object "
            '(e.g. {"entity": "face", "largest": true}) — never an id',
        )
    return _selector({"selector": value})


async def _load(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """Base path, the current tree, and the feature being edited."""
    document_id = validated_id(args, "document_id")
    element_id = validated_id(args, "element_id")
    feature_id = args.get("feature_id")
    if not isinstance(feature_id, str) or not _FEATURE_ID_RE.fullmatch(feature_id):
        raise ConnectorError("config_invalid", "feature_id must be a safe Onshape feature ID")
    workspace_id = await workspace_for(connector, client, args)
    base = element_base_path("partstudios", document_id, workspace_id, element_id)
    tree = await connector.get_json(client, f"{base}/features", what="feature tree")
    return base, tree if isinstance(tree, dict) else {}, _feature(tree, feature_id)


def _unverified_update() -> ConnectorError:
    return ConnectorError(
        "mutation_unverified", "The feature may have changed; inspect it before retrying."
    )


def _authored_parameters(parameters: Any) -> Any:
    if not isinstance(parameters, list):
        raise _unverified_update()
    result = {}
    for parameter in parameters:
        if not isinstance(parameter, dict):
            raise _unverified_update()
        identity = parameter.get("parameterId")
        if not isinstance(identity, str) or not identity or identity in result:
            raise _unverified_update()
        clean = stable_spec(parameter)
        if parameter.get("btType") == "BTMParameterQuantity-147":
            for field in ("value", "units", "isInteger", "valueString"):
                clean.pop(field, None)
        result[identity] = clean
    return result


@dataclass(frozen=True)
class _FeatureEdit:
    base: str
    tree: dict[str, Any]
    feature: dict[str, Any]
    parameters: list[dict[str, Any]]
    changes: list[tuple[str, str | None, str]]
    rows: list[dict[str, Any]]

    @classmethod
    async def plan(
        cls, connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
    ) -> _FeatureEdit:
        base, tree, feature = await _load(connector, client, args)
        parameters, changes = await _edited_parameters(
            connector, client, base, feature, args.get("parameters")
        )
        microversion = tree.get("sourceMicroversion")
        if not changes or not isinstance(microversion, str) or not microversion:
            raise ConnectorError(
                "config_invalid", "A nonempty edit and source microversion are required"
            )
        try:
            state = json.dumps(
                {
                    "base": base,
                    "tree": stable_spec(
                        {k: v for k, v in tree.items() if k != "serializationVersion"}
                    ),
                    "parameters": stable_spec(parameters),
                },
                sort_keys=True,
                allow_nan=False,
            )
        except (TypeError, ValueError):
            raise ConnectorError("api_error", "The feature state is malformed") from None
        digest = hashlib.sha256(state.encode()).hexdigest()
        name = feature.get("name", feature["featureId"])
        rows = [
            {"label": "Feature", "before": None, "after": f"{base} / {feature['featureId']}"},
            {"label": "Source microversion", "before": None, "after": microversion},
            {
                "label": "Feature state fingerprint",
                "before": None,
                "after": ":".join(digest[i : i + 16] for i in range(0, 64, 16)),
            },
            *[
                {"label": f"{name} · {pid}", "before": before, "after": after}
                for pid, before, after in changes
            ],
        ]
        if len(rows) > 40 or any(
            isinstance(v, str) and len(v) > 400 for r in rows for v in r.values()
        ):
            raise ConnectorError(
                "config_invalid", "The complete feature preview exceeds its limits"
            )
        return cls(base, tree, feature, parameters, changes, rows)

    def verify(self, tree: Any) -> None:
        actual = _feature(tree, self.feature["featureId"])
        if (
            not _healthy(tree, actual)
            or actual.get("name") != self.feature.get("name")
            or actual.get("featureType") != self.feature.get("featureType")
            or _authored_parameters(actual.get("parameters"))
            != _authored_parameters(self.parameters)
        ):
            raise _unverified_update()


async def _update_feature(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> dict[str, Any]:
    plan = await _FeatureEdit.plan(connector, client, args)
    envelope = {
        key: plan.tree[key]
        for key in ("serializationVersion", "sourceMicroversion", "libraryVersion")
        if key in plan.tree
    }
    body = {
        **envelope,
        "rejectMicroversionSkew": True,
        "feature": {**plan.feature, "parameters": plan.parameters},
    }
    require_matching_preview(plan.rows)
    try:
        await connector.post_json(
            client,
            f"{plan.base}/features/featureid/{plan.feature['featureId']}",
            body,
            what="feature update",
        )
        plan.verify(
            await connector.get_json(client, f"{plan.base}/features", what="feature readback")
        )
    except ConnectorError as exc:
        raise _unverified_update() from exc
    return {
        "feature_id": plan.feature["featureId"],
        "name": plan.feature.get("name", ""),
        "verified": True,
        "changed": [
            {"parameter": pid, "before": before, "after": after}
            for pid, before, after in plan.changes
        ],
    }


async def _preview_update_feature(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> list[dict[str, Any]]:
    return (await _FeatureEdit.plan(connector, client, args)).rows


_SELECTOR_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "description": (
        "Describes geometry without naming an id: entity (face|edge), optional "
        "surface/geometry type, body, largest, smallest, nearest_to [x,y,z] in metres. "
        "Resolved against the live model, so it cannot go stale."
    ),
    "properties": {
        "entity": {"type": "string", "enum": sorted(_ENTITY_KINDS)},
        "surface": {"type": "string"},
        "geometry": {"type": "string"},
        "body": {"type": "string"},
        "largest": {"type": "boolean"},
        "smallest": {"type": "boolean"},
        "nearest_to": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
    },
    "required": ["entity"],
    "additionalProperties": False,
}

REFERENCE_OPERATIONS: Final[tuple[OnshapeOperation, ...]] = (
    OnshapeOperation(
        name="onshape.resolve_reference",
        description=(
            "Check which face or edge a description picks out, before using it in an "
            "edit. Returns a description, never an id — ids are microversion-scoped and "
            "are resolved at write time instead."
        ),
        params=schema(
            element=True,
            extra={"selector": _SELECTOR_SCHEMA},
            required=("document_id", "element_id", "selector"),
        ),
        returns={"type": "object"},
        run=_resolve_reference,
        tags=("read", "geometry"),
    ),
    OnshapeOperation(
        name="onshape.update_feature",
        description=(
            "Change parameters on an existing feature, leaving the rest of it alone. "
            "Parameters that point at geometry take a selector object, never an id."
        ),
        params=schema(
            element=True,
            extra={
                "feature_id": {
                    "type": "string",
                    "description": "featureId from onshape.get_feature_tree.",
                },
                "parameters": {
                    "type": "object",
                    "description": (
                        "parameterId → new value. A geometry parameter takes a selector "
                        "object instead of a value."
                    ),
                    "additionalProperties": True,
                },
            },
            required=("document_id", "element_id", "feature_id", "parameters"),
        ),
        returns={"type": "object"},
        run=_update_feature,
        requires_confirmation=True,
        preview=_preview_update_feature,
        tags=("write", "geometry"),
    ),
)

__all__ = ["REFERENCE_OPERATIONS"]
