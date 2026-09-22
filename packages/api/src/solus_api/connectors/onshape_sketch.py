"""Create one metric circle on an observed planar face, with verified readback."""

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Annotated, Any, cast

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.onshape import ONSHAPE_ID_RE, OnshapeConnector, element_base_path
from solus_api.connectors.onshape_confirmation import require_matching_preview, stable_spec
from solus_api.connectors.onshape_cut import (
    FEATURE_ID_RE,
    Identity,
    _features,
    _healthy,
    _same_value,
)
from solus_api.connectors.onshape_ops import (
    OnshapeOperation,
    _live_parameters,
    _read_messages,
    workspace_for,
)

Coordinate = Annotated[float, Field(ge=-10000, le=10000)]


class SketchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    document_id: Identity
    workspace_id: Identity | None = None
    element_id: Identity
    body_id: Identity
    face_id: Identity
    name: Annotated[str, Field(min_length=1, max_length=120)]
    center_x_mm: Coordinate
    center_y_mm: Coordinate
    radius_mm: Annotated[float, Field(gt=0, le=10000)]


def _invalid() -> ConnectorError:
    return ConnectorError(
        "api_error",
        "The sketch requires complete, current planar geometry and feature specifications.",
    )


def _unverified() -> ConnectorError:
    return ConnectorError(
        "mutation_unverified",
        "The sketch may have been created but its result could not be verified. "
        "Inspect Onshape before retrying.",
    )


def _point(value: Any) -> list[float]:
    if isinstance(value, dict):
        value = [value.get(axis) for axis in "xyz"]
    if (
        not isinstance(value, list)
        or len(value) != 3
        or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
            for v in value
        )
    ):
        raise _invalid()
    return [float(v) for v in value]


