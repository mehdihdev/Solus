"""SOLUSDEV-322 P1-T2 — `services/machine_simulators.py`: the simulator facts derived from the
machine's redacted `tool_versions` lines, stored beside the raw map as `attrs.simulators`.

Nothing is guessed: a family is named only from the binary that printed its version, and an
absent binary yields None / False, never a default.
"""

from __future__ import annotations

import uuid

from solus_api.models import Project, Team, User
from solus_api.services.machine_simulators import derive_simulators
from solus_api.services.machines import MachineIn, upsert_machine
from sqlalchemy.ext.asyncio import AsyncSession

CLASSIC = "Gazebo multi-robot simulator, version 11.14.0"
COMPANION = "0123456789abcdef0123456789abcdef"


def test_derive_gazebo_new_family_from_gz_sim_versions() -> None:
    # `gz sim --versions` on Harmonic prints the bare simulator version.
    assert derive_simulators({"gz": "8.15.0"})["gazebo"] == {"family": "gz", "version": "8.15.0"}


def test_derive_ignition_from_ign() -> None:
    assert derive_simulators({"ign": "6.16.0"})["gazebo"] == {
        "family": "ignition",
        "version": "6.16.0",
    }


def test_derive_classic_from_gzserver_or_classic_gz_line() -> None:
    for raw in ({"gzserver": CLASSIC}, {"gz": CLASSIC}, {"gazebo": CLASSIC}):
        assert derive_simulators(raw)["gazebo"] == {"family": "classic", "version": "11.14.0"}
    # Two families installed: the newest one is the fact; the other is not lost but not named.
    both = derive_simulators({"gz": "8.15.0", "gzserver": CLASSIC})
    assert both["gazebo"] == {"family": "gz", "version": "8.15.0"}


def test_nothing_detected_is_none_not_guessed() -> None:
    assert derive_simulators({"python3": "Python 3.12.3"}) == {
        "gazebo": None,
        "nvidia_smi": False,
        "ngspice": None,
    }
    assert derive_simulators({}) == {"gazebo": None, "nvidia_smi": False, "ngspice": None}
    derived = derive_simulators(
        {
            "nvidia-smi": "NVIDIA-SMI version  : 550.54.14",
            "ngspice": "** ngspice-42 : Circuit level simulation program",
        }
    )
    assert derived["nvidia_smi"] is True
    assert derived["ngspice"] == "42"
    assert derived["gazebo"] is None


async def _project_and_user(db: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    team = Team(name="sim-derive")
    db.add(team)
    await db.flush()
    project = Project(team_id=team.id, name="sim-derive")
    user = User(supabase_user_id=uuid.uuid4().hex, email="derive@example.com")
    db.add_all([project, user])
    await db.commit()
    return project.id, user.id


async def test_upsert_machine_stores_derived_simulators(db: AsyncSession) -> None:
    project_id, user_id = await _project_and_user(db)
    body = MachineIn(hostname="bench", os="Linux", arch="x86_64")

    machine = await upsert_machine(
        db, project_id, user_id, COMPANION, body, tool_versions={"gz": "8.15.0", "nvidia-smi": "x"}
    )
    assert machine.attrs["simulators"] == {
        "gazebo": {"family": "gz", "version": "8.15.0"},
        "nvidia_smi": True,
        "ngspice": None,
    }
    # None keeps the last report, derived facts included; an answer with no simulator binaries
    # replaces them with honest nothing.
    kept = await upsert_machine(db, project_id, user_id, COMPANION, body, tool_versions=None)
    assert kept.attrs["simulators"]["gazebo"] == {"family": "gz", "version": "8.15.0"}
    gone = await upsert_machine(db, project_id, user_id, COMPANION, body, tool_versions={})
    assert gone.attrs["simulators"] == {"gazebo": None, "nvidia_smi": False, "ngspice": None}
