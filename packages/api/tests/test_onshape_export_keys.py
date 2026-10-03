"""ADR-038 §3: exports are cached per element microversion + a dependency fingerprint."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import httpx
from solus_api.connectors.httpcache import InMemoryCacheStore
from solus_api.connectors.integration_cache import IntegrationCache
from solus_api.connectors.onshape import OnshapeConnector

REV = "docrev1"


def _connector(listing: list[dict[str, Any]]) -> OnshapeConnector:
    subject = OnshapeConnector(
        client_id="id",
        client_secret="secret",
        account_ref="account",
        cache=IntegrationCache(InMemoryCacheStore()),
    )
    subject.get_json = AsyncMock(return_value=listing)  # type: ignore[method-assign]
    return subject


def _el(element_id: str, kind: str, micro: Any = "") -> dict[str, Any]:
    row: dict[str, Any] = {"id": element_id, "elementType": kind}
    if micro != "":
        row["microversionId"] = micro
    return row


async def _revisions(listing: list[dict[str, Any]]) -> dict[str, tuple[str, str]]:
    subject = _connector(listing)
    async with httpx.AsyncClient() as client:
        await subject._elements_at(client, "doc", "workspace", REV)
    return subject._export_revisions("doc", REV)


BASE = [
    _el("ps1", "PARTSTUDIO", "ps1v0"),
    _el("ps2", "PARTSTUDIO", "ps2v0"),
    _el("vs1", "VARIABLESTUDIO", "vs1v0"),
    _el("as1", "ASSEMBLY", "as1v0"),
    _el("dr1", "DRAWING", "dr1v0"),
    _el("bl1", "BLOB", "bl1v0"),
]


def _with(listing: list[dict[str, Any]], element_id: str, micro: str) -> list[dict[str, Any]]:
    return [{**row, "microversionId": micro} if row["id"] == element_id else row for row in listing]


async def test_each_exportable_element_gets_its_own_microversion() -> None:
    revisions = await _revisions(BASE)
    assert set(revisions) == {"ps1", "ps2", "as1"}
    assert [revisions[e][0] for e in ("ps1", "ps2", "as1")] == ["ps1v0", "ps2v0", "as1v0"]


async def test_a_variable_studio_edit_invalidates_part_studios_and_assemblies() -> None:
    before, after = await _revisions(BASE), await _revisions(_with(BASE, "vs1", "vs1v1"))
    assert all(before[e][1] != after[e][1] for e in ("ps1", "ps2", "as1"))


async def test_a_part_studio_edit_invalidates_every_part_studio_and_assembly() -> None:
    before, after = await _revisions(BASE), await _revisions(_with(BASE, "ps1", "ps1v1"))
    assert all(before[e][1] != after[e][1] for e in ("ps1", "ps2", "as1"))
    assert after["ps1"][0] == "ps1v1" and after["ps2"][0] == "ps2v0"


async def test_an_assembly_edit_leaves_part_studio_exports_valid() -> None:
    before, after = await _revisions(BASE), await _revisions(_with(BASE, "as1", "as1v1"))
    assert before["ps1"] == after["ps1"] and before["ps2"] == after["ps2"]
    assert before["as1"] != after["as1"]


async def test_drawings_never_invalidate_an_export() -> None:
    before = await _revisions(BASE)
    assert await _revisions(_with(BASE, "dr1", "changed")) == before


async def test_a_blob_edit_invalidates_part_studios_and_assemblies() -> None:
    """Blobs (imported geometry, fonts, ...) can be consumed by Part Studios and assemblies,
    so a changed blob must not be served a stale export. (This replaces the old assertion
    that blobs never invalidate an export, which pinned the stale-export gap.)"""
    before, after = await _revisions(BASE), await _revisions(_with(BASE, "bl1", "bl1v1"))
    assert all(before[e][1] != after[e][1] for e in ("ps1", "ps2", "as1"))
    assert before["ps1"][0] == after["ps1"][0]  # each element's OWN microversion is unchanged


async def test_a_feature_studio_edit_invalidates_part_studios_and_assemblies() -> None:
    listing = [*BASE, _el("fs1", "FEATURESTUDIO", "fs1v0")]
    before = await _revisions(listing)
    after = await _revisions(_with(listing, "fs1", "fs1v1"))
    assert set(before) == {"ps1", "ps2", "as1"}  # a Feature Studio is a dependency, not a target
    assert all(before[e][1] != after[e][1] for e in ("ps1", "ps2", "as1"))


async def test_a_blob_without_a_microversion_degrades_to_document_keys() -> None:
    assert await _revisions([_el("ps1", "PARTSTUDIO", "m"), _el("bl1", "BLOB")]) == {}


async def test_the_fingerprint_does_not_depend_on_listing_order() -> None:
    assert await _revisions(BASE) == await _revisions(list(reversed(BASE)))


async def test_part_studio_and_assembly_fingerprints_are_domain_separated() -> None:
    only = [_el("a", "PARTSTUDIO", "m"), _el("b", "ASSEMBLY", "m")]
    revisions = await _revisions(only)
    assert revisions["a"][1] != revisions["b"][1]


async def test_a_missing_or_malformed_microversion_falls_back_to_document_keys() -> None:
    # No microversionId at all: nothing is invented — every export is keyed by document.
    bare = [_el("ps1", "PARTSTUDIO"), _el("as1", "ASSEMBLY")]
    assert await _revisions(bare) == {}
    # One unusable dependency removes only the exports that depend on it.
    one_bad = [
        _el("ps1", "PARTSTUDIO", "ps1v0"),
        _el("as1", "ASSEMBLY", "../bad"),
        _el("dr1", "DRAWING"),
    ]
    revisions = await _revisions(one_bad)
    assert set(revisions) == {"ps1"}
    non_string = [_el("ps1", "PARTSTUDIO", 7)]
    assert await _revisions(non_string) == {}


async def test_listing_rows_with_invalid_ids_are_ignored() -> None:
    revisions = await _revisions([_el("../x", "PARTSTUDIO", "m"), _el("ps1", "PARTSTUDIO", "m1")])
    assert set(revisions) == {"ps1"}


async def test_a_listing_for_another_version_is_never_used_for_keys() -> None:
    subject = _connector(BASE)
    async with httpx.AsyncClient() as client:
        await subject._elements_at(client, "doc", "workspace", REV)
    assert subject._export_revisions("doc", "otherrev") == {}


def test_export_keys_live_in_a_fresh_namespace_so_document_keyed_entries_are_not_misread() -> None:
    subject = OnshapeConnector(client_id="id", client_secret="secret", account_ref="account")
    key = subject._payload_key("export", "doc", "ps1v0", "ps1", "fingerprint")
    assert "revision-v3-export" in key
    assert "revision-v2" not in key
