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
    SUPPORTED_SCHEMA_VERSIONS,
    Backend,
    ExtensionManifest,
    ExtensionMeta,
    Graph,
    GraphKind,
    PageView,
    Permissions,
    SettingField,
    Settings,
    Store,
    StoreLinks,
    StoreSection,
    Tools,
    Views,
    WidgetView,
    WindowView,
    composed_tool_name,
    declares_first_party,
    graph_kind_name,
    is_safe_extension_id,
    manifest_problems,
    parse_extension_manifest,
)

FIXTURES = Path(__file__).resolve().parents[3] / "shared-types" / "fixtures" / "extension-manifest"


def _load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


# --- the shared fixtures validate ------------------------------------------


@pytest.mark.parametrize(
    ("name", "schema_version"),
    [
        ("manifest-full.json", 1),
        ("manifest-minimal.json", 1),
        ("manifest-v2-first-party.json", 2),
        ("manifest-v2-community.json", 2),
    ],
)
def test_fixtures_validate(name: str, schema_version: int) -> None:
    manifest = parse_extension_manifest(_load(name))
    assert manifest.schema_version == schema_version
    assert manifest.schema_version in SUPPORTED_SCHEMA_VERSIONS
    assert manifest_problems(_load(name)) == []


def test_latest_schema_version_is_two_and_one_stays_supported() -> None:
    # SOLUSDEV-246 (STORE ST1): v2 adds the first-party tables; every v1
    # manifest published before it parses unchanged.
    assert EXTENSION_MANIFEST_SCHEMA_VERSION == 2
    assert SUPPORTED_SCHEMA_VERSIONS == (1, 2)


# --- SOLUSDEV-246: the first-party tables ----------------------------------


def test_v1_manifests_default_the_first_party_tables_to_nothing() -> None:
    manifest = parse_extension_manifest(_load("manifest-minimal.json"))
    assert manifest.backend is None
    assert manifest.graph.kinds == []
    assert manifest.tools.names == []
    assert declares_first_party(manifest) is False


def test_v2_community_manifest_declares_nothing_first_party() -> None:
    manifest = parse_extension_manifest(_load("manifest-v2-community.json"))
    assert declares_first_party(manifest) is False


def test_v2_first_party_manifest_carries_backend_graph_and_tools() -> None:
    manifest = parse_extension_manifest(_load("manifest-v2-first-party.json"))
    assert manifest.backend is not None
    assert manifest.backend.capability == "fixture-bundle"
    assert manifest.backend.routes is True
    assert [k.name for k in manifest.graph.kinds] == ["note"]
    assert manifest.graph.kinds[0].domain == "code"
    assert manifest.tools.names == ["add_note", "clear_notes"]
    assert declares_first_party(manifest) is True


def test_namespacing_helpers_match_the_documented_shapes() -> None:
    # Graph kinds land as `ext:<id>:<name>`; tools register as `<id>.<name>`
    # (the dotted form the model-boundary translation already handles).
    assert graph_kind_name("fixture-bundle", "note") == "ext:fixture-bundle:note"
    assert composed_tool_name("fixture-bundle", "add_note") == "fixture-bundle.add_note"
    # Longest legal id (64) + "." + longest legal name (32) stays under the
    # provider cap of 128 the prompt layer enforces.
    assert len(composed_tool_name("a" * 64, "b" * 32)) <= 128


@pytest.mark.parametrize(
    ("name", "needle"),
    [
        ("v2-bad-tool-name.invalid.json", "tools.names.0"),
        ("v2-capability-mismatch.invalid.json", "backend.capability"),
        ("v1-with-backend.invalid.json", "backend"),
        ("v2-too-many-kinds.invalid.json", "graph.kinds"),
    ],
)
def test_first_party_tables_are_strict(name: str, needle: str) -> None:
    with pytest.raises(ValidationError):
        parse_extension_manifest(_load(name))
    problems = manifest_problems(_load(name))
    assert problems and any(needle in p for p in problems), problems


def test_v1_manifest_treats_first_party_tables_as_unknown_fields() -> None:
    # Parity with the TS parser: at schema_version 1 the tables are simply
    # unknown, so an old bundle carrying them fails exactly as before.
    problems = manifest_problems(_load("v1-with-backend.invalid.json"))
    assert any(p.startswith("backend: unknown field") for p in problems), problems


def test_graph_kind_names_are_distinct_and_domains_closed() -> None:
    m = _load("manifest-v2-first-party.json")
    m["graph"] = {"kinds": [{"name": "note", "domain": "code"}, {"name": "note", "domain": "code"}]}
    assert any("graph.kinds" in p for p in manifest_problems(m))
    m["graph"] = {"kinds": [{"name": "note", "domain": "plumbing"}]}
    assert any("graph.kinds.0.domain" in p for p in manifest_problems(m))


def test_tool_names_are_distinct_and_bounded() -> None:
    m = _load("manifest-v2-first-party.json")
    m["tools"] = {"names": ["add_note", "add_note"]}
    assert any("tools.names" in p for p in manifest_problems(m))
    m["tools"] = {"names": [f"t{i}" for i in range(17)]}
    assert any("tools.names" in p for p in manifest_problems(m))


def test_backend_routes_defaults_false_and_capability_is_required() -> None:
    m = _load("manifest-v2-first-party.json")
    m["backend"] = {"capability": "fixture-bundle"}
    parsed = parse_extension_manifest(m)
    assert parsed.backend is not None and parsed.backend.routes is False
    m["backend"] = {"routes": True}
    assert any("backend.capability" in p for p in manifest_problems(m))


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
            Backend,
            Graph,
            GraphKind,
            Tools,
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
