"""`wrap_model`: gz/ignition get an SDF model carrying the joint-state publisher and one
position controller per joint (topics `/model/<name>/joint/<j>/0/cmd_pos`); classic gets the
URDF as-is (`gz model -f` accepts URDF). Conversion runs the family's `sdf -p` as argv."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path

import pytest

from integrations.mcp.gazebo.solus.adapters.adapter_base import CliError, Completed, run_argv
from integrations.mcp.gazebo.solus.family_detect import Family
from integrations.mcp.gazebo.solus.spawn import wrap_model

URDF = b'<?xml version="1.0"?>\n<robot name="twolink"><link name="base"/></robot>\n'


def _recording() -> tuple[list[list[str]], Callable[[list[str], float], Completed]]:
    calls: list[list[str]] = []

    def run(argv: list[str], timeout: float) -> Completed:
        calls.append(list(argv))
        assert Path(argv[-1]).is_file(), "the URDF must be on disk while sdf -p runs"
        return run_argv(argv, timeout)

    return calls, run


@pytest.mark.parametrize(
    ("fixture", "sdf_version", "state_plugin", "controller_plugin", "namespace"),
    [
        (
            "gz8",
            "1.11",
            "gz-sim-joint-state-publisher-system",
            "gz-sim-joint-position-controller-system",
            "gz::sim::systems",
        ),
        (
            "ign6",
            "1.9",
            "ignition-gazebo-joint-state-publisher-system",
            "ignition-gazebo-joint-position-controller-system",
            "ignition::gazebo::systems",
        ),
    ],
)
def test_spawn_wrap_adds_state_publisher_and_one_controller_per_joint(
    fixture_family: Callable[[str], Family],
    fixture: str,
    sdf_version: str,
    state_plugin: str,
    controller_plugin: str,
    namespace: str,
) -> None:
    family = fixture_family(fixture)
    calls, run = _recording()
    out = wrap_model(URDF, family, ["shoulder", "elbow"], "arm1", run=run)
    assert len(calls) == 1
    assert calls[0][:3] == [str(family.exe), "sdf", "-p"] and len(calls[0]) == 4
    assert not Path(calls[0][3]).exists(), "the temporary URDF is removed"
    root = ET.fromstring(out)
    assert root.tag == "sdf" and root.get("version") == sdf_version
    model = root.find("model")
    assert model is not None and model.get("name") == "arm1"
    plugins = model.findall("plugin")
    states = [p for p in plugins if p.get("filename") == state_plugin]
    assert len(states) == 1 and states[0].get("name") == f"{namespace}::JointStatePublisher"
    controllers = [p for p in plugins if p.get("filename") == controller_plugin]
    assert [c.get("name") for c in controllers] == [f"{namespace}::JointPositionController"] * 2
    assert [c.findtext("joint_name") for c in controllers] == ["shoulder", "elbow"]
    assert [c.findtext("topic") for c in controllers] == [
        "/model/arm1/joint/shoulder/0/cmd_pos",
        "/model/arm1/joint/elbow/0/cmd_pos",
    ]
    assert all(c.findtext("p_gain") for c in controllers)
    assert [j.get("name") for j in model.findall("joint")] == ["shoulder", "elbow"]


def test_spawn_wrap_classic_passes_urdf_through(fixture_family: Callable[[str], Family]) -> None:
    calls, run = _recording()
    assert wrap_model(URDF, fixture_family("classic11"), ["shoulder"], "arm1", run=run) == URDF
    assert calls == []


def test_spawn_wrap_accepts_sdf_input_without_conversion(
    fixture_family: Callable[[str], Family],
) -> None:
    sdf = (
        b"<sdf version='1.9'><model name='x'><link name='base'/>"
        b"<joint name='j' type='revolute'><parent>base</parent><child>tip</child></joint>"
        b"<link name='tip'/></model></sdf>"
    )
    calls, run = _recording()
    out = wrap_model(sdf, fixture_family("gz8"), ["j"], "renamed", run=run)
    assert calls == []
    model = ET.fromstring(out).find("model")
    assert model is not None and model.get("name") == "renamed"
    assert [c.findtext("topic") for c in model.findall("plugin") if c.findtext("topic")] == [
        "/model/renamed/joint/j/0/cmd_pos"
    ]


@pytest.mark.parametrize(
    ("data", "joints", "name"),
    [
        (b"<!DOCTYPE robot [<!ENTITY x 'y'>]><robot/>", ["shoulder"], "arm1"),
        (URDF, ["--pos-t"], "arm1"),
        (URDF, ["shoulder"], "-x"),
        (URDF, ["shoulder"], 'a"b'),
        (URDF, ["wrist"], "arm1"),  # not a joint of the converted model
        (b"just text", ["shoulder"], "arm1"),
        (b"<sdf version='1.9'><world name='w'/></sdf>", ["shoulder"], "arm1"),  # no <model>
    ],
)
def test_spawn_wrap_refuses_hostile_or_mismatched_input(
    fixture_family: Callable[[str], Family], data: bytes, joints: list[str], name: str
) -> None:
    calls, run = _recording()
    with pytest.raises(ValueError):
        wrap_model(data, fixture_family("gz8"), joints, name, run=run)
    assert all(c[1:3] == ["sdf", "-p"] for c in calls)


def test_spawn_wrap_bounds_input_size(fixture_family: Callable[[str], Family]) -> None:
    calls, run = _recording()
    with pytest.raises(ValueError):
        wrap_model(
            b"<robot>" + b" " * (4 * 1024 * 1024 + 1), fixture_family("gz8"), ["j"], "a", run=run
        )
    assert calls == []


def test_spawn_conversion_failure_never_leaks_the_private_temp_path(
    fixture_family: Callable[[str], Family],
) -> None:
    def failing(argv: list[str], timeout: float) -> Completed:
        return Completed(tuple(argv), 255, "", f"Error: File [{argv[-1]}] does not exist.\n")

    with pytest.raises(CliError) as excinfo:
        wrap_model(URDF, fixture_family("gz8"), ["shoulder"], "arm1", run=failing)
    assert "/" not in excinfo.value.reason and "model.urdf" in excinfo.value.reason


_SDF_HEAD = b"<sdf version='1.9'><model name='x'><link name='base'/>"
_SDF_JOINT = (
    b"<joint name='j' type='revolute'><parent>base</parent><child>tip</child></joint>"
    b"<link name='tip'/>"
)


def test_wrap_refuses_plugin_element_gz(fixture_family: Callable[[str], Family]) -> None:
    sdf = _SDF_HEAD + _SDF_JOINT + b"<plugin filename='/tmp/evil.so' name='x'/></model></sdf>"
    calls, run = _recording()
    with pytest.raises(ValueError, match="plugin"):
        wrap_model(sdf, fixture_family("gz8"), ["j"], "arm1", run=run)
    assert calls == []


def test_wrap_refuses_plugin_in_urdf_gazebo_tag_classic(
    fixture_family: Callable[[str], Family],
) -> None:
    urdf = (
        b'<robot name="r"><link name="base"/>'
        b'<gazebo><plugin filename="/tmp/evil.so" name="x"/></gazebo></robot>'
    )
    calls, run = _recording()
    with pytest.raises(ValueError):
        wrap_model(urdf, fixture_family("classic11"), ["shoulder"], "arm1", run=run)
    assert calls == []


@pytest.mark.parametrize(
    "body",
    [
        b"<include><uri>file:///etc</uri></include>",
        b"<include><uri>model://evil</uri></include>",
        b"<link name='l'><visual name='v'><geometry><mesh><uri>/etc/passwd</uri></mesh>"
        b"</geometry></visual></link>",
        b"<link name='l'><visual name='v'><geometry><mesh><uri>../../x.stl</uri></mesh>"
        b"</geometry></visual></link>",
        b"<link name='l'><visual name='v'><geometry><mesh><uri>package://x/a.stl</uri></mesh>"
        b"</geometry></visual></link>",
        b"<link name='l'><visual name='v'><material><script><uri>a</uri></script></material>"
        b"</visual></link>",
        b"<transmission name='t'/>",
        b"<extension/>",
        b"<gazebo/>",
        b"<x:plugin xmlns:x='urn:evil' filename='/tmp/evil.so'/>",
        b"<link name='l' x:href='urn:e' xmlns:x='urn:evil'/>",
        b"<link name='/abs'/>",
        b"<frame name='f' attached_to='..'/>",
    ],
)
def test_wrap_refuses_include_and_uri(fixture_family: Callable[[str], Family], body: bytes) -> None:
    sdf = _SDF_HEAD + _SDF_JOINT + body + b"</model></sdf>"
    calls, run = _recording()
    with pytest.raises(ValueError):
        wrap_model(sdf, fixture_family("gz8"), ["j"], "arm1", run=run)
    assert calls == []


def test_wrap_allows_relative_mesh_uri(fixture_family: Callable[[str], Family]) -> None:
    sdf = (
        _SDF_HEAD
        + _SDF_JOINT
        + b"<link name='l'><visual name='v'><geometry><mesh><uri>meshes/arm.stl</uri></mesh>"
        b"</geometry></visual></link></model></sdf>"
    )
    calls, run = _recording()
    out = wrap_model(sdf, fixture_family("gz8"), ["j"], "arm1", run=run)
    assert ET.fromstring(out).find("model") is not None


_URDF_PLUGIN = (
    b'<robot name="r"><link name="base"/>'
    b'<gazebo><plugin filename="/tmp/evil.so" name="x"/></gazebo></robot>'
)


def test_wrap_refuses_urdf_gazebo_tag_before_conversion_gz(
    fixture_family: Callable[[str], Family],
) -> None:
    calls, run = _recording()
    with pytest.raises(ValueError):
        wrap_model(_URDF_PLUGIN, fixture_family("gz8"), ["shoulder"], "arm1", run=run)
    assert calls == [], "a hostile URDF never reaches the converter"


@pytest.mark.parametrize(
    "stdout",
    [
        "<sdf version='1.9'><model name='t'><joint name='shoulder' type='revolute'/>"
        "<plugin filename='/tmp/evil.so' name='x'/></model></sdf>",
        "<sdf version='1.9'><model name='t'><joint name='shoulder' type='revolute'/>"
        "<include><uri>file:///etc</uri></include></model></sdf>",
        "<sdf><!DOCTYPE sdf [<!ENTITY x 'y'>]><model name='t'/></sdf>",
        "<sdf version='1.9'><model name='t'>" + " " * (4 * 1024 * 1024) + "</model></sdf>",
    ],
)
def test_wrap_rechecks_converter_output(
    fixture_family: Callable[[str], Family], stdout: str
) -> None:
    def hostile(argv: list[str], timeout: float) -> Completed:
        return Completed(tuple(argv), 0, stdout, "")

    with pytest.raises(ValueError):
        wrap_model(URDF, fixture_family("gz8"), ["shoulder"], "arm1", run=hostile)
