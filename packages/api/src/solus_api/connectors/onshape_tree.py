"""Bounded Onshape document navigation (live-verified vendor tree API).

Only known node identities are translated into requests. Vendor treeHref/next
links are validated as evidence, never used as arbitrary request destinations.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import httpx

from solus_api.connectors.contracts import ConnectorError, Credentials

if TYPE_CHECKING:
    from solus_api.connectors.onshape import OnshapeConnector

_ID = re.compile(r"[0-9a-f]{24}\Z")
_OWNER = re.compile(r"owner:(resourceuserowner|resourcecompanyowner):([0-9a-f]{24})\Z")
_MAX_OFFSET = 100000
_PAGE_SIZE = 20


def navigation_path(node: str, offset: int) -> str:
    """Validate all caller-controlled navigation before credentials or I/O."""
    if not 0 <= offset <= _MAX_OFFSET or (node == "root" and offset != 0):
        raise ConnectorError("config_invalid", "Invalid document-tree offset")
    if node == "root":
        return "/api/globaltreenodes"
    if node == "shared":
        return "/api/globaltreenodes/magic/12"
    if node.startswith("folder:") and _ID.fullmatch(node.removeprefix("folder:")):
        return f"/api/globaltreenodes/folder/{node.removeprefix('folder:')}"
    owner = _OWNER.fullmatch(node)
    if owner:
        return f"/api/v1/globaltreenodes/{owner[1]}/{owner[2]}"
    raise ConnectorError("config_invalid", "Invalid document-tree node")


def _invalid() -> ConnectorError:
    return ConnectorError("api_error", "Onshape returned an unsupported document-tree response")


def _verified_url(raw: Any, path: str, base_url: str) -> httpx.URL:
    if not isinstance(raw, str) or not raw:
        raise _invalid()
    try:
        base = httpx.URL(base_url)
        url = base.join(raw)
    except httpx.InvalidURL as exc:
        raise _invalid() from exc
    canonical = path.replace("/api/v1/", "/api/")
    if (
        (url.scheme, url.host, url.port) != (base.scheme, base.host, base.port)
        or url.scheme != "https"
        or url.userinfo
        or url.fragment
        or url.path not in {canonical, canonical.replace("/api/", "/api/v1/", 1)}
    ):
        raise _invalid()
    return url


def _root_node(kind: Any, identity: Any) -> str | None:
    if kind in {"resourceuserowner", "resourcecompanyowner"}:
        return f"owner:{kind}:{identity}"
    if kind == "magic" and str(identity) == "12":
        return "shared"
    return None


def _row(item: Any, *, root: bool, base_url: str) -> dict[str, Any] | None:
    if not isinstance(item, dict) or not isinstance(item.get("resourceType"), str):
        raise _invalid()
    kind, identity = item.get("resourceType"), item.get("id")
    node: str | None
    if root and (node := _root_node(kind, identity)) is None:
        return None
    if not root:
        if kind == "folder":
            node = f"folder:{identity}"
        elif kind == "document":
            node = None
        else:
            raise _invalid()
    name = item.get("name")
    if not isinstance(name, str) or not name.strip():
        raise _invalid()
    if node != "shared" and (not isinstance(identity, str) or not _ID.fullmatch(identity)):
        raise _invalid()
    if node is not None:
        link = _verified_url(item.get("treeHref"), navigation_path(node, 0), base_url)
        if link.query:
            raise _invalid()
    return {
        "id": str(identity),
        "name": name,
        "kind": "folder" if node else "document",
        "node": node,
    }


def _next_offset(raw: Any, *, path: str, offset: int, base_url: str) -> int | None:
    if raw is None or raw == "":
        return None
    if path == "/api/globaltreenodes":
        raise _invalid()
    url = _verified_url(raw, path, base_url)
    pairs = url.params.multi_items()
    if len(pairs) != len(set(key for key, _ in pairs)) or set(url.params) - {"offset", "limit"}:
        raise _invalid()
    text = url.params.get("offset", "")
    if (
        len(text) > 6
        or not text.isascii()
        or not text.isdecimal()
        or url.params.get("limit", "20") != "20"
    ):
        raise _invalid()
    next_offset = int(text)
    if not offset < next_offset <= _MAX_OFFSET:
        raise _invalid()
    return next_offset


async def list_document_tree(
    connector: OnshapeConnector, creds: Credentials, node: str, offset: int
) -> dict[str, Any]:
    path = navigation_path(node, offset)
    async with connector.http(creds) as client:
        base_url = str(client.base_url)
        body = await connector.get_json(
            client,
            path,
            what="document tree",
            params=None if node == "root" else {"offset": offset, "limit": _PAGE_SIZE},
        )
    if not isinstance(body, dict) or not isinstance(body.get("items"), list):
        raise _invalid()
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw in body["items"]:
        row = _row(raw, root=node == "root", base_url=base_url)
        if row is not None and (key := (row["kind"], row["id"])) not in seen:
            seen.add(key)
            rows.append(row)
    return {
        "items": rows,
        "next_offset": _next_offset(body.get("next"), path=path, offset=offset, base_url=base_url),
    }
