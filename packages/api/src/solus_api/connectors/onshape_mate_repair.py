"""Recover an observed rigid mate's secondary alignment from immutable historical poses."""

import copy
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.onshape import OnshapeConnector, element_base_path
from solus_api.connectors.onshape_assembly_geometry import InspectionArgs, _complete
from solus_api.connectors.onshape_assembly_paths import nested_instances
from solus_api.connectors.onshape_circle_geometry import _poses
from solus_api.connectors.onshape_confirmation import require_matching_preview
from solus_api.connectors.onshape_cut import (
    FeatureIdentity,
    Identity,
    _features,
    _healthy,
    _same_value,
)
from solus_api.connectors.onshape_fastened_geometry import measure_fastened
from solus_api.connectors.onshape_mate_offsets import verify_revolute_poses
from solus_api.connectors.onshape_mates import _fingerprint, _invalid, _root, _spec, _unverified
from solus_api.connectors.onshape_ops import OnshapeOperation, _live_parameters, workspace_for

_INCLUDE = {"includeMateFeatures": "true", "includeMateConnectors": "true"}


class RepairArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    document_id: Identity
    element_id: Identity
    workspace_id: Identity | None = None
    feature_id: FeatureIdentity
    reference_microversion: Identity


def _feature(tree: dict[str, Any], identity: str) -> dict[str, Any]:
    matches = [f for f in _features(tree) if f["featureId"] == identity]
    if (
        len(matches) != 1
        or not _healthy(tree, matches[0])
        or matches[0].get("featureType") != "mate"
    ):
        raise _invalid()
    return matches[0]


def _connectors(feature: dict[str, Any]) -> tuple[str, str]:
    params = {p["parameterId"]: p for p in _live_parameters(feature)}
    required = {
        "mateType": "FASTENED",
        "primaryAxisAlignment": True,
        "mateOffsetEnabled": False,
        "limitsEnabled": False,
        "functionalconnection": False,
    }
    for key, value in required.items():
        if not _same_value(params.get(key), {"value": value}):
            raise _invalid()
    query = params.get("mateConnectorsQuery", {})
    rows = query.get("queries")
    if not isinstance(rows, list) or len(rows) != 2:
        raise _invalid()
    identities = []
    for row in rows:
        if (
            not isinstance(row, dict)
            or row.get("btType") != "BTMFeatureQueryWithOccurrence-157"
            or row.get("path") != []
        ):
            raise _invalid()
        identity = row.get("featureId")
        if not isinstance(identity, str):
            raise _invalid()
        identities.append(identity)
    return identities[0], identities[1]


def _identities(payload: dict[str, Any], args: RepairArgs, tracked: Any) -> dict[Any, Any]:
    inspection = InspectionArgs(
        document_id=args.document_id, element_id=args.element_id, include_nested=True
    )
    instances, _ = nested_instances(payload, inspection, tracked)
    revision = payload["rootAssembly"]["documentMicroversion"]

    def stable(ref: tuple[str, ...]) -> tuple[Any, ...]:
        anchored = ref[0] == args.document_id and ref[2] == revision
        return (
            *ref[:2],
            (anchored, None if anchored else ref[2]),
            *ref[3:],
        )

    return {
        instance.path: (
            stable((*instance.donor, instance.body)),
            tuple(stable(a) for a in instance.ancestors),
        )
        for instance in instances
    }


def _same_assembly(
    before: dict[str, Any], after: dict[str, Any], args: RepairArgs, tracked: Any
) -> None:
    _complete(before)
    _complete(after)
    if _poses(before["rootAssembly"]).keys() != _poses(after["rootAssembly"]).keys() or _identities(
        before, args, tracked
    ) != _identities(after, args, tracked):
        raise _invalid()


