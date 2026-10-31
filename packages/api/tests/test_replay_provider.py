"""SOLUSDEV-321 P2-T4 — the dev-only `replay` bench provider, API half: the path of a recording
confined under the configured root (`confined_file`, shared with the MCAP provider) and the robot
session it opens (`replay_session`: tenancy, path and the config the runner is handed; the
transport is livebench's, `test_stall_replay.py` runs the two together)."""

import os
import uuid
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from conftest import create_project, create_team, me
from fixtures.fake_arm import DEVICE_REF, FakeArm, seed_fake_arm
from httpx import AsyncClient
from solus_api.core.errors import APIError
from solus_api.hardware.config import HardwareConfig, ProtocolBinding
from solus_api.livebench.bench_router import ReplayRealConfig
from solus_api.livebench.replay_provider import MAX_RECORDING_BYTES, confined_file, replay_session
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

Maker = async_sessionmaker[AsyncSession]
_CAP = 2 * 1024 * 1024


def _recording_file(root: Path | str, raw: str, max_bytes: int | None = None) -> Path:
    """`confined_file` with the replay provider's rules."""
    return confined_file(
        root,
        raw,
        field="recording",
        root_name="bench replay root",
        suffix=".json",
        max_bytes=max_bytes,
    )


def _mcap_file(root: Path, raw: str) -> Path:
    """`confined_file` with the MCAP provider's rules, as the router states them."""
    return confined_file(root, raw, field="mcap_path", root_name="bench data root", suffix=".mcap")


def _refused(call: Callable[[], Path]) -> APIError:
    with pytest.raises(APIError) as refused:
        call()
    assert (refused.value.status_code, refused.value.code) == (422, "validation_error")
    return refused.value


def _replay_root(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    (root / "sub").mkdir(parents=True)
    return root


def test_confined_file_resolves_a_relative_or_an_absolute_path_inside_the_root(
    tmp_path: Path,
) -> None:
    root = _replay_root(tmp_path)
    capture = root / "sub" / "capture.json"
    capture.write_text("{}")
    inside = root / "sub" / "inside.json"
    inside.symlink_to(capture)  # a link that stays inside the root is fine

    assert _recording_file(root, "sub/capture.json") == capture.resolve()
    assert _recording_file(str(root), str(capture)) == capture.resolve()
    assert _recording_file(root, "sub/../sub/inside.json") == capture.resolve()


@pytest.mark.parametrize(
    "raw",
    ["../outside.json", "sub/../../outside.json", "@outside", "@link", "@dir_link/outside.json"],
)
def test_confined_file_refuses_every_way_out_of_the_root(tmp_path: Path, raw: str) -> None:
    root = _replay_root(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    (root / "link.json").symlink_to(outside)  # a symlink out of the root
    (root / "dir_link").symlink_to(tmp_path, target_is_directory=True)
    by_name = {
        "@outside": str(outside),
        "@link": "link.json",
        "@dir_link/outside.json": "dir_link/outside.json",
    }

    refused = _refused(lambda: _recording_file(root, by_name.get(raw, raw)))

    assert refused.message == "recording escapes the bench replay root"


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("notes.txt", "recording must name a .json file"),
        ("missing.json", "recording does not exist"),
        ("sub", "recording must name a .json file"),
        ("dir.json", "recording does not exist"),  # a directory is not a recording
        ("pipe.json", "recording does not exist"),  # nor is a pipe, which would block a read
        ("a\x00b.json", "recording is not a usable path"),
        ("x" * 300 + ".json", "recording does not exist"),  # too long to stat: not a 500
        ("loop.json", "recording is not a usable path"),
    ],
)
def test_confined_file_names_what_is_wrong_with_a_path_it_cannot_use(
    tmp_path: Path, raw: str, message: str
) -> None:
    root = _replay_root(tmp_path)
    (root / "notes.txt").write_text("{}")
    (root / "dir.json").mkdir()
    os.mkfifo(root / "pipe.json")
    (root / "loop.json").symlink_to(root / "loop.json")

    assert _refused(lambda: _recording_file(root, raw)).message == message


def test_confined_file_refuses_a_file_over_its_cap(tmp_path: Path) -> None:
    root = _replay_root(tmp_path)
    (root / "big.json").write_bytes(b"x" * _CAP + b"y")
    (root / "ok.json").write_bytes(b"x" * _CAP)

    assert _recording_file(root, "ok.json", _CAP).name == "ok.json"
    assert _refused(lambda: _recording_file(root, "big.json", _CAP)).message == (
        "recording is larger than 2 MiB"
    )
    assert MAX_RECORDING_BYTES == 32 * 1024 * 1024


def test_confined_file_keeps_the_mcap_providers_words(tmp_path: Path) -> None:
    """The MCAP provider reuses it: the same checks, the same messages."""
    root = _replay_root(tmp_path)
    (root / "run.mcap").write_bytes(b"\x89MCAP0\r\n")

    assert _mcap_file(root, "run.mcap").name == "run.mcap"
    escaped = _refused(lambda: _mcap_file(root, "../run.mcap"))
    assert escaped.message == "mcap_path escapes the bench data root"
    assert _refused(lambda: _mcap_file(root, "run.bin")).message == (
        "mcap_path must name a .mcap file"
    )
    assert _refused(lambda: _mcap_file(root, "ghost.mcap")).message == "mcap_path does not exist"


