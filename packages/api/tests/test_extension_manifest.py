"""SOLUSDEV-235 (ADR-035) — extension.toml TEXT loading on top of the contract."""

from __future__ import annotations

import pytest
from fixtures.extensions import FULL_MANIFEST_TOML, MINIMAL_MANIFEST_TOML
from solus_api.extensions.manifest import (
    MANIFEST_TEXT_MAX_BYTES,
    ManifestError,
    load_manifest,
    manifest_text_problems,
)
from solus_contracts.extension_manifest import ExtensionManifest


def test_loads_a_minimal_manifest() -> None:
    manifest = load_manifest(MINIMAL_MANIFEST_TOML)
    assert isinstance(manifest, ExtensionManifest)
    assert manifest.extension.id == "bom-lite"
    assert manifest.views.widget is not None
    assert manifest.views.widget.entry == "widget.html"
    assert manifest_text_problems(MINIMAL_MANIFEST_TOML) == []


def test_loads_a_full_manifest() -> None:
    manifest = load_manifest(FULL_MANIFEST_TOML)
    assert manifest.permissions.scopes == ["graph.read"]
    assert manifest.store.privacy_policy == "PRIVACY.md"
    assert [s.body for s in manifest.store.sections] == ["docs/HOW.md"]


def test_contract_problems_use_dotted_paths() -> None:
    text = MINIMAL_MANIFEST_TOML.replace('id = "bom-lite"', 'id = "Not A Slug"')
    problems = manifest_text_problems(text)
    assert problems and any(p.startswith("extension.id:") for p in problems), problems
    with pytest.raises(ManifestError) as exc:
        load_manifest(text)
    assert exc.value.problems == problems


def test_unknown_fields_reject() -> None:
    text = MINIMAL_MANIFEST_TOML + '\n[extension.hooks]\npostinstall = "rm -rf /"\n'
    assert any("postinstall" in p or "hooks" in p for p in manifest_text_problems(text))


def test_toml_syntax_errors_become_problems() -> None:
    text = MINIMAL_MANIFEST_TOML + "\n[views\nbroken = \n"
    problems = manifest_text_problems(text)
    assert len(problems) == 1
    assert problems[0].startswith("extension.toml:")
    with pytest.raises(ManifestError):
        load_manifest(text)


def test_text_over_the_cap_is_refused_before_parsing() -> None:
    text = MINIMAL_MANIFEST_TOML + "# " + "x" * MANIFEST_TEXT_MAX_BYTES
    problems = manifest_text_problems(text)
    assert len(problems) == 1
    assert "exceeds" in problems[0] and str(MANIFEST_TEXT_MAX_BYTES) in problems[0]


def test_empty_text_is_a_problem_not_a_crash() -> None:
    assert manifest_text_problems("")
    with pytest.raises(ManifestError):
        load_manifest("")


def test_manifest_error_message_lists_the_problems() -> None:
    with pytest.raises(ManifestError, match="extension.id"):
        load_manifest(MINIMAL_MANIFEST_TOML.replace('id = "bom-lite"', 'id = "B"'))
