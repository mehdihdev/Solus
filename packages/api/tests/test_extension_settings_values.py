"""Settings VALUES against a manifest's `[settings]` (SOLUSDEV-235 EXT-09,
docs/api/extensions.md §6.3, schema invariant #3): the pure validator table and
the route's `422` / oversize behaviour."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.core.config import Settings
from solus_api.extensions.settings_schema import (
    SETTINGS_MAX_BYTES,
    coerce_settings,
    encoded_size,
    settings_with_defaults,
    validate_settings_values,
)
from solus_contracts.extension_manifest import parse_extension_manifest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from test_extension_installs import (
    MANIFEST,
    ext_url,
    install,
    installs_app,
    project_for,
    seed_extension,
)

FULL = parse_extension_manifest(MANIFEST)


@pytest.fixture
def app(settings: Settings, engine: AsyncEngine) -> FastAPI:
    return installs_app(settings, engine)


# --------------------------------------------------------------- pure table
@pytest.mark.parametrize(
    "values",
    [
        {},
        {"refresh": "hourly"},
        {"flag_eol": False},
        {"max_rows": 10},
        {"max_rows": 500},
        {"max_rows": 250.5},
        {"vendor": ""},
        {"refresh": "manual", "flag_eol": True, "max_rows": 42, "vendor": "Digi-Key"},
    ],
)
def test_valid_values_produce_no_problems(values: dict[str, Any]) -> None:
    assert validate_settings_values(FULL, values) == []


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ({"nope": 1}, "settings.nope: unknown setting"),
        (
            {"refresh": "weekly"},
            "settings.refresh: must be one of every_sync, hourly, daily, manual",
        ),
        ({"refresh": 3}, "settings.refresh: must be a select"),
        ({"flag_eol": "true"}, "settings.flag_eol: must be a boolean"),
        ({"flag_eol": 1}, "settings.flag_eol: must be a boolean"),
        ({"max_rows": True}, "settings.max_rows: must be a number"),
        ({"max_rows": "100"}, "settings.max_rows: must be a number"),
        ({"max_rows": 9}, "settings.max_rows: must be >= 10"),
        ({"max_rows": 501}, "settings.max_rows: must be <= 500"),
        ({"vendor": 7}, "settings.vendor: must be a string"),
        ({"vendor": None}, "settings.vendor: must be a string"),
    ],
)
def test_each_violation_is_named_by_dotted_key(values: dict[str, Any], expected: str) -> None:
    assert validate_settings_values(FULL, values) == [expected]


def test_problems_accumulate_unknown_keys_first_then_declared_order() -> None:
    problems = validate_settings_values(FULL, {"max_rows": 0, "zzz": 1, "refresh": "x"})
    assert problems == [
        "settings.zzz: unknown setting",
        "settings.refresh: must be one of every_sync, hourly, daily, manual",
        "settings.max_rows: must be >= 10",
    ]


def test_settings_with_defaults_fills_declared_defaults_only() -> None:
    assert settings_with_defaults(FULL, {"refresh": "daily"}) == {
        "refresh": "daily",
        "flag_eol": True,
        "max_rows": 100,
    }


def test_coerce_settings_drops_unknown_and_invalid_then_fills_defaults() -> None:
    assert coerce_settings(FULL, {"refresh": "daily", "max_rows": -1, "x": 1, "vendor": "M"}) == {
        "refresh": "daily",
        "flag_eol": True,
        "max_rows": 100,
        "vendor": "M",
    }


def test_encoded_size_is_the_canonical_compact_encoding() -> None:
    assert encoded_size({"b": 1, "a": "é"}) == len('{"a":"é","b":1}'.encode())
    assert SETTINGS_MAX_BYTES == 16 * 1024


# ------------------------------------------------------------------- route
@pytest.mark.parametrize(
    "values",
    [{"nope": 1}, {"refresh": "weekly"}, {"flag_eol": "true"}, {"max_rows": 5}, {"max_rows": "9"}],
)
async def test_patch_with_invalid_settings_is_422_naming_the_problems(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession, values: dict[str, Any]
) -> None:
    await seed_extension(db)
    _, project_id = await project_for(client, alice_headers)
    assert (await install(client, alice_headers, project_id)).status_code == 201

    resp = await client.patch(
        ext_url(project_id, "bom"), json={"settings": values}, headers=alice_headers
    )

    assert resp.status_code == 422, resp.text
    error = resp.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"] == validate_settings_values(FULL, values)


async def test_patch_with_an_oversized_settings_object_is_422(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    await seed_extension(db)
    _, project_id = await project_for(client, alice_headers)
    assert (await install(client, alice_headers, project_id)).status_code == 201

    resp = await client.patch(
        ext_url(project_id, "bom"),
        json={"settings": {"vendor": "v" * SETTINGS_MAX_BYTES}},
        headers=alice_headers,
    )

    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "validation_error"


async def test_patch_rejects_invalid_settings_without_touching_the_stored_ones(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    await seed_extension(db)
    _, project_id = await project_for(client, alice_headers)
    assert (await install(client, alice_headers, project_id)).status_code == 201

    bad = await client.patch(
        ext_url(project_id, "bom"),
        json={"enabled": False, "settings": {"refresh": "weekly"}},
        headers=alice_headers,
    )

    assert bad.status_code == 422
    listed = await client.get(ext_url(project_id), headers=alice_headers)
    item = listed.json()["data"][0]
    assert item["enabled"] is True  # nothing in the body was applied
    assert item["settings"]["refresh"] == "every_sync"
