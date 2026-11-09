"""SOLUSDEV-321 P4-T3 — rung 3, electrics: the SPICE transient, run by the pinned circuit simulator
inside its ARQ job only (R86).

No real simulator runs here. A fake executable stands where the binary is pinned: a short Python
script in a private directory, with this interpreter on its first line. It records its argument
list, its working directory, its environment, its limits and the deck it was handed. Then it
writes an ASCII rawfile, sleeps, floods its output or fails, as each test asks.
"""

from __future__ import annotations

import json
import shutil
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Final

import pytest
from solus_api.core.config import Settings
from solus_api.graph import kinds
from solus_api.graph.live import LiveHub
from solus_api.models import GraphEntity
from solus_api.simulation.providers import ngspice_provider
from solus_api.simulation.providers.ngspice_provider import (
    LOG_TAIL_BYTES,
    MAX_OUTPUT_BYTES,
    NgspiceProvider,
    pinned_simulator,
    read_rawfile,
    run_ngspice_sim,
)
from solus_api.simulation.providers.spice_deck import DeckRefusedError, ModelNotFoundError
from solus_api.simulation.sim_capability import (
    MissingInputs,
    SimProvider,
    SimQuestion,
    SimulationFailedError,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from test_sim_facts import _seed

FIXTURES: Final = Path(__file__).parent / "fixtures"
MOTOR: Final = {
    "nodes": ["/M+", "0"],
    "resistance_ohm": 2.5,
    "inductance_h": 0.0012,
    "back_emf_v_per_rad_s": 0.02,
    "speed_rad_s": 300.0,
}
FACTS: Final = {
    "spice_netlist": (FIXTURES / "spice_motor_drive.net").read_text(),
    "spice_probe": {"node": "/M+"},
    "motor": MOTOR,
}
#: What the fake writes: three points of a 12 V drive into the motor. Its current through the
#: back-EMF source peaks at 2.4 A and ends at 2.05 A; the motor terminal dips to 11.2 V.
RAWFILE: Final = """Title: solus rung-3 deck
Date: Wed Oct 28 12:00:00  2026
Plotname: Transient Analysis
Flags: real
No. Variables: 4
No. Points: 3
Variables:
\t0\ttime\ttime
\t1\tv(/m+)\tvoltage
\t2\ti(vsolus_bemf)\tcurrent
\t3\tv1#branch\tcurrent
Values:
 0\t0.000000000000000e+00
\t1.200000000000000e+01
\t0.000000000000000e+00
\t-0.000000000000000e+00
 1\t1.000000000000000e-03
\t1.120000000000000e+01
\t2.400000000000000e+00
\t-2.400000000000000e+00
 2\t2.000000000000000e-03
\t1.155000000000000e+01
\t2.050000000000000e+00
\t-2.050000000000000e+00
"""
FAKE: Final = """#!{python}
import json, os, resource, shutil, sys, time
args = sys.argv[1:]
deck = open(args[-1]).read()
limits = {{n: list(resource.getrlimit(getattr(resource, n))) for n in {limits!r}}}
record = {{"argv": sys.argv, "cwd": os.getcwd(), "env": dict(os.environ), "limits": limits,
          "listing": sorted(os.listdir(".")), "deck": deck}}
json.dump(record, open({record!r}, "w"))
mode = {mode!r}
if mode == "sleep":
    time.sleep(60)
if mode == "flood":
    sys.stdout.write("x" * (4 * 1024 * 1024))
    sys.stdout.flush()
if mode == "fail":
    open(args[args.index("-o") + 1], "w").write("Error: \\x1b[31mjunk\\x07 " * 5000)
    sys.exit(3)
shutil.copy({raw!r}, args[args.index("-r") + 1])
"""


def _fake(directory: Path, mode: str = "ok", raw: str = RAWFILE) -> Path:
    """A stand-in simulator in `directory`: it records what it was given in `record.json`."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "canned.raw").write_text(raw)
    script = directory / "sim"
    script.write_text(
        FAKE.format(
            python=sys.executable,
            limits=("RLIMIT_CPU", "RLIMIT_AS", "RLIMIT_FSIZE", "RLIMIT_CORE"),
            record=str(directory / "record.json"),
            mode=mode,
            raw=str(directory / "canned.raw"),
        )
    )
    script.chmod(0o755)
    return script


def _record(fake: Path) -> dict[str, Any]:
    record: dict[str, Any] = json.loads((fake.parent / "record.json").read_text())
    return record


def _run(binary: Path | None, facts: dict[str, Any] = FACTS) -> Any:
    provider = NgspiceProvider(binary)
    return provider.run(provider.inputs_for(facts))


def _settings(binary: Path | None) -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        supabase_jwt_secret="dummy",
        database_url="sqlite+aiosqlite://",
        ngspice_bin=binary,
    )


def _request(project: uuid.UUID, subject: uuid.UUID, facts: dict[str, Any]) -> dict[str, Any]:
    return {"project_id": str(project), "subject_id": str(subject), "facts": facts}


def _question(quantity: str, facts: dict[str, Any]) -> SimQuestion:
    return SimQuestion(subject_id=uuid.uuid4(), quantity=quantity, facts=facts)


@pytest.mark.parametrize(
    "pinned", ["unset", "relative", "missing", "a-directory", "not-executable"]
)
async def test_unpinned_or_absent_binary_reports_unavailable(
    pinned: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine: AsyncEngine
) -> None:
    def looked_up(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("the binary is pinned by a setting, never looked up on PATH")

    monkeypatch.setattr(shutil, "which", looked_up)
    plain = tmp_path / "plain"
    plain.write_text("not a program")
    binary = {
        "unset": None,
        "relative": Path("bin/sim"),
        "missing": tmp_path / "missing",
        "a-directory": tmp_path,
        "not-executable": plain,
    }[pinned]
    provider = NgspiceProvider(binary)
    assert pinned_simulator(binary) is None
    assert provider.available is False
    with pytest.raises(SimulationFailedError, match="not available on this machine"):
        _run(binary)
    # the job says so too, before anything runs; a subject no project holds is flagged nowhere
    ctx = {
        "settings": _settings(binary),
        "sessionmaker": async_sessionmaker(engine, expire_on_commit=False),
        "graph_hub": LiveHub(),
    }
    status = await run_ngspice_sim(ctx, _request(uuid.uuid4(), uuid.uuid4(), FACTS))
    assert status == {
        "status": "not_available",
        "reason": "spice_transient is not available on this machine",
    }


async def _not_available_findings(session: AsyncSession) -> list[GraphEntity]:
    return list(
        await session.scalars(
            select(GraphEntity).where(
                GraphEntity.kind == kinds.FINDING,
                GraphEntity.attrs["rule_id"].astext == "simulation_not_available",
            )
        )
    )


async def test_a_job_without_its_simulator_leaves_a_finding_on_the_subject(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    """M140: the queue keeps no result, so a worker without the pinned simulator would leave
    nothing a person sees. The job raises one standing info on the subject, naming the provider
    and why it did not run; another run of it counts on the same finding, and nothing ran."""
    project_id, part_id = await _seed(db, name="drive")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    ctx = {"settings": _settings(None), "sessionmaker": sessions, "graph_hub": LiveHub()}

    for _ in range(2):
        status = await run_ngspice_sim(ctx, _request(project_id, part_id, FACTS))
        assert status["status"] == "not_available"

    async with sessions() as read:
        (flagged,) = await _not_available_findings(read)
        assert await _counted(read) == 0
    attrs = flagged.attrs
    assert (attrs["severity"], attrs["source"], attrs["subjects"]) == (
        "info",
        "simulation",
        [str(part_id)],
    )
    assert attrs["headline"] == (
        "could not simulate on the worker: spice_transient is not available on this machine"
    )
    said = {key: attrs["evidence"][key] for key in ("provider", "rung", "reason")}
    assert said == {
        "provider": "spice_transient",
        "rung": 3,
        "reason": "spice_transient is not available on this machine",
    }
    assert attrs["count"] == 2 and flagged.domain == "electrical"


def test_runs_the_pinned_binary_with_a_fixed_argv_in_a_private_cwd(tmp_path: Path) -> None:
    fake = _fake(tmp_path / "bin")
    # the pin may be a link: what runs is the file it resolves to
    link = tmp_path / "pinned"
    link.symlink_to(fake)
    result = _run(link)
    record = _record(fake)
    assert record["argv"] == [
        str(fake.resolve()),
        "-b",
        "-n",
        "-r",
        "out.raw",
        "-o",
        "out.log",
        "deck.cir",
    ]
    cwd = Path(record["cwd"])
    assert cwd.name.startswith("solus-spice-") and not cwd.exists()
    assert record["env"] == {"HOME": str(cwd), "SPICE_ASCIIRAWFILE": "1", "LC_ALL": "C"}
    # Solus wrote the deck into the private directory, and no init file is beside it
    assert record["listing"] == ["deck.cir", "stderr.txt", "stdout.txt"]
    deck = record["deck"].splitlines()
    assert deck[0] == "solus rung-3 deck"
    assert deck[-2:] == [".tran 1e-05 0.02 uic", ".end"]
    assert ".include" not in record["deck"] and ".tran 10u 20m" not in record["deck"]
    assert ".model d_generic D(is=1e-14 n=1 rs=0.1)" in deck
    # the values are read back from the rawfile the run wrote
    assert result.values["peak_current_a"].value == pytest.approx(2.4)
    assert result.values["final_current_a"].value == pytest.approx(2.05)
    assert result.values["min_node_voltage_v"].value == pytest.approx(11.2)
    assert result.values["peak_current_a"].unit == "A"
    assert result.values["min_node_voltage_v"].unit == "V"
    assert result.provenance.solver == "spice_transient"


def test_the_motor_is_r_l_and_a_back_emf_derived_from_the_speed(tmp_path: Path) -> None:
    fake = _fake(tmp_path)
    result = _run(fake)
    deck = _record(fake)["deck"].splitlines()
    # 0.02 V s/rad at 300 rad/s is a 6 V back-EMF, in series with 2.5 ohm and 1.2 mH
    assert deck[-5:-2] == [
        "Rsolus_motor /M+ solus_motor_l 2.5",
        "Lsolus_motor solus_motor_l solus_motor_e 0.0012",
        "Vsolus_bemf solus_motor_e 0 DC 6",
    ]
    inputs = result.provenance.inputs
    assert (inputs["back_emf_v"].value, inputs["back_emf_v"].source) == (6.0, "derived")
    assert inputs["motor"].source == "known"
    assert inputs["spice_analysis"].value == {"step_s": 1e-5, "stop_s": 0.02}
    assert inputs["spice_analysis"].source == "assumed"
    assert inputs["spice_netlist"].value == {
        "cards": 5,
        "dropped": [
            {"line": 1, "directive": ".title"},
            {"line": 2, "directive": ".include"},
            {"line": 3, "directive": ".tran"},
            {"line": 11, "directive": ".end"},
        ],
        "dropped_count": 4,
    }
    assert any("constant speed" in line for line in result.provenance.leaves_out)
    # a stated source is measured instead of the motor; a stated window replaces the default
    window = {**FACTS, "spice_probe": {"node": "/M+", "source": "V1"}}
    window["spice_analysis"] = {"step_s": 1e-6, "stop_s": 0.01}
    stated = _run(fake, window)
    assert stated.values["peak_current_a"].value == pytest.approx(2.4)
    assert _record(fake)["deck"].splitlines()[-2] == ".tran 1e-06 0.01 uic"
    assert stated.provenance.inputs["spice_analysis"].source == "known"


def test_the_child_runs_under_limits_and_a_wall_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _fake(tmp_path / "ok")
    _run(fake)
    limits = _record(fake)["limits"]
    assert limits["RLIMIT_CPU"][1] <= 20
    assert limits["RLIMIT_AS"][1] <= 2 * 1024**3
    assert limits["RLIMIT_FSIZE"] == [MAX_OUTPUT_BYTES, MAX_OUTPUT_BYTES]
    # review Minor 3: a child killed at a cap (SIGXCPU, SIGXFSZ) dumps no core, file or piped
    assert limits["RLIMIT_CORE"] == [0, 0]
    monkeypatch.setattr(ngspice_provider, "WALL_SECONDS", 1)
    sleeper = _fake(tmp_path / "sleep", mode="sleep")
    started = time.monotonic()
    with pytest.raises(SimulationFailedError, match="ran past 1 s"):
        _run(sleeper)
    assert time.monotonic() - started < 15
    assert not Path(_record(sleeper)["cwd"]).exists()


def test_output_past_its_cap_ends_the_run_and_never_reaches_a_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ngspice_provider, "MAX_OUTPUT_BYTES", 64 * 1024)
    flood = _fake(tmp_path, mode="flood")
    with pytest.raises(SimulationFailedError) as failed:
        _run(flood)
    assert _record(flood)["limits"]["RLIMIT_FSIZE"] == [64 * 1024, 64 * 1024]
    assert len(str(failed.value)) <= LOG_TAIL_BYTES + 64


def test_a_failed_run_reports_a_bounded_printable_tail(tmp_path: Path) -> None:
    with pytest.raises(SimulationFailedError) as failed:
        _run(_fake(tmp_path, mode="fail"))
    reason = str(failed.value)
    assert reason.startswith("the simulator exited 3: ")
    assert len(reason) <= LOG_TAIL_BYTES + 64
    assert reason.isprintable() and "\x1b" not in reason and "\x07" not in reason


def test_a_hostile_export_or_an_unknown_model_is_refused_before_anything_runs(
    tmp_path: Path,
) -> None:
    fake = _fake(tmp_path)
    red_team = {**FACTS, "spice_netlist": (FIXTURES / "spice_red_team.net").read_text()}
    with pytest.raises(DeckRefusedError, match="line 3: `.control` is refused"):
        _run(fake, red_team)
    unknown = {**FACTS, "spice_netlist": "V1 /M+ 0 DC 12\nD1 0 /M+ 1N4148\n"}
    with pytest.raises(ModelNotFoundError, match="model `1n4148` not found"):
        _run(fake, unknown)
    assert not (tmp_path / "record.json").exists()


@pytest.mark.parametrize(
    ("change", "why"),
    [
        pytest.param({"Values:": "Binary:"}, "not an ASCII rawfile", id="binary"),
        pytest.param({"Flags: real": "Flags: complex"}, "not real-valued", id="complex"),
        pytest.param({"No. Points: 3": "No. Points: 4"}, "values", id="points-past-the-data"),
        pytest.param({"1.155": "nan15"}, "values", id="not-a-number"),
        pytest.param({"No. Points: 3": "No. Points: 100002"}, "header", id="too-many-points"),
        pytest.param({"No. Variables: 4": "No. Variables: 513"}, "header", id="too-many-vectors"),
    ],
)
def test_the_rawfile_is_read_through_bounds(
    tmp_path: Path, change: dict[str, str], why: str
) -> None:
    text = RAWFILE
    for old, new in change.items():
        text = text.replace(old, new)
    raw = tmp_path / "out.raw"
    raw.write_text(text)
    with pytest.raises(SimulationFailedError, match=why):
        read_rawfile(raw)


def test_the_rawfile_names_voltages_and_currents_either_way(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = tmp_path / "out.raw"
    raw.write_text(RAWFILE)
    vectors = read_rawfile(raw)
    assert set(vectors) == {("t", "time"), ("v", "/m+"), ("i", "vsolus_bemf"), ("i", "v1")}
    assert vectors[("i", "v1")].tolist() == [-0.0, -2.4, -2.05]
    # a file past the byte bound is refused before it is parsed
    monkeypatch.setattr(ngspice_provider, "MAX_OUTPUT_BYTES", 64)
    with pytest.raises(SimulationFailedError, match="past its bound"):
        read_rawfile(raw)


def test_can_answer_names_what_a_question_lacks() -> None:
    provider: SimProvider = NgspiceProvider(None)
    assert (provider.name, provider.domain, provider.rung) == ("spice_transient", "electrical", 3)
    assert provider.quantities == {"peak_current_a", "final_current_a", "min_node_voltage_v"}
    every = ("final_current_a", "min_node_voltage_v", "peak_current_a")
    assert provider.can_answer(_question("peak_current_a", FACTS)) == MissingInputs(covered=every)
    assert provider.can_answer(_question("peak_current_a", {})).names == (
        "spice_netlist",
        "spice_probe",
    )
    unprobed = {key: value for key, value in FACTS.items() if key != "spice_probe"}
    # the motor's current needs no probe; a voltage needs the probe's node
    assert provider.can_answer(_question("peak_current_a", unprobed)).names == ()
    lacks = provider.can_answer(_question("min_node_voltage_v", unprobed))
    assert lacks.names == ("spice_probe",)
    assert lacks.covered == ("final_current_a", "peak_current_a")
    for broken, name in (
        ({**FACTS, "motor": {**MOTOR, "inductance_h": 0}}, "motor"),
        ({**FACTS, "motor": {**MOTOR, "nodes": ["/M+", "solus_motor_l"]}}, "motor"),
        ({**FACTS, "spice_analysis": {"step_s": 1.0, "stop_s": 2.0}}, "spice_analysis"),
        ({**FACTS, "spice_probe": {"node": "/M+", "source": "R1"}}, "spice_probe"),
        ({**FACTS, "spice_netlist": ""}, "spice_netlist"),
    ):
        assert name in provider.can_answer(_question("peak_current_a", broken)).names
    with pytest.raises(ValueError, match="does not compute"):
        provider.can_answer(_question("mass_kg", FACTS))
    # only the facts it reads travel to a run
    assert set(NgspiceProvider(None).inputs_for({**FACTS, "colour": "red"})) == {
        "spice_netlist",
        "spice_probe",
        "motor",
    }


def _counted(session: AsyncSession) -> Any:
    return session.scalar(
        select(func.count()).select_from(GraphEntity).where(GraphEntity.kind == kinds.SIM_RESULT)
    )


async def test_the_job_records_the_run_and_reports_a_refusal(
    db: AsyncSession, engine: AsyncEngine, tmp_path: Path
) -> None:
    project_id, part_id = await _seed(db, name="drive")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    ctx = {"settings": _settings(_fake(tmp_path)), "sessionmaker": sessions, "graph_hub": LiveHub()}
    status = await run_ngspice_sim(ctx, _request(project_id, part_id, FACTS))
    assert status["status"] == "recorded"
    async with sessions() as read:
        row = await read.get(GraphEntity, uuid.UUID(str(status["sim_result_id"])))
        assert row is not None and row.kind == kinds.SIM_RESULT
        assert row.attrs["rung"] == 3
        assert row.attrs["values"]["peak_current_a"] == {"value": 2.4, "unit": "A"}
        assert row.attrs["provenance"]["solver"] == "spice_transient"
    red_team = {**FACTS, "spice_netlist": (FIXTURES / "spice_red_team.net").read_text()}
    refused = await run_ngspice_sim(ctx, _request(project_id, part_id, red_team))
    assert refused["status"] == "refused"
    assert "line 3: `.control` is refused" in str(refused["reason"])
    async with sessions() as read:
        assert await _counted(read) == 1
    # a subject the project does not hold is never written
    foreign = await run_ngspice_sim(ctx, _request(project_id, uuid.uuid4(), FACTS))
    assert foreign == {"status": "failed", "reason": "not recorded: not_found"}
    # a malformed request is the enqueuer's bug and raises
    with pytest.raises(ValueError, match="facts"):
        await run_ngspice_sim(ctx, {**_request(project_id, part_id, FACTS), "facts": "text"})
