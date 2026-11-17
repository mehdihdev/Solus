"""SOLUSDEV-326 P2-T6 — the plug-in path: a device that arrives is inspected before anyone asks.

When the `DeviceWatcher` sees a device nothing binds and the machine's owner has not said "Not
now" to, the API runs the `inspect_device` service at once — no model is called — keeps the
inspection for the owner in that project, and records the device's state in the machine's
owner-only memory: `inspecting`, then `inspected`, `busy` or `unknown`. SOL's
`hardware.inspect_device` answers that inspection while it is fresh, so the owner's first turn
after the notice reaches its first card in two model calls.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fixtures.fake_systems import FakeSolSystems
from httpx import AsyncClient
from solus_api.agent.confirmations import (
    ParkedCall,
    decide_confirmation,
    request_confirmation,
)
from solus_api.agent.dynamic_gate import registry_needs_card
from solus_api.agent.modes import ActionMode, build_mode_dispatch
from solus_api.agent.runtime import AgentRunContext, LlmRunner, build_dispatch
from solus_api.agent.stream import AgentEventType
from solus_api.agent.tools.hardware_cards import ADD_PARTS
from solus_api.agent.tools.hardware_onboarding import (
    INSPECT_DEVICE,
    LIST_DEVICES,
    register_hardware_tools,
)
from solus_api.agent.tools.registry import ToolRegistry
from solus_api.agent.tools.shapes import ToolCall, ToolErrorCode
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.graph.live import LiveHub, Subscription
from solus_api.graph.read_scope import owns_machine
from solus_api.hardware import device_memory, device_watch, inspections
from solus_api.hardware.device_memory import DeviceContext
from solus_api.hardware.device_watch import DeviceWatcher
from solus_api.hardware.inspections import INSPECTION_FRESH_S, INSPECTIONS
from solus_api.hardware.plug_in import arrivals, machine_owner
from solus_api.models import DataEvent, SolMode, User
from solus_api.orchestration import gateway
from solus_api.orchestration.providers import ToolUse, Usage
from solus_api.services.physical_robots import PhysicalRobotService
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from test_device_memory import (
    _backfilled_robot,
    _brain_item,
    _configure,
    _fresh_machine,
    _machine,
    _part,
    _usb_device,
)
from test_device_memory import host as host
from test_device_watch import _drained, _reader
from test_hardware_detect import DEVICE_REF, _wire_device
from test_hardware_onboarding import _Local
from test_hardware_onboarding import private_home as private_home
from test_in_graph import _Team, _team


@pytest.fixture(autouse=True)
def no_model(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every gateway entry is counted; only the count test below hands the runner a model."""
    calls: list[str] = []
    for name in ("stream", "complete", "computer_use"):
        real = getattr(gateway, name)

        def counted(*args: Any, _name: str = name, _real: Any = real, **kwargs: Any) -> Any:
            calls.append(_name)
            return _real(*args, **kwargs)

        monkeypatch.setattr(gateway, name, counted)
    return calls