def _unique(rows: Any, identity: str) -> dict[str, Any]:
    if not isinstance(rows, list) or any(
        not isinstance(row, dict) or not isinstance(row.get("id"), str) for row in rows
    ):
        raise _invalid()
    ids = [row["id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise _invalid()
    selected = [row for row in rows if row["id"] == identity]
    if len(selected) != 1:
        raise _invalid()
    return cast(dict[str, Any], selected[0])


def _spec(body: Any) -> dict[str, Any]:
    rows = _read_messages(body.get("featureSpecs") if isinstance(body, dict) else None)
    matches = [row for row in rows if row.get("featureType") == "newSketch"]
    if len(matches) != 1 or matches[0].get("namespace") != "":
        raise _invalid()
    params = {p["parameterId"]: p for p in _live_parameters(matches[0])}
    plane = params.get("sketchPlane", {})
    default = plane.get("defaultValue")
    if (
        plane.get("btType") != "BTParameterSpecQuery-174"
        or not isinstance(default, dict)
        or default.get("btType") != "BTMParameterQueryList-148"
    ):
        raise _invalid()
    return matches[0]


def _microversion(geometry: dict[str, Any]) -> Any:
    value = geometry.get("microversionId")
    if isinstance(value, dict) and value.get("btType") == "BTMicroversionId-366":
        return value.get("theId")
    return value


def _verify_parameters(actual: dict[str, Any], expected: dict[str, Any]) -> None:
    observed = {p["parameterId"]: p for p in _live_parameters(actual)}
    if set(observed) - {"sketchPlane", "disableImprinting", "asVersion"}:
        raise _unverified()
    if not _same_value(observed.get("sketchPlane"), expected["parameters"][0]):
        raise _unverified()
    if "disableImprinting" in observed and not _same_value(
        observed["disableImprinting"], {"btType": "BTMParameterBoolean-144", "value": False}
    ):
        raise _unverified()
    version = observed.get("asVersion")
    if version is not None and (
        not _same_value(
            version,
            {
                "btType": "BTMParameterEnum-145",
                "enumName": "FeatureScriptVersionNumber",
                "namespace": "",
            },
        )
        or not isinstance(version.get("value"), str)
        or not version["value"].startswith("V")
    ):
        raise _unverified()


@dataclass(frozen=True)
class _Sketch:
    args: SketchArgs
    base: str
    workspace: str
    tree: dict[str, Any]
    origin: list[float]
    normal: list[float]
    fingerprint: str

    @classmethod
    async def observe(
        cls, connector: OnshapeConnector, client: httpx.AsyncClient, raw: dict[str, Any]
    ) -> "_Sketch":
        try:
            args = SketchArgs.model_validate({k: v for k, v in raw.items() if k != "_documents"})
        except ValidationError:
            raise ConnectorError("config_invalid", "Invalid circle sketch arguments") from None
        if not args.name.strip() or not args.name.isprintable():
            raise ConnectorError("config_invalid", "Sketch name must be printable and nonempty")
        workspace = await workspace_for(connector, client, args.model_dump(exclude_none=True))
        base = element_base_path("partstudios", args.document_id, workspace, args.element_id)
        tree = await connector.get_json(client, f"{base}/features", what="sketch feature tree")
        _features(tree)
        if (
            not isinstance(tree.get("sourceMicroversion"), str)
            or not ONSHAPE_ID_RE.fullmatch(tree["sourceMicroversion"])
            or not isinstance(tree.get("serializationVersion"), str)
            or not tree["serializationVersion"]
            or type(tree.get("libraryVersion")) is not int
        ):
            raise _invalid()
        geometry = await connector.get_json(
            client, f"{base}/bodydetails", what="sketch planar face"
        )
        if (
            not isinstance(geometry, dict)
            or geometry.get("errorEnum", "NO_ERROR") != "NO_ERROR"
            or _microversion(geometry) != tree["sourceMicroversion"]
        ):
            raise _invalid()
        body = _unique(geometry.get("bodies"), args.body_id)
        face = _unique(body.get("faces"), args.face_id)
        surface = face.get("surface")
        if not isinstance(surface, dict) or str(surface.get("type")).upper() != "PLANE":
            raise _invalid()
        origin, normal = _point(surface.get("origin")), _point(surface.get("normal"))
        if not math.isclose(math.hypot(*normal), 1.0, rel_tol=1e-6, abs_tol=1e-6):
            raise _invalid()
        spec = _spec(
            await connector.immutable_feature_specs(
                client,
                document_id=args.document_id,
                element_id=args.element_id,
                microversion_id=tree["sourceMicroversion"],
                collection="partstudios",
            )
        )
        try:
            canonical = json.dumps(
                {
                    "body": body,
                    "spec": stable_spec(spec),
                    # Fresh serialization metadata is echoed on POST, but is not CAD identity.
                    "tree": stable_spec(
                        {k: v for k, v in tree.items() if k != "serializationVersion"}
                    ),
                },
                sort_keys=True,
                allow_nan=False,
            )
        except (TypeError, ValueError):
            raise _invalid() from None
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        return cls(
            args,
            base,
            workspace,
            tree,
            origin,
            normal,
            ":".join(digest[i : i + 16] for i in range(0, 64, 16)),
        )

    def feature(self) -> dict[str, Any]:
        return {
            "btType": "BTMSketch-151",
            "featureType": "newSketch",
            "name": self.args.name,
            "suppressed": False,
            "parameters": [
                {
                    "btType": "BTMParameterQueryList-148",
                    "parameterId": "sketchPlane",
                    "queries": [
                        {
                            "btType": "BTMIndividualQuery-138",
                            "deterministicIds": [self.args.face_id],
                        }
                    ],
                }
            ],
            "entities": [
                {
                    "btType": "BTMSketchCurve-4",
                    "isConstruction": False,
                    "entityId": "solus-circle",
                    "centerId": "solus-circle.center",
                    "geometry": {
                        "btType": "BTCurveGeometryCircle-115",
                        "xCenter": self.args.center_x_mm / 1000,
                        "yCenter": self.args.center_y_mm / 1000,
                        "radius": self.args.radius_mm / 1000,
                        "xDir": 1,
                        "yDir": 0,
                        "clockwise": False,
                    },
                }
            ],
            "constraints": [],
        }

    def rows(self) -> list[dict[str, Any]]:
        values = [
            ("Sketch", self.args.name),
            ("Part Studio", f"{self.args.document_id} / {self.workspace} / {self.args.element_id}"),
            ("Body and planar face", f"{self.args.body_id} / {self.args.face_id}"),
            ("Source microversion", self.tree["sourceMicroversion"]),
            ("Geometry and specification", self.fingerprint),
            ("Plane origin in metres", str(self.origin)),
            ("Plane normal", str(self.normal)),
            (
                "Centre in local sketch plane",
                f"({self.args.center_x_mm}, {self.args.center_y_mm}) mm",
            ),
            ("Radius", f"{self.args.radius_mm} mm"),
        ]
        return [{"label": k, "before": None, "after": v} for k, v in values]

    def verify(self, body: Any, identity: str) -> dict[str, Any]:
        matches = [f for f in _features(body) if f["featureId"] == identity]
        if len(matches) != 1 or not _healthy(body, matches[0]):
            raise _unverified()
        actual, expected = matches[0], self.feature()
        _verify_parameters(actual, expected)
        if (
            actual.get("constraints") != []
            or actual.get("featureType") != "newSketch"
            or actual.get("name") != self.args.name
        ):
            raise _unverified()
        entities = actual.get("entities")
        if (
            not isinstance(entities, list)
            or len(entities) != 1
            or not isinstance(entities[0], dict)
        ):
            raise _unverified()
        entity, wanted = entities[0], expected["entities"][0]
        if entity.get("isConstruction", False) is not False:
            raise _unverified()
        observed = entity.get("geometry")
        if not isinstance(observed, dict) or any(
            entity.get(k) != wanted[k] for k in ("btType", "entityId", "centerId")
        ):
            raise _unverified()
        for key, value in wanted["geometry"].items():
            got = observed.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if (
                    isinstance(got, bool)
                    or not isinstance(got, (int, float))
                    or not math.isfinite(got)
                    or not math.isclose(got, value, rel_tol=1e-10, abs_tol=1e-12)
                ):
                    raise _unverified()
            elif not _same_value(got, value):
                raise _unverified()
        return observed


async def preview_sketch(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> list[dict[str, Any]]:
    return (await _Sketch.observe(connector, client, args)).rows()


async def create_circle_sketch(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> dict[str, Any]:
    sketch = await _Sketch.observe(connector, client, args)
    require_matching_preview(sketch.rows())
    old_ids = {f["featureId"] for f in _features(sketch.tree)}
    payload = {
        **{
            k: sketch.tree[k]
            for k in ("sourceMicroversion", "serializationVersion", "libraryVersion")
        },
        "rejectMicroversionSkew": True,
        "feature": sketch.feature(),
    }
    try:
        result = await connector.post_json(
            client, f"{sketch.base}/features", payload, what="circle sketch"
        )
        feature = result.get("feature") if isinstance(result, dict) else None
        identity = feature.get("featureId") if isinstance(feature, dict) else None
        if (
            not isinstance(identity, str)
            or not FEATURE_ID_RE.fullmatch(identity)
            or identity in old_ids
            or result.get("error")
            or result.get("errors")
            or result.get("microversionSkew")
            or result.get("success") is False
        ):
            raise _unverified()
        after = await connector.get_json(
            client, f"{sketch.base}/features", what="circle sketch verification"
        )
        geometry = sketch.verify(after, identity)
    except (ConnectorError, httpx.HTTPError, ValueError, TypeError) as exc:
        raise _unverified() from exc
    return {"feature_id": identity, "name": sketch.args.name, "geometry": geometry}


SKETCH_OPERATIONS = (
    OnshapeOperation(
        name="onshape.create_circle_sketch",
        description=(
            "Create one circle on an observed planar face. Centre coordinates use "
            "the local sketch plane in mm. Requires a complete preview and approval."
        ),
        params=SketchArgs.model_json_schema(),
        returns={"type": "object"},
        run=create_circle_sketch,
        preview=preview_sketch,
        requires_confirmation=True,
        tags=("write", "geometry"),
    ),
)
