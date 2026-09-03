"""Transport-free Onshape operations — SOLUS-ONS-A1.

The operations an Onshape MCP server exposes, expressed as plain async functions
over an already-authenticated client. Deliberately **not** tools and **not** a
transport:

* today they are wrapped as in-process `Tool`s (`agent/tools/onshape_tools.py`),
  which inherits arg validation, timeouts, the never-raises envelope and the
  destructive-action gate from the W0-04 registry;
* later the same functions can back a stdio/HTTP MCP server, or sit on top of
  Onshape's own official server if it ships — the spec's "keep the tool interface
  separable from the transport" requirement, satisfied by having no transport here
  at all.

**Scope is never an argument.** No operation accepts `project_id`, `team_id` or a
secret ref; the tool layer binds the tenant before the model sees anything
(CLAUDE.md §7, the `get_entity` idiom). Every id the model *does* supply is
validated against `_ID_RE` before it reaches a URL.

A1 was reads and queries only; A3 adds writes, every one of them behind
`requires_confirmation` and each able to describe its own change so a user
approves a DIFF rather than an action name. `get_body_details` is deliberately
here because its face/edge ids ARE the deterministic ids a write parameter takes
— the resolver A4 builds on.

**Nothing here invents a payload.** `BTVariableParams` is fully published, so
`set_variable` is spec-derived. Every BTM parameter subtype
(`BTMParameterQuantity-147` and the rest) is a `btType`-only stub in Onshape's
OpenAPI spec, so `add_feature` clones the value field carried by the LIVE
`featurespecs` default and refuses anything it cannot derive that way. A refused
write is recoverable; a corrupted model is not.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Final

import httpx

from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.onshape import (
    ONSHAPE_ID_RE,
    ONSHAPE_MAX_PAGE_LIMIT,
    OnshapeConnector,
    element_base_path,
)

#: Feature names travel to a UI; a model-supplied one is bounded.
_NAME_CAP: Final = 120

#: Onshape ids are opaque alphanumeric handles. Validated before ANY URL
#: interpolation — a model-supplied id is untrusted input (CLAUDE.md §7).
_ID_RE: Final = ONSHAPE_ID_RE

_DOC_PROP: Final[dict[str, Any]] = {
    "type": "string",
    "description": "Onshape document id (from onshape.list_documents).",
}
_ELEM_PROP: Final[dict[str, Any]] = {
    "type": "string",
    "description": "Onshape element (tab) id (from onshape.list_elements).",
}
_WS_PROP: Final[dict[str, Any]] = {
    "type": "string",
    "description": "Workspace id. Omit to use the document's default workspace.",
}

Runner = Callable[[OnshapeConnector, httpx.AsyncClient, dict[str, Any]], Awaitable[dict[str, Any]]]
#: A preview is a READ that answers "what exactly will change?" — the rows the
#: user approves. Same signature as a runner; a different return shape.
Previewer = Callable[
    [OnshapeConnector, httpx.AsyncClient, dict[str, Any]], Awaitable[list[dict[str, Any]]]
]


@dataclass(frozen=True)
class OnshapeOperation:
    """One callable Onshape capability plus the schema a model is held to."""

    name: str
    description: str
    params: dict[str, Any]
    returns: dict[str, Any]
    run: Runner
    #: A write operation sets this, and the W0-04 registry's
    #: `confirmation_refusal` then makes it un-dispatchable until the user
    #: approves the concrete action.
    requires_confirmation: bool = False
    #: The diff this operation would apply, for the confirmation card. Required
    #: in practice for anything gated: approving a bare action name is not
    #: meaningful consent.
    preview: Previewer | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)


# --------------------------------------------------------------- helpers


def validated_id(args: dict[str, Any], key: str, *, required: bool = True) -> str:
    value = args.get(key)
    if value is None and not required:
        return ""
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ConnectorError(
            "config_invalid", f"{key} must be an Onshape id (letters and digits only)"
        )
    return value


async def workspace_for(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> str:
    """The workspace the caller named, or the document's default.

    Making a model carry a workspace id it never saw is a needless failure mode —
    every read here is against the default workspace unless told otherwise.
    """
    if args.get("workspace_id") is not None:
        return validated_id(args, "workspace_id")
    return await connector.default_workspace(client, validated_id(args, "document_id"))


def schema(
    *,
    document: bool = True,
    element: bool = False,
    extra: dict[str, Any] | None = None,
    required: tuple[str, ...] = (),
) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    if document:
        properties["document_id"] = _DOC_PROP
        properties["workspace_id"] = _WS_PROP
    if element:
        properties["element_id"] = _ELEM_PROP
    properties.update(extra or {})
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


def _messages(items: Any) -> list[dict[str, Any]]:
    """Flatten Onshape's `{btType, message}` envelopes.

    The envelope is a serialization detail; a model reasoning about a feature
    tree should never have to know it exists.
    """
    flattened: list[dict[str, Any]] = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict):
            inner = item.get("message")
            flattened.append(inner if isinstance(inner, dict) else item)
    return flattened


# --------------------------------------------------------------- operations


#: Same bound the connector's own sweep uses — an account listing is not a
#: place to loop without a floor.
_MAX_DOCUMENT_PAGES = 10


async def _list_documents(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> dict[str, Any]:
    """The documents THIS PROJECT tracks, never the whole Onshape account.

    This is the model's menu, and it used to be every document the customer's
    account could open — strictly wider than the project's scope, and the reason
    "change this" resolved by guessing. The tracked set is injected by Solus code
    as `_documents` (`agent/tools/onshape_tools.py`), never supplied by the
    model: every operation schema is `additionalProperties: False`, so a model
    that tried to send it is rejected at validation before this runs.

    An ABSENT `_documents` is a wiring error, and it refuses rather than falling
    back to the account listing — a fallback here would silently restore exactly
    the hole this closes.
    """
    tracked = args.get("_documents")
    if not isinstance(tracked, list):
        raise ConnectorError(
            "config_invalid", "the tracked document set was not supplied to this call"
        )
    allowed = {value for value in tracked if isinstance(value, str)}
    if not allowed:
        return {"documents": []}

    documents: list[dict[str, str]] = []
    # Onshape caps `limit` at 20, so a project tracking more than a page's worth
    # would silently lose the rest of its own documents on a single-page read.
    async for item in _document_pages(connector, client):
        if item.get("id") in allowed:
            documents.append(
                {
                    "id": item.get("id", ""),
                    "name": item.get("name", ""),
                    "owner": (item.get("owner") or {}).get("name", ""),
                }
            )
        if len(documents) == len(allowed):
            break
    return {"documents": documents}


async def _document_pages(
    connector: OnshapeConnector, client: httpx.AsyncClient
) -> AsyncIterator[dict[str, Any]]:
    """Every document the account can open, page by page and bounded."""
    for page in range(_MAX_DOCUMENT_PAGES):
        body = await connector.get_json(
            client,
            "/api/v6/documents",
            what="document list",
            params={"limit": ONSHAPE_MAX_PAGE_LIMIT, "offset": page * ONSHAPE_MAX_PAGE_LIMIT},
        )
        items = body.get("items") if isinstance(body, dict) else None
        rows = [
            item for item in (items if isinstance(items, list) else []) if isinstance(item, dict)
        ]
        for item in rows:
            yield item
        if len(rows) < ONSHAPE_MAX_PAGE_LIMIT:
            return


async def _list_elements(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> dict[str, Any]:
    document_id = validated_id(args, "document_id")
    workspace_id = await workspace_for(connector, client, args)
    body = await connector.get_json(
        client,
        f"/api/v6/documents/d/{document_id}/w/{workspace_id}/elements",
        what="element list",
    )
    elements = [
        {
            "id": item.get("id", ""),
            "name": item.get("name", ""),
            "type": item.get("elementType", ""),
        }
        for item in (body if isinstance(body, list) else [])
        if isinstance(item, dict)
    ]
    return {"workspace_id": workspace_id, "elements": elements}


async def _element_read(
    connector: OnshapeConnector,
    client: httpx.AsyncClient,
    args: dict[str, Any],
    *,
    kind: str,
    suffix: str,
    what: str,
    params: dict[str, Any] | None = None,
) -> Any:
    document_id = validated_id(args, "document_id")
    element_id = validated_id(args, "element_id")
    workspace_id = await workspace_for(connector, client, args)
    path = element_base_path(kind, document_id, workspace_id, element_id) + suffix
    return await connector.get_json(client, path, what=what, params=params)


async def _get_feature_tree(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> dict[str, Any]:
    body = await _element_read(
        connector, client, args, kind="partstudios", suffix="/features", what="feature tree"
    )
    features = [
        {
            "name": message.get("name", ""),
            "feature_id": message.get("featureId", ""),
            "feature_type": message.get("featureType", ""),
        }
        for message in _messages(body.get("features") if isinstance(body, dict) else None)
    ]
    # The envelope trio travels back out: a later write echoes it so a stale
    # geometry reference fails loudly instead of silently reattaching.
    envelope = {
        key: body.get(key)
        for key in ("serializationVersion", "sourceMicroversion", "libraryVersion")
        if isinstance(body, dict) and body.get(key) is not None
    }
    return {"features": features, "envelope": envelope}


async def _get_feature_specs(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> dict[str, Any]:
    body = await _element_read(
        connector, client, args, kind="partstudios", suffix="/featurespecs", what="feature specs"
    )
    specs = [
        {
            "featureType": message.get("featureType", ""),
            "name": message.get("featureTypeName", ""),
            "parameter_ids": sorted((message.get("parameterIdToSpec") or {}).keys()),
        }
        for message in _messages(body.get("featureSpecs") if isinstance(body, dict) else None)
    ]
    return {"feature_specs": specs}


async def _get_body_details(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> dict[str, Any]:
    body = await _element_read(
        connector,
        client,
        args,
        kind="partstudios",
        suffix="/bodydetails",
        what="body details",
        # Without this the analytic surface/edge data is omitted, and "which edge
        # is on the left" becomes unanswerable.
        params={"includeGeometricData": "true"},
    )
    return {"bodies": body.get("bodies", []) if isinstance(body, dict) else []}


async def _get_mass_properties(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> dict[str, Any]:
    body = await _element_read(
        connector,
        client,
        args,
        kind="partstudios",
        suffix="/massproperties",
        what="mass properties",
    )
    return {"bodies": body.get("bodies", {}) if isinstance(body, dict) else {}}


async def _get_assembly_definition(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> dict[str, Any]:
    body = await _element_read(
        connector,
        client,
        args,
        kind="assemblies",
        suffix="",
        what="assembly definition",
        # Onshape defaults every include flag to false; an assembly read without
        # mates is silently useless.
        params={"includeMateFeatures": "true", "includeMateConnectors": "true"},
    )
    root = body.get("rootAssembly", {}) if isinstance(body, dict) else {}
    return {
        "instances": root.get("instances", []),
        "features": _messages(root.get("features")),
        "occurrences": root.get("occurrences", []),
    }


async def _get_variables(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> dict[str, Any]:
    body = await _element_read(
        connector, client, args, kind="variables", suffix="/variables", what="variables"
    )
    variables: list[dict[str, Any]] = []
    for table in body if isinstance(body, list) else []:
        if isinstance(table, dict):
            variables.extend(v for v in table.get("variables", []) if isinstance(v, dict))
    return {"variables": variables}


_ELEMENT_REQUIRED = ("document_id", "element_id")

READ_OPERATIONS: Final[tuple[OnshapeOperation, ...]] = (
    OnshapeOperation(
        name="onshape.list_documents",
        description="List the Onshape documents this account can open.",
        params=schema(document=False),
        returns={"type": "object"},
        run=_list_documents,
        tags=("read",),
    ),
    OnshapeOperation(
        name="onshape.list_elements",
        description="List the tabs (part studios, assemblies, drawings) in a document.",
        params=schema(required=("document_id",)),
        returns={"type": "object"},
        run=_list_elements,
        tags=("read",),
    ),
    OnshapeOperation(
        name="onshape.get_feature_tree",
        description=(
            "The ordered feature tree of a part studio, plus the write envelope a "
            "later edit must echo back."
        ),
        params=schema(element=True, required=_ELEMENT_REQUIRED),
        returns={"type": "object"},
        run=_get_feature_tree,
        tags=("read",),
    ),
    OnshapeOperation(
        name="onshape.get_feature_specs",
        description=(
            "Every feature type this part studio can accept and its valid parameter "
            "ids — including custom features. Consult before constructing an edit."
        ),
        params=schema(element=True, required=_ELEMENT_REQUIRED),
        returns={"type": "object"},
        run=_get_feature_specs,
        tags=("read", "discovery"),
    ),
    OnshapeOperation(
        name="onshape.get_body_details",
        description=(
            "Bodies with their face, edge and vertex ids and analytic geometry. "
            "These ids are what a geometry-referencing edit points at."
        ),
        params=schema(element=True, required=_ELEMENT_REQUIRED),
        returns={"type": "object"},
        run=_get_body_details,
        tags=("read", "geometry"),
    ),
    OnshapeOperation(
        name="onshape.get_mass_properties",
        description="Mass, volume and centre of mass for a part studio.",
        params=schema(element=True, required=_ELEMENT_REQUIRED),
        returns={"type": "object"},
        run=_get_mass_properties,
        tags=("read", "geometry"),
    ),
    OnshapeOperation(
        name="onshape.get_assembly_definition",
        description="An assembly's instances, occurrences and mate features.",
        params=schema(element=True, required=_ELEMENT_REQUIRED),
        returns={"type": "object"},
        run=_get_assembly_definition,
        tags=("read",),
    ),
    OnshapeOperation(
        name="onshape.get_variables",
        description=(
            "Variables in a Variable Studio. On a parametric model these are usually "
            "the right thing to change."
        ),
        params=schema(element=True, required=_ELEMENT_REQUIRED),
        returns={"type": "object"},
        run=_get_variables,
        tags=("read",),
    ),
)


# ----------------------------------------------------------- writes (A3)

#: `BTVariableParams.name`, straight from Onshape's OpenAPI spec. Validating it
#: here turns a confusing upstream 400 into a usable message, and stops a crafted
#: name from ever reaching the payload.
_VAR_NAME_RE: Final = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

#: Onshape requires a variable `type`. ANY is the honest default for a variable a
#: model is creating: it accepts whatever the expression evaluates to, rather
#: than us guessing LENGTH and rejecting "4".
_DEFAULT_VAR_TYPE: Final = "ANY"

#: Keys on a BTM parameter that are metadata rather than the value. Whatever key
#: is left after removing these IS the value field — which is how `add_feature`
#: works without knowing that a quantity happens to carry `expression`.
_PARAM_METADATA: Final = frozenset(
    {
        "btType",
        "parameterId",
        "parameterName",
        "nodeId",
        "importMicroversion",
        "libraryRelationType",
        "valueString",
    }
)

#: Values a parameter may carry. A dict or list would be a nested payload the
#: model authored — exactly the shape that must never reach a write.
_SCALAR: Final = (str, int, float, bool)


def _variables_path(document_id: str, workspace_id: str, element_id: str) -> str:
    return f"/api/v6/variables/d/{document_id}/w/{workspace_id}/e/{element_id}/variables"


async def _variable_table(
    connector: OnshapeConnector, client: httpx.AsyncClient, path: str
) -> list[dict[str, Any]]:
    """Every variable currently in the studio, flattened out of its table."""
    body = await connector.get_json(client, path, what="variables")
    existing: list[dict[str, Any]] = []
    for table in body if isinstance(body, list) else []:
        if isinstance(table, dict):
            existing.extend(v for v in table.get("variables", []) if isinstance(v, dict))
    return existing


def _variable_name(args: dict[str, Any]) -> str:
    name = args.get("name")
    if not isinstance(name, str) or not _VAR_NAME_RE.fullmatch(name):
        raise ConnectorError(
            "config_invalid",
            "name must start with a letter or underscore and contain only letters, "
            "digits and underscores",
        )
    return name


def _merged_variables(
    existing: list[dict[str, Any]], name: str, expression: str, var_type: str | None
) -> tuple[list[dict[str, Any]], bool]:
    """The full table to POST back, plus whether the variable is new.

    `POST .../variables` REPLACES the studio's table. Sending only the changed
    variable would silently delete every other one — so the whole table travels,
    with exactly one entry rewritten.
    """
    payload: list[dict[str, Any]] = []
    found = False
    for variable in existing:
        entry = {
            "name": variable.get("name", ""),
            "type": variable.get("type", _DEFAULT_VAR_TYPE),
            "expression": variable.get("expression", ""),
        }
        if variable.get("description"):
            entry["description"] = str(variable["description"])
        if entry["name"] == name:
            found = True
            entry["expression"] = expression
            if var_type:
                entry["type"] = var_type
        payload.append(entry)
    if not found:
        payload.append(
            {"name": name, "type": var_type or _DEFAULT_VAR_TYPE, "expression": expression}
        )
    return payload, not found


def _expression(args: dict[str, Any]) -> str:
    value = args.get("expression")
    if not isinstance(value, str) or not value.strip():
        raise ConnectorError("config_invalid", "expression must be a non-empty string")
    return value


async def _set_variable(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> dict[str, Any]:
    document_id = validated_id(args, "document_id")
    element_id = validated_id(args, "element_id")
    name = _variable_name(args)
    expression = _expression(args)
    workspace_id = await workspace_for(connector, client, args)
    path = _variables_path(document_id, workspace_id, element_id)

    existing = await _variable_table(connector, client, path)
    payload, created = _merged_variables(existing, name, expression, args.get("type"))
    await connector.post_json(client, path, payload, what="variable update")
    return {"name": name, "expression": expression, "created": created}


async def _preview_set_variable(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> list[dict[str, Any]]:
    document_id = validated_id(args, "document_id")
    element_id = validated_id(args, "element_id")
    name = _variable_name(args)
    expression = _expression(args)
    workspace_id = await workspace_for(connector, client, args)
    existing = await _variable_table(
        connector, client, _variables_path(document_id, workspace_id, element_id)
    )
    current = next((v for v in existing if v.get("name") == name), None)
    before = current.get("expression") if current else None
    return [{"label": name, "before": before, "after": expression}]


def _feature_spec(specs: Any, feature_type: str) -> dict[str, Any]:
    """The live spec for one feature type.

    `featurespecs` is per-document and includes custom features the user
    imported, so it — never a hardcoded list — is the authority on what this
    part studio can accept.
    """
    for message in _messages(specs.get("featureSpecs") if isinstance(specs, dict) else None):
        if message.get("featureType") == feature_type:
            return message
    raise ConnectorError(
        "config_invalid",
        f"this part studio has no feature type '{feature_type}' — "
        "call onshape.get_feature_specs to see what it accepts",
    )


def parameter_value_field(template: dict[str, Any]) -> str | None:
    """Which key on a BTM parameter holds its value, read off the live default.

    Onshape publishes no field list for any BTM parameter subtype, so the only
    honest source is a real parameter object — and a spec's `defaultValue` is
    one. Exactly one non-metadata key means we know where the value goes;
    anything else means we do not, and the caller refuses.
    """
    candidates = [key for key in template if key not in _PARAM_METADATA]
    return candidates[0] if len(candidates) == 1 else None


def _parameter(spec: dict[str, Any], parameter_id: str, value: Any) -> dict[str, Any]:
    template = spec.get("defaultValue")
    if not isinstance(template, dict) or not isinstance(template.get("btType"), str):
        raise ConnectorError(
            "config_invalid",
            f"parameter '{parameter_id}' has no example value in this document, so its "
            "payload shape cannot be derived — set it in Onshape instead",
        )
    if "Query" in template["btType"]:
        raise ConnectorError(
            "config_invalid",
            f"parameter '{parameter_id}' points at geometry. Deterministic ids are "
            "microversion-scoped and are never tool arguments — use the reference "
            "resolver instead",
        )
    field_name = parameter_value_field(template)
    if field_name is None:
        raise ConnectorError(
            "config_invalid",
            f"parameter '{parameter_id}' has an ambiguous payload shape; refusing to guess",
        )
    if not isinstance(value, _SCALAR):
        raise ConnectorError("config_invalid", f"parameter '{parameter_id}' must be a single value")
    return {**template, "parameterId": parameter_id, field_name: value}


def _feature_parameters(spec: dict[str, Any], supplied: Any) -> list[dict[str, Any]]:
    if supplied is None:
        return []
    if not isinstance(supplied, dict):
        raise ConnectorError("config_invalid", "parameters must be an object")
    by_id = spec.get("parameterIdToSpec")
    known = by_id if isinstance(by_id, dict) else {}
    parameters: list[dict[str, Any]] = []
    for parameter_id, value in supplied.items():
        parameter_spec = known.get(parameter_id)
        if not isinstance(parameter_spec, dict):
            raise ConnectorError(
                "config_invalid",
                f"'{spec.get('featureType', '?')}' has no parameter '{parameter_id}'",
            )
        parameters.append(_parameter(parameter_spec, parameter_id, value))
    return parameters


def _feature_name(args: dict[str, Any]) -> str:
    name = args.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ConnectorError("config_invalid", "name must be a non-empty string")
    return name[:_NAME_CAP]


async def _add_feature(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> dict[str, Any]:
    document_id = validated_id(args, "document_id")
    element_id = validated_id(args, "element_id")
    feature_type = args.get("feature_type")
    if not isinstance(feature_type, str) or not feature_type:
        raise ConnectorError("config_invalid", "feature_type must be a string")
    name = _feature_name(args)
    workspace_id = await workspace_for(connector, client, args)
    base = element_base_path("partstudios", document_id, workspace_id, element_id)

    specs = await connector.get_json(client, f"{base}/featurespecs", what="feature specs")
    spec = _feature_spec(specs, feature_type)
    parameters = _feature_parameters(spec, args.get("parameters"))

    # The envelope trio is echoed from the CURRENT tree, with skew rejected: a
    # write built against a stale microversion must fail loudly rather than
    # silently reattach to different geometry.
    tree = await connector.get_json(client, f"{base}/features", what="feature tree")
    envelope = {
        key: tree.get(key)
        for key in ("serializationVersion", "sourceMicroversion", "libraryVersion")
        if isinstance(tree, dict) and tree.get(key) is not None
    }
    body: dict[str, Any] = {
        **envelope,
        "rejectMicroversionSkew": True,
        "feature": {
            "btType": "BTMFeature-134",
            "featureType": feature_type,
            "name": name,
            "parameters": parameters,
        },
    }
    created = await connector.post_json(client, f"{base}/features", body, what="feature creation")
    feature = created.get("feature") if isinstance(created, dict) else None
    return {
        "feature_id": (feature or {}).get("featureId", "") if isinstance(feature, dict) else "",
        "name": name,
        "feature_type": feature_type,
    }


async def _preview_add_feature(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> list[dict[str, Any]]:
    """What the new feature will be. Adding creates, so every row has no before.

    The parameters are run through the same validation the write uses, so a
    preview that renders is a write that will build — the user is never shown a
    change that cannot happen.
    """
    document_id = validated_id(args, "document_id")
    element_id = validated_id(args, "element_id")
    feature_type = args.get("feature_type")
    if not isinstance(feature_type, str) or not feature_type:
        raise ConnectorError("config_invalid", "feature_type must be a string")
    name = _feature_name(args)
    workspace_id = await workspace_for(connector, client, args)
    base = element_base_path("partstudios", document_id, workspace_id, element_id)
    specs = await connector.get_json(client, f"{base}/featurespecs", what="feature specs")
    spec = _feature_spec(specs, feature_type)
    supplied = args.get("parameters")
    _feature_parameters(spec, supplied)
    settings = supplied if isinstance(supplied, dict) else {}
    detail = ", ".join(f"{key}={value}" for key, value in settings.items())
    return [
        {
            "label": name,
            "before": None,
            "after": f"new {feature_type}" + (f" ({detail})" if detail else ""),
        }
    ]


WRITE_OPERATIONS: Final[tuple[OnshapeOperation, ...]] = (
    OnshapeOperation(
        name="onshape.set_variable",
        description=(
            "Set a Variable Studio variable's expression, creating it if needed. On a "
            "parametric model this is usually the right way to change a dimension. "
            "Other variables in the studio are preserved."
        ),
        params=schema(
            element=True,
            extra={
                "name": {
                    "type": "string",
                    "description": "Variable name (letters, digits, underscore).",
                },
                "expression": {
                    "type": "string",
                    "description": "Onshape expression, e.g. '120 mm' or '4'.",
                },
                "type": {
                    "type": "string",
                    "description": "FeatureScript VariableType, e.g. LENGTH. Defaults to ANY.",
                },
            },
            required=("document_id", "element_id", "name", "expression"),
        ),
        returns={"type": "object"},
        run=_set_variable,
        requires_confirmation=True,
        preview=_preview_set_variable,
        tags=("write",),
    ),
    OnshapeOperation(
        name="onshape.add_feature",
        description=(
            "Add a feature to a part studio. Valid feature types and parameter ids come "
            "from onshape.get_feature_specs for THIS document. Parameters that point at "
            "existing geometry are not accepted here."
        ),
        params=schema(
            element=True,
            extra={
                "feature_type": {
                    "type": "string",
                    "description": "featureType from onshape.get_feature_specs.",
                },
                "name": {"type": "string", "description": "Name for the new feature."},
                "parameters": {
                    "type": "object",
                    "description": "parameterId → value, from the feature's spec.",
                    "additionalProperties": True,
                },
            },
            required=("document_id", "element_id", "feature_type", "name"),
        ),
        returns={"type": "object"},
        run=_add_feature,
        requires_confirmation=True,
        preview=_preview_add_feature,
        tags=("write", "geometry"),
    ),
)

ALL_OPERATIONS: Final[tuple[OnshapeOperation, ...]] = READ_OPERATIONS + WRITE_OPERATIONS


def every_operation() -> tuple[OnshapeOperation, ...]:
    """Every Onshape operation, including the A4 reference ones.

    Imported lazily so the dependency stays one-way: `onshape_refs` builds on
    this module's primitives, never the reverse.
    """
    from solus_api.connectors.onshape_refs import REFERENCE_OPERATIONS

    return ALL_OPERATIONS + REFERENCE_OPERATIONS


def operation_by_name(name: str) -> OnshapeOperation | None:
    """Exact-name lookup. Unknown or unqualified names resolve to nothing."""
    return next((op for op in every_operation() if op.name == name), None)


__all__ = [
    "ALL_OPERATIONS",
    "element_base_path",
    "every_operation",
    "parameter_value_field",
    "schema",
    "validated_id",
    "workspace_for",
    "READ_OPERATIONS",
    "WRITE_OPERATIONS",
    "OnshapeOperation",
    "operation_by_name",
]