@dataclass(frozen=True)
class _Repair:
    args: RepairArgs
    base: str
    tree: dict[str, Any]
    current: dict[str, Any]
    historical: dict[str, Any]
    feature: dict[str, Any]
    alignment: dict[str, Any]
    spec: dict[str, Any]
    tracked: Any

    @classmethod
    async def observe(
        cls, connector: OnshapeConnector, client: httpx.AsyncClient, raw: dict[str, Any]
    ) -> "_Repair":
        try:
            args = RepairArgs.model_validate({k: v for k, v in raw.items() if k != "_documents"})
        except ValidationError:
            raise _invalid() from None
        workspace = await workspace_for(connector, client, args.model_dump(exclude_none=True))
        base = element_base_path("assemblies", args.document_id, workspace, args.element_id)
        tree = await connector.get_json(client, base + "/features", what="rigid mate state")
        feature = _feature(tree, args.feature_id)
        first, second = _connectors(feature)
        for identity in (first, second):
            matches = [f for f in _features(tree) if f["featureId"] == identity]
            if (
                len(matches) != 1
                or matches[0].get("featureType") != "mateConnector"
                or not _healthy(tree, matches[0])
            ):
                raise _invalid()
        current = await connector.get_json(
            client, base, what="current rigid assembly", params=_INCLUDE
        )
        _root(current, tree)
        historical = await connector.get_json(
            client,
            base.replace(f"/w/{workspace}/", f"/m/{args.reference_microversion}/"),
            what="historical rigid assembly",
            params=_INCLUDE,
        )
        _root(historical, {"sourceMicroversion": args.reference_microversion})
        _same_assembly(historical, current, args, raw.get("_documents"))
        measured = copy.deepcopy(current["rootAssembly"])
        measured["occurrences"] = historical["rootAssembly"]["occurrences"]
        alignment = measure_fastened(measured, first, second)
        spec = _spec(
            await connector.immutable_feature_specs(
                client,
                document_id=args.document_id,
                element_id=args.element_id,
                microversion_id=tree["sourceMicroversion"],
                collection="assemblies",
            ),
            "mate",
        )
        if alignment["secondary_axis_alignment"] not in spec["secondaryAxisAlignment"]["options"]:
            raise _invalid()
        return cls(
            args, base, tree, current, historical, feature, alignment, spec, raw.get("_documents")
        )

    def edited(self) -> dict[str, Any]:
        feature = copy.deepcopy(self.feature)
        params = {p["parameterId"]: p for p in _live_parameters(feature)}
        axis = params.get("secondaryAxisAlignment")
        if (
            not isinstance(axis, dict)
            or axis.get("btType") != "BTMParameterEnum-145"
            or axis.get("enumName") != "Reorient secondary axis"
        ):
            raise _invalid()
        axis["value"] = self.alignment["secondary_axis_alignment"]
        return feature

    def preview(self) -> list[dict[str, Any]]:
        edited = self.edited()
        return [
            {"label": label, "before": None, "after": value}
            for label, value in (
                ("Operation", "Restore rigid mate secondary alignment"),
                ("Feature", self.args.feature_id),
                ("Reference microversion", self.args.reference_microversion),
                ("Current assembly fingerprint", _fingerprint(self.current)),
                ("Historical pose fingerprint", _fingerprint(self.historical)),
                ("Current feature fingerprint", _fingerprint(self.feature)),
                ("Observed specification fingerprint", _fingerprint(self.spec)),
                ("Measured alignment fingerprint", _fingerprint(self.alignment)),
                ("Secondary alignment", self.alignment["secondary_axis_alignment"]),
                ("Edit fingerprint", _fingerprint(edited)),
            )
        ]

    async def run(self, connector: OnshapeConnector, client: httpx.AsyncClient) -> dict[str, Any]:
        require_matching_preview(self.preview())
        feature = self.edited()
        envelope = {
            k: self.tree[k]
            for k in ("sourceMicroversion", "serializationVersion", "libraryVersion")
        }
        try:
            response = await connector.post_json(
                client,
                f"{self.base}/features/featureid/{quote(self.args.feature_id, safe='')}",
                {**envelope, "rejectMicroversionSkew": True, "feature": feature},
                what="restore rigid mate alignment",
            )
            if (
                not isinstance(response, dict)
                or any(response.get(k) for k in ("error", "errors", "microversionSkew"))
                or response.get("success") is False
            ):
                raise _unverified()
            tree = await connector.get_json(
                client, self.base + "/features", what="restored mate verification"
            )
            if not _same_value(_feature(tree, self.args.feature_id), feature):
                raise _unverified()
            after = await connector.get_json(
                client, self.base, what="restored rigid pose verification", params=_INCLUDE
            )
            _root(after, tree)
            _same_assembly(self.historical, after, self.args, self.tracked)
            verify_revolute_poses(self.historical["rootAssembly"], after["rootAssembly"])
        except (ConnectorError, httpx.HTTPError, ValueError, TypeError, KeyError) as error:
            raise _unverified() from error
        return {
            "feature_id": self.args.feature_id,
            "pose_restored": True,
            "secondary_axis_alignment": self.alignment["secondary_axis_alignment"],
            "reference_microversion": self.args.reference_microversion,
        }


async def preview(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> list[dict[str, Any]]:
    return (await _Repair.observe(connector, client, args)).preview()


async def restore(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> dict[str, Any]:
    return await (await _Repair.observe(connector, client, args)).run(connector, client)


REPAIR_OPERATION = OnshapeOperation(
    name="onshape.restore_fastened_pose",
    description=(
        "Restore an existing healthy no-offset FASTENED mate to immutable historical assembly "
        "poses by changing only its measured secondary alignment. Requires stable part identities "
        "and a complete bound preview; verifies every historical occurrence pose afterward."
    ),
    params=RepairArgs.model_json_schema(),
    returns={"type": "object"},
    run=restore,
    preview=preview,
    requires_confirmation=True,
    tags=("onshape", "write"),
)
