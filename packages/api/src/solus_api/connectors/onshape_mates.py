"""Root-assembly face connectors and explicit mates with bound observations."""

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Annotated, Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.onshape import ONSHAPE_ID_RE, OnshapeConnector, element_base_path
from solus_api.connectors.onshape_circle_geometry import circle_frame, verify_connector_frame
from solus_api.connectors.onshape_confirmation import require_matching_preview, stable_spec
from solus_api.connectors.onshape_cut import (
    FEATURE_ID_RE,
    FeatureIdentity,
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
from solus_api.connectors.onshape_sketch import _microversion, _point, _unique


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    document_id: Identity
    element_id: Identity
    workspace_id: Identity | None = None
    name: Annotated[str, Field(min_length=1, max_length=120)]


# Topology tokens only enter JSON queries/lookups, never resource URL paths.
_TOPOLOGY_ID = re.compile(r"[A-Za-z0-9_+/-]{1,128}")
TopologyIdentity = Annotated[str, Field(pattern=r"^[A-Za-z0-9_+/-]{1,128}$")]


class _PartConnectorArgs(_Args):
    instance_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_+/-]{1,128}$")]


class FaceConnectorArgs(_PartConnectorArgs):
    face_id: TopologyIdentity


class CircleConnectorArgs(_Args):
    edge_id: TopologyIdentity
    instance_id: TopologyIdentity | None = None
    occurrence_path: Annotated[list[TopologyIdentity], Field(min_length=1, max_length=8)] | None = (
        None
    )

    @model_validator(mode="after")
    def one_occurrence(self) -> "CircleConnectorArgs":
        if (self.instance_id is None) == (self.occurrence_path is None):
            raise ValueError("Supply exactly one root instance_id or complete occurrence_path")
        return self

    @property
    def path(self) -> tuple[str, ...]:
        if self.occurrence_path is not None:
            return tuple(self.occurrence_path)
        assert self.instance_id is not None
        return (self.instance_id,)


class FastenedMateArgs(_Args):
    first_connector_id: FeatureIdentity
    second_connector_id: FeatureIdentity


class RevoluteMateArgs(FastenedMateArgs):
    """Two observed local connectors; the operation fixes the rotational constraint."""

    axial_offset_m: (
        Annotated[float, Field(strict=True, ge=-500, le=500, allow_inf_nan=False)] | None
    ) = None


MateType = Literal["FASTENED", "REVOLUTE"]


_FLAGS = {
    "mateConnector": {"realign": False, "transform": False, "flipPrimary": False},
    "mate": {
        "mateOffsetEnabled": False,
        "limitsEnabled": False,
        "functionalconnection": False,
        "primaryAxisAlignment": True,
    },
}
_ENUMS = {
    "mateConnector": {"originType": ("Origin type", "ON_ENTITY")},
    "mate": {
        "mateType": ("Mate type", "FASTENED"),
        "secondaryAxisAlignment": ("Reorient secondary axis", "PLUS_X"),
    },
}
_QUERY = {"mateConnector": "originQuery", "mate": "mateConnectorsQuery"}


def _invalid() -> ConnectorError:
    return ConnectorError("api_error", "Mating requires complete, current assembly observations.")


def _unverified() -> ConnectorError:
    return ConnectorError(
        "mutation_unverified",
        "The assembly feature may have been created but could not be verified. "
        "Inspect Onshape before retrying.",
    )


def _fingerprint(value: Any) -> str:
    try:
        canonical = json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError):
        raise _invalid() from None
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    return ":".join(digest[i : i + 16] for i in range(0, 64, 16))


def _enum_values(kind: str, mate_type: MateType) -> dict[str, tuple[str, str]]:
    values = dict(_ENUMS[kind])
    if kind == "mate":
        values["mateType"] = ("Mate type", mate_type)
    return values


