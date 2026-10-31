"""SOLUSDEV-321 P6 — `software/policy_reader.py`: what a policy produces and what a controller
takes, read by structure from module and config texts that are never run (`ast` only; YAML capped,
no anchors or aliases), and `module_contract_mismatch`, which compares the two within one source.
The fixture (`tests/fixtures/policy_mismatch/`) states a 6-wide action space, twice, against a
controller of 7 joints."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest
from solus_api.agent.interfaces import EntityRead, GraphContext
from solus_api.checkers.cells.software_software import ModuleContractMismatch
from solus_api.checkers.fact_store import FactStore, ModuleFacts
from solus_api.checkers.interface import Severity
from solus_api.checkers.matrix_rule import RuleResult
from solus_api.software import policy_reader
from solus_api.software.policy_reader import ModuleInterface, read_policy
from solus_api.software.ros_reader import MAX_YAML_BYTES

FIXTURE = Path(__file__).parent / "fixtures" / "policy_mismatch"
SOFTWARE = Path(policy_reader.__file__).parent
#: The framework and vendor words `software/` must never name (the vendor sweep's own list).
FRAMEWORKS = re.compile(r"gym|hydra|torch|lerobot|stable.?baselines|ros2_control", re.IGNORECASE)
#: The standard arm + gripper controller layout (I1): two controllers of different widths in one
#: file, each declared under `controller_manager` before the mapping that states its joints.
ARM_AND_GRIPPER = """\
controller_manager:
  ros__parameters:
    arm_controller:
      type: joint_trajectory_controller/JointTrajectoryController
    gripper_controller:
      type: position_controllers/GripperActionController
arm_controller:
  ros__parameters:
    joints: [shoulder_pan, shoulder_lift, elbow, wrist_1, wrist_2, wrist_3]
gripper_controller:
  ros__parameters:
    joints: [finger]