# ---------------------------------------------------------------------------- the session


class _Runner:
    """The livebench runner, as far as a replay session goes: it keeps what it is asked to open."""

    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, Any], uuid.UUID]] = []

    async def open_replay(self, config: dict[str, Any], *, project_id: uuid.UUID) -> str:
        self.calls.append((config, project_id))
        return "connection"


def _maker(engine: AsyncEngine) -> Maker:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _project_with_arm(
    client: AsyncClient, headers: dict[str, str], maker: Maker, *, name: str = "Rover"
) -> tuple[uuid.UUID, FakeArm]:
    await me(client, headers)
    team = await create_team(client, headers, name=name)
    project = uuid.UUID((await create_project(client, headers, team["id"]))["id"])
    async with maker() as db:
        arm = await seed_fake_arm(db, project, user_id=None)
        await db.commit()
    return project, arm


def _config(robot: uuid.UUID, recording: str = "capture.json", **over: Any) -> ReplayRealConfig:
    return ReplayRealConfig.model_validate(
        {
            "provider": "replay",
            "recording": recording,
            "driver_id": "lb06",
            "robot_entity_id": str(robot),
            **over,
        }
    )


async def test_replay_session_hands_the_runner_the_robots_config_with_the_requested_driver(
    client: AsyncClient, alice_headers: dict[str, str], engine: AsyncEngine, tmp_path: Path
) -> None:
    maker = _maker(engine)
    project, arm = await _project_with_arm(client, alice_headers, maker)
    (tmp_path / "capture.json").write_text("{}")  # the runner is a double: the text is not read
    runner = _Runner()
    settings = SimpleNamespace(bench_replay_root=tmp_path)

    async with maker() as db:
        config = _config(arm.robot, driver_id="other-driver", realtime=False)
        open_conn, label, device, robot = await replay_session(
            runner, db, project, config, settings
        )
    connection = await open_conn()

    assert (connection, robot) == ("connection", arm.robot)
    ((payload, opened_for),) = runner.calls
    assert opened_for == project
    assert payload["recording"] == str((tmp_path / "capture.json").resolve())
    assert payload["realtime"] is False
    assert payload["max_bytes"] == MAX_RECORDING_BYTES  # the runner's read is bounded by the cap
    document = HardwareConfig.model_validate(payload["document"])  # still a valid document
    assert document.protocol == ProtocolBinding(driver_id="other-driver")
    assert document.identity is not None and document.identity.device_ref == DEVICE_REF
    assert [entry.address for entry in document.bus_map] == [str(n) for n in range(1, 7)]
    assert set(document.parts) == {str(part) for part in arm.parts}
    assert label == "Replay capture.json as Fake arm"
    assert device == {"device_ref": DEVICE_REF, "driver_id": "other-driver", "replay": True}
    assert str(tmp_path) not in label + str(device)  # the server's paths stay on the server


async def test_replay_session_checks_the_root_then_the_robot_then_the_path_then_the_config(
    client: AsyncClient,
    alice_headers: dict[str, str],
    engine: AsyncEngine,
    tmp_path: Path,
) -> None:
    maker = _maker(engine)
    project, arm = await _project_with_arm(client, alice_headers, maker)
    _, foreign = await _project_with_arm(client, alice_headers, maker, name="Other")
    (tmp_path / "capture.json").write_text("{}")
    bare = await client.post(
        f"/api/v1/projects/{project}/entities",
        headers=alice_headers,
        json={"type": "physical_robot", "name": "Bare"},
    )
    assert bare.status_code == 201, bare.text
    bare_id = uuid.UUID(bare.json()["data"]["id"])

    async def refusal(root: Path | None, config: ReplayRealConfig) -> APIError:
        async with maker() as db:
            with pytest.raises(APIError) as refused:
                await replay_session(
                    _Runner(), db, project, config, SimpleNamespace(bench_replay_root=root)
                )
        return refused.value

    unset = await refusal(None, _config(foreign.robot, "../nowhere.json"))  # for every body
    unknown = await refusal(tmp_path, _config(uuid.uuid4(), "../nowhere.json"))
    other_project = await refusal(tmp_path, _config(foreign.robot, "../nowhere.json"))
    escapes = await refusal(tmp_path, _config(arm.robot, "../nowhere.json"))
    unconfigured = await refusal(tmp_path, _config(bare_id))

    assert (unset.status_code, unset.code) == (503, "source_unavailable")
    assert [(e.status_code, e.code) for e in (unknown, other_project)] == [(404, "not_found")] * 2
    assert (escapes.status_code, escapes.code) == (422, "validation_error")
    assert (unconfigured.status_code, unconfigured.code) == (422, "validation_error")
    assert "transport identity" in unconfigured.message
