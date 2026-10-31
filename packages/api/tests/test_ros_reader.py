"""SOLUSDEV-321 P6 — `software/ros_reader.py`: a ROS workspace's nodes and topics read from its
package texts, never run (`tests/fixtures/ros2_ws/`, `tests/fixtures/plain_repo/`).

The fixture is a colcon workspace with two Python packages: `talker_py`, started from a Python
launch file in the `robot` namespace, publishes `chatter`; `listener_py`, started from an XML launch
file that remaps `chatter` to `/robot/chatter`, subscribes to it. Both name `std_msgs/msg/String`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest
from solus_api.software import ros_reader
from solus_api.software.ros_reader import (
    MAX_YAML_BYTES,
    RosNode,
    RosPackageSources,
    RosSourceFile,
    RosTopic,
    RosWorkspace,
    parse_ros_workspace,
)

FIXTURES: Final = Path(__file__).resolve().parent / "fixtures"


def fixture_sources(root: Path) -> list[RosPackageSources]:
    """`root`'s packages as a connector hands them over: each `package.xml`, and the files beneath
    its directory with their folder-relative paths."""
    found: list[RosPackageSources] = []
    for manifest in sorted(root.rglob("package.xml")):
        files = tuple(
            RosSourceFile(path.relative_to(root).as_posix(), path.read_text())
            for path in sorted(manifest.parent.rglob("*"))
            if path.is_file() and path.name != "package.xml"
        )
        found.append(
            RosPackageSources(
                RosSourceFile(manifest.relative_to(root).as_posix(), manifest.read_text()), files
            )
        )
    return found


def _first_line_with(path: Path, needle: str) -> int:
    return next(i for i, line in enumerate(path.read_text().splitlines(), 1) if needle in line)


def _demo_package(*files: tuple[str, str], name: str = "demo_pkg") -> RosPackageSources:
    manifest = RosSourceFile("pkg/package.xml", f"<package><name>{name}</name></package>")
    return RosPackageSources(manifest, tuple(RosSourceFile(path, text) for path, text in files))


def test_ros2_fixture_workspace_nodes_topics_publishes_subscribes() -> None:
    root = FIXTURES / "ros2_ws"

    workspace = parse_ros_workspace(fixture_sources(root))

    assert workspace.nodes == (
        RosNode("/listener", "listener_py", "listener", (), ("/robot/chatter",)),
        RosNode("/robot/talker", "talker_py", "talker", ("/robot/chatter",), ()),
    )
    assert workspace.topics == (RosTopic("/robot/chatter", "std_msgs/msg/String"),)
    talker_launch = root / "src/talker_py/launch/talker.launch.py"
    listener_launch = root / "src/listener_py/launch/listener.launch.xml"
    assert workspace.launched_at == {
        "/robot/talker": (
            f"src/talker_py/launch/talker.launch.py:{_first_line_with(talker_launch, 'Node(')}"
        ),
        "/listener": (
            "src/listener_py/launch/listener.launch.xml:"
            f"{_first_line_with(listener_launch, '<node')}"
        ),
    }
    talker = root / "src/talker_py/talker_py/talker.py"
    listener = root / "src/listener_py/listener_py/listener.py"
    assert workspace.declared_at == {
        ("/robot/talker", "/robot/chatter"): (
            f"src/talker_py/talker_py/talker.py:{_first_line_with(talker, 'create_publisher')}"
        ),
        ("/listener", "/robot/chatter"): (
            "src/listener_py/listener_py/listener.py:"
            f"{_first_line_with(listener, 'create_subscription')}"
        ),
    }


def test_non_ros_repo_writes_nothing() -> None:
    """A repository with no `package.xml` hands the reader nothing, and an empty workspace is what
    comes back (the connectors then land no ROS entity: `test_local_folder.py`)."""
    plain = FIXTURES / "plain_repo"
    assert list(plain.rglob("package.xml")) == []
    assert parse_ros_workspace(fixture_sources(plain)) == RosWorkspace()
    # the same files under a manifest that names no ROS package yield nothing either
    files = tuple((p.relative_to(plain).as_posix(), p.read_text()) for p in plain.rglob("*.*"))
    assert parse_ros_workspace([_demo_package(*files, name="Not A Package")]) == RosWorkspace()


def test_launch_py_is_parsed_never_executed(tmp_path: Path) -> None:
    sentinel = tmp_path / "ran"
    write = f"__import__('pathlib').Path({str(sentinel)!r}).write_text"
    hostile = (
        f"{write}('module')\n"
        "from launch_ros.actions import Node\n\n\n"
        "def generate_launch_description():\n"
        f"    {write}('function')\n"
        "    return [Node(package='demo_pkg', executable='demo', name='hostile')]\n"
    )

    workspace = parse_ros_workspace([_demo_package(("pkg/launch/demo.launch.py", hostile))])

    assert [node.name for node in workspace.nodes] == ["/hostile"]
    assert workspace.launched_at == {"/hostile": "pkg/launch/demo.launch.py:7"}
    assert not sentinel.exists()
    # nothing in the reader could run one: no code-running builtin, loader or import machinery
    source = Path(ros_reader.__file__).read_text()
    for word in ("exec(", "eval(", "compile(", "__import__", "importlib", "runpy"):
        assert word not in source, word


def test_a_yaml_launch_lands_and_anchors_aliases_and_oversize_refuse() -> None:
    plain = "launch:\n- node:\n    pkg: demo_pkg\n    exec: demo\n    name: from_yaml\n"
    aliased = "base: &b {pkg: demo_pkg, exec: demo, name: aliased}\nlaunch:\n- node: *b\n"
    big = plain + "#" * MAX_YAML_BYTES + "\n"

    def names(text: str) -> list[str]:
        workspace = parse_ros_workspace([_demo_package(("pkg/launch/demo.yaml", text))])
        return [node.name for node in workspace.nodes]

    assert names(plain) == ["/from_yaml"]
    assert names(aliased) == []
    assert names(big) == []


@pytest.mark.parametrize(
    "text",
    [
        "def generate_launch_description():\n    return " + "[" * 2000 + "]" * 2000 + "\n",
        "def generate_launch_description(:\n",
        "\x00",
    ],
    ids=["deep", "syntax", "nul"],
)
def test_a_hostile_or_broken_launch_yields_nothing(text: str) -> None:
    workspace = parse_ros_workspace([_demo_package(("pkg/launch/x.launch.py", text))])
    assert workspace == RosWorkspace()


def test_dtd_and_broken_xml_yield_nothing() -> None:
    bomb = (
        '<!DOCTYPE l [<!ENTITY a "aaaa">]><launch><node pkg="demo_pkg" exec="d" name="x"/></launch>'
    )
    for text in (bomb, "<launch"):
        workspace = parse_ros_workspace([_demo_package(("pkg/launch/x.launch.xml", text))])
        assert workspace == RosWorkspace()


def test_masked_and_out_of_grammar_names_never_land() -> None:
    launch = (
        "def generate_launch_description():\n"
        "    return [\n"
        "        Node(package='demo_pkg', executable='a', name='[REDACTED]'),\n"
        "        Node(package='demo_pkg', executable='b', name='{node}'),\n"
        "        Node(package='demo_pkg', executable='c', name='kept', namespace='ns'),\n"
        "        Node(package='demo_pkg', executable='d', name='trailing\\n'),\n"
        "    ]\n"
    )
    module = (
        "from std_msgs.msg import String\n\n"
        "class C(Node):\n"
        "    def __init__(self):\n"
        "        super().__init__('c')\n"
        "        self.create_publisher(String, '[REDACTED]', 10)\n"
        "        self.create_publisher(String, 'bad name', 10)\n"
        "        self.create_publisher(String, '~/status', 10)\n"
    )
    setup = "setup(entry_points={'console_scripts': ['c = demo_pkg.c:main']})\n"
    workspace = parse_ros_workspace(
        [
            _demo_package(
                ("pkg/launch/x.launch.py", launch),
                ("pkg/setup.py", setup),
                ("pkg/demo_pkg/c.py", module),
            )
        ]
    )
    assert workspace.nodes == (RosNode("/ns/kept", "demo_pkg", "c", ("/ns/kept/status",), ()),)
    assert workspace.topics == (RosTopic("/ns/kept/status", "std_msgs/msg/String"),)


def test_a_compiled_node_lands_without_topics() -> None:
    """A node whose executable is no Python module of its package (compiled code) lands from its
    launch line with no publishes and no subscribes: Empty beats invented (R133)."""
    launch = '<launch><node pkg="demo_pkg" exec="driver" name="driver"/></launch>\n'
    workspace = parse_ros_workspace([_demo_package(("pkg/launch/driver.launch.xml", launch))])
    assert workspace.nodes == (RosNode("/driver", "demo_pkg", "driver", (), ()),)
    assert workspace.topics == ()


def test_a_node_whose_package_or_executable_breaks_its_rule_never_lands() -> None:
    """m2: a launch line's package must be a ROS package name and its executable an identifier
    with at most one `.py` or `.sh` suffix (R141: an ament_cmake script such as `talker.py`
    lands), each at most 128 characters; a node failing either is dropped, so no free text
    reaches the node's attrs."""
    launch = (
        "<launch>\n"
        '  <node pkg="demo_pkg" exec="driver" name="kept"/>\n'
        '  <node pkg="demo_pkg" exec="talker.py" name="script"/>\n'
        '  <node pkg="Demo-Pkg" exec="driver" name="cased"/>\n'
        f'  <node pkg="{"p" * 129}" exec="driver" name="long_package"/>\n'
        '  <node pkg="demo_pkg" exec="tal ker" name="spaced"/>\n'
        '  <node pkg="demo_pkg" exec="talker.rb" name="other_suffix"/>\n'
        '  <node pkg="demo_pkg" exec="talker.py.sh" name="two_suffixes"/>\n'
        f'  <node pkg="demo_pkg" exec="{"e" * 129}" name="long_executable"/>\n'
        "</launch>\n"
    )
    workspace = parse_ros_workspace([_demo_package(("pkg/launch/all.launch.xml", launch))])
    assert workspace.nodes == (
        RosNode("/kept", "demo_pkg", "driver", (), ()),
        RosNode("/script", "demo_pkg", "talker.py", (), ()),
    )
    assert set(workspace.launched_at) == {"/kept", "/script"}