"""


def _line(text: str, needle: str) -> int:
    return next(n for n, line in enumerate(text.splitlines(), 1) if needle in line)


def _fixture() -> dict[str, tuple[str, list[ModuleInterface]]]:
    found = {}
    for path in sorted(FIXTURE.rglob("*")):
        if path.is_file():
            rel, text = path.relative_to(FIXTURE).as_posix(), path.read_text()
            found[rel] = (text, read_policy(rel, text))
    return found


def _judged(
    interfaces: dict[str, list[ModuleInterface]],
) -> tuple[dict[str, uuid.UUID], list[RuleResult]]:
    """The rule's results over one source holding these files' interfaces."""
    ids = {path: uuid.uuid4() for path in interfaces}
    graph = GraphContext(
        entities=[
            EntityRead(id=ids[path], kind="code_file", domain="code", name=path)
            for path in interfaces
        ],
        edges=[],
    )
    source = uuid.uuid4()
    facts = FactStore(
        module_interfaces={
            ids[path]: ModuleFacts(source, tuple(found))
            for path, found in interfaces.items()
            if found
        }
    )
    return ids, ModuleContractMismatch().results(graph, facts)


def test_the_fixture_states_a_six_wide_policy_twice_and_a_seven_input_controller() -> None:
    found = _fixture()
    policy_text, policy = found["config/policy.yaml"]
    controller_text, controller = found["config/controller.yaml"]
    env_text, env = found["envs/arm_env.py"]
    assert policy == [
        ModuleInterface(
            role="policy",
            inputs=24,
            outputs=6,
            ref=f"config/policy.yaml:{_line(policy_text, 'action_dim')}",
            checkpoint="checkpoints/arm_policy.pt",
        )
    ]
    # I1: the ref is the line of the `joints` that state the inputs, not the key's first mention
    assert controller == [
        ModuleInterface(
            role="controller",
            inputs=7,
            ref=f"config/controller.yaml:{_line(controller_text, 'joints:')}",
        )
    ]
    assert env == [
        ModuleInterface(
            role="policy",
            inputs=24,
            outputs=6,
            ref=f"envs/arm_env.py:{_line(env_text, 'action_space')}",
        )
    ]
    assert not (FIXTURE / "checkpoints").exists()  # recorded, never opened


def test_module_contract_mismatch_on_dim_difference() -> None:
    interfaces = {path: found for path, (_text, found) in _fixture().items()}
    ids, results = _judged(interfaces)

    fails = [r for r in results if r.status == "fail"]
    assert {
        (r.evidence["policy_ref"].split(":")[0], r.evidence["action_dim"], r.evidence["input_dim"])
        for r in fails
    } == {("config/policy.yaml", 6, 7), ("envs/arm_env.py", 6, 7)}
    assert len(results) == 2 and all(r.severity is Severity.WARNING for r in fails)
    first = next(r for r in fails if r.evidence["policy_ref"].startswith("config/policy.yaml"))
    assert first.message == (
        "`config/policy.yaml`'s action space is 6 wide but `config/controller.yaml` takes 7 inputs"
    )
    assert first.subjects == (ids["config/policy.yaml"], ids["config/controller.yaml"])
    assert first.evidence["controller_ref"].startswith("config/controller.yaml:")


def test_an_arm_and_a_gripper_beside_one_policy_are_never_paired_by_guess() -> None:
    """I1: which controller a policy feeds is stated nowhere, so a source holding controllers of
    two widths answers ONE `unknown_input` naming the pairing, and never a fail. A source holding
    one of them is judged: the arm passes, the gripper fails."""
    controllers = read_policy("config/controllers.yaml", ARM_AND_GRIPPER)
    assert [(c.inputs, c.ref) for c in controllers] == [
        (6, f"config/controllers.yaml:{_line(ARM_AND_GRIPPER, 'shoulder_pan')}"),
        (1, f"config/controllers.yaml:{_line(ARM_AND_GRIPPER, '[finger]')}"),
    ]
    policy = read_policy("config/policy.yaml", "policy:\n  action_dim: 6\n")

    ids, results = _judged({"config/policy.yaml": policy, "config/controllers.yaml": controllers})
    (only,) = results
    assert only.status == "unknown_input" and only.missing is not None
    assert only.missing.name == "policy and controller pairing"
    assert only.subjects == (ids["config/policy.yaml"], ids["config/controllers.yaml"])
    for kept, status in ((controllers[:1], "pass"), (controllers[1:], "fail")):
        _, results = _judged({"config/policy.yaml": policy, "config/controllers.yaml": kept})
        assert [r.status for r in results] == [status]


def test_every_controller_beneath_a_controller_key_is_read_once() -> None:
    """I1: controllers nested under one key (a MoveIt-style layout) are each read, so a source's
    widths are complete; one also under its own `*_controller` key is not read twice."""
    text = (
        "simple_controller_manager:\n"
        "  arm_controller:\n    joints: [a, b, c, d, e, f]\n"
        "  hand:\n    joints: [g]\n"
    )
    assert [(c.inputs, c.ref) for c in read_policy("cfg/moveit_controllers.yaml", text)] == [
        (6, "cfg/moveit_controllers.yaml:3"),
        (1, "cfg/moveit_controllers.yaml:5"),
    ]


def test_a_matching_contract_passes_and_another_sources_modules_never_meet() -> None:
    six = ModuleInterface(role="policy", outputs=6, ref="cfg/p.yaml:2")
    seven = ModuleInterface(role="controller", inputs=7, ref="cfg/c.yaml:1")
    also_six = ModuleInterface(role="controller", inputs=6, ref="cfg/c6.yaml:1")
    ids = {name: uuid.uuid4() for name in ("p", "c", "c6")}
    graph = GraphContext(
        entities=[
            EntityRead(id=i, kind="code_file", domain="code", name=n) for n, i in ids.items()
        ],
        edges=[],
    )
    ours, theirs = uuid.uuid4(), uuid.uuid4()
    facts = FactStore(
        module_interfaces={
            ids["p"]: ModuleFacts(ours, (six,)),
            ids["c6"]: ModuleFacts(ours, (also_six,)),
            ids["c"]: ModuleFacts(theirs, (seven,)),  # another repo's controller: never compared
        }
    )
    results = ModuleContractMismatch().results(graph, facts)
    assert [r.status for r in results if r.subjects[:1] == (ids["p"],)] == ["pass"]
    assert not any(r.status == "fail" for r in results)


def test_an_ambiguous_or_missing_side_answers_unknown_input() -> None:
    unsettled = ModuleInterface(role="policy", ref="cfg/p.yaml:3", ambiguous=("action_dim",))
    lonely = ModuleInterface(role="controller", inputs=7, ref="cfg/c.yaml:1")
    six = ModuleInterface(role="policy", outputs=6, ref="cfg/p6.yaml:1")
    hazy = ModuleInterface(role="controller", ref="cfg/c.yaml:9", ambiguous=("command_dim",))
    for interfaces in (
        {"cfg/p.yaml": [unsettled], "cfg/c.yaml": [lonely]},
        {"cfg/c.yaml": [lonely]},
        {"cfg/p6.yaml": [six], "cfg/c.yaml": [lonely, hazy]},  # I1: hazy may be the one fed
    ):
        _, results = _judged(interfaces)
        assert results and all(r.status == "unknown_input" for r in results)
        assert all(r.missing is not None and r.missing.set_in for r in results)
    _, results = _judged({"cfg/p.yaml": [unsettled], "cfg/c.yaml": [lonely]})
    assert any(r.missing is not None and r.missing.name == "action_dim" for r in results)


@pytest.mark.parametrize(
    ("path", "text", "expected"),
    [
        (
            "agent/config.yaml",
            "model:\n  output_features:\n    action: {shape: [6]}\n"
            "  input_features:\n    state: {shape: [24]}\n    image: {shape: [3, 96, 96]}\n",
            [("policy", None, 6, ("input_features",))],
        ),
        (
            "cfg/policy.yaml",
            "policy:\n  obs_dim: ${env.obs}\n  action_dim: 6\n",
            [("policy", None, 6, ("obs_dim",))],
        ),
        (
            "cfg/arm.yaml",
            "arm_controller:\n  parameters:\n    joints: [a, b, c]\n",
            [("controller", 3, None, ())],
        ),
        (
            "cfg/cmd.yaml",
            "base_controller:\n  command_dim: 2\n",
            [("controller", 2, None, ())],
        ),
        (
            "env.py",
            "action_space = Box(low=-1, high=1, shape=(n,))\n",
            [("policy", None, None, ("action_space.shape",))],
        ),
        ("plain.yaml", "name: demo\nrate_hz: 100\n", []),
        ("tool.py", "def main():\n    return 1\n", []),
    ],
    ids=[
        "features",
        "interpolated",
        "controller-joints",
        "controller-dim",
        "unsettled",
        "yaml",
        "py",
    ],
)
def test_structure_states_an_interface_and_ambiguity_is_named(
    path: str, text: str, expected: list[tuple[object, ...]]
) -> None:
    found = read_policy(path, text)
    assert [(i.role, i.inputs, i.outputs, i.ambiguous) for i in found] == expected


@pytest.mark.parametrize(
    "text",
    [
        "base: &b {action_dim: 6}\npolicy: *b\n",
        "policy:\n  action_dim: 6\n" + "#" * MAX_YAML_BYTES + "\n",
        "policy: [" * 2000,
        "policy:\n  action_dim: true\n",
        "policy:\n  action_dim: 0\n",
    ],
    ids=["alias", "oversize", "deep", "bool", "zero"],
)
def test_a_hostile_or_unsettled_yaml_states_no_dimension(text: str) -> None:
    assert [(i.outputs, i.inputs) for i in read_policy("cfg/policy.yaml", text)] in (
        [],
        [(None, None)],
    )


@pytest.mark.parametrize(
    "text", ["def broken(:\n", "x = " + "(" * 3000 + ")" * 3000 + "\n", "\x00"]
)
def test_a_hostile_or_broken_module_states_nothing(text: str) -> None:
    assert read_policy("env.py", text) == []


def test_no_framework_name_under_software() -> None:
    """The vendor sweep for the software readers: they detect by structure, so no framework or
    vendor name appears anywhere under `software/`, and nothing there can run what it reads."""
    for path in sorted(SOFTWARE.rglob("*.py")):
        source = path.read_text()
        assert FRAMEWORKS.search(source) is None, path.name
        for word in ("exec(", "eval(", "compile(", "__import__", "importlib", "runpy", "open("):
            assert word not in source, (path.name, word)