def _spec(body: Any, kind: str, mate_type: MateType = "FASTENED") -> dict[str, dict[str, Any]]:
    rows = _read_messages(body.get("featureSpecs") if isinstance(body, dict) else None)
    matches = [row for row in rows if row.get("featureType") == kind]
    if len(matches) != 1 or matches[0].get("namespace") != "":
        raise _invalid()
    parameters = {p["parameterId"]: p for p in _live_parameters(matches[0])}
    for key, (enum, value) in _enum_values(kind, mate_type).items():
        parameter = parameters.get(key, {})
        options = parameter.get("options")
        if (
            parameter.get("btType") != "BTParameterSpecEnum-171"
            or parameter.get("enumName") != enum
            or parameter.get("namespace") != ""
            or not isinstance(options, list)
            or any(not isinstance(option, str) for option in options)
            or value not in options
        ):
            raise _invalid()
    for key in _FLAGS[kind]:
        if parameters.get(key, {}).get("btType") != "BTParameterSpecBoolean-170":
            raise _invalid()
    if mate_type == "REVOLUTE":
        offset = parameters.get("mateOffsetDistanceZ", {})
        if (
            offset.get("btType") != "BTParameterSpecQuantity-173"
            or offset.get("quantityType") != "LENGTH"
        ):
            raise _invalid()
    query = parameters.get(_QUERY[kind], {})
    if (
        query.get("btType") != "BTParameterSpecQuery-174"
        or type(query.get("maxNumberOfPicks")) is not int
        or query["maxNumberOfPicks"] != (1 if kind == "mateConnector" else 2)
    ):
        raise _invalid()
    # UI visibility trees and their child order vary between GETs. Only schema
    # fields and defaults that affect execution belong to this fingerprint.
    keys = (
        "btType",
        "parameterId",
        "enumName",
        "namespace",
        "options",
        "quantityType",
        "maxNumberOfPicks",
        "defaultValue",
    )
    return {
        key: {k: stable_spec(v) for k, v in p.items() if k in keys} for key, p in parameters.items()
    }


def _root(body: Any, tree: dict[str, Any]) -> dict[str, Any]:
    root = body.get("rootAssembly") if isinstance(body, dict) else None
    if (
        not isinstance(root, dict)
        or not isinstance(root.get("documentMicroversion"), str)
        or not ONSHAPE_ID_RE.fullmatch(root["documentMicroversion"])
        or not isinstance(tree.get("sourceMicroversion"), str)
        or not ONSHAPE_ID_RE.fullmatch(tree["sourceMicroversion"])
        or root.get("documentMicroversion") != tree.get("sourceMicroversion")
        or root.get("configuration") != "default"
        or root.get("fullConfiguration", "default") != "default"
        or not isinstance(root.get("instances"), list)
        or not isinstance(root.get("occurrences"), list)
    ):
        raise _invalid()
    ids = [row.get("id") if isinstance(row, dict) else None for row in root["instances"]]
    if any(not isinstance(identity, str) or not identity for identity in ids) or len(ids) != len(
        set(ids)
    ):
        raise _invalid()
    paths: set[tuple[str, ...]] = set()
    for occurrence in root["occurrences"]:
        path = occurrence.get("path") if isinstance(occurrence, dict) else None
        transform = occurrence.get("transform") if isinstance(occurrence, dict) else None
        if (
            not isinstance(path, list)
            or not path
            or any(not isinstance(identity, str) or not identity for identity in path)
            or tuple(path) in paths
            or not isinstance(transform, list)
            or len(transform) != 16
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in transform)
        ):
            raise _invalid()
        paths.add(tuple(path))
    return root