@pytest.fixture(autouse=True)
def fresh_store(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """An empty inspection store on a clock the test moves."""
    now = [1_000.0]
    monkeypatch.setattr(INSPECTIONS, "_entries", type(INSPECTIONS._entries)())
    monkeypatch.setattr(INSPECTIONS, "_clock", lambda: now[0])
    return now


def _bob(team: _Team) -> uuid.UUID:
    return uuid.UUID(team.bob["id"])


def _factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _plugged(app: FastAPI, hub: LiveHub, local: Any, *, ticks: int = 1) -> DeviceWatcher:
    """A watcher that ticked and whose inspections all settled."""
    watcher = DeviceWatcher(hub, local, sessions=app.state.sessionmaker)
    for _ in range(ticks):
        await _tick(watcher)
    return watcher


async def _tick(watcher: DeviceWatcher) -> None:
    await watcher._tick()
    await watcher.settled()


async def _states(app: FastAPI, project: str) -> dict[str, Any]:
    rows = (await _fresh_machine(app, project)).get("devices") or []
    return {row["device_ref"]: row.get("state") for row in rows}


def _heard(reader: Subscription) -> list[Any]:
    return [[device.get("state") for device in frame["devices"]] for frame in _drained(reader)]


async def _owned(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> _Team:
    """A team whose project knows THIS machine as Alice's."""
    team = await _team(client, alice_headers, bob_headers)
    await _machine(db, team.project, str(team.alice_id))
    await db.execute(update(User).values(data_collection_consent=True))
    await db.commit()
    return team


# ------------------------------------------------------------------------------- the watcher


async def test_a_plugged_in_device_is_inspected_for_the_machines_owner_with_no_model_call(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
    host: list[str | None],
    no_model: list[str],
) -> None:
    team = await _owned(client, alice_headers, bob_headers, db)
    hub, local = LiveHub(), _Local()
    mine = _reader(hub, team.project, str(team.alice_id))
    theirs = _reader(hub, team.project, str(_bob(team)))

    await _plugged(app, hub, local)

    assert no_model == []
    assert local.asked == [
        {
            "device_ref": DEVICE_REF,
            "budget_s": 0.5,
            "repo_sources": None,
            "scope": team.project,
            "member": str(team.alice_id),
        }
    ]
    kept = INSPECTIONS.latest(team.project_id, team.alice_id, DEVICE_REF)
    assert kept is not None and [row.address for row in kept.proposal.rows] == ["1", "2"]
    assert INSPECTIONS.latest(team.project_id, _bob(team), DEVICE_REF) is None
    assert await _states(app, team.project) == {DEVICE_REF: "inspected"}
    # The owner's feed says so as it happens; a teammate at this machine reads no state.
    assert _heard(mine) == [["inspecting"], ["inspected"]]
    assert _heard(theirs) == [[None], [None]]
    events = list(
        await db.scalars(select(DataEvent).where(DataEvent.event_type == "hardware.inspected"))
    )
    assert [(event.user_id, event.payload["device_ref"]) for event in events] == [
        (team.alice_id, DEVICE_REF)
    ]


async def test_an_unchanged_list_is_not_inspected_again_and_a_replug_is(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
    host: list[str | None],
) -> None:
    team = await _owned(client, alice_headers, bob_headers, db)
    hub, local = LiveHub(), _Local()
    _reader(hub, team.project, str(team.alice_id))
    watcher = await _plugged(app, hub, local, ticks=3)
    assert len(local.asked) == 1

    local.devices = [*local.devices, _usb_device("OTHER")]  # another device arrives
    await _tick(watcher)
    assert [asked["device_ref"] for asked in local.asked] == [DEVICE_REF, "usb:OTHER"]
    assert await _states(app, team.project) == {DEVICE_REF: "inspected", "usb:OTHER": "unknown"}

    local.devices = [_wire_device()]
    await _tick(watcher)
    assert (await _states(app, team.project))[DEVICE_REF] == "inspected"
    local.devices = []
    await _tick(watcher)
    local.devices = [_wire_device()]
    await _tick(watcher)
    assert [asked["device_ref"] for asked in local.asked][2:] == [DEVICE_REF]


async def test_a_device_the_owner_said_not_now_to_is_not_inspected(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
    host: list[str | None],
) -> None:
    """The owner's "Not now" (the server route, one `hardware.device_dismissed` event) holds
    across the plug-in; a teammate's says nothing about the owner's machine."""
    team = await _owned(client, alice_headers, bob_headers, db)
    for headers, ref in ((alice_headers, DEVICE_REF), (bob_headers, "usb:OTHER")):
        said = await client.post(
            team.url("hardware", "devices", "dismissals"), json={"device_ref": ref}, headers=headers
        )
        assert said.status_code == 200, said.text
    events = list(
        await db.scalars(
            select(DataEvent).where(DataEvent.event_type == "hardware.device_dismissed")
        )
    )
    assert sorted((str(event.user_id), event.payload["device_ref"]) for event in events) == sorted(
        [(str(team.alice_id), DEVICE_REF), (str(_bob(team)), "usb:OTHER")]
    )
    hub, local = LiveHub(), _Local()
    local.devices = [_wire_device(), _usb_device("OTHER")]
    local.proposals = {"usb:OTHER": {**(local.proposal or {}), "device_ref": "usb:OTHER"}}
    mine = _reader(hub, team.project, str(team.alice_id))

    await _plugged(app, hub, local)

    assert [asked["device_ref"] for asked in local.asked] == ["usb:OTHER"]
    assert await _states(app, team.project) == {DEVICE_REF: None, "usb:OTHER": "inspected"}
    assert INSPECTIONS.latest(team.project_id, team.alice_id, DEVICE_REF) is None
    assert all(None in states for states in _heard(mine))


async def test_a_device_something_binds_is_not_inspected(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
    host: list[str | None],
) -> None:
    team = await _owned(client, alice_headers, bob_headers, db)
    await _backfilled_robot(db, team.project)  # its stored brain binds usb:BBB
    hub, local = LiveHub(), _Local()
    local.devices = [_usb_device("BBB")]
    _reader(hub, team.project, str(team.alice_id))

    await _plugged(app, hub, local)

    assert local.asked == [] and await _states(app, team.project) == {"usb:BBB": None}


@pytest.mark.parametrize("holder", ["robot", "part"])
async def test_a_device_only_a_teammates_hidden_hardware_holds_reads_as_unbound_to_the_owner(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
    engine: AsyncEngine,
    host: list[str | None],
    holder: str,
) -> None:
    """§1a: hardware Bob keeps out of the graph must not show through Alice's machine. A device
    only it holds is inspected, and reads on every surface, exactly like one nothing holds."""
    team = await _owned(client, alice_headers, bob_headers, db)
    if holder == "robot":
        hidden = await PhysicalRobotService(db).create(
            team.project_id, "Bobs secret arm", in_graph=False, onboarded_by=_bob(team)
        )
        await _configure(db, team.project, hidden, _brain_item("BBB", "bus-driver"))
    else:
        hidden = await _part(db, team.project, "Bobs secret arm", external_ref="usb:BBB")
        hidden.attrs = {"in_graph": False, "onboarded_by": str(_bob(team))}
    await db.commit()
    hub, local = LiveHub(), _Local()
    app.state.bench_local = local
    refs = ["usb:BBB", "usb:FREE"]
    local.devices = [_usb_device("BBB"), _usb_device("FREE")]
    local.proposals = {ref: {**(local.proposal or {}), "device_ref": ref} for ref in refs}
    mine = _reader(hub, team.project, str(team.alice_id))

    await _plugged(app, hub, local)

    def annotations(rows: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            row["device_ref"]: (row["bound_to"], row["dismissed"], row["state"]) for row in rows
        }

    unbound = dict.fromkeys(refs, (None, False, "inspected"))
    assert sorted(asked["device_ref"] for asked in local.asked) == refs
    frames = _drained(mine)
    assert annotations(frames[-1]["devices"]) == unbound
    detected = await client.get(team.url("hardware", "detected"), headers=alice_headers)
    assert detected.status_code == 200, detected.text
    assert annotations(detected.json()["data"]) == unbound
    listed = await _tools(engine, team, team.alice_id, local).invoke(
        ToolCall(tool=LIST_DEVICES, args={})
    )
    assert listed.ok and listed.value is not None, listed.error
    assert all(row["inspection_id"] for row in listed.value["devices"])
    assert len(listed.value["devices"]) == 2
    told = json.dumps([frames, detected.json(), listed.value], default=str)
    assert str(hidden.id) not in told and "secret" not in told
    # Its onboarder still reads what holds it.
    theirs = await client.get(team.url("hardware", "detected"), headers=bob_headers)
    assert annotations(theirs.json()["data"])["usb:BBB"] == (str(hidden.id), False, None)


async def test_a_busy_device_is_recorded_busy(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
    host: list[str | None],
) -> None:
    team = await _owned(client, alice_headers, bob_headers, db)
    hub, local = LiveHub(), _Local()
    local.busy = True  # the serial owner's DeviceBusyError
    mine = _reader(hub, team.project, str(team.alice_id))

    watcher = await _plugged(app, hub, local)

    assert await _states(app, team.project) == {DEVICE_REF: "busy"}
    assert _heard(mine) == [["inspecting"], ["busy"]]
    assert INSPECTIONS.latest(team.project_id, team.alice_id, DEVICE_REF) is None
    local.busy = False
    await _tick(watcher)  # nothing changed: busy is not retried behind the owner's back
    assert len(local.asked) == 1


@pytest.mark.parametrize("why", ["running", "left", "broken"])
async def test_a_device_that_cannot_be_listened_to_is_recorded_unknown(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
    host: list[str | None],
    why: str,
) -> None:
    """A board already running when Solus started is never restarted without its owner's card;
    one that left, or a runner that fails, is no reason to stop watching."""
    team = await _owned(client, alice_headers, bob_headers, db)
    hub, local = LiveHub(), _Local()
    _reader(hub, team.project, str(team.alice_id))
    if why == "running":
        local.restarts = True
    elif why == "left":
        local.proposal = None
    else:
        local.listen_restarts = None  # type: ignore[method-assign,assignment]

    await _plugged(app, hub, local)

    assert await _states(app, team.project) == {DEVICE_REF: "unknown"}
    assert len(local.asked) == (0 if why != "left" else 1)
    assert INSPECTIONS.latest(team.project_id, team.alice_id, DEVICE_REF) is None


async def test_nothing_is_inspected_for_an_owner_who_is_not_reading_here(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
    host: list[str | None],
) -> None:
    """An inspection is the owner's alone: a teammate reading the project on the owner's machine
    opens no port, and a machine the project does not know has no owner to inspect for."""
    team = await _owned(client, alice_headers, bob_headers, db)
    hub, local = LiveHub(), _Local()
    _reader(hub, team.project, str(_bob(team)))
    await _plugged(app, hub, local)
    assert local.asked == [] and await _states(app, team.project) == {DEVICE_REF: None}

    host[0] = None
    _reader(hub, team.project, str(team.alice_id))
    local.devices = [_wire_device(), _usb_device("OTHER")]
    await _plugged(app, hub, local)
    assert local.asked == []


async def test_an_inspection_a_dead_process_left_behind_is_run_again(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
    host: list[str | None],
) -> None:
    team = await _owned(client, alice_headers, bob_headers, db)
    machine = await _machine(db, team.project, str(team.alice_id))
    machine.attrs = {
        **machine.attrs,
        "devices": [
            {
                "device_ref": DEVICE_REF,
                "identity_basis": "serial",
                "headline": "",
                "last_seen": "2026-11-15T10:00:01+00:00",
                "present": True,
                "state": "inspecting",
            }
        ],
    }
    await db.commit()
    hub, local = LiveHub(), _Local()
    _reader(hub, team.project, str(team.alice_id))

    await _plugged(app, hub, local)

    assert len(local.asked) == 1 and await _states(app, team.project) == {DEVICE_REF: "inspected"}


async def test_a_device_dismissed_while_its_inspection_waits_is_never_opened(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
    host: list[str | None],
) -> None:
    """One device is listened to at a time, so an arrival can wait tens of seconds behind
    another: a "Not now" said in that wait holds. Nothing is opened, the `inspecting` it waited
    under is cleared and the readers are told, so the row never reads "Identifying" again."""
    team = await _owned(client, alice_headers, bob_headers, db)
    hub, local = LiveHub(), _Local()
    mine = _reader(hub, team.project, str(team.alice_id))
    watcher = DeviceWatcher(hub, local, sessions=app.state.sessionmaker)

    async with watcher._listening:  # an earlier arrival is being listened to
        await watcher._tick()
        said = await client.post(
            team.url("hardware", "devices", "dismissals"),
            json={"device_ref": DEVICE_REF},
            headers=alice_headers,
        )
        assert said.status_code == 200, said.text
    await watcher.settled()

    assert local.asked == []
    assert INSPECTIONS.latest(team.project_id, team.alice_id, DEVICE_REF) is None
    assert await _states(app, team.project) == {DEVICE_REF: None}
    assert _heard(mine)[-1] == [None]
    assert team.project_id not in watcher._told  # the next tick tells this project again


def test_a_machines_owner_is_its_exact_stored_id_or_nobody() -> None:
    """`read_scope.owns_machine` compares the stored string exactly: the watcher inspects for,
    and reads the "Not now" list of, that same person and no near-spelling of them."""
    owner = uuid.uuid4()
    assert machine_owner({"owner_user_id": str(owner)}) == owner
    for stored in (str(owner).upper(), owner.hex, f"{{{owner}}}", None, 7):
        assert machine_owner({"owner_user_id": stored}) is None, stored
        assert owns_machine({"owner_user_id": stored}, owner) is False
    row = {"device_ref": DEVICE_REF, "present": True}
    machine = {"owner_user_id": str(owner), "devices": [row]}
    context = DeviceContext(machine, {})
    assert arrivals(machine, context, ()) == [DEVICE_REF]
    assert arrivals({**machine, "dismissed": {str(owner): [DEVICE_REF]}}, context, ()) == []
    # A list filed under another spelling of the id is not the owner's.
    assert arrivals({**machine, "dismissed": {str(owner).upper(): [DEVICE_REF]}}, context, ()) == [
        DEVICE_REF
    ]


async def test_a_device_that_left_and_came_back_mid_inspection_is_inspected_afresh(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
    host: list[str | None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """What was heard before the replug is not what is plugged in now: its result is never
    stamped onto the new arrival, which gets its own inspection at the next tick."""
    team = await _owned(client, alice_headers, bob_headers, db)
    heard, gate = [0], asyncio.Event()

    async def slow(*args: Any, **kwargs: Any) -> None:
        heard[0] += 1
        await gate.wait()

    monkeypatch.setattr(inspections, "inspect_device", slow)
    hub, local = LiveHub(), _Local()
    _reader(hub, team.project, str(team.alice_id))
    watcher = DeviceWatcher(hub, local, sessions=app.state.sessionmaker)
    await watcher._tick()
    local.devices = []
    await watcher._tick()
    local.devices = [_wire_device()]
    await watcher._tick()

    gate.set()
    await watcher.settled()

    assert heard == [1] and await _states(app, team.project) == {DEVICE_REF: None}
    await _tick(watcher)
    assert heard == [2] and await _states(app, team.project) == {DEVICE_REF: "inspected"}


async def test_an_inspection_whose_state_could_not_be_recorded_is_owed_again_at_the_next_tick(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
    host: list[str | None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    team = await _owned(client, alice_headers, bob_headers, db)
    real, failed = device_memory.record_state, [False]

    async def once_broken(*args: Any, **kwargs: Any) -> Any:
        if not failed[0]:
            failed[0] = True
            raise RuntimeError("database went away")
        return await real(*args, **kwargs)

    monkeypatch.setattr(device_watch, "record_state", once_broken)
    hub, local = LiveHub(), _Local()
    _reader(hub, team.project, str(team.alice_id))

    watcher = await _plugged(app, hub, local)
    assert await _states(app, team.project) == {DEVICE_REF: "inspecting"}
    await _tick(watcher)  # the enumeration did not change

    assert len(local.asked) == 2 and await _states(app, team.project) == {DEVICE_REF: "inspected"}


async def test_stopping_the_watcher_ends_a_running_inspection(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
    host: list[str | None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    team = await _owned(client, alice_headers, bob_headers, db)
    started = asyncio.Event()

    async def never(*args: Any, **kwargs: Any) -> Any:
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(inspections, "inspect_device", never)
    hub = LiveHub()
    _reader(hub, team.project, str(team.alice_id))
    watcher = DeviceWatcher(hub, _Local(), sessions=app.state.sessionmaker)
    await watcher._tick()
    await asyncio.wait_for(started.wait(), 5)

    await asyncio.wait_for(watcher.stop(), 5)

    assert await _states(app, team.project) == {DEVICE_REF: "inspecting"}


async def test_the_devices_state_is_its_owners_alone_on_every_read(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
    engine: AsyncEngine,
    host: list[str | None],
) -> None:
    team = await _owned(client, alice_headers, bob_headers, db)
    hub, local = LiveHub(), _Local()
    app.state.bench_local = local
    _reader(hub, team.project, str(team.alice_id))
    await _plugged(app, hub, local)

    async def detected(headers: dict[str, str]) -> list[Any]:
        response = await client.get(team.url("hardware", "detected"), headers=headers)
        assert response.status_code == 200, response.text
        return [row["state"] for row in response.json()["data"]]

    assert await detected(alice_headers) == ["inspected"]
    assert await detected(bob_headers) == [None]
    for headers, shown in ((alice_headers, True), (bob_headers, False)):
        listed = await client.get(team.url("entities"), params={"type": "machine"}, headers=headers)
        assert listed.status_code == 200, listed.text
        assert ("inspected" in listed.text) is shown


# ------------------------------------------------------------------------------- the tool


def _tools(engine: AsyncEngine, team: _Team, user: uuid.UUID, local: Any) -> ToolRegistry:
    registry = ToolRegistry()
    register_hardware_tools(
        registry, _factory(engine), team.project_id, user_id=user, local=local, hub=LiveHub()
    )
    return registry


async def test_inspect_device_answers_the_plug_in_inspection_while_it_is_fresh(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
    engine: AsyncEngine,
    host: list[str | None],
    fresh_store: list[float],
) -> None:
    team = await _owned(client, alice_headers, bob_headers, db)
    hub, local = LiveHub(), _Local()
    _reader(hub, team.project, str(team.alice_id))
    await _plugged(app, hub, local)
    kept = INSPECTIONS.latest(team.project_id, team.alice_id, DEVICE_REF)
    assert kept is not None
    alice = _tools(engine, team, team.alice_id, local)
    call = ToolCall(tool=INSPECT_DEVICE, args={"device_ref": DEVICE_REF})

    local.restarts = True  # the port is not opened again, so nothing restarts: no card
    assert await registry_needs_card(alice, call) is False
    answered = await alice.invoke(call)
    assert answered.ok and answered.value is not None, answered.error
    assert answered.value["inspection_id"] == kept.id and len(local.asked) == 1
    listed = await alice.invoke(ToolCall(tool=LIST_DEVICES, args={}))
    assert listed.value is not None
    assert [row["inspection_id"] for row in listed.value["devices"]] == [kept.id]

    # It is the owner's: a teammate's call listens for itself (here: would restart, so a card).
    bob = _tools(engine, team, _bob(team), local)
    assert await registry_needs_card(bob, call) is True
    local.restarts = False
    theirs = await bob.invoke(call)
    assert theirs.value is not None and theirs.value["inspection_id"] != kept.id
    assert [asked["member"] for asked in local.asked] == [str(team.alice_id), str(_bob(team))]

    # ... and a card tool can stamp it for as long as a card lasts.
    assert INSPECTIONS.get(team.project_id, team.alice_id, kept.id) is not None


async def test_inspect_device_answers_the_plug_in_inspection_once_and_then_listens(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
    engine: AsyncEngine,
    host: list[str | None],
    fresh_store: list[float],
) -> None:
    """ "Check again": the plug-in heard an unpowered bus, the person powers it and asks inside
    the fresh window. Only the first call is answered what the plug-in heard — and told how long
    ago that was; every later call opens the port."""
    team = await _owned(client, alice_headers, bob_headers, db)
    hub, local = LiveHub(), _Local()
    _reader(hub, team.project, str(team.alice_id))
    await _plugged(app, hub, local)
    kept = INSPECTIONS.latest(team.project_id, team.alice_id, DEVICE_REF)
    assert kept is not None
    alice = _tools(engine, team, team.alice_id, local)
    call = ToolCall(tool=INSPECT_DEVICE, args={"device_ref": DEVICE_REF})

    fresh_store[0] += 7
    first = await alice.invoke(call)
    assert first.value is not None and first.value["inspection_id"] == kept.id
    assert first.value["heard_s_ago"] == 7 and len(local.asked) == 1

    local.restarts = True  # the second call would open the port: it is carded like any listen
    assert await registry_needs_card(alice, call) is True
    local.restarts = False
    second = await alice.invoke(call)
    assert second.value is not None and second.value["inspection_id"] != kept.id
    assert "heard_s_ago" not in second.value and len(local.asked) == 2
    third = await alice.invoke(call)  # nor is the tool's own inspection ever answered again
    assert third.value is not None and len(local.asked) == 3
    assert third.value["inspection_id"] not in (kept.id, second.value["inspection_id"])


async def test_a_spent_plug_in_inspection_never_becomes_an_uncarded_restart(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
    engine: AsyncEngine,
    host: list[str | None],
    fresh_store: list[float],
) -> None:
    """The gate saw the plug-in's inspection (no card), then another turn spent it: the call that
    was not carded opens nothing and asks to be called again, which parks the restart card. Only
    the approved, stored call listens, and a model can never say it was approved."""
    team = await _owned(client, alice_headers, bob_headers, db)
    hub, local = LiveHub(), _Local()
    _reader(hub, team.project, str(team.alice_id))
    await _plugged(app, hub, local)
    alice = _tools(engine, team, team.alice_id, local)
    call = ToolCall(tool=INSPECT_DEVICE, args={"device_ref": DEVICE_REF})
    local.restarts = True
    asked = len(local.asked)

    assert await registry_needs_card(alice, call) is False  # the plug-in's answer is waiting
    spent = INSPECTIONS.unasked(
        team.project_id, team.alice_id, DEVICE_REF, within_s=INSPECTION_FRESH_S, take=True
    )
    assert spent is not None
    refused = await alice.invoke(call)

    assert not refused.ok and refused.error is not None
    assert refused.error.code is ToolErrorCode.UNAUTHORIZED and refused.error.retryable
    assert len(local.asked) == asked
    forged = await alice.invoke(
        call.model_copy(update={"args": {**call.args, "restart_approved": True}})
    )
    assert forged.error is not None and forged.error.code is ToolErrorCode.INVALID_ARGS
    assert len(local.asked) == asked

    assert await registry_needs_card(alice, call) is True
    async with _factory(engine)() as session:
        parked = await request_confirmation(
            session,
            alice,
            call,
            project_id=team.project_id,
            team_id=uuid.UUID(team.team),
            user_id=team.alice_id,
            sol_mode=SolMode.EXPERT,
        )
        await session.commit()
    assert parked is not None and parked.confirmation_id is not None and parked.card is not None
    assert len(local.asked) == asked
    async with _factory(engine)() as session:
        approved = await decide_confirmation(
            session,
            alice,
            parked.confirmation_id,
            approve=True,
            project_id=team.project_id,
            user_id=team.alice_id,
        )
    assert approved.ok and approved.value is not None, approved.error
    assert len(local.asked) == asked + 1


async def test_inspect_device_listens_when_the_plug_in_inspection_is_no_longer_fresh(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
    engine: AsyncEngine,
    host: list[str | None],
    fresh_store: list[float],
) -> None:
    team = await _owned(client, alice_headers, bob_headers, db)
    hub, local = LiveHub(), _Local()
    _reader(hub, team.project, str(team.alice_id))
    await _plugged(app, hub, local)
    kept = INSPECTIONS.latest(team.project_id, team.alice_id, DEVICE_REF)
    assert kept is not None

    fresh_store[0] += INSPECTION_FRESH_S + 1
    again = await _tools(engine, team, team.alice_id, local).invoke(
        ToolCall(tool=INSPECT_DEVICE, args={"device_ref": DEVICE_REF})
    )

    assert again.value is not None and again.value["inspection_id"] != kept.id
    assert len(local.asked) == 2


class _TwoCalls:
    """A scripted provider: listen to the device, then offer to add what was found."""

    def __init__(self) -> None:
        self.calls = 0
        self.inspection_id = ""

    async def stream(self, *args: Any, conversation: Any, **kwargs: Any) -> Any:
        self.calls += 1
        if self.calls == 1:
            yield ToolUse(id="tu_1", name=INSPECT_DEVICE, args={"device_ref": DEVICE_REF})
        elif self.calls == 2:
            yield ToolUse(
                id="tu_2",
                name=ADD_PARTS,
                args={
                    "inspection_id": self.inspection_id,
                    "target": {"kind": "new", "name": "Rover arm"},
                },
            )
        else:
            yield "I've put a card up to add the two servos."
        yield Usage(tokens_in=5, tokens_out=2)


async def test_the_first_turn_after_a_notice_reaches_its_first_card_in_two_model_calls(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
    engine: AsyncEngine,
    host: list[str | None],
    no_model: list[str],
) -> None:
    """Plug-in, then the owner's notice turn as the Hardware page sends it (Build, every action
    carded): model call 1 asks for the inspection the plug-in already made — no port opens —
    and model call 2 parks the first card."""
    team = await _owned(client, alice_headers, bob_headers, db)
    hub, local = LiveHub(), _Local()
    _reader(hub, team.project, str(team.alice_id))
    await _plugged(app, hub, local)
    assert no_model == [] and len(local.asked) == 1
    kept = INSPECTIONS.latest(team.project_id, team.alice_id, DEVICE_REF)
    assert kept is not None
    maker = _factory(engine)
    registry = _tools(engine, team, team.alice_id, local)
    model = _TwoCalls()
    model.inspection_id = kept.id
    parked_at: list[tuple[int, ParkedCall]] = []

    async def park(call: ToolCall) -> ParkedCall | None:
        async with maker() as session:
            parked = await request_confirmation(
                session,
                registry,
                call,
                project_id=team.project_id,
                team_id=uuid.UUID(team.team),
                user_id=team.alice_id,
            )
            await session.commit()
        if parked is not None:
            parked_at.append((model.calls, parked))
        return parked

    ctx = AgentRunContext(
        prompt=f"Solus: a device was plugged in: `{DEVICE_REF}`.",
        tools=tuple(registry.list()),
        dispatch=build_mode_dispatch(
            ActionMode.DO, registry.list(), build_dispatch(registry, park), registry=registry
        ),
        systems=FakeSolSystems(),
        project_id=team.project_id,
        user_id=team.alice_id,
        sessionmaker=maker,
        secret_store=InMemorySecretStore(),
        action_mode=ActionMode.DO,
    )
    adapters: Any = {name: model for name in ("anthropic", "openai", "google")}

    events = [event async for event in LlmRunner(adapters=adapters).run(ctx)]

    assert [event.type for event in events if event.type is AgentEventType.ERROR] == []
    results = [event.data for event in events if event.type is AgentEventType.TOOL_RESULT]
    assert results[0]["ok"] and results[0]["value"]["inspection_id"] == kept.id
    ((calls_at_first_card, parked),) = parked_at
    assert calls_at_first_card == 2  # the target: at most two model calls to the first card
    assert parked.card is not None and parked.card["title"] == "Add 2 parts as a new robot"
    assert parked.args["proposal"]["device_ref"] == DEVICE_REF
    assert len(local.asked) == 1  # the turn opened no port: the plug-in's inspection answered
    assert len(no_model) == model.calls  # every model call of the turn went through the gateway
