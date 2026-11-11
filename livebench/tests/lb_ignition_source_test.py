"""SOLUSDEV-322 P3-T5: the ignition family (Fortress) streams exactly like the new family under
`ign` — `ign topic -e -t <t> --json-output` (RECON §2 verified the flag on Fortress 6.16.0)."""

from pathlib import Path

from livebench.sim.gazebo_family import find_exe
from livebench.sim.gazebo_source import GazeboTopicSource
from livebench.sim.ignition_source import IgnitionTopicSource

IGN6 = Path(__file__).resolve().parent / "fixtures" / "bin" / "ign6"
JOINT_TOPIC = "/world/empty/model/twolink/joint_state"


async def test_ignition_source_argv_and_json() -> None:
    exe = find_exe("ignition", env={"SOLUS_GAZEBO_PATH": str(IGN6)})
    source = IgnitionTopicSource([JOINT_TOPIC, "/world/empty/stats"], exe=exe)

    assert exe == IGN6 / "ign"
    assert source.family == "ignition"
    assert isinstance(source, GazeboTopicSource)
    assert source.argv(JOINT_TOPIC) == [
        str(exe), "topic", "-e", "-t", JOINT_TOPIC, "--json-output",
    ]  # fmt: skip

    packets = [p async for p in source]

    joints = [p for p in packets if p.device_id.startswith("empty/twolink/")]
    stats = [p for p in packets if p.device_id == "/world/empty/stats"]
    assert len(joints) == 6 and len(stats) == 1
    assert joints[0].units == {"shoulder.position": "rad", "shoulder.velocity": "rad/s"}
    assert stats[0].values["realTimeFactor"] == 0.996024864764724
