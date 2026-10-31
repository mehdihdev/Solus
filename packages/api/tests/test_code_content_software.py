"""SOLUSDEV-321 P6 — the software reads a code-host sync adds (`connectors/code_content.py:
read_software`): the ROS packages a repository commits land as nodes and topics under its repo
node, read through `CodeContentReader` at the synced commit and bounded; a failed read is a sync
error on its path; anything else leaves the result as it was, and nothing fails the sync."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Final

import httpx
import pytest
from solus_api.checkers.matrix_runner import run_matrix
from solus_api.connectors import code_content
from solus_api.connectors.code_content import read_software
from solus_api.connectors.contracts import (
    Credentials,
    Domain,
    EntityOut,
    RelationOut,
    SyncContext,
    SyncResult,
)
from solus_api.connectors.github import GitHubConnector
from solus_api.connectors.local_folder import LocalFolderConnector
from solus_api.connectors.runtime import run_sync
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.models import GraphEntity, Membership, Source, User
from solus_api.services.machines import ensure_member
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_runtime import _seed_source, maker  # noqa: F401 — `maker` is a fixture

FIXTURES: Final = Path(__file__).resolve().parent / "fixtures"
COMMIT: Final = "a" * 40
CREDENTIALS: Final = Credentials(token="test-token")


def _blob(path: str) -> str:
    return hashlib.sha1(path.encode()).hexdigest()  # noqa: S324 — a fake blob id


def repo_result(root: Path, extra: dict[str, str] | None = None) -> tuple[SyncResult, Served]:
    """A code-host sync result whose code files are `root`'s files (plus `extra`), and the
    provider that serves their blobs."""
    files = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }
    files.update({path: text.encode() for path, text in (extra or {}).items()})
    entities = [
        EntityOut(
            source_key=":repo",
            type="code_repo",
            domain=Domain.CODE,
            name="org/robot",
            properties={"branch": "main", "commit": COMMIT},
        ),
        *(
            EntityOut(
                source_key=path,
                type="code_file",
                domain=Domain.CODE,
                name=path.rsplit("/", 1)[-1],
                properties={"path": path, "sha": _blob(path), "size": len(data)},
            )
            for path, data in files.items()
        ),
    ]
    result = SyncResult(
        entities=entities,
        relations=[RelationOut(from_key=":repo", to_key=path, type="contains") for path in files],
        cursor={"branch": "main", "sha": COMMIT},
    )
    return result, Served({_blob(path): (path, data) for path, data in files.items()})


class Served:
    """A provider serving blobs by id; it records every path read and refuses the ones asked."""

    def __init__(self, blobs: dict[str, tuple[str, bytes]]) -> None:
        self.blobs = blobs
        self.read: list[str] = []
        self.refused: set[str] = set()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, data = self.blobs[request.url.path.rsplit("/", 1)[-1]]
        self.read.append(path)
        return httpx.Response(404 if path in self.refused else 200, content=data)


def _github(monkeypatch: pytest.MonkeyPatch, served: Served) -> GitHubConnector:
    connector = GitHubConnector()
    client = lambda creds: httpx.AsyncClient(transport=httpx.MockTransport(served))  # noqa: E731
    monkeypatch.setattr(connector, "_http", client)
    return connector


def _by_key(result: SyncResult) -> dict[str, EntityOut]:
    return {entity.source_key: entity for entity in result.entities}


async def test_a_repositorys_ros_packages_land_under_the_repo_node(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, served = repo_result(FIXTURES / "ros2_ws")

    out = await read_software(_github(monkeypatch, served), CREDENTIALS, {"repo": "org/r"}, result)

    entities = _by_key(out)
    talker, listener = entities["ros_node:/robot/talker"], entities["ros_node:/listener"]
    assert talker.properties["publishes"] == ["/robot/chatter"]
    assert listener.properties["subscribes"] == ["/robot/chatter"]
    assert entities["ros_topic:/robot/chatter"].properties == {"type": "std_msgs/msg/String"}
    contains = {(r.from_key, r.to_key) for r in out.relations if r.type == "contains"}
    for key in ("ros_node:/robot/talker", "ros_node:/listener", "ros_topic:/robot/chatter"):
        assert (":repo", key) in contains
    assert set(_by_key(result)) <= set(entities)  # what the connector landed stays
    assert out.errors == [] and out.cursor == result.cursor
    # only what the reader needs was read: manifests, launch and setup files, module directories
    assert sorted(served.read) == [
        "src/listener_py/launch/listener.launch.xml",
        "src/listener_py/listener_py/__init__.py",
        "src/listener_py/listener_py/listener.py",
        "src/listener_py/package.xml",
        "src/listener_py/setup.py",
        "src/talker_py/launch/talker.launch.py",
        "src/talker_py/package.xml",
        "src/talker_py/setup.py",
        "src/talker_py/talker_py/__init__.py",
        "src/talker_py/talker_py/talker.py",
    ]


async def test_hidden_test_and_credential_paths_are_never_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extra = {
        f"src/talker_py/{rel}": "SECRET = 1\n"
        for rel in (
            ".hidden.py",
            "tests/test_talker.py",
            "talker_py/secrets.py",
            "talker_py/credentials/config.py",
            "tools/debug.py",
        )
    }
    result, served = repo_result(FIXTURES / "ros2_ws", extra)

    await read_software(_github(monkeypatch, served), CREDENTIALS, {"repo": "org/r"}, result)

    assert not set(served.read) & set(extra)


async def test_a_failed_read_is_a_sync_error_on_its_path_and_the_rest_lands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, served = repo_result(FIXTURES / "ros2_ws")
    served.refused.add("src/listener_py/listener_py/listener.py")

    out = await read_software(_github(monkeypatch, served), CREDENTIALS, {"repo": "org/r"}, result)

    entities = _by_key(out)
    assert entities["ros_node:/listener"].properties["subscribes"] == []  # its module was refused
    assert entities["ros_node:/robot/talker"].properties["publishes"] == ["/robot/chatter"]
    (error,) = out.errors
    assert error.item == "src/listener_py/listener_py/listener.py"


async def test_reads_stop_at_the_cap_and_say_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(code_content, "MAX_SOFTWARE_READS", 3)
    result, served = repo_result(FIXTURES / "ros2_ws")

    out = await read_software(_github(monkeypatch, served), CREDENTIALS, {"repo": "org/r"}, result)

    assert len(served.read) == 3
    assert [error.item for error in out.errors] == [":repo"]
    assert "3" in out.errors[0].message


async def test_a_plain_repository_lands_nothing_and_stays_as_it_was(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, served = repo_result(FIXTURES / "plain_repo")

    out = await read_software(_github(monkeypatch, served), CREDENTIALS, {"repo": "org/r"}, result)

    # its config is a policy candidate by name, so it is read; it states no interface
    assert out == result and served.read == ["config.yaml"]


async def test_a_repositorys_policy_and_controller_files_carry_their_interfaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The policy reader's facts ride on the files they were read from, as `module_interfaces`;
    nothing new is created, and only the candidates are read."""
    result, served = repo_result(FIXTURES / "policy_mismatch")

    out = await read_software(_github(monkeypatch, served), CREDENTIALS, {"repo": "org/r"}, result)

    entities = _by_key(out)

    def stated(path: str, side: str) -> list[object]:
        return [item[side] for item in entities[path].properties["module_interfaces"]]

    assert stated("config/policy.yaml", "outputs") == [6]
    assert stated("envs/arm_env.py", "outputs") == [6]
    assert stated("config/controller.yaml", "inputs") == [7]
    assert set(entities) == set(_by_key(result)) and out.errors == []
    assert sorted(served.read) == [
        "config/controller.yaml",
        "config/policy.yaml",
        "envs/arm_env.py",
    ]


