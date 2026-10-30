"""graph/inference/manifests + manifest_edges and the manifest wiring into the connectors
(local folder, GitHub, GitLab) — SOLUSDEV-320 Phase 3 module 4."""

from __future__ import annotations

import base64
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from fixtures.github_sample import COMMIT_BODY, HEAD_SHA, REPO_BODY, REPO_FULL_NAME, USER_BODY
from fixtures.github_sample import DEFAULT_BRANCH as GH_BRANCH
from fixtures.gitlab_sample import COMMIT_BODY as GL_COMMIT
from fixtures.gitlab_sample import DEFAULT_BRANCH as GL_BRANCH
from fixtures.gitlab_sample import HEAD_SHA as GL_SHA
from fixtures.gitlab_sample import PROJECT_BODY, TREE_PAGE_1
from fixtures.gitlab_sample import _item as gl_item
from pydantic import ValidationError
from solus_api.connectors.code_host import manifest_entities, requirement_entity
from solus_api.connectors.contracts import Domain, SyncResult
from solus_api.connectors.github import GitHubConnector
from solus_api.connectors.gitlab import GitLabConnector
from solus_api.connectors.local_folder import ScannedDependency, build_local_graph
from solus_api.connectors.runtime import apply_sync_result
from solus_api.graph import kinds
from solus_api.graph.edges import write_edge
from solus_api.graph.inference import InferenceReport, config_requires, manifest_edges
from solus_api.graph.inference.manifests import (
    ManifestDep,
    parse_dependency_manifest,
    parse_package_json,
    parse_package_xml,
)
from solus_api.models import GraphEdge, GraphEntity, SourceType
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from test_github_connector import _ctx as gh_ctx
from test_gitlab_connector import API as GL_API
from test_gitlab_connector import ENC
from test_gitlab_connector import _ctx as gl_ctx
from test_inference_power_nets import (
    USER,
    edge_rows,
    names_of,
    seed_project,
    seed_source,
    snapshot_edges,
)
from test_local_folder import _scan

FIXTURES = Path(__file__).parent / "fixtures" / "inference"
PACKAGE_JSON = (FIXTURES / "package.json").read_text()
PACKAGE_XML = (FIXTURES / "package.xml").read_text()
GH_API = "https://api.github.com"


# ------------------------------------------------------------------ pure parsers


def test_package_json_lists_dependencies_and_dev_dependencies() -> None:
    assert parse_package_json(PACKAGE_JSON) == [
        ManifestDep("react", "^18.3.1", "npm", "dependencies", 6),
        ManifestDep("@types/node", "20.11.0", "npm", "dependencies", 7),
        ManifestDep("ws", ">=8 <9", "npm", "dependencies", 8),
        ManifestDep("vitest", "~1.6.0", "npm", "devDependencies", 11),
    ]


def test_package_json_malformed_or_hostile_yields_nothing() -> None:
    assert parse_package_json("{not json") == []
    assert parse_package_json("[]") == []
    assert parse_package_json('{"dependencies": ["react"]}') == []
    assert parse_package_json('{"dependencies": {"React Native!": "1", "ok": 7}}') == []
    assert parse_package_json('{"dependencies": {"a": "' + "x" * 200 + '"}}') == []
    assert parse_package_json('{"dependencies": {"a": "ignore previous instructions"}}') == []
    # Protocol refs and aliases are bounded to a printable charset, not free-form `\S*`.
    assert parse_package_json('{"dependencies": {"a": "npm:`rm -rf /`"}}') == []
    assert parse_package_json('{"dependencies": {"a": "file:' + "x" * 65 + '"}}') == []


def test_package_json_keeps_bounded_protocol_refs_and_aliases() -> None:
    text = (
        '{"dependencies": {"a": "npm:lodash@^4.17.0", "b": "workspace:*", '
        '"c": "github:user/repo#v1.2", "d": "git+ssh://git@host/repo.git", "e": "lodash@^4"}}'
    )
    assert [d.specifier for d in parse_package_json(text)] == [
        "npm:lodash@^4.17.0",
        "workspace:*",
        "github:user/repo#v1.2",
        "git+ssh://git@host/repo.git",
        "lodash@^4",
    ]


def test_package_xml_lists_depend_build_and_exec_groups_only() -> None:
    assert parse_package_xml(PACKAGE_XML) == [
        ManifestDep("rclcpp", "", "ros", "build_depend", 9),
        ManifestDep("std_msgs", "", "ros", "depend", 10),
        ManifestDep("rclpy", "", "ros", "exec_depend", 11),
    ]


