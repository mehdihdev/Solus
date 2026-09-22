"""One explicit-part blind cut, built from observed built-in schema and verified after writing."""

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Annotated, Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.onshape import ONSHAPE_ID_RE, OnshapeConnector, element_base_path
from solus_api.connectors.onshape_confirmation import require_matching_preview, stable_spec
from solus_api.connectors.onshape_ops import (
    OnshapeOperation,
    _live_parameters,
    _read_messages,
    workspace_for,
)

Identity = Annotated[str, Field(pattern=ONSHAPE_ID_RE.pattern, min_length=1)]
# Feature tokens are JSON references, never resource URL path segments.
FEATURE_ID_RE = re.compile(r"[A-Za-z0-9_+/-]{1,64}")
FeatureIdentity = Annotated[str, Field(pattern=r"^[A-Za-z0-9_+/-]{1,64}$")]


class CutArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    document_id: Identity
    element_id: Identity
    workspace_id: Identity | None = None
    sketch_feature_id: FeatureIdentity
    part_id: Identity
    name: Annotated[str, Field(min_length=1, max_length=120)]
    depth_mm: Annotated[float, Field(gt=0, le=10000)]
    opposite_direction: bool


_ENUMS = {
    "bodyType": ("ExtendedToolBodyType", "SOLID"),
    "operationType": ("NewBodyOperationType", "REMOVE"),
    "endBound": ("BoundingType", "BLIND"),
}
_TYPES = {
    "entities": "BTParameterSpecQuery-174",
    "booleanScope": "BTParameterSpecQuery-174",
    "depth": "BTParameterSpecQuantity-173",
    "oppositeDirection": "BTParameterSpecBoolean-170",
    "defaultScope": "BTParameterSpecBoolean-170",
}


def _invalid(message: str) -> ConnectorError:
    return ConnectorError("api_error", message)


def _unverified() -> ConnectorError:
    return ConnectorError(
        "mutation_unverified",
        "The cut may have been applied, but its result could not be verified. "
        "Inspect the Onshape feature tree before retrying.",
    )


def _verify_spec(body: Any) -> dict[str, Any]:
    specs = _read_messages(body.get("featureSpecs") if isinstance(body, dict) else None)
    matching = [spec for spec in specs if spec.get("featureType") == "extrude"]
    if len(matching) != 1 or matching[0].get("namespace") != "":
        raise _invalid("A unique built-in extrude specification is required")
    parameters = {p["parameterId"]: p for p in _live_parameters(matching[0])}
    for identity, kind in _TYPES.items():
        if parameters.get(identity, {}).get("btType") != kind:
            raise _invalid("The built-in cut parameter specification has changed")
    if parameters["depth"].get("quantityType") != "LENGTH":
        raise _invalid("The cut depth must be a length quantity")
    for identity, (enum, value) in _ENUMS.items():
        parameter = parameters.get(identity, {})
        options = parameter.get("options")
        if (
            parameter.get("btType") != "BTParameterSpecEnum-171"
            or parameter.get("enumName") != enum
            or parameter.get("namespace") != ""
            or not isinstance(options, list)
            or not all(isinstance(option, str) for option in options)
            or value not in options
        ):
            raise _invalid("The built-in cut enum specification has changed")
    return matching[0]


def _features(body: Any) -> list[dict[str, Any]]:
    if not isinstance(body, dict) or body.get("isComplete", True) is not True:
        raise _invalid("Onshape returned an incomplete feature tree")
    features = _read_messages(body.get("features") if isinstance(body, dict) else None)
    identities: set[str] = set()
    for feature in features:
        identity = feature.get("featureId")
        if (
            not isinstance(identity, str)
            or not FEATURE_ID_RE.fullmatch(identity)
            or identity in identities
        ):
            raise _invalid("Onshape returned malformed or duplicate feature identities")
        identities.add(identity)
    return features


def _healthy(body: dict[str, Any], feature: dict[str, Any]) -> bool:
    states = body.get("featureStates")
    state = states.get(feature["featureId"]) if isinstance(states, dict) else None
    if isinstance(state, dict) and "message" in state:
        state = state["message"]
    return (
        feature.get("suppressed", False) is False
        and isinstance(state, dict)
        and state.get("featureStatus") == "OK"
        and state.get("inactive", False) is False
    )