async def test_policy_reads_stop_at_their_own_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(code_content, "MAX_POLICY_READS", 1)
    result, served = repo_result(FIXTURES / "policy_mismatch")

    await read_software(_github(monkeypatch, served), CREDENTIALS, {"repo": "org/r"}, result)

    assert served.read == ["config/controller.yaml"]


async def test_only_a_code_host_is_read() -> None:
    result, served = repo_result(FIXTURES / "ros2_ws")
    out = await read_software(LocalFolderConnector(), CREDENTIALS, {"repo": "org/r"}, result)
    assert out is result and served.read == []


async def test_a_reader_that_breaks_never_fails_the_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    result, served = repo_result(FIXTURES / "ros2_ws")

    def broken(packages: Any) -> Any:
        raise RuntimeError("reader bug")

    monkeypatch.setattr(code_content, "parse_ros_workspace", broken)
    out = await read_software(_github(monkeypatch, served), CREDENTIALS, {"repo": "org/r"}, result)
    assert out is result


class _ScriptedGitHub(GitHubConnector):
    """A GitHub connector whose sync answers a fixed result (its files' blobs served by `_http`)."""

    def __init__(self, result: SyncResult) -> None:
        super().__init__()
        self._result = result

    async def sync(self, ctx: SyncContext) -> SyncResult:
        return self._result