async def _part(
    connector: OnshapeConnector,
    client: httpx.AsyncClient,
    args: _PartConnectorArgs,
    root: dict[str, Any],
    tracked: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    instance = _unique(root["instances"], args.instance_id)
    if (
        instance.get("type") != "Part"
        or instance.get("suppressed") is not False
        or instance.get("configuration") != "default"
        or instance.get("fullConfiguration", "default") != "default"
        or not any(row["path"] == [args.instance_id] for row in root["occurrences"])
    ):
        raise _invalid()
    part_id = instance.get("partId")
    if not isinstance(part_id, str) or not _TOPOLOGY_ID.fullmatch(part_id):
        raise _invalid()
    keys = ("documentId", "elementId", "documentMicroversion")
    if any(
        not isinstance(instance.get(k), str) or not ONSHAPE_ID_RE.fullmatch(instance[k])
        for k in keys
    ):
        raise _invalid()
    if not isinstance(tracked, list) or instance["documentId"] not in tracked:
        raise ConnectorError(
            "not_found", "The selected part document is not tracked in this project."
        )
    body = await connector.immutable_body_details(
        client,
        document_id=instance["documentId"],
        element_id=instance["elementId"],
        microversion_id=instance["documentMicroversion"],
    )
    if (
        not isinstance(body, dict)
        or body.get("errorEnum", "NO_ERROR") != "NO_ERROR"
        or _microversion(body) != instance["documentMicroversion"]
    ):
        raise _invalid()
    part = _unique(body.get("bodies"), instance["partId"])
    if str(part.get("type")).upper() != "SOLID":
        raise _invalid()
    return instance, part


async def _face(
    connector: OnshapeConnector,
    client: httpx.AsyncClient,
    args: FaceConnectorArgs,
    root: dict[str, Any],
    tracked: Any,
) -> dict[str, Any]:
    instance, part = await _part(connector, client, args, root, tracked)
    face = _unique(part.get("faces"), args.face_id)
    surface = face.get("surface")
    if not isinstance(surface, dict) or str(surface.get("type")).upper() != "PLANE":
        raise _invalid()
    _point(surface.get("origin"))
    normal = _point(surface.get("normal"))
    if not math.isclose(math.hypot(*normal), 1.0, rel_tol=1e-6, abs_tol=1e-6):
        raise _invalid()
    return {"instance": instance, "face": face}


def _circle_instance(
    args: CircleConnectorArgs,
    payload: dict[str, Any],
    tracked: Any,
) -> Any:
    from solus_api.connectors.onshape_assembly_geometry import InspectionArgs, _complete
    from solus_api.connectors.onshape_assembly_paths import nested_instances

    inspection = InspectionArgs(
        document_id=args.document_id,
        element_id=args.element_id,
        instance_ids=[args.path[0]],
        include_nested=True,
    )
    instances, _ = nested_instances(_complete(payload), inspection, tracked)
    matches = [instance for instance in instances if instance.path == args.path]
    if len(matches) != 1:
        raise _invalid()
    return matches[0]


async def _circle(
    connector: OnshapeConnector,
    client: httpx.AsyncClient,
    args: CircleConnectorArgs,
    payload: dict[str, Any],
    tracked: Any,
) -> dict[str, Any]:
    from solus_api.connectors.onshape_assembly_geometry import _complete

    instance = _circle_instance(args, payload, tracked)
    body = _complete(
        await connector.immutable_body_details(
            client,
            document_id=instance.document,
            element_id=instance.element,
            microversion_id=instance.revision,
        )
    )
    if _microversion(body) != instance.revision:
        raise _invalid()
    part = _unique(body.get("bodies"), instance.body)
    frame = circle_frame(part, args.edge_id, instance.transform)
    return {
        "path": args.path,
        "tracked": tuple(tracked),
        "ancestors": instance.ancestors,
        "donor": (*instance.donor, instance.body),
        "edge": _unique(part.get("edges"), args.edge_id),
        "frame": frame,
    }


def _selected_connectors(
    args: FastenedMateArgs,
    features: list[dict[str, Any]],
    tree: dict[str, Any],
    root: dict[str, Any],
) -> dict[str, Any]:
    selected = {}
    for label, identity in (
        ("first", args.first_connector_id),
        ("second", args.second_connector_id),
    ):
        matches = [f for f in features if f["featureId"] == identity]
        if (
            len(matches) != 1
            or matches[0].get("featureType") != "mateConnector"
            or not _healthy(tree, matches[0])
        ):
            raise _invalid()
        selected[label] = matches[0]
    if isinstance(args, RevoluteMateArgs):
        from solus_api.connectors.onshape_mate_offsets import measure_revolute_offset

        selected["offset"] = measure_revolute_offset(
            root, args.first_connector_id, args.second_connector_id, args.axial_offset_m
        )
    else:
        from solus_api.connectors.onshape_fastened_geometry import measure_fastened

        selected["alignment"] = measure_fastened(
            root, args.first_connector_id, args.second_connector_id
        )
    return selected


@dataclass(frozen=True)
class _Mate:
    args: FaceConnectorArgs | CircleConnectorArgs | FastenedMateArgs
    kind: str
    base: str
    workspace: str
    tree: dict[str, Any]
    root: dict[str, Any]
    selected: dict[str, Any]
    spec: dict[str, dict[str, Any]]
    mate_type: MateType = "FASTENED"

    @classmethod
    async def observe(
        cls,
        connector: OnshapeConnector,
        client: httpx.AsyncClient,
        raw: dict[str, Any],
        kind: str,
        mate_type: MateType = "FASTENED",
        circle: bool = False,
    ) -> "_Mate":
        model: type[FaceConnectorArgs | CircleConnectorArgs | FastenedMateArgs] = (
            FaceConnectorArgs if kind == "mateConnector" else FastenedMateArgs
        )
        if mate_type == "REVOLUTE":
            model = RevoluteMateArgs
        if circle:
            model = CircleConnectorArgs
        try:
            args = model.model_validate({k: v for k, v in raw.items() if k != "_documents"})
        except ValidationError:
            raise ConnectorError("config_invalid", "Invalid assembly mating arguments") from None
        if (
            not args.name.strip()
            or not args.name.isprintable()
            or (
                isinstance(args, FastenedMateArgs)
                and args.first_connector_id == args.second_connector_id
            )
        ):
            raise ConnectorError(
                "config_invalid", "Choose a printable name and distinct connectors"
            )
        workspace = await workspace_for(connector, client, args.model_dump(exclude_none=True))
        base = element_base_path("assemblies", args.document_id, workspace, args.element_id)
        tree = await connector.get_json(client, f"{base}/features", what="assembly features")
        features = _features(tree)
        if (
            not isinstance(tree.get("sourceMicroversion"), str)
            or not ONSHAPE_ID_RE.fullmatch(tree["sourceMicroversion"])
            or not isinstance(tree.get("serializationVersion"), str)
            or not tree["serializationVersion"]
            or type(tree.get("libraryVersion")) is not int
        ):
            raise _invalid()
        payload = await connector.get_json(
            client,
            base,
            what="root assembly",
            params={"includeMateFeatures": "true", "includeMateConnectors": "true"},
        )
        root = _root(payload, tree)
        if isinstance(args, CircleConnectorArgs):
            selected = await _circle(connector, client, args, payload, raw.get("_documents"))
        elif isinstance(args, FaceConnectorArgs):
            selected = await _face(connector, client, args, root, raw.get("_documents"))
        else:
            selected = _selected_connectors(args, features, tree, root)
        spec = _spec(
            await connector.immutable_feature_specs(
                client,
                document_id=args.document_id,
                element_id=args.element_id,
                microversion_id=tree["sourceMicroversion"],
                collection="assemblies",
            ),
            kind,
            mate_type,
        )
        if (
            "alignment" in selected
            and selected["alignment"]["secondary_axis_alignment"]
            not in spec["secondaryAxisAlignment"]["options"]
        ):
            raise _invalid()
        return cls(args, kind, base, workspace, tree, root, selected, spec, mate_type)

    def parameters(self) -> list[dict[str, Any]]:
        enums = _enum_values(self.kind, self.mate_type)
        if "alignment" in self.selected:
            enums["secondaryAxisAlignment"] = (
                "Reorient secondary axis",
                self.selected["alignment"]["secondary_axis_alignment"],
            )
        result: list[dict[str, Any]] = [
            {"btType": "BTMParameterEnum-145", "parameterId": key, "enumName": enum, "value": value}
            for key, (enum, value) in enums.items()
        ]
        if isinstance(self.args, (FaceConnectorArgs, CircleConnectorArgs)):
            circle = isinstance(self.args, CircleConnectorArgs)
            queries = [
                {
                    "btType": "BTMInferenceQueryWithOccurrence-1083",
                    "inferenceType": "CENTER" if circle else "CENTROID",
                    "path": list(self.args.path)
                    if isinstance(self.args, CircleConnectorArgs)
                    else [self.args.instance_id],
                    "deterministicIds": [
                        self.args.edge_id
                        if isinstance(self.args, CircleConnectorArgs)
                        else self.args.face_id
                    ],
                }
            ]
        else:
            queries = [
                {
                    "btType": "BTMFeatureQueryWithOccurrence-157",
                    "featureId": identity,
                    "path": [],
                    "queryData": "",
                }
                for identity in (self.args.first_connector_id, self.args.second_connector_id)
            ]
        result.insert(
            1,
            {
                "btType": "BTMParameterQueryWithOccurrenceList-67",
                "parameterId": _QUERY[self.kind],
                "queries": queries,
            },
        )
        flags = dict(_FLAGS[self.kind])
        if self.mate_type == "REVOLUTE":
            offset = self.selected["offset"]["applied_offset_m"]
            flags["mateOffsetEnabled"] = offset != 0
            flags["primaryAxisAlignment"] = self.selected["offset"]["primary_axis_alignment"]
            result.append(
                {
                    "btType": "BTMParameterQuantity-147",
                    "parameterId": "mateOffsetDistanceZ",
                    "expression": f"{offset:.17g} m",
                }
            )
        result.extend(
            {"btType": "BTMParameterBoolean-144", "parameterId": key, "value": value}
            for key, value in flags.items()
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
                "btType": "BTMMateConnector-66" if self.kind == "mateConnector" else "BTMMate-64",
                "featureType": self.kind,
                "name": self.args.name,
                "suppressed": False,
                **({"version": 2} if self.kind == "mate" else {}),
                "parameters": self.parameters(),
            },
        }

    def preview(self) -> list[dict[str, Any]]:
        values = [
            ("Operation", self.kind + ": " + self.args.name),
            ("Assembly", f"{self.args.document_id} / {self.workspace} / {self.args.element_id}"),
            ("Source microversion", self.tree["sourceMicroversion"]),
            ("Assembly state fingerprint", _fingerprint(self.root)),
            ("Built-in specification fingerprint", _fingerprint(self.spec)),
            ("Selected geometry fingerprint", _fingerprint(self.selected)),
        ]
        if isinstance(self.args, FaceConnectorArgs):
            instance = self.selected["instance"]
            values.extend(
                [
                    ("Root occurrence and face", f"{self.args.instance_id} / {self.args.face_id}"),
                    (
                        "Donor part",
                        " / ".join(
                            instance[k]
                            for k in ("documentId", "elementId", "partId", "documentMicroversion")
                        ),
                    ),
                    ("Origin", "CENTROID of the observed planar face; no realignment or transform"),
                ]
            )
        elif isinstance(self.args, CircleConnectorArgs):
            values.extend(
                (f"Occurrence path segment {i + 1}", value)
                for i, value in enumerate(self.args.path)
            )
            values.extend(
                [
                    ("Circle edge", self.args.edge_id),
                    ("Origin", "CENTER of an observed complete circle; no offsets or realignment"),
                    ("Expected world center (m)", str(self.selected["frame"]["origin"])),
                    ("Expected world primary axis", str(self.selected["frame"]["axis"])),
                ]
            )
        else:
            values.extend(
                [
                    ("First local connector", self.args.first_connector_id),
                    ("Second local connector", self.args.second_connector_id),
                    (
                        "Constraint",
                        f"{self.mate_type}; no "
                        + ("" if self.mate_type == "REVOLUTE" else "offset, ")
                        + "limits or functional connection; "
                        "preserve observed occurrence poses",
                    ),
                ]
            )
        if self.mate_type == "REVOLUTE":
            values.append(
                (
                    "Motion",
                    "One rotational degree of freedom; preserve every observed occurrence pose",
                )
            )
            values.append(
                ("Measured axial offset (m)", str(self.selected["offset"]["applied_offset_m"]))
            )
        if "alignment" in self.selected:
            values.append(
                (
                    "Measured secondary alignment",
                    self.selected["alignment"]["secondary_axis_alignment"],
                )
            )
        if any(not value.isprintable() or len(value) > 400 for _, value in values):
            raise _invalid()
        return [{"label": label, "before": None, "after": value} for label, value in values]

    def _post_reference(self, reference: tuple[str, ...], root: dict[str, Any]) -> tuple[str, ...]:
        # A write advances references anchored to this same document's prewrite revision.
        if (
            reference[0] == self.args.document_id
            and reference[2] == self.root["documentMicroversion"]
        ):
            return (*reference[:2], root["documentMicroversion"], *reference[3:])
        return reference

    async def verify_coordinates(
        self,
        connector: OnshapeConnector,
        client: httpx.AsyncClient,
        tree: dict[str, Any],
        identity: str,
    ) -> dict[str, Any]:
        if not isinstance(self.args, (CircleConnectorArgs, FastenedMateArgs)):
            return {}
        body = await connector.get_json(
            client,
            self.base,
            what="mate connector coordinate verification",
            params={"includeMateFeatures": "true", "includeMateConnectors": "true"},
        )
        root = _root(body, tree)
        if isinstance(self.args, FastenedMateArgs):
            from solus_api.connectors.onshape_mate_offsets import verify_revolute_poses

            verify_revolute_poses(self.root, root)
            if not isinstance(self.args, RevoluteMateArgs):
                return {
                    "pose_preserved": True,
                    "secondary_axis_alignment": self.selected["alignment"][
                        "secondary_axis_alignment"
                    ],
                }
            return {
                "pose_preserved": True,
                "axial_offset_m": self.selected["offset"]["applied_offset_m"],
            }
        observed = _circle_instance(self.args, body, list(self.selected["tracked"]))
        if observed.ancestors != tuple(
            self._post_reference(ref, root) for ref in self.selected["ancestors"]
        ) or (*observed.donor, observed.body) != self._post_reference(self.selected["donor"], root):
            raise _unverified()
        frame = verify_connector_frame(
            self.root, root, identity, self.args.path, self.selected["frame"]
        )
        return {"world_origin_m": frame["origin"], "world_axis": frame["axis"]}

    def verify(self, body: Any, identity: str) -> None:
        found = [f for f in _features(body) if f["featureId"] == identity]
        if (
            len(found) != 1
            or not _healthy(body, found[0])
            or found[0].get("name") != self.args.name
            or found[0].get("featureType") != self.kind
        ):
            raise _unverified()
        observed = {p["parameterId"]: p for p in _live_parameters(found[0])}
        expected = {p["parameterId"]: p for p in self.parameters()}
        if any(not _same_value(observed.get(key), value) for key, value in expected.items()):
            raise _unverified()
        for key in observed.keys() - expected.keys():
            default = self.spec.get(key, {}).get("defaultValue")
            if not isinstance(default, dict) or not _same_value(observed[key], default):
                raise _unverified()


