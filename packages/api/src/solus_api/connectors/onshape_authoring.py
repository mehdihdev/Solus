"""Part discovery and one-part insertion using published Onshape schemas.

Insertion is pinned to an observed donor microversion. Its generic vendor
response is never treated as proof: a subsequent assembly read must identify
exactly one new matching instance, or the outcome is explicitly unverified.
"""

import re
from dataclasses import dataclass
from math import isfinite
from typing import Any

import httpx

from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.onshape import OnshapeConnector, element_base_path
from solus_api.connectors.onshape_confirmation import require_matching_preview
from solus_api.connectors.onshape_ops import OnshapeOperation, schema, validated_id, workspace_for


async def list_parts(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> dict[str, Any]:
    document = validated_id(args, "document_id")
    element = validated_id(args, "element_id")
    workspace = await workspace_for(connector, client, args)
    parts = await connector.get_json(
        client, element_base_path("parts", document, workspace, element), what="parts"
    )
    if not isinstance(parts, list) or not all(
        isinstance(part, dict) and isinstance(part.get("partId"), str) for part in parts
    ):
        raise ConnectorError("api_error", "Onshape returned an invalid part listing")
    return {"parts": parts}


async def get_part_bounds(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> dict[str, Any]:
    document = validated_id(args, "document_id")
    element = validated_id(args, "element_id")
    part = validated_id(args, "part_id")
    workspace = await workspace_for(connector, client, args)
    body = await connector.get_json(
        client,
        f"{element_base_path('parts', document, workspace, element)}/partid/{part}/boundingboxes",
        what="part bounds",
    )
    if not isinstance(body, dict):
        raise ConnectorError("api_error", "Onshape returned invalid part bounds")
    for axis in "XYZ":
        low, high = body.get(f"low{axis}"), body.get(f"high{axis}")
        if (
            not isinstance(low, (int, float))
            or isinstance(low, bool)
            or not isinstance(high, (int, float))
            or isinstance(high, bool)
            or not isfinite(low)
            or not isfinite(high)
            or low > high
        ):
            raise ConnectorError("api_error", "Onshape returned invalid part bounds")
    return body


@dataclass(frozen=True)
class _Insertion:
    target: str
    document: str
    element: str
    part: str
    microversion: str

    @classmethod
    async def from_args(
        cls, connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
    ) -> "_Insertion":
        # Validate every identifier before even default-workspace discovery.
        ids = {
            key: validated_id(args, key)
            for key in (
                "document_id",
                "element_id",
                "source_document_id",
                "source_element_id",
                "part_id",
                "source_microversion_id",
            )
        }
        workspace = await workspace_for(connector, client, args)
        return cls(
            element_base_path("assemblies", ids["document_id"], workspace, ids["element_id"]),
            ids["source_document_id"],
            ids["source_element_id"],
            ids["part_id"],
            ids["source_microversion_id"],
        )

    async def donor(self, connector: OnshapeConnector, client: httpx.AsyncClient) -> dict[str, Any]:
        parts = await connector.get_json(
            client,
            f"/api/v6/parts/d/{self.document}/m/{self.microversion}/e/{self.element}",
            what="donor part",
        )
        if not isinstance(parts, list):
            raise ConnectorError("api_error", "Onshape returned an invalid donor listing")
        matches = [
            part for part in parts if isinstance(part, dict) and part.get("partId") == self.part
        ]
        if len(matches) != 1:
            raise ConnectorError("not_found", "The donor part was not found at that microversion")
        return matches[0]

    async def assembly(
        self, connector: OnshapeConnector, client: httpx.AsyncClient
    ) -> dict[str, Any]:
        body = await connector.get_json(client, self.target, what="target assembly")
        root = body.get("rootAssembly") if isinstance(body, dict) else None
        if (
            not isinstance(root, dict)
            or not isinstance(root.get("instances"), list)
            or not isinstance(root.get("documentMicroversion"), str)
            or not root["documentMicroversion"]
        ):
            raise ConnectorError("api_error", "Onshape returned an invalid target assembly")
        identities: set[str] = set()
        for instance in root["instances"]:
            identity = instance.get("id") if isinstance(instance, dict) else None
            if (
                not isinstance(identity, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", identity)
                or identity in identities
            ):
                raise ConnectorError(
                    "api_error", "Onshape returned invalid assembly instance identities"
                )
            identities.add(identity)
        return root

    def payload(self) -> dict[str, Any]:
        return {
            "documentId": self.document,
            "elementId": self.element,
            "partId": self.part,
            "microversionId": self.microversion,
            "isAssembly": False,
            "isWholePartStudio": False,
            "isHidden": False,
            "isSuppressed": False,
        }

    def matches(self, instance: Any) -> bool:
        return (
            isinstance(instance, dict)
            and all(
                instance.get(key) == value
                for key, value in {
                    "documentId": self.document,
                    "elementId": self.element,
                    "partId": self.part,
                    "documentMicroversion": self.microversion,
                }.items()
            )
            and instance.get("isHidden", False) is False
            and instance.get("isSuppressed", False) is False
            and not instance.get("errorStatus")
            and not instance.get("status")
        )


def _unverified() -> ConnectorError:
    return ConnectorError(
        "mutation_unverified",
        "Insertion could not be verified. Inspect the assembly before trying again "
        "to avoid inserting a duplicate.",
    )


async def preview_insert(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> list[dict[str, Any]]:
    insertion = await _Insertion.from_args(connector, client, args)
    donor = await insertion.donor(connector, client)
    root = await insertion.assembly(connector, client)
    return _insertion_rows(insertion, args, donor, root)


def _insertion_rows(
    insertion: _Insertion, args: dict[str, Any], donor: dict[str, Any], root: dict[str, Any]
) -> list[dict[str, Any]]:
    return [
        {
            "label": "target assembly",
            "before": None,
            "after": f"{args['document_id']} / {args['element_id']}",
        },
        {
            "label": "target microversion",
            "before": root["documentMicroversion"],
            "after": root["documentMicroversion"],
        },
        {
            "label": "insert one part",
            "before": None,
            "after": (
                f"{donor.get('name') or insertion.part}: {insertion.document} / "
                f"{insertion.element} / {insertion.part}"
            ),
        },
        {"label": "donor microversion", "before": None, "after": insertion.microversion},
    ]


async def insert_part(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> dict[str, Any]:
    insertion = await _Insertion.from_args(connector, client, args)
    donor = await insertion.donor(connector, client)
    before = await insertion.assembly(connector, client)
    require_matching_preview(_insertion_rows(insertion, args, donor, before))
    old_ids = {row["id"] for row in before["instances"]}
    try:
        response = await connector.post_json(
            client, f"{insertion.target}/instances", insertion.payload(), what="part insertion"
        )
    except ConnectorError as exc:
        # A rejected credential can safely refresh; other POST failures may
        # have committed server-side, so never advertise an automatic retry.
        if exc.code == "invalid_credentials":
            raise
        raise _unverified() from exc
    if (
        not isinstance(response, dict)
        or response.get("error")
        or response.get("errors")
        or response.get("errorStatus")
        or response.get("success") is False
        or str(response.get("status", "")).upper() in {"ERROR", "FAILED", "FAILURE"}
    ):
        raise _unverified()
    try:
        after = await insertion.assembly(connector, client)
    except ConnectorError as exc:
        # In particular, a 401 AFTER insertion must not cause call_with_refresh
        # to rerun the entire write and create a second instance.
        raise _unverified() from exc
    created = [
        row["id"]
        for row in after["instances"]
        if insertion.matches(row)
        and isinstance(row.get("id"), str)
        and row["id"]
        and row["id"] not in old_ids
    ]
    if len(created) != 1:
        raise _unverified()
    return {"instance_ids": created}


_PART_ID = {"type": "string", "description": "Actual partId from onshape.list_parts."}
AUTHORING_OPERATIONS = (
    OnshapeOperation(
        name="onshape.list_parts",
        description="List live parts, names, part IDs, and observed microversion IDs.",
        params=schema(element=True, required=("document_id", "element_id")),
        returns={"type": "object"},
        run=list_parts,
    ),
    OnshapeOperation(
        name="onshape.get_part_bounds",
        description="Read the exact live bounding box of a discovered part.",
        params=schema(
            element=True,
            extra={"part_id": _PART_ID},
            required=("document_id", "element_id", "part_id"),
        ),
        returns={"type": "object"},
        run=get_part_bounds,
    ),
    OnshapeOperation(
        name="onshape.insert_part",
        description=(
            "Insert one discovered part into an assembly, pinned to its observed "
            "immutable microversion. Both documents must be tracked in this project. "
            "Requires approval of the target and donor preview."
        ),
        params=schema(
            element=True,
            extra={
                "part_id": _PART_ID,
                "source_document_id": {
                    "type": "string",
                    "description": "Tracked donor document id.",
                },
                "source_element_id": {
                    "type": "string",
                    "description": "Donor Part Studio element id.",
                },
                "source_microversion_id": {
                    "type": "string",
                    "description": "Observed donor microversionId from list_parts.",
                },
            },
            required=(
                "document_id",
                "element_id",
                "source_document_id",
                "source_element_id",
                "part_id",
                "source_microversion_id",
            ),
        ),
        returns={"type": "object"},
        run=insert_part,
        requires_confirmation=True,
        preview=preview_insert,
        tags=("write", "geometry"),
    ),
)