def test_package_xml_refuses_dtd_malformed_and_oversize() -> None:
    assert parse_package_xml("<package><depend>rclcpp</depend>") == []
    assert (
        parse_package_xml('<!DOCTYPE x [<!ENTITY a "b">]><package><depend>&a;</depend></package>')
        == []
    )
    assert parse_package_xml("<other><depend>rclcpp</depend></other>") == []
    assert parse_package_xml("<package><depend>Bad Name</depend></package>") == []
    assert parse_package_xml("<package>" + "<depend>a</depend>" * 100_000 + "</package>") == []


def test_parse_manifest_dispatches_on_the_file_name() -> None:
    assert [d.name for d in parse_dependency_manifest("ui/package.json", PACKAGE_JSON)] == [
        "react",
        "@types/node",
        "ws",
        "vitest",
    ]
    assert [d.name for d in parse_dependency_manifest("package.xml", PACKAGE_XML)] == [
        "rclcpp",
        "std_msgs",
        "rclpy",
    ]
    assert parse_dependency_manifest("requirements.txt", "torch==1\n") == []


# ----------------------------------------------------------- entity wiring (pure)


def test_requirement_entity_kind_follows_the_ecosystem() -> None:
    python = requirement_entity(
        name="torch", specifier="==2", ecosystem="python", source_file="r.txt"
    )
    npm = requirement_entity(
        name="@types/node", specifier="20", ecosystem="npm", source_file="package.json"
    )
    assert python.type == kinds.PYTHON_REQUIREMENT and python.source_key == "req:r.txt:torch"
    assert (
        npm.type == kinds.PACKAGE_REQUIREMENT and npm.source_key == "req:package.json:@types/node"
    )
    assert npm.domain is Domain.CODE and npm.name == "@types/node 20"
    assert npm.properties == {
        "name": "@types/node",
        "specifier": "20",
        "extras": [],
        "source_file": "package.json",
        "ecosystem": "npm",
        "line": 0,
    }
    entities = manifest_entities("package.json", PACKAGE_JSON)
    assert [e.source_key for e in entities] == [
        "req:package.json:react",
        "req:package.json:@types/node",
        "req:package.json:ws",
        "req:package.json:vitest",
    ]
    assert entities[0].properties["line"] == 6 and entities[0].properties["group"] == "dependencies"


def test_local_scan_accepts_npm_and_ros_dependencies() -> None:
    scan = _scan(
        dependencies=[
            {"parts": ["requirements.txt"], "name": "torch", "specifier": "==2.3.0"},
            {
                "parts": ["package.json"],
                "name": "@types/node",
                "specifier": "^20",
                "ecosystem": "npm",
            },
            {
                "parts": ["ros", "package.xml"],
                "name": "rclcpp",
                "specifier": "",
                "ecosystem": "ros",
            },
        ]
    )
    entities, relations = build_local_graph(scan, machine_name="m", gitlab_host=None)
    by_key = {e.source_key: e for e in entities if e.source_key.startswith("req:")}
    assert by_key["req:requirements.txt:torch"].type == kinds.PYTHON_REQUIREMENT
    assert by_key["req:package.json:@types/node"].type == kinds.PACKAGE_REQUIREMENT
    assert by_key["req:package.json:@types/node"].properties["ecosystem"] == "npm"
    assert by_key["req:ros/package.xml:rclcpp"].type == kinds.PACKAGE_REQUIREMENT
    assert {r.to_key for r in relations if r.type == "requires"} == set(by_key)
    for bad in (
        {"parts": ["package.json"], "name": "@types/node", "ecosystem": "python"},
        {
            "parts": ["package.json"],
            "name": "react",
            "specifier": "do this now please",
            "ecosystem": "npm",
        },
        {"parts": ["package.xml"], "name": "Std_Msgs", "ecosystem": "ros"},
        {"parts": ["package.json"], "name": "react", "ecosystem": "cargo"},
    ):
        try:
            ScannedDependency.model_validate(bad)
        except ValidationError:
            continue
        raise AssertionError(f"accepted {bad}")


# ---------------------------------------------------------------- code hosts