async def _preview(
    connector: OnshapeConnector,
    client: httpx.AsyncClient,
    args: dict[str, Any],
    kind: str,
    mate_type: MateType = "FASTENED",
    circle: bool = False,
) -> list[dict[str, Any]]:
    return (await _Mate.observe(connector, client, args, kind, mate_type, circle)).preview()


async def _create(
    connector: OnshapeConnector,
    client: httpx.AsyncClient,
    args: dict[str, Any],
    kind: str,
    mate_type: MateType = "FASTENED",
    circle: bool = False,
) -> dict[str, Any]:
    mate = await _Mate.observe(connector, client, args, kind, mate_type, circle)
    require_matching_preview(mate.preview())
    old = {f["featureId"] for f in _features(mate.tree)}
    try:
        response = await connector.post_json(
            client, f"{mate.base}/features", mate.payload(), what="assembly mating"
        )
        feature = response.get("feature") if isinstance(response, dict) else None
        identity = feature.get("featureId") if isinstance(feature, dict) else None
        if (
            not isinstance(identity, str)
            or not FEATURE_ID_RE.fullmatch(identity)
            or identity in old
            or response.get("error")
            or response.get("errors")
            or response.get("microversionSkew")
            or response.get("success") is False
        ):
            raise _unverified()
        after = await connector.get_json(
            client, f"{mate.base}/features", what="assembly mating verification"
        )
        mate.verify(after, identity)
        coordinates = await mate.verify_coordinates(connector, client, after, identity)
    except (ConnectorError, httpx.HTTPError, ValueError, TypeError) as error:
        raise _unverified() from error
    return {"feature_id": identity, "feature_type": kind, "name": mate.args.name, **coordinates}