@dataclass(frozen=True)
class _Cut:
    args: CutArgs
    base: str
    workspace: str
    tree: dict[str, Any]
    sketch: dict[str, Any]
    part: dict[str, Any]
    spec_fingerprint: str
    defaults: dict[str, Any]

    @classmethod
    async def observe(
        cls, connector: OnshapeConnector, client: httpx.AsyncClient, raw: dict[str, Any]
    ) -> "_Cut":
        try:
            # The in-process wrapper adds its authorized document menu after
            # caller schema validation. No other unknown field is accepted.
            args = CutArgs.model_validate({k: v for k, v in raw.items() if k != "_documents"})
        except ValidationError:
            raise ConnectorError("config_invalid", "Invalid scoped cut arguments") from None
        if not args.name.strip() or not args.name.isprintable():
            raise ConnectorError("config_invalid", "The cut name must be printable and nonempty")
        workspace = await workspace_for(connector, client, args.model_dump(exclude_none=True))
        base = element_base_path("partstudios", args.document_id, workspace, args.element_id)
        body = await connector.get_json(client, f"{base}/features", what="cut feature tree")
        features = _features(body)
        if (
            not isinstance(body.get("sourceMicroversion"), str)
            or not ONSHAPE_ID_RE.fullmatch(body["sourceMicroversion"])
            or not isinstance(body.get("serializationVersion"), str)
            or not body["serializationVersion"]
            or type(body.get("libraryVersion")) is not int
        ):
            raise _invalid("Onshape did not return a complete feature-tree version")
        matching = [f for f in features if f["featureId"] == args.sketch_feature_id]
        if (
            len(matching) != 1
            or matching[0].get("featureType") != "newSketch"
            or not _healthy(body, matching[0])
        ):
            raise _invalid("The selected sketch must exist and regenerate successfully")
        parts = await connector.get_json(
            client,
            element_base_path("parts", args.document_id, workspace, args.element_id),
            what="cut target parts",
        )
        if not isinstance(parts, list) or any(
            not isinstance(part, dict) or not isinstance(part.get("partId"), str) for part in parts
        ):
            raise _invalid("Onshape returned malformed part identities")
        target = [part for part in parts if part["partId"] == args.part_id]
        if len(target) != 1:
            raise _invalid("The cut requires exactly one observed target part")
        specs = await connector.immutable_feature_specs(
            client,
            document_id=args.document_id,
            element_id=args.element_id,
            microversion_id=body["sourceMicroversion"],
            collection="partstudios",
        )
        spec = _verify_spec(specs)
        try:
            canonical = json.dumps(
                {
                    "spec": stable_spec(spec),
                    "libraryVersion": body["libraryVersion"],
                },
                sort_keys=True,
                allow_nan=False,
            )
        except (TypeError, ValueError):
            raise _invalid("Onshape returned an invalid built-in specification") from None
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        fingerprint = ":".join(digest[i : i + 16] for i in range(0, 64, 16))
        defaults = {
            p["parameterId"]: stable_spec(p.get("defaultValue")) for p in _live_parameters(spec)
        }
        return cls(args, base, workspace, body, matching[0], target[0], fingerprint, defaults)

    def parameters(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = [
            {"btType": "BTMParameterEnum-145", "parameterId": key, "enumName": enum, "value": value}
            for key, (enum, value) in _ENUMS.items()
        ]
        result.extend(
            [
                {
                    "btType": "BTMParameterQueryList-148",
                    "parameterId": "entities",
                    "queries": [
                        {
                            "btType": "BTMIndividualSketchRegionQuery-140",
                            "featureId": self.args.sketch_feature_id,
                        }
                    ],
                },
                {
                    "btType": "BTMParameterQueryList-148",
                    "parameterId": "booleanScope",
                    "queries": [
                        {
                            "btType": "BTMIndividualQuery-138",
                            "deterministicIds": [self.args.part_id],
                        }
                    ],
                },
                {
                    "btType": "BTMParameterQuantity-147",
                    "parameterId": "depth",
                    "expression": f"{self.args.depth_mm} mm",
                },
                {
                    "btType": "BTMParameterBoolean-144",
                    "parameterId": "oppositeDirection",
                    "value": self.args.opposite_direction,
                },
                {
                    "btType": "BTMParameterBoolean-144",
                    "parameterId": "defaultScope",
                    "value": False,
                },
            ]
        )
        return result

    def payload(self) -> dict[str, Any]:
        return {
            **{
                key: self.tree[key]
                for key in ("sourceMicroversion", "serializationVersion", "libraryVersion")
            },
            "rejectMicroversionSkew": True,
            "feature": {
                "btType": "BTMFeature-134",
                "featureType": "extrude",
                "name": self.args.name,
                "suppressed": False,
                "parameters": self.parameters(),
            },
        }

    def verify(self, body: Any, identity: str) -> None:
        features = _features(body)
        matching = [feature for feature in features if feature["featureId"] == identity]
        if len(matching) != 1 or not _healthy(body, matching[0]):
            raise _unverified()
        feature = matching[0]
        if feature.get("featureType") != "extrude" or feature.get("name") != self.args.name:
            raise _unverified()
        observed = {p["parameterId"]: p for p in _live_parameters(feature)}
        for expected in self.parameters():
            actual = observed.get(expected["parameterId"], {})
            for key, value in expected.items():
                # JSON comparison distinguishes true from 1 and false from 0.
                if not _same_value(actual.get(key), value):
                    raise _unverified()
        sent = {p["parameterId"] for p in self.parameters()}
        for key in observed.keys() - sent:
            default = self.defaults.get(key)
            if not isinstance(default, dict) or not _same_value(
                stable_spec(observed[key]), default
            ):
                raise _unverified()


def _same_value(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            _same_value(actual.get(k), v) for k, v in expected.items()
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(_same_value(a, e) for a, e in zip(actual, expected, strict=True))
        )
    return type(actual) is type(expected) and actual == expected


async def preview_cut(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> list[dict[str, Any]]:
    cut = await _Cut.observe(connector, client, args)
    return preview_rows(cut)


def preview_rows(cut: _Cut) -> list[dict[str, Any]]:
    values = [
        ("Cut", cut.args.name),
        ("Part Studio", f"{cut.args.document_id} / {cut.workspace} / {cut.args.element_id}"),
        ("Source microversion", cut.tree["sourceMicroversion"]),
        ("Built-in specification fingerprint", cut.spec_fingerprint),
        (
            "Sketch regions",
            f"All sketch regions: {cut.sketch.get('name', '')} / {cut.args.sketch_feature_id}",
        ),
        ("Only target part", f"{cut.part.get('name', '')} / {cut.args.part_id}"),
        ("Blind depth", f"{cut.args.depth_mm} mm"),
        ("Opposite direction", str(cut.args.opposite_direction).lower()),
        ("Operation and scope", "REMOVE; defaultScope=false; one explicit target part"),
    ]
    if any(len(value) > 400 or not value.isprintable() for _, value in values):
        raise _invalid("The cut preview cannot be represented completely")
    return [{"label": label, "before": None, "after": value} for label, value in values]


async def extrude_cut(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> dict[str, Any]:
    cut = await _Cut.observe(connector, client, args)
    require_matching_preview(preview_rows(cut))
    old_ids = {feature["featureId"] for feature in _features(cut.tree)}
    try:
        result = await connector.post_json(
            client, f"{cut.base}/features", cut.payload(), what="scoped cut"
        )
        feature = result.get("feature") if isinstance(result, dict) else None
        identity = feature.get("featureId") if isinstance(feature, dict) else None
        if (
            not isinstance(identity, str)
            or not FEATURE_ID_RE.fullmatch(identity)
            or identity in old_ids
        ):
            raise _unverified()
        if (
            result.get("error")
            or result.get("errors")
            or result.get("microversionSkew")
            or result.get("success") is False
        ):
            raise _unverified()
        after = await connector.get_json(client, f"{cut.base}/features", what="cut verification")
        cut.verify(after, identity)
    except (ConnectorError, httpx.HTTPError, ValueError, TypeError) as error:
        raise _unverified() from error
    return {
        "feature_id": identity,
        "name": cut.args.name,
        "feature_type": "extrude",
        "part_id": cut.args.part_id,
    }


CUT_OPERATIONS = (
    OnshapeOperation(
        name="onshape.extrude_cut",
        description=(
            "Add a blind REMOVE extrusion using all regions of an existing sketch, "
            "limited to one observed target part. Preview and approval required."
        ),
        params=CutArgs.model_json_schema(),
        returns={"type": "object"},
        run=extrude_cut,
        preview=preview_cut,
        requires_confirmation=True,
        tags=("onshape", "write"),
    ),
)
