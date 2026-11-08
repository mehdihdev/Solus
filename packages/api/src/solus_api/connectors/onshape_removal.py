"""Suppress, rename and delete — SOLUSDEV-319.

docs/api/onshape-development.md §"Removal, rename, move and part metadata".

Suppress and rename are feature edits: the complete live feature is POSTed back
with one field changed, carrying `sourceMicroversion` + `rejectMicroversionSkew`,
so Onshape itself refuses a stale write. DELETE takes no such guard, so the
approval binds the source microversion and a fingerprint of the whole element,
and execution rereads both and refuses (without dispatching) on any change. The
residual window between that reread and the DELETE is accepted, as for insertion.

Breakage is reported, never repaired: a best-effort scan lists what may depend
on the target before the write, and the readback lists every feature or mate that
newly left the OK state. A revert would itself be an unverified write.

Feature names and parameters are vendor data and untrusted: they reach only
preview rows and results, length-capped, never instruction position.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Final

import httpx

from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.onshape import ONSHAPE_ID_RE, OnshapeConnector, element_base_path
from solus_api.connectors.onshape_confirmation import require_matching_preview, stable_spec
from solus_api.connectors.onshape_ops import (
    OnshapeOperation,
    schema,
    validated_id,
    workspace_for,
)

_COLLECTIONS: Final = {"partstudio": "partstudios", "assembly": "assemblies"}
#: Feature and instance ids carry underscores and dashes, unlike document ids.
_NODE_ID_RE: Final = re.compile(r"[A-Za-z0-9_-]{1,64}")
_NAME_MAX: Final = 64
_DEPENDENTS_MAX: Final = 10
_TEXT_MAX: Final = 120
_ENVELOPE_KEYS: Final = ("serializationVersion", "sourceMicroversion", "libraryVersion")
IRREVERSIBLE: Final = (
    "Delete — this cannot be undone from Solus (Onshape's document history still has it)"
)


def _unverified() -> ConnectorError:
    return ConnectorError(
        "mutation_unverified", "The model may have changed; inspect it before retrying."
    )


def _invalid(message: str) -> ConnectorError:
    return ConnectorError("config_invalid", message)


def _node_id(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not _NODE_ID_RE.fullmatch(value):
        raise _invalid(f"{key} must be an Onshape id from a fresh read")
    return value


def _collection(args: dict[str, Any]) -> str:
    kind = args.get("element_type")
    if kind not in _COLLECTIONS:
        raise _invalid(f"element_type must be one of {sorted(_COLLECTIONS)}")
    return _COLLECTIONS[kind]


def _short(value: Any) -> str:
    text = str(value)
    return text if len(text) <= _TEXT_MAX else text[: _TEXT_MAX - 1] + "…"


def _visible_name(value: Any) -> str:
    """The strict visible-text rule: no control, format (bidi, zero-width) or
    separator characters other than a plain space, and no edge whitespace."""
    if not isinstance(value, str) or not value or len(value) > _NAME_MAX:
        raise _invalid(f"name must be 1–{_NAME_MAX} characters")
    if value != value.strip() or any(
        unicodedata.category(ch)[0] == "C" or (unicodedata.category(ch)[0] == "Z" and ch != " ")
        for ch in value
    ):
        raise _invalid("name must be visible characters only, without edge spaces")
    return value


def _mentions(value: Any, token: str) -> bool:
    text = json.dumps(stable_spec(value), sort_keys=True)
    return re.search(rf"(?<![A-Za-z0-9_-]){re.escape(token)}(?![A-Za-z0-9_-])", text) is not None


def _features(tree: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    items = tree.get("features")
    if not isinstance(items, list):
        raise ConnectorError("api_error", "Onshape returned a malformed feature collection")
    features: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        message = item.get("message", item) if isinstance(item, dict) else None
        identity = message.get("featureId") if isinstance(message, dict) else None
        if not isinstance(identity, str) or not _NODE_ID_RE.fullmatch(identity) or identity in seen:
            raise ConnectorError("api_error", "Onshape returned malformed feature identities")
        assert isinstance(message, dict)
        seen.add(identity)
        features.append(message)
    return tuple(features)


def _states(tree: dict[str, Any]) -> dict[str, str]:
    raw = tree.get("featureStates")
    states: dict[str, str] = {}
    for fid, state in (raw if isinstance(raw, dict) else {}).items():
        state = state.get("message", state) if isinstance(state, dict) else None
        status = state.get("featureStatus") if isinstance(state, dict) else None
        states[str(fid)] = status if isinstance(status, str) and status else "UNKNOWN"
    return states


@dataclass(frozen=True)
class _Element:
    """One fresh read of a Part Studio's or assembly's feature list."""

    base: str
    tree: dict[str, Any]
    features: tuple[dict[str, Any], ...]
    states: dict[str, str]

    @classmethod
    async def read(
        cls,
        connector: OnshapeConnector,
        client: httpx.AsyncClient,
        args: dict[str, Any],
        collection: str,
    ) -> _Element:
        document_id = validated_id(args, "document_id")
        element_id = validated_id(args, "element_id")
        workspace_id = await workspace_for(connector, client, args)
        base = element_base_path(collection, document_id, workspace_id, element_id)
        return await cls.load(connector, client, base)

    @classmethod
    async def load(
        cls, connector: OnshapeConnector, client: httpx.AsyncClient, base: str
    ) -> _Element:
        tree = await connector.get_json(client, f"{base}/features", what="feature list")
        microversion = tree.get("sourceMicroversion") if isinstance(tree, dict) else None
        if not isinstance(microversion, str) or not ONSHAPE_ID_RE.fullmatch(microversion):
            raise ConnectorError("api_error", "Onshape returned no source microversion")
        return cls(base, tree, _features(tree), _states(tree))

    def feature(self, feature_id: str) -> dict[str, Any]:
        for feature in self.features:
            if feature["featureId"] == feature_id:
                return feature
        raise ConnectorError(
            "not_found",
            f"no feature '{feature_id}' here — read the feature list to find its id",
        )

    def has(self, feature_id: str) -> bool:
        return any(f["featureId"] == feature_id for f in self.features)

    def envelope(self) -> dict[str, Any]:
        return {key: self.tree[key] for key in _ENVELOPE_KEYS if key in self.tree}

    def identity_rows(self, label: str, value: str, extra: Any = None) -> list[dict[str, Any]]:
        state = {k: v for k, v in self.tree.items() if k != "serializationVersion"}
        digest = hashlib.sha256(
            json.dumps(stable_spec([state, extra]), sort_keys=True, allow_nan=False).encode()
        ).hexdigest()
        return [
            {"label": label, "before": None, "after": value},
            {
                "label": "Source microversion",
                "before": None,
                "after": self.tree["sourceMicroversion"],
            },
            {
                "label": "Feature state fingerprint",
                "before": None,
                "after": ":".join(digest[i : i + 16] for i in range(0, 64, 16)),
            },
        ]

    def dependent_rows(self, token: str, *, after: str | None = None) -> list[dict[str, Any]]:
        """Features (after `after` in the list, when given) whose parameters name
        `token`. Best-effort, labelled as such; never blocks."""
        start = next((i + 1 for i, f in enumerate(self.features) if f["featureId"] == after), 0)
        names = [
            _short(f.get("name", f["featureId"]))
            for f in self.features[start:]
            if f["featureId"] != token and _mentions(f.get("parameters"), token)
        ]
        rows = [{"label": "May depend on it", "before": None, "after": n} for n in names]
        if len(rows) > _DEPENDENTS_MAX:
            more = len(rows) - _DEPENDENTS_MAX
            rows = [
                *rows[:_DEPENDENTS_MAX],
                {"label": "May depend on it", "before": None, "after": f"… and {more} more"},
            ]
        return rows

    def downstream(self, after: _Element, *, skip: str | None = None) -> list[dict[str, str]]:
        """Every feature that was OK before the write and is not OK after it."""
        return [
            {
                "feature_id": f["featureId"],
                "name": _short(f.get("name", f["featureId"])),
                "status": after.states.get(f["featureId"], "UNKNOWN"),
            }
            for f in after.features
            if f["featureId"] != skip
            and self.states.get(f["featureId"]) == "OK"
            and after.states.get(f["featureId"]) != "OK"
        ]


# --------------------------------------------------------- suppress / rename


@dataclass(frozen=True)
class _Edit:
    element: _Element
    feature: dict[str, Any]
    field: str
    value: Any
    rows: list[dict[str, Any]]

    @classmethod
    async def plan(
        cls,
        connector: OnshapeConnector,
        client: httpx.AsyncClient,
        args: dict[str, Any],
        field: str,
    ) -> _Edit:
        collection = _collection(args)
        feature_id = _node_id(args, "feature_id")
        if field == "suppressed" and not isinstance(args.get("suppressed"), bool):
            raise _invalid("suppressed must be true or false")
        element = await _Element.read(connector, client, args, collection)
        feature = element.feature(feature_id)
        name = feature.get("name", feature_id)
        if field == "suppressed":
            value: Any = args["suppressed"]
            before: Any = bool(feature.get("suppressed", False))
            if feature.get("suppressionConfigured") is True:
                raise _invalid(
                    f"'{_short(name)}' is suppressed per configuration; change it in Onshape"
                )
            dependents = element.dependent_rows(feature_id, after=feature_id) if value else []
        else:
            value = _visible_name(args.get("name"))
            before = name
            dependents = []
        if before == value:
            raise _invalid(f"'{_short(name)}' already has {field} = {value}")
        rows = [
            *element.identity_rows("Feature", f"{_short(name)} ({feature_id})"),
            {
                "label": f"{_short(name)} · {field.capitalize()}",
                "before": str(before),
                "after": str(value),
            },
            *dependents,
        ]
        return cls(element, feature, field, value, rows)

    async def apply(
        self, connector: OnshapeConnector, client: httpx.AsyncClient
    ) -> tuple[_Element, dict[str, Any]]:
        require_matching_preview(self.rows)
        feature_id = self.feature["featureId"]
        body = {
            **self.element.envelope(),
            "rejectMicroversionSkew": True,
            "feature": {**self.feature, self.field: self.value},
        }
        try:
            await connector.post_json(
                client,
                f"{self.element.base}/features/featureid/{feature_id}",
                body,
                what="feature update",
            )
            after = await _Element.load(connector, client, self.element.base)
            actual = after.feature(feature_id)
            default = False if self.field == "suppressed" else None
            if actual.get(self.field, default) != self.value or actual.get(
                "featureType"
            ) != self.feature.get("featureType"):
                raise _unverified()
        except ConnectorError as exc:
            raise _unverified() from exc
        return after, actual


async def _preview_suppress(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> list[dict[str, Any]]:
    return (await _Edit.plan(connector, client, args, "suppressed")).rows


async def _suppress(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> dict[str, Any]:
    edit = await _Edit.plan(connector, client, args, "suppressed")
    after, actual = await edit.apply(connector, client)
    return {
        "feature_id": actual["featureId"],
        "name": _short(actual.get("name", "")),
        "suppressed": edit.value,
        "verified": True,
        "downstream_errors": edit.element.downstream(after, skip=actual["featureId"]),
    }


async def _preview_rename(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> list[dict[str, Any]]:
    return (await _Edit.plan(connector, client, args, "name")).rows


async def _rename(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> dict[str, Any]:
    edit = await _Edit.plan(connector, client, args, "name")
    after, actual = await edit.apply(connector, client)
    return {
        "feature_id": actual["featureId"],
        "name": edit.value,
        "previous_name": _short(edit.feature.get("name", "")),
        "verified": True,
        "downstream_errors": edit.element.downstream(after, skip=actual["featureId"]),
    }


# ------------------------------------------------------------------- delete


async def _plan_delete_feature(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> tuple[_Element, dict[str, Any], list[dict[str, Any]]]:
    collection = _collection(args)
    feature_id = _node_id(args, "feature_id")
    element = await _Element.read(connector, client, args, collection)
    feature = element.feature(feature_id)
    rows = [
        {"label": "Action", "before": None, "after": IRREVERSIBLE},
        *element.identity_rows(
            "Feature", f"{_short(feature.get('name', feature_id))} ({feature_id})"
        ),
        *element.dependent_rows(feature_id, after=feature_id),
    ]
    return element, feature, rows


async def _preview_delete_feature(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> list[dict[str, Any]]:
    return (await _plan_delete_feature(connector, client, args))[2]


async def _delete_feature(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> dict[str, Any]:
    element, feature, rows = await _plan_delete_feature(connector, client, args)
    require_matching_preview(rows)
    feature_id = feature["featureId"]
    try:
        await connector.request(
            client,
            "DELETE",
            f"{element.base}/features/featureid/{feature_id}",
            what="feature delete",
        )
        after = await _Element.load(connector, client, element.base)
        if after.has(feature_id):
            raise _unverified()
    except ConnectorError as exc:
        raise _unverified() from exc
    return {
        "feature_id": feature_id,
        "name": _short(feature.get("name", "")),
        "deleted": True,
        "verified": True,
        "downstream_errors": element.downstream(after),
    }


async def _instances(
    connector: OnshapeConnector, client: httpx.AsyncClient, base: str
) -> tuple[dict[str, str], ...]:
    """The assembly's top-level instances, reduced to stable identity fields."""
    body = await connector.get_json(client, base, what="assembly definition")
    root = body.get("rootAssembly") if isinstance(body, dict) else None
    items = root.get("instances") if isinstance(root, dict) else None
    if not isinstance(items, list):
        raise ConnectorError("api_error", "Onshape returned a malformed assembly definition")
    instances: list[dict[str, str]] = []
    for item in items:
        identity = item.get("id") if isinstance(item, dict) else None
        if not isinstance(identity, str) or not _NODE_ID_RE.fullmatch(identity):
            raise ConnectorError("api_error", "Onshape returned malformed instance identities")
        assert isinstance(item, dict)
        instances.append(
            {k: str(item[k]) for k in ("id", "name", "type", "partId", "documentId") if k in item}
        )
    return tuple(instances)