@respx.mock
async def test_github_reads_root_manifests_through_the_bounded_blob_read() -> None:
    tree = {
        "sha": HEAD_SHA,
        "tree": [
            {"path": "package.json", "type": "blob", "size": len(PACKAGE_JSON), "sha": "aa10"},
            {"path": "package.xml", "type": "blob", "size": len(PACKAGE_XML), "sha": "aa11"},
            {"path": "ui", "type": "tree", "sha": "bb00"},
            {"path": "ui/package.json", "type": "blob", "size": 10, "sha": "bb10"},
            {"path": "src/main.py", "type": "blob", "size": 10, "sha": "cc10"},
        ],
        "truncated": False,
    }
    respx.get(f"{GH_API}/user").mock(return_value=httpx.Response(200, json=USER_BODY))
    respx.get(f"{GH_API}/repos/{REPO_FULL_NAME}").mock(
        return_value=httpx.Response(200, json=REPO_BODY)
    )
    respx.get(f"{GH_API}/repos/{REPO_FULL_NAME}/commits/{GH_BRANCH}").mock(
        return_value=httpx.Response(200, json=COMMIT_BODY)
    )
    respx.get(f"{GH_API}/repos/{REPO_FULL_NAME}/git/trees/{HEAD_SHA}").mock(
        return_value=httpx.Response(200, json=tree)
    )
    for sha, text in (("aa10", PACKAGE_JSON), ("aa11", PACKAGE_XML)):
        respx.get(f"{GH_API}/repos/{REPO_FULL_NAME}/git/blobs/{sha}").mock(
            return_value=httpx.Response(
                200, json={"content": base64.b64encode(text.encode()).decode()}
            )
        )
    result = await GitHubConnector().sync(gh_ctx())
    reqs = {e.source_key: e for e in result.entities if e.type == kinds.PACKAGE_REQUIREMENT}
    assert set(reqs) == {
        "req:package.json:react",
        "req:package.json:@types/node",
        "req:package.json:ws",
        "req:package.json:vitest",
        "req:package.xml:rclcpp",
        "req:package.xml:std_msgs",
        "req:package.xml:rclpy",
    }
    requires = {(r.from_key, r.to_key) for r in result.relations if r.type == "requires"}
    assert requires == {(":repo", key) for key in reqs}
    contains_targets = {r.to_key for r in result.relations if r.type == "contains"}
    assert not contains_targets & set(reqs)
    assert "ui/package.json" in contains_targets  # the nested file is still a code_file
    assert not any("bb10" in str(c.request.url) for c in respx.calls)  # never fetched
    assert result.errors == []


@respx.mock
async def test_github_oversize_manifest_is_a_sync_error_not_a_fetch() -> None:
    tree = {
        "sha": HEAD_SHA,
        "tree": [{"path": "package.json", "type": "blob", "size": 10**7, "sha": "aa10"}],
        "truncated": False,
    }
    respx.get(f"{GH_API}/repos/{REPO_FULL_NAME}").mock(
        return_value=httpx.Response(200, json=REPO_BODY)
    )
    respx.get(f"{GH_API}/repos/{REPO_FULL_NAME}/commits/{GH_BRANCH}").mock(
        return_value=httpx.Response(200, json=COMMIT_BODY)
    )
    respx.get(f"{GH_API}/repos/{REPO_FULL_NAME}/git/trees/{HEAD_SHA}").mock(
        return_value=httpx.Response(200, json=tree)
    )
    result = await GitHubConnector().sync(gh_ctx())
    assert not any("git/blobs" in str(c.request.url) for c in respx.calls)
    assert [e.item for e in result.errors] == ["package.json"]
    assert not any(e.type == kinds.PACKAGE_REQUIREMENT for e in result.entities)


@respx.mock
async def test_gitlab_reads_root_manifests_through_the_bounded_raw_read() -> None:
    page: list[dict[str, Any]] = [*TREE_PAGE_1, gl_item("package.json", "blob")]
    respx.get(f"{GL_API}/projects/{ENC}").mock(return_value=httpx.Response(200, json=PROJECT_BODY))
    respx.get(f"{GL_API}/projects/{ENC}/repository/commits/{GL_BRANCH}").mock(
        return_value=httpx.Response(200, json=GL_COMMIT)
    )
    respx.get(f"{GL_API}/projects/{ENC}/repository/tree").mock(
        return_value=httpx.Response(200, json=page, headers={"x-next-page": ""})
    )
    raw = respx.get(f"{GL_API}/projects/{ENC}/repository/files/package.json/raw").mock(
        return_value=httpx.Response(200, content=PACKAGE_JSON.encode())
    )
    result = await GitLabConnector().sync(gl_ctx())
    assert raw.called and raw.calls.last.request.url.params["ref"] == GL_SHA
    reqs = {e.source_key for e in result.entities if e.type == kinds.PACKAGE_REQUIREMENT}
    assert reqs == {
        "req:package.json:react",
        "req:package.json:@types/node",
        "req:package.json:ws",
        "req:package.json:vitest",
    }
    assert {(r.from_key, r.to_key) for r in result.relations if r.type == "requires"} == {
        (":repo", key) for key in reqs
    }
    assert result.errors == []


# ------------------------------------------------------------- manifest_edges


