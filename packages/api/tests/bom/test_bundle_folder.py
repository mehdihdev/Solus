"""SOLUSDEV-246 (STORE ST4) — the committed BOM bundle folder IS a publishable bundle.

Mirrors `test_fixture_bundle_folder.py`: zips
`packages/shared-types/fixtures/extension-bundles/bom/`, runs the full bundle
validator, and checks the first-party gate matches the in-repo `bom` capability.
"""

from __future__ import annotations

from conftest import API_DIR
from solus_api.extensions.bundle import inspect_bundle
from solus_api.widgets.publish_gate import first_party_problems
from solus_api.widgets.registry import discover_capabilities
from solus_contracts.extension_manifest import declares_first_party
from test_fixture_bundle_folder import zip_folder

FOLDER = API_DIR.parent / "shared-types" / "fixtures" / "extension-bundles" / "bom"


def test_the_bom_folder_passes_the_full_bundle_validator() -> None:
    report = inspect_bundle(zip_folder(FOLDER))
    assert report.ok, report.problems
    manifest = report.manifest
    assert manifest is not None
    assert manifest.schema_version == 2
    assert manifest.extension.id == "bom"
    assert manifest.extension.requires == [["eda", "cad"]]
    assert manifest.views.page is not None and manifest.views.page.label == "BOM"
    assert manifest.backend is not None and manifest.backend.routes is True
    assert [k.name for k in manifest.graph.kinds] == ["item"]
    assert manifest.tools.names == ["add_item"]
    assert [f.key for f in manifest.settings.fields] == [
        "preferred_suppliers",
        "cost_target",
        "currency",
    ]
    assert declares_first_party(manifest)


def test_the_bom_folder_matches_its_in_repo_capability() -> None:
    report = inspect_bundle(zip_folder(FOLDER))
    assert report.manifest is not None
    caps = discover_capabilities()
    assert "bom" in caps
    assert first_party_problems(report.manifest, is_staff=True, capabilities=caps) == []
    assert first_party_problems(report.manifest, is_staff=False, capabilities=caps) == [
        "backend: first-party only (publisher is not Solus staff)"
    ]