async def test_run_sync_lands_a_code_hosts_ros_packages(
    maker: async_sessionmaker[AsyncSession],  # noqa: F811 — the imported fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemorySecretStore()
    source = await _seed_source(maker, store)
    result, served = repo_result(FIXTURES / "ros2_ws")
    connector = _ScriptedGitHub(result)
    client = lambda creds: httpx.AsyncClient(transport=httpx.MockTransport(served))  # noqa: E731
    monkeypatch.setattr(connector, "_http", client)

    await run_sync(
        source_id=source.id, sessionmaker=maker, connector=connector, secret_store=store, force=True
    )

    async with maker() as db:
        rows = await db.scalars(
            select(GraphEntity).where(
                GraphEntity.source_id == source.id, GraphEntity.kind.in_(["ros_node", "ros_topic"])
            )
        )
        assert sorted(row.name for row in rows) == ["/listener", "/robot/chatter", "/robot/talker"]


async def test_module_contract_mismatch_fires_on_a_synced_policy_mismatch(
    maker: async_sessionmaker[AsyncSession],  # noqa: F811 — the imported fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P6 acceptance, leg 3, through the code-content path: a repository whose policy acts 6 wide
    against a controller of 7 joints, synced, then a matrix run."""
    store = InMemorySecretStore()
    source = await _seed_source(maker, store)
    result, served = repo_result(FIXTURES / "policy_mismatch")
    connector = _ScriptedGitHub(result)
    client = lambda creds: httpx.AsyncClient(transport=httpx.MockTransport(served))  # noqa: E731
    monkeypatch.setattr(connector, "_http", client)

    await run_sync(
        source_id=source.id, sessionmaker=maker, connector=connector, secret_store=store, force=True
    )
    async with maker() as db:
        report = await run_matrix(db, source.project_id)
        await db.commit()

    fails = [r for r in report.results["module_contract_mismatch"] if r.status == "fail"]
    assert sorted((r.evidence["action_dim"], r.evidence["input_dim"]) for r in fails) == [
        (6, 7),
        (6, 7),
    ]
    assert report.findings_raised >= len(fails)


async def test_a_code_sync_recomputes_its_creators_expertise(
    maker: async_sessionmaker[AsyncSession],  # noqa: F811 — the imported fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SOLUSDEV-321 P6: after a code source's sync commits, its creator's levels follow (one
    guarded call in `_commit_success`); only the four levels land on their member node. P6 fix 1
    (m6, a moved pin): the repo alone reaches `working`, since `expert` needs the creator's own
    questions about the domain, so whoever connects a big team repo is not `expert` in it all."""
    store = InMemorySecretStore()
    source = await _seed_source(maker, store)
    async with maker() as db:
        user = User(supabase_user_id=f"sync-{source.id}", email="sync@example.com")
        db.add(user)
        await db.flush()
        db.add(Membership(team_id=source.team_id, user_id=user.id))
        row = await db.get(Source, source.id)
        assert row is not None
        row.created_by = user.id
        # R168: a sync lands only what the connector produced — the member node is made when the
        # person registers a machine, and the levels are written onto that existing node.
        await ensure_member(db, source.project_id, user.id)
        await db.commit()
    result, served = repo_result(FIXTURES / "ros2_ws")
    connector = _ScriptedGitHub(result)
    client = lambda creds: httpx.AsyncClient(transport=httpx.MockTransport(served))  # noqa: E731
    monkeypatch.setattr(connector, "_http", client)

    await run_sync(
        source_id=source.id, sessionmaker=maker, connector=connector, secret_store=store, force=True
    )

    async with maker() as db:
        (member,) = await db.scalars(
            select(GraphEntity).where(
                GraphEntity.project_id == source.project_id, GraphEntity.kind == "member"
            )
        )
        assert member.attrs["expertise"] == {
            "control": "working",
            "electronics": "working",
            "mechanical": "working",
            "software": "working",
        }
