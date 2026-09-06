"""SOLUSDEV-246 — the committed fixture bundle folder IS a publishable bundle.

Zips `packages/shared-types/fixtures/extension-bundles/fixture-bundle/` exactly
as `docs/extensions/publishing.md` §1 tells developers to, runs the FULL bundle
validator on it, and checks the first-party gate passes for staff and refuses
everyone else. If this fails, the acceptance path ("a fixture bundle with all
five parts installs") is broken before any server is involved.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from conftest import API_DIR
from solus_api.extensions.bundle import inspect_bundle
from solus_api.widgets.publish_gate import first_party_problems
from solus_api.widgets.registry import discover_capabilities
from solus_contracts.extension_manifest import declares_first_party

FOLDER = API_DIR.parent / "shared-types" / "fixtures" / "extension-bundles" / "fixture-bundle"


def zip_folder(folder: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(p for p in folder.rglob("*") if p.is_file()):
            zf.write(path, path.relative_to(folder).as_posix())
    return buffer.getvalue()


def test_the_fixture_folder_passes_the_full_bundle_validator() -> None:
    report = inspect_bundle(zip_folder(FOLDER))
    assert report.ok, report.problems
    assert report.manifest is not None
    manifest = report.manifest
    assert manifest.schema_version == 2
    assert manifest.extension.id == "fixture-bundle"
    assert manifest.views.page is not None and manifest.views.page.label == "Fixture"
    assert manifest.backend is not None and manifest.backend.routes is True
    assert [k.name for k in manifest.graph.kinds] == ["note"]
    assert manifest.tools.names == ["add_note", "clear_notes"]
    assert [f.key for f in manifest.settings.fields] == ["max_notes", "prefix"]
    assert declares_first_party(manifest)


def test_the_fixture_folder_is_first_party_and_matches_its_in_repo_capability() -> None:
    report = inspect_bundle(zip_folder(FOLDER))
    assert report.manifest is not None
    caps = discover_capabilities()
    assert first_party_problems(report.manifest, is_staff=True, capabilities=caps) == []
    assert first_party_problems(report.manifest, is_staff=False, capabilities=caps) == [
        "backend: first-party only (publisher is not Solus staff)"
    ]