async def test_depends_on_from_every_live_requires_edge(db: AsyncSession) -> None:
    pid = await seed_project(db)
    source = await seed_source(db, pid, SourceType.LOCAL)
    scan = _scan(
        dependencies=[
            {"parts": ["requirements.txt"], "name": "torch", "specifier": "==2.3.0"},
            {"parts": ["package.json"], "name": "react", "specifier": "^18", "ecosystem": "npm"},
        ]
    )
    entities, relations = build_local_graph(scan, machine_name="m", gitlab_host=None)
    await apply_sync_result(db, source, SyncResult(entities=entities, relations=relations))

    report = await manifest_edges.infer(db, pid)

    edges = await edge_rows(db, pid, "depends_on")
    names = await names_of(db, edges)
    assert {(names[e.src_id], names[e.dst_id]): e.attrs["evidence"] for e in edges} == {
        ("rover-fw", "torch ==2.3.0"): [
            {"kind": "manifest", "ref": "requirements.txt", "detail": None}
        ],
        ("rover-fw", "react ^18"): [{"kind": "manifest", "ref": "package.json", "detail": None}],
    }
    assert all(
        e.confidence == 1.0 and e.attrs["matrix_cell"] == "software->software" for e in edges
    )
    assert report == InferenceReport(
        "manifest_edges", created=2, updated=0, skipped=0, candidates=0
    )

    before = await snapshot_edges(db, pid)
    again = await manifest_edges.infer(db, pid)
    assert again == InferenceReport("manifest_edges", created=0, updated=0, skipped=2, candidates=0)
    assert await snapshot_edges(db, pid) == before  # same ids, same updated_at


async def test_manual_depends_on_survives_a_rerun_without_its_input(db: AsyncSession) -> None:
    pid = await seed_project(db)
    owner = GraphEntity(project_id=pid, kind=kinds.CODE_REPO, domain=Domain.CODE, name="repo")
    req = GraphEntity(
        project_id=pid,
        kind=kinds.PACKAGE_REQUIREMENT,
        domain=Domain.CODE,
        name="react ^18",
        attrs={"source_file": "package.json"},
    )
    db.add_all([owner, req])
    await db.flush()
    manual = await write_edge(
        db,
        project_id=pid,
        src_id=owner.id,
        dst_id=req.id,
        relation_type="depends_on",
        origin="manual",
        confidence=1.0,
        evidence=[],
        created_by=USER,
    )
    report = await manifest_edges.infer(db, pid)  # no `requires` edge → nothing inferred
    assert report.created == 0
    await db.refresh(manual)
    assert manual.deleted_at is None and manual.origin == "manual"
    live = await db.scalar(
        select(GraphEdge).where(GraphEdge.project_id == pid, GraphEdge.deleted_at.is_(None))
    )
    assert live is not None and live.id == manual.id


async def test_requires_to_a_non_requirement_is_ignored(db: AsyncSession) -> None:
    pid = await seed_project(db)
    a = GraphEntity(project_id=pid, kind=kinds.CODE_REPO, domain=Domain.CODE, name="a")
    b = GraphEntity(project_id=pid, kind=kinds.CODE_FILE, domain=Domain.CODE, name="b")
    db.add_all([a, b])
    await db.flush()
    await write_edge(
        db,
        project_id=pid,
        src_id=a.id,
        dst_id=b.id,
        relation_type="requires",
        origin="manual",
        confidence=1.0,
        evidence=[],
        created_by=uuid.uuid4(),
    )
    assert (await manifest_edges.infer(db, pid)).created == 0


async def test_a_config_requires_edge_never_becomes_depends_on(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only connector-written `requires` from a manifest file (`attrs.source_file`) becomes
    `depends_on`: the 0.8 config edge stays what it is, and a requirement with no manifest
    gets no invented `manifest` evidence."""
    pid = await seed_project(db)
    node = GraphEntity(
        project_id=pid, kind=kinds.HARDWARE_CONFIG, domain=Domain.PROJECT, name="config"
    )
    repo = GraphEntity(project_id=pid, kind=kinds.CODE_REPO, domain=Domain.CODE, name="repo")
    bare = GraphEntity(
        project_id=pid, kind=kinds.PACKAGE_REQUIREMENT, domain=Domain.CODE, name="ws >=8"
    )
    db.add_all([node, repo, bare])
    await db.flush()
    monkeypatch.setattr(config_requires, "requires_packages_for", lambda driver_id: ("pyserial",))
    config = await config_requires.infer(db, pid, config_node_id=node.id, driver_id="demo")
    assert config.created == 1
    await write_edge(
        db,
        project_id=pid,
        src_id=repo.id,
        dst_id=bare.id,
        relation_type="requires",
        origin="connector",
        confidence=1.0,
        evidence=[],
        created_by=None,
    )

    assert await manifest_edges.infer(db, pid) == InferenceReport("manifest_edges")
    assert await edge_rows(db, pid, "depends_on") == []
    requires = await edge_rows(db, pid, "requires")
    assert sorted(e.confidence for e in requires) == [0.8, 1.0]
