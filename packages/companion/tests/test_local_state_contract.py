"""SOLUSDEV-166 (ADR-034) — the ~/.solus local-state contract, Python half.

Validates the SAME fixtures the TypeScript suite parses
(packages/shared-types/fixtures/local-state/) and regenerates the ``_fields.json``
manifest from the pydantic models' SERIALIZATION ALIASES — the on-disk names the
TS field lists are compared against. A field added on either side breaks one of
the two suites (the json.ts drift-guard pattern).

Lives in the companion suite because the companion is the Python consumer of
these files (it already owns ``~/.solus/companion_id``).
"""

import json
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError
from solus_contracts import (
    PROJECT_REGISTRY_SCHEMA_VERSION,
    ProjectFolderLink,
    ProjectRegistry,
)

FIXTURES = Path(__file__).resolve().parents[2] / "shared-types" / "fixtures" / "local-state"


def _load(name: str) -> object:
    return json.loads((FIXTURES / name).read_text())


# --- the shared fixtures validate ------------------------------------------


@pytest.mark.parametrize("name", ["registry.json", "registry-minimal.json"])
def test_fixtures_validate(name: str) -> None:
    registry = ProjectRegistry.model_validate(_load(name))
    assert registry.schema_version == PROJECT_REGISTRY_SCHEMA_VERSION


def test_round_trip_preserves_the_on_disk_camel_case_names() -> None:
    raw = _load("registry.json")
    registry = ProjectRegistry.model_validate(raw)
    assert registry.model_dump(by_alias=True, exclude_none=True) == raw
    link = registry.projects["proj_a1B2c3"]
    assert link.repo_url == "https://gitlab.com/team/rover.git"


# --- the field manifest the TS suite checks itself against ------------------


def _alias_manifest(models: list[type[BaseModel]]) -> dict[str, list[str]]:
    """Model name → sorted ON-DISK field names (serialization alias or name)."""
    return {
        m.__name__: sorted(
            field.serialization_alias or field.alias or name
            for name, field in m.model_fields.items()
        )
        for m in models
    }


def test_the_field_manifest_is_current() -> None:
    path = FIXTURES / "_fields.json"
    expected = _alias_manifest([ProjectFolderLink, ProjectRegistry])
    committed = json.loads(path.read_text()) if path.is_file() else None
    if committed != expected:
        path.write_text(json.dumps(expected, indent=2, sort_keys=True) + "\n")
    assert committed == expected, (
        f"{path} was stale and has been regenerated — commit it; "
        "the TypeScript suite checks its field lists against this manifest."
    )


# --- strict rejection, mirroring the TS parse ------------------------------


def test_reserved_id_fixture_is_rejected() -> None:
    # Parity with the TS parser: the shared reserved-id fixture must be invalid
    # to BOTH sides, or the "fixtures prevent drift" guarantee is false.
    with pytest.raises(ValidationError):
        ProjectRegistry.model_validate(_load("reserved-id.invalid.json"))


@pytest.mark.parametrize(
    ("why", "value"),
    [
        ("missing schema_version", {"projects": {}}),
        (
            "a reserved __proto__ id",
            {"schema_version": 1, "projects": {"__proto__": {"path": "/a"}}},
        ),
        ("zero schema_version", {"schema_version": 0, "projects": {}}),
        ("newer schema_version", {"schema_version": 2, "projects": {}}),
        ("unknown top-level field", {"schema_version": 1, "projects": {}, "extra": True}),
        (
            "unknown link field",
            {"schema_version": 1, "projects": {"p1": {"path": "/a", "evil": "x"}}},
        ),
        ("empty link path", {"schema_version": 1, "projects": {"p1": {"path": ""}}}),
        (
            "non-string repoUrl",
            {"schema_version": 1, "projects": {"p1": {"path": "/a", "repoUrl": 7}}},
        ),
        (
            "project id with a path separator",
            {"schema_version": 1, "projects": {"../evil": {"path": "/a"}}},
        ),
        (
            "project id with a space",
            {"schema_version": 1, "projects": {"a b": {"path": "/a"}}},
        ),
    ],
)
def test_rejects(why: str, value: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ProjectRegistry.model_validate(value)