def test_disagreeing_types_land_unknown_and_another_package_launches_by_name() -> None:
    """A launch file may start another package's node; its module resolves through that
    package's own `setup.py`. Two publishers naming different types leave the type unknown."""
    launch = (
        "def generate_launch_description():\n"
        "    return [Node(package='two_pkg', executable='pub', name='a'),\n"
        "            Node(package='two_pkg', executable='other', name='b')]\n"
    )
    one = _demo_package(("pkg/launch/all.launch.py", launch), name="one_pkg")
    module = (
        "from std_msgs.msg import {kind}\n\n"
        "class P(Node):\n"
        "    def __init__(self):\n"
        "        super().__init__('p')\n"
        "        self.create_publisher({kind}, '/shared', 10)\n"
    )
    scripts = "['pub = two_pkg.pub:main', 'other = two_pkg.other:main']"
    two = RosPackageSources(
        RosSourceFile("two/package.xml", "<package><name>two_pkg</name></package>"),
        (
            RosSourceFile("two/setup.py", f"setup(entry_points={{'console_scripts': {scripts}}})"),
            RosSourceFile("two/two_pkg/pub.py", module.format(kind="String")),
            RosSourceFile("two/two_pkg/other.py", module.format(kind="Bool")),
        ),
    )
    workspace = parse_ros_workspace([one, two])
    assert [(node.name, node.publishes) for node in workspace.nodes] == [
        ("/a", ("/shared",)),
        ("/b", ("/shared",)),
    ]
    assert workspace.topics == (RosTopic("/shared", None),)
