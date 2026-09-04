"""SOLUSDEV-235 (ADR-035) — the extension.toml contract, Python half.

Validates the SAME fixtures the TypeScript suite parses
(packages/shared-types/fixtures/extension-manifest/) and regenerates the
``_fields.json`` manifest from the pydantic models' field names, which the TS
field lists are compared against. Lives in the API suite because the API's
publish validator is the Python consumer of this shape.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError
from solus_contracts.extension_manifest import (
    EXTENSION_ID_PATTERN,
    EXTENSION_MANIFEST_FILENAME,
    EXTENSION_MANIFEST_SCHEMA_VERSION,
    PERMISSION_SCOPES,
    ExtensionManifest,
    ExtensionMeta,
    PageView,
    Permissions,
    SettingField,
    Settings,
    Store,
    StoreLinks,
    StoreSection,
    Views,
    WidgetView,
    WindowView,
    is_safe_extension_id,
    manifest_problems,
    parse_extension_manifest,
)

FIXTURES = Path(__file__).resolve().parents[3] / "shared-types" / "fixtures" / "extension-manifest"


def _load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


# --- the shared fixtures validate ------------------------------------------


@pytest.mark.parametrize("name", ["manifest-full.json", "manifest-minimal.json"])
def test_fixtures_validate(name: str) -> None:
    manifest = parse_extension_manifest(_load(name))
    assert manifest.schema_version == EXTENSION_MANIFEST_SCHEMA_VERSION
    assert manifest_problems(_load(name)) == []


def test_minimal_manifest_defaults_the_optional_blocks() -> None:
    manifest = parse_extension_manifest(_load("manifest-minimal.json"))
    assert manifest.permissions.scopes == []
    assert manifest.permissions.network == []
    assert manifest.settings.fields == []
    assert manifest.store.privacy_policy is None
    assert manifest.store.sections == []


def test_the_manifest_file_has_one_fixed_name() -> None:
    assert EXTENSION_MANIFEST_FILENAME == "extension.toml"


# --- the field manifest the TS suite checks itself against ------------------


def _field_manifest(models: list[type[BaseModel]]) -> dict[str, list[str]]:
    return {m.__name__: sorted(m.model_fields) for m in models}


def test_the_field_manifest_is_current() -> None:
    path = FIXTURES / "_fields.json"
    expected = _field_manifest(
        [
            ExtensionManifest,
            ExtensionMeta,
            Views,
            WidgetView,
            PageView,
            WindowView,
            Permissions,
            Settings,
            SettingField,
            Store,
            StoreLinks,
            StoreSection,
        ]
    )
    committed = json.loads(path.read_text()) if path.is_file() else None
    if committed != expected:
        path.write_text(json.dumps(expected, indent=2, sort_keys=True) + "\n")
    assert committed == expected, (
        f"{path} was stale and has been regenerated — commit it; "
        "the TypeScript suite checks its field lists against this manifest."
    )


# --- strict rejection, mirroring the TS parse ------------------------------


@pytest.mark.parametrize(
    ("name", "needle"),
    [
        ("bad-id.invalid.json", "extension.id"),
        ("missing-privacy.invalid.json", "privacy_policy"),
        ("unknown-field.invalid.json", "postinstall"),
        ("traversal.invalid.json", "views.page.entry"),
    ],
)
def test_invalid_fixtures_are_rejected_and_name_the_field(name: str, needle: str) -> None:
    with pytest.raises(ValidationError):
        parse_extension_manifest(_load(name))
    problems = manifest_problems(_load(name))
    assert problems and any(needle in p for p in problems), problems


def test_newer_schema_version_is_rejected_here() -> None:
    # The Python side is the PUBLISH validator: a newer schema than this server
    # knows must be refused, never partially accepted.
    with pytest.raises(ValidationError):
        parse_extension_manifest(_load("newer-schema.json"))


def _minimal() -> dict[str, Any]:
    return _load("manifest-minimal.json")


def _with_privacy(m: dict[str, Any]) -> dict[str, Any]:
    m["store"] = {**m["store"], "privacy_policy": "PRIVACY.md"}
    return m


def test_at_least_one_view_is_required() -> None:
    m = _minimal()
    m["views"] = {}
    assert manifest_problems(m)


def test_scopes_are_a_closed_set_and_bounded() -> None:
    m = _with_privacy(_minimal())
    m["permissions"] = {"scopes": ["filesystem.write"], "network": []}
    assert manifest_problems(m)
    m["permissions"] = {"scopes": [*PERMISSION_SCOPES, "graph.read"], "network": []}
    assert manifest_problems(m)


@pytest.mark.parametrize(
    "origin", ["http://api.example", "https://api.example/v1", "https://", "api.example"]
)
def test_network_must_be_https_origins(origin: str) -> None:
    m = _with_privacy(_minimal())
    m["permissions"] = {"scopes": [], "network": [origin]}
    assert manifest_problems(m)


def test_network_alone_requires_a_privacy_policy() -> None:
    m = _minimal()
    m["permissions"] = {"scopes": [], "network": ["https://api.example"]}
    assert any("privacy_policy" in p for p in manifest_problems(m))


@pytest.mark.parametrize(
    "field",
    [
        {"key": "mode", "type": "select", "label": "Mode"},
        {"key": "n", "type": "number", "label": "N", "default": "ten"},
        {"key": "Bad Key", "type": "boolean", "label": "B"},
        {"key": "s", "type": "select", "label": "S", "options": ["a"], "default": "b"},
    ],
)
def test_setting_fields_are_typed(field: dict[str, Any]) -> None:
    m = _minimal()
    m["settings"] = {"fields": [field]}
    assert manifest_problems(m)


def test_setting_keys_are_unique() -> None:
    m = _minimal()
    m["settings"] = {
        "fields": [
            {"key": "a", "type": "boolean", "label": "A"},
            {"key": "a", "type": "boolean", "label": "B"},
        ]
    }
    assert manifest_problems(m)


@pytest.mark.parametrize(
    "store",
    [
        {"overview": "OVERVIEW.exe"},
        {"overview": "OVERVIEW.md", "links": {"documentation": "http://x.example"}},
        {"overview": "OVERVIEW.md", "links": {"homepage": "https://x.example"}},
        {"overview": "OVERVIEW.md", "screenshots": ["shots/a.gif"]},
        {"overview": "OVERVIEW.md", "sections": [{"title": "T", "body": "../x.md"}]},
    ],
)
def test_store_block_is_strict(store: dict[str, Any]) -> None:
    m = _minimal()
    m["store"] = store
    assert manifest_problems(m)


@pytest.mark.parametrize("version", ["v1", "1.0", "1.0.0.0", ""])
def test_version_is_semver(version: str) -> None:
    m = _minimal()
    m["extension"]["version"] = version
    assert manifest_problems(m)


def test_requires_kinds_are_closed_and_groups_non_empty() -> None:
    m = _minimal()
    m["extension"]["requires"] = [["bluetooth"]]
    assert manifest_problems(m)
    m["extension"]["requires"] = [[]]
    assert manifest_problems(m)


def test_id_rule_matches_the_ts_side() -> None:
    import re

    rx = re.compile(EXTENSION_ID_PATTERN)
    assert rx.match("bom") and rx.match("can-telemetry-2")
    assert not rx.match("b") and not rx.match("Bom") and not rx.match("2bom")
    assert not rx.match("a" * 65)
    assert not is_safe_extension_id("constructor")
    assert is_safe_extension_id("bom")