async def _plan_delete_instance(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> tuple[_Element, dict[str, str], list[dict[str, Any]]]:
    instance_id = _node_id(args, "instance_id")
    element = await _Element.read(connector, client, args, "assemblies")
    instances = await _instances(connector, client, element.base)
    instance = next((i for i in instances if i["id"] == instance_id), None)
    if instance is None:
        raise ConnectorError(
            "not_found",
            f"no top-level instance '{instance_id}' — read the assembly definition for ids",
        )
    rows = [
        {"label": "Action", "before": None, "after": IRREVERSIBLE},
        *element.identity_rows(
            "Instance",
            f"{_short(instance.get('name', instance_id))} ({instance_id})",
            extra=instances,
        ),
        *element.dependent_rows(instance_id),
    ]
    return element, instance, rows


async def _preview_delete_instance(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> list[dict[str, Any]]:
    return (await _plan_delete_instance(connector, client, args))[2]


async def _delete_instance(
    connector: OnshapeConnector, client: httpx.AsyncClient, args: dict[str, Any]
) -> dict[str, Any]:
    element, instance, rows = await _plan_delete_instance(connector, client, args)
    require_matching_preview(rows)
    instance_id = instance["id"]
    try:
        await connector.request(
            client,
            "DELETE",
            f"{element.base}/instance/nodeid/{instance_id}",
            what="instance delete",
        )
        remaining = await _instances(connector, client, element.base)
        after = await _Element.load(connector, client, element.base)
        if any(i["id"] == instance_id for i in remaining):
            raise _unverified()
    except ConnectorError as exc:
        raise _unverified() from exc
    return {
        "instance_id": instance_id,
        "name": _short(instance.get("name", "")),
        "deleted": True,
        "verified": True,
        "downstream_errors": element.downstream(after),
    }


# ----------------------------------------------------------------- registry

_ELEMENT_TYPE: Final = {
    "type": "string",
    "enum": sorted(_COLLECTIONS),
    "description": (
        "partstudio for Part Studio features; assembly for mates and other assembly features."
    ),
}
_FEATURE_ID: Final = {
    "type": "string",
    "description": (
        "featureId from onshape.get_feature_tree or get_assembly_definition (view=features)."
    ),
}
_FEATURE_REQUIRED: Final = ("document_id", "element_id", "element_type", "feature_id")

REMOVAL_OPERATIONS: Final[tuple[OnshapeOperation, ...]] = (
    OnshapeOperation(
        name="onshape.suppress_feature",
        description=(
            "Suppress or unsuppress one feature (a Part Studio feature, or an assembly "
            "feature such as a mate). This is how to remove something when the person "
            "says remove, hide or get rid of it: it can be undone. Use "
            "onshape.delete_feature only when they explicitly say delete. The result "
            "lists features that broke because of the change."
        ),
        params=schema(
            element=True,
            extra={
                "element_type": _ELEMENT_TYPE,
                "feature_id": _FEATURE_ID,
                "suppressed": {
                    "type": "boolean",
                    "description": "true suppresses, false restores.",
                },
            },
            required=(*_FEATURE_REQUIRED, "suppressed"),
        ),
        returns={"type": "object"},
        run=_suppress,
        requires_confirmation=True,
        preview=_preview_suppress,
        tags=("write", "geometry"),
    ),
    OnshapeOperation(
        name="onshape.rename_feature",
        description="Rename one Part Studio or assembly feature. Changes nothing else.",
        params=schema(
            element=True,
            extra={
                "element_type": _ELEMENT_TYPE,
                "feature_id": _FEATURE_ID,
                "name": {"type": "string", "minLength": 1, "maxLength": _NAME_MAX},
            },
            required=(*_FEATURE_REQUIRED, "name"),
        ),
        returns={"type": "object"},
        run=_rename,
        requires_confirmation=True,
        preview=_preview_rename,
        tags=("write",),
    ),
    OnshapeOperation(
        name="onshape.delete_feature",
        description=(
            "Permanently delete one Part Studio or assembly feature. Only when the "
            "person explicitly asks to delete it; for remove or get rid of, use "
            "onshape.suppress_feature, which can be undone. The result lists features "
            "that broke because of the deletion."
        ),
        params=schema(
            element=True,
            extra={"element_type": _ELEMENT_TYPE, "feature_id": _FEATURE_ID},
            required=_FEATURE_REQUIRED,
        ),
        returns={"type": "object"},
        run=_delete_feature,
        requires_confirmation=True,
        preview=_preview_delete_feature,
        tags=("write", "geometry"),
    ),
    OnshapeOperation(
        name="onshape.delete_instance",
        description=(
            "Permanently delete one top-level instance from an assembly. Only when the "
            "person explicitly asks to delete it. instance_id comes from "
            "onshape.get_assembly_definition. The result lists mates that broke."
        ),
        params=schema(
            element=True,
            extra={
                "instance_id": {
                    "type": "string",
                    "description": "A top-level instance id from onshape.get_assembly_definition.",
                }
            },
            required=("document_id", "element_id", "instance_id"),
        ),
        returns={"type": "object"},
        run=_delete_instance,
        requires_confirmation=True,
        preview=_preview_delete_instance,
        tags=("write", "geometry"),
    ),
)

__all__ = ["IRREVERSIBLE", "REMOVAL_OPERATIONS"]
