"""Vendor tree parsing uses fixed, validated navigation, never arbitrary URLs."""

from typing import Any

import httpx
import pytest
import respx
from solus_api.connectors.contracts import ConnectorError, Credentials
from solus_api.connectors.onshape import ONSHAPE_API_BASE, OnshapeConnector

OWNER = "a" * 24
FOLDER = "b" * 24
DOCUMENT = "c" * 24
BASE = f"{ONSHAPE_API_BASE}/api/globaltreenodes"


async def browse(node: str = "root", offset: int = 0) -> dict[str, Any]:
    return await OnshapeConnector(client_id="c", client_secret="s").list_document_tree(
        Credentials(token="test"), node, offset
    )


@respx.mock
async def test_root_contains_only_verified_owner_and_shared_navigation() -> None:
    respx.get(BASE).respond(
        200,
        json={
            "items": [
                {
                    "id": OWNER,
                    "name": "My Onshape",
                    "resourceType": "resourceuserowner",
                    "treeHref": (
                        f"{ONSHAPE_API_BASE}/api/v1/globaltreenodes/resourceuserowner/{OWNER}"
                    ),
                },
                {
                    "id": "12",
                    "name": "Shared with me",
                    "resourceType": "magic",
                    "subType": 12,
                    "treeHref": f"{BASE}/magic/12",
                },
                {"id": "4", "resourceType": "magic", "name": "Public"},
            ]
        },
    )
    result = await browse()
    assert [item["node"] for item in result["items"]] == [
        f"owner:resourceuserowner:{OWNER}",
        "shared",
    ]
    assert all(item["kind"] == "folder" for item in result["items"])
    assert result["next_offset"] is None


@respx.mock
async def test_folder_children_and_next_page_are_exact_document_ids() -> None:
    route = respx.get(f"{BASE}/folder/{FOLDER}").respond(
        200,
        json={
            "items": [
                {
                    "id": DOCUMENT,
                    "name": "Chassis",
                    "resourceType": "document",
                    "jsonType": "document-summary",
                },
                {
                    "id": OWNER,
                    "name": "Parts",
                    "resourceType": "folder",
                    "jsonType": "folder",
                    "treeHref": f"{BASE}/folder/{OWNER}",
                },
            ],
            "next": f"{BASE}/folder/{FOLDER}?offset=20&limit=20",
        },
    )
    result = await browse(f"folder:{FOLDER}")
    assert result == {
        "items": [
            {"id": DOCUMENT, "name": "Chassis", "kind": "document", "node": None},
            {"id": OWNER, "name": "Parts", "kind": "folder", "node": f"folder:{OWNER}"},
        ],
        "next_offset": 20,
    }
    assert route.calls[0].request.url.params == httpx.QueryParams({"offset": 0, "limit": 20})


@pytest.mark.parametrize(
    "next_url",
    [
        f"https://attacker.invalid/api/globaltreenodes/folder/{FOLDER}?offset=20&limit=20",
        f"{BASE}/folder/{OWNER}?offset=20&limit=20",
        f"{BASE}/folder/{FOLDER}?offset=0&limit=20",
        f"{BASE}/folder/{FOLDER}?offset=100001&limit=20",
        f"{BASE}/folder/{FOLDER}?offset=20&offset=40&limit=20",
        f"{BASE}/folder/{FOLDER}?offset=20&limit=100",
    ],
)
@respx.mock
async def test_bad_next_link_fails_without_following(next_url: str) -> None:
    respx.get(f"{BASE}/folder/{FOLDER}").respond(200, json={"items": [], "next": next_url})
    with pytest.raises(ConnectorError):
        await browse(f"folder:{FOLDER}")
    assert len(respx.calls) == 1


@pytest.mark.parametrize(
    "body",
    [
        [],
        {"items": "bad"},
        {"items": [{"id": DOCUMENT, "name": "Unknown", "resourceType": "new-vendor-type"}]},
        {"items": [{"id": "../bad", "name": "Bad", "resourceType": "document"}]},
        {
            "items": [
                {
                    "id": FOLDER,
                    "name": "Bad",
                    "resourceType": "folder",
                    "treeHref": "https://attacker.invalid/",
                }
            ]
        },
    ],
)
@respx.mock
async def test_schema_changes_fail_clearly(body: Any) -> None:
    respx.get(f"{BASE}/magic/12").respond(200, json=body)
    with pytest.raises(ConnectorError) as excinfo:
        await browse("shared")
    assert excinfo.value.code == "api_error"


@pytest.mark.parametrize(
    "node,offset",
    [("folder:../bad", 0), ("owner:unknown:" + OWNER, 0), ("root", 20), ("shared", -1)],
)
@respx.mock
async def test_invalid_input_never_reaches_provider(node: str, offset: int) -> None:
    with pytest.raises(ConnectorError):
        await browse(node, offset)
    assert len(respx.calls) == 0


@pytest.mark.parametrize("kind", ["resourceuserowner", "resourcecompanyowner"])
@respx.mock
async def test_owner_navigation_uses_known_versioned_endpoint(kind: str) -> None:
    route = respx.get(f"{ONSHAPE_API_BASE}/api/v1/globaltreenodes/{kind}/{OWNER}").respond(
        200, json={"items": [{"id": DOCUMENT, "name": "Chassis", "resourceType": "document"}]}
    )
    result = await browse(f"owner:{kind}:{OWNER}", 20)
    assert result["items"][0]["id"] == DOCUMENT
    assert route.calls[0].request.url.params["offset"] == "20"


@respx.mock
async def test_root_pagination_is_not_silently_discarded() -> None:
    respx.get(BASE).respond(200, json={"items": [], "next": f"{BASE}?offset=20"})
    with pytest.raises(ConnectorError):
        await browse()