async def preview_face_mate_connector(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> list[dict[str, Any]]:
    return await _preview(connector, client, args, "mateConnector")


async def create_face_mate_connector(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> dict[str, Any]:
    return await _create(connector, client, args, "mateConnector")


async def preview_fastened_mate(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> list[dict[str, Any]]:
    return await _preview(connector, client, args, "mate")


async def create_fastened_mate(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> dict[str, Any]:
    return await _create(connector, client, args, "mate")


async def preview_revolute_mate(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> list[dict[str, Any]]:
    return await _preview(connector, client, args, "mate", "REVOLUTE")


async def create_revolute_mate(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> dict[str, Any]:
    return await _create(connector, client, args, "mate", "REVOLUTE")


async def preview_circle_mate_connector(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> list[dict[str, Any]]:
    return await _preview(connector, client, args, "mateConnector", circle=True)


async def create_circle_mate_connector(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> dict[str, Any]:
    return await _create(connector, client, args, "mateConnector", circle=True)


MATE_OPERATIONS = (
    OnshapeOperation(
        name="onshape.create_face_mate_connector",
        description=(
            "Create a centroid mate connector on one observed planar face of a root "
            "Part instance. No offsets or realignment. Requires preview and approval."
        ),
        params=FaceConnectorArgs.model_json_schema(),
        returns={"type": "object"},
        run=create_face_mate_connector,
        preview=preview_face_mate_connector,
        requires_confirmation=True,
        tags=("onshape", "write"),
    ),
    OnshapeOperation(
        name="onshape.create_fastened_mate",
        description=(
            "Fasten two distinct, observed assembly-local mate connectors without "
            "offsets or limits. Requires preview and approval."
        ),
        params=FastenedMateArgs.model_json_schema(),
        returns={"type": "object"},
        run=create_fastened_mate,
        preview=preview_fastened_mate,
        requires_confirmation=True,
        tags=("onshape", "write"),
    ),
    OnshapeOperation(
        name="onshape.create_revolute_mate",
        description=(
            "Join two distinct, healthy assembly-local mate connectors with one rotational "
            "degree of freedom while preserving observed poses. Coaxial antiparallel axes "
            "must already coincide, or supply axial_offset_m matching the measured "
            "dot(first_origin-second_origin, first_world_z) in meters. No limits or "
            "functional connections. Requires a complete state-bound preview and pose readback."
        ),
        params=RevoluteMateArgs.model_json_schema(),
        returns={"type": "object"},
        run=create_revolute_mate,
        preview=preview_revolute_mate,
        requires_confirmation=True,
        tags=("onshape", "write"),
    ),
    OnshapeOperation(
        name="onshape.create_circle_mate_connector",
        description=(
            "Create a CENTER mate connector on a verified complete circular edge of one "
            "part occurrence. Supply exactly one root instance_id or complete occurrence_path "
            "(up to eight segments); all ancestor and donor documents must be tracked. "
            "No offsets or realignment. Verifies actual world "
            "center/axis and unchanged occurrence poses. Requires a bound complete preview."
        ),
        params=CircleConnectorArgs.model_json_schema(),
        returns={"type": "object"},
        run=create_circle_mate_connector,
        preview=preview_circle_mate_connector,
        requires_confirmation=True,
        tags=("onshape", "write"),
    ),
)
