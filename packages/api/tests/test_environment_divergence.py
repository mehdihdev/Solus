"""SOLUSDEV-320 P5-T3: environment divergences — the pure `diff_environment` table and the
stored `environment/divergences` document (`GET /projects/{id}/environment/divergences`),
shaped field for field like the desktop's `EnvironmentDivergencesDoc`."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from conftest import add_member, create_project, create_team, me
from httpx import AsyncClient
from solus_api.graph import kinds
from solus_api.models import GraphEntity, ProjectMembership, SolusEntry, SolusEntryKind
from solus_api.services.code_env import CodeEnvironment, upsert_code_environment
from solus_api.services.environment_divergence import (
    diff_environment,
    find_divergences_entry,
    recompute_divergences,
)
from solus_api.services.machines import MachineIn, upsert_machine
from solus_api.services.solus_payloads import EnvironmentDivergencesDoc, EnvironmentSpec
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from test_environment_spec import _seed_requirements

NOW = datetime(2026, 10, 18, 10, tzinfo=UTC)
SPEC = EnvironmentSpec.model_validate(
    {
        "schema_version": 1,
        "computed_at": NOW,
        "packages": [
            {
                "name": "torch",
                "ecosystem": "python",
                "specifier": "==2.4.0",
                "required_by": [],
                "source": "manifest",
            },
            {
                "name": "numpy",
                "ecosystem": "python",
                "specifier": None,
                "required_by": [],
                "source": "manifest",
            },
            {
                "name": "xacro",
                "ecosystem": "ros",
                "specifier": None,
                "required_by": [],
                "source": "manifest",
            },
        ],
        "tools": [{"name": "git", "version": None}, {"name": "ros2", "version": "humble"}],
    }
)


def _machine_env(*pins: tuple[str, str | None]) -> dict[str, Any]:
    return CodeEnvironment.model_validate(
        {
            "type": "venv",
            "name": ".venv",
            "path": ".venv",
            "packages": [{"name": n, "version": v} for n, v in pins],
            "provenance": "detected",
            "captured_at": NOW,
        }
    ).model_dump(mode="json")


def _group(cause: str, *items: dict[str, Any]) -> dict[str, Any]:
    return {
        "cause": cause,
        "items": [{"expected": None, "actual": None, "detail": None, **i} for i in items],
    }


TOOLS = {"git": "git version 2.45.0", "ros2": "ros2 0.25.0 (humble)"}


@pytest.mark.parametrize(
    ("env", "tools", "expected"),
    [
        # Everything the spec names is installed as pinned; tools present → nothing.
        (_machine_env(("torch", "2.4.0"), ("numpy", "2.1.0")), TOOLS, []),
        # A package the spec names is not installed.
        (
            _machine_env(("torch", "2.4.0")),
            TOOLS,
            [_group("missing", {"name": "numpy"})],
        ),
        # Installed, but outside the specifier.
        (
            _machine_env(("torch", "2.3.1"), ("numpy", "2.1.0")),
            TOOLS,
            [_group("version_drift", {"name": "torch", "expected": "==2.4.0", "actual": "2.3.1"})],
        ),
        # Installed with a platform build tag (+cu121): the pin holds, the build differs.
        (
            _machine_env(("torch", "2.4.0+cu121"), ("numpy", "2.1.0")),
            TOOLS,
            [
                _group(
                    "platform_build",
                    {
                        "name": "torch",
                        "expected": "==2.4.0",
                        "actual": "2.4.0+cu121",
                        "detail": "platform build +cu121",
                    },
                )
            ],
        ),
        # Installed packages the spec never asked for.
        (
            _machine_env(("torch", "2.4.0"), ("numpy", "2.1.0"), ("requests", "2.32.0")),
            TOOLS,
            [_group("extra", {"name": "requests", "actual": "2.32.0"})],
        ),
        # Tools: an absent one is missing; a versioned one that does not mention it drifts.
        (
            _machine_env(("torch", "2.4.0"), ("numpy", "2.1.0")),
            {"ros2": "ros2 0.30.0 (jazzy)"},
            [
                _group("missing", {"name": "git"}),
                _group(
                    "version_drift",
                    {"name": "ros2", "expected": "humble", "actual": "ros2 0.30.0 (jazzy)"},
                ),
            ],
        ),
        # No environment observed on the machine: nothing can be said (never "all missing").
        (None, TOOLS, []),
        # An installed version the probe could not read is unknown, not drift.
        (_machine_env(("torch", None), ("numpy", "2.1.0")), TOOLS, []),
    ],
)
def test_diff_environment_table(
    env: dict[str, Any] | None, tools: dict[str, str], expected: list[dict[str, Any]]
) -> None:
    assert diff_environment(SPEC, env, tools) == expected


def test_diff_with_an_empty_spec_reports_no_extras() -> None:
    empty = EnvironmentSpec(computed_at=NOW, packages=[], tools=[])
    assert diff_environment(empty, _machine_env(("requests", "2.32.0")), {}) == []


# ------------------------------------------------------------------ stored document + route


async def _project(client: AsyncClient, headers: dict[str, str]) -> tuple[str, str, str]:
    user = await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    return str(project["id"]), str(team["id"]), str(user["id"])


async def _machine_with_env(
    db: AsyncSession,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    companion: str,
    hostname: str,
    pins: tuple[tuple[str, str | None], ...],
    tool_versions: dict[str, str],
) -> uuid.UUID:
    machine = await upsert_machine(
        db,
        project_id,
        user_id,
        companion,
        MachineIn(hostname=hostname, os="linux", arch="arm64"),
        tool_versions=tool_versions,
    )
    env = CodeEnvironment.model_validate(_machine_env(*pins))
    await upsert_code_environment(
        db, project_id, env, created_by=user_id, author="system", configured_entity_id=machine.id
    )
    return machine.id


async def test_divergences_doc_groups_per_machine_and_cause(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project, _, user = await _project(client, alice_headers)
    pid, uid = uuid.UUID(project), uuid.UUID(user)
    await _seed_requirements(db, pid)  # torch ==2.4.0, xacro (ros), pyserial (config)
    bench_1 = await _machine_with_env(
        db, pid, uid, "a" * 32, "bench-1", (("torch", "2.3.1"),), {"git": "git version 2.45.0"}
    )
    bench_2 = await _machine_with_env(
        db,
        pid,
        uid,
        "b" * 32,
        "bench-2",
        (("torch", "2.4.0+cu121"), ("pyserial", "3.5"), ("requests", "2.32.0")),
        {},
    )
    await db.commit()
    entry = await recompute_divergences(db, pid)
    await db.commit()
    assert entry.section == "environment" and entry.subsection == "divergences"
    assert entry.kind == SolusEntryKind.CONFIG
    subject = await db.get(GraphEntity, entry.configured_entity_id)  # the cell's own node
    assert subject is not None and subject.kind == kinds.SOLUS_SUBSECTION
    assert subject.attrs == {"section": "environment", "subsection": "divergences"}
    doc = EnvironmentDivergencesDoc.model_validate(entry.payload)
    assert doc.spec_entry_id is not None
    spec_entry = await db.get(SolusEntry, doc.spec_entry_id)
    assert spec_entry is not None and spec_entry.subsection == "spec"
    by_machine = {m.machine_id: m for m in doc.machines}
    assert set(by_machine) == {bench_1, bench_2}
    assert by_machine[bench_1].hostname == "bench-1"
    assert [(g.cause, [i.name for i in g.items]) for g in by_machine[bench_1].causes] == [
        ("missing", ["pyserial"]),
        ("version_drift", ["torch"]),
    ]
    assert [(g.cause, [i.name for i in g.items]) for g in by_machine[bench_2].causes] == [
        ("platform_build", ["torch"]),
        ("extra", ["requests"]),
    ]

    resp = await client.get(
        f"/api/v1/projects/{project}/environment/divergences", headers=alice_headers
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data == entry.payload
    assert set(data) == {"schema_version", "computed_at", "spec_entry_id", "machines"}
    assert data["schema_version"] == 1
    for machine in data["machines"]:
        assert set(machine) == {"machine_id", "hostname", "causes"}
        for group in machine["causes"]:
            assert set(group) == {"cause", "items"}
            for item in group["items"]:
                assert (
                    {"name", "expected", "actual"}
                    <= set(item)
                    <= {
                        "name",
                        "expected",
                        "actual",
                        "detail",
                    }
                )

    # Recomputed in place: same row.
    again = await recompute_divergences(db, pid)
    assert again.id == entry.id
    rows = list(
        await db.scalars(
            select(SolusEntry).where(
                SolusEntry.project_id == pid, SolusEntry.subsection == "divergences"
            )
        )
    )
    assert [r.id for r in rows] == [entry.id]


async def test_route_computes_on_first_read_and_scopes_to_members(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    project, team, _ = await _project(client, alice_headers)
    resp = await client.get(
        f"/api/v1/projects/{project}/environment/divergences", headers=alice_headers
    )
    assert resp.status_code == 200, resp.text
    doc = resp.json()["data"]
    assert doc["machines"] == [] and doc["spec_entry_id"] is not None
    bob = await me(client, bob_headers)
    resp = await client.get(
        f"/api/v1/projects/{project}/environment/divergences", headers=bob_headers
    )
    assert resp.status_code == 404
    await add_member(client, alice_headers, bob_headers, bob, team, role="viewer")
    resp = await client.get(
        f"/api/v1/projects/{project}/environment/divergences", headers=bob_headers
    )
    assert resp.status_code == 200  # a viewer may read


async def test_a_share_only_reader_gets_the_document_but_stores_nothing(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    project, _, _ = await _project(client, alice_headers)
    bob = await me(client, bob_headers)
    db.add(ProjectMembership(project_id=uuid.UUID(project), user_id=uuid.UUID(bob["id"])))
    await db.commit()
    resp = await client.get(
        f"/api/v1/projects/{project}/environment/divergences", headers=bob_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["machines"] == []
    assert await find_divergences_entry(db, uuid.UUID(project)) is None
    resp = await client.get(
        f"/api/v1/projects/{project}/environment/divergences", headers=alice_headers
    )
    assert resp.status_code == 200
    assert await find_divergences_entry(db, uuid.UUID(project)) is not None
