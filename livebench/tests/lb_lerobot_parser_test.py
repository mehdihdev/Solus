"""SOLUSDEV-248 R2: the lerobot repo-config plugin. `Robot`/`Teleoperator` classes are read by
AST (never imported) and paired with the HF-cache calibration JSON. The reference case is the
user's own SO-101 pair; fixtures/lerobot_calibration holds its real calibration values."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from livebench.hardware.channel import TransportRegistry
from livebench.hardware.driver import DriverRegistry
from livebench.hardware.interrogator import InterrogatorRegistry
from livebench.hardware.registries import Registries
from livebench.hardware.repo_config import (
    RepoConfigMatch,
    RepoPartDecl,
    iter_repo_files,
    match_configs,
    scan_repo,
)
from livebench.plugins.lerobot import register
from livebench.plugins.lerobot.lerobot_parser import LerobotConfigParser
from solus_api.hardware.config import BusMapEntry, CalibrationMode

FIXTURE_CALIBRATION = Path(__file__).parent / "fixtures" / "lerobot_calibration"
REAL_CLONE = Path("/home/beeboss/lerobot")
REAL_CALIBRATION = Path("~/.cache/huggingface/lerobot/calibration").expanduser()
FOLLOWER_ID = "lerobot:SOFollower:my_awesome_follower_arm"
SO_PARTS = [
    ("shoulder_pan", "1", "sts3215"),
    ("shoulder_lift", "2", "sts3215"),
    ("elbow_flex", "3", "sts3215"),
    ("wrist_flex", "4", "sts3215"),
    ("wrist_roll", "5", "sts3215"),
    ("gripper", "6", "sts3215"),
]
SHOULDER_PAN_CALIBRATION = {
    "drive_mode": 0,
    "homing_offset": -2043,
    "range_min": 719,
    "range_max": 3441,
}

# The exact idiom of lerobot's so_follower.py / so_leader.py (v0.4.4).
KOCH = """
from lerobot.motors import Motor, MotorNormMode
from lerobot.motors.dynamixel import DynamixelMotorsBus


class KochFollower(Robot):
    name = "koch_follower"

    def __init__(self, config):
        self.bus = DynamixelMotorsBus(
            port="/dev/ttyUSB0",
            motors={
                "shoulder_pan": Motor(id=1, model="xl430-w250", norm_mode=MotorNormMode.DEGREES),
                "elbow_flex": Motor(2, "xl330-m288", MotorNormMode.RANGE_M100_100),
                "gripper": Motor(3, "xl330-m288", something_unresolvable),
                **extra_motors,
            },
        )
"""


def _lerobot_source(class_name: str, base: str, name: str) -> str:
    return f'''
from lerobot.motors import Motor, MotorCalibration, MotorNormMode
from lerobot.motors.feetech import FeetechMotorsBus


class {class_name}({base}):
    config_class = SomeConfig
    name = "{name}"

    def __init__(self, config):
        super().__init__(config)
        self.config = config
        norm_mode_body = (
            MotorNormMode.DEGREES if config.use_degrees else MotorNormMode.RANGE_M100_100
        )
        self.bus = FeetechMotorsBus(
            port=self.config.port,
            motors={{
                "shoulder_pan": Motor(1, "sts3215", norm_mode_body),
                "shoulder_lift": Motor(2, "sts3215", norm_mode_body),
                "elbow_flex": Motor(3, "sts3215", norm_mode_body),
                "wrist_flex": Motor(4, "sts3215", norm_mode_body),
                "wrist_roll": Motor(5, "sts3215", norm_mode_body),
                "gripper": Motor(6, "sts3215", MotorNormMode.RANGE_0_100),
            }},
            calibration=self.calibration,
        )
'''


def _lerobot_file(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    _lerobot_file(
        root,
        "src/lerobot/robots/so_follower/so_follower.py",
        _lerobot_source("SOFollower", "Robot", "so_follower"),
    )
    _lerobot_file(
        root,
        "src/lerobot/teleoperators/so_leader/so_leader.py",
        _lerobot_source("SOLeader", "Teleoperator", "so_leader"),
    )
    return root


@pytest.fixture
def calibration_root(tmp_path: Path) -> Path:
    shutil.copytree(FIXTURE_CALIBRATION, tmp_path / "calibration")
    return tmp_path / "calibration"


def _scan_lerobot(root: Path, calibration_root: Path) -> list[RepoConfigMatch]:
    parser = LerobotConfigParser(calibration_root=calibration_root)
    return parser.scan(root, iter_repo_files(root))


def _by_id(matches: list[RepoConfigMatch], config_id: str) -> RepoConfigMatch:
    return next(m for m in matches if m.config_id == config_id)


def test_follower_class_pairs_with_its_real_calibration(repo: Path, calibration_root: Path) -> None:
    matches = _scan_lerobot(repo, calibration_root)
    assert sorted(m.config_id for m in matches) == [
        FOLLOWER_ID,
        "lerobot:SOLeader:None",
        "lerobot:SOLeader:bee_leader_arm",
    ]
    follower = _by_id(matches, FOLLOWER_ID)
    assert follower.parser_id == "lerobot"
    assert follower.label == "SOFollower · my_awesome_follower_arm"
    assert follower.source == str(repo / "src/lerobot/robots/so_follower/so_follower.py")
    assert follower.protocol_hint == "feetech-sts"
    assert follower.port_hint is None  # lerobot binds the port at the CLI
    assert follower.calibration_source == str(
        calibration_root / "robots/so_follower/my_awesome_follower_arm.json"
    )
    assert follower.params == {
        "lerobot_name": "so_follower",
        "note": "lerobot toggles this with use_degrees",
    }
    assert [(p.name, p.address, p.model) for p in follower.parts] == SO_PARTS
    pan = follower.parts[0]
    assert pan.calibration_mode is CalibrationMode.DEGREES  # physical units win over the toggle
    assert pan.calibration == SHOULDER_PAN_CALIBRATION
    assert pan.calibration_source == follower.calibration_source
    assert follower.parts[5].calibration_mode is CalibrationMode.RANGE_0_100
    assert all(p.calibration is not None for p in follower.parts)


def test_leader_yields_one_match_per_calibration_file(repo: Path, calibration_root: Path) -> None:
    matches = _scan_lerobot(repo, calibration_root)
    bee = _by_id(matches, "lerobot:SOLeader:bee_leader_arm")
    no_id = _by_id(matches, "lerobot:SOLeader:None")
    assert bee.label == "SOLeader · bee_leader_arm"
    assert no_id.label == "SOLeader · (no id)"
    assert bee.calibration_source == str(
        calibration_root / "teleoperators/so_leader/bee_leader_arm.json"
    )
    assert no_id.calibration_source == str(calibration_root / "teleoperators/so_leader/None.json")
    assert (bee.parts[5].calibration or {})["range_min"] == 2032
    assert (no_id.parts[5].calibration or {})["range_min"] == 2037


def test_skips_examples_tests_docs_and_a_class_without_calibration_is_one_bare_match(
    repo: Path, calibration_root: Path
) -> None:
    for rel in ("examples/demo.py", "tests/test_demo.py", "docs/demo.py", "benchmarks/demo.py"):
        _lerobot_file(repo, rel, _lerobot_source("Demo", "Robot", "so_follower"))
    _lerobot_file(repo, "src/koch.py", KOCH)
    matches = _scan_lerobot(repo, calibration_root)
    assert not any("Demo" in m.config_id for m in matches)
    koch = _by_id(matches, "lerobot:KochFollower")
    assert koch.label == "KochFollower"
    assert koch.protocol_hint == "dynamixel-2"
    assert koch.port_hint == "/dev/ttyUSB0"
    assert koch.calibration_source is None
    assert koch.params == {"lerobot_name": "koch_follower"}
    assert koch.parts == [
        RepoPartDecl("shoulder_pan", "1", "xl430-w250", CalibrationMode.DEGREES),
        RepoPartDecl("elbow_flex", "2", "xl330-m288", CalibrationMode.RANGE_M100_100),
        RepoPartDecl("gripper", "3", "xl330-m288", None),
    ]


def test_malformed_or_non_object_calibration_json_is_skipped(
    repo: Path, calibration_root: Path
) -> None:
    _lerobot_file(calibration_root, "robots/so_follower/broken.json", "{not json")
    _lerobot_file(calibration_root, "robots/so_follower/list.json", "[1, 2]")
    ids = [
        m.config_id for m in _scan_lerobot(repo, calibration_root) if "SOFollower" in m.config_id
    ]
    assert ids == [FOLLOWER_ID]


def test_a_calibration_file_none_of_whose_ids_agree_still_yields_the_bare_class(
    repo: Path, calibration_root: Path
) -> None:
    shutil.rmtree(calibration_root / "robots/so_follower")
    entry = {"id": 9, "drive_mode": 0, "homing_offset": 1, "range_min": 0, "range_max": 4095}
    _lerobot_file(
        calibration_root,
        "robots/so_follower/other.json",
        json.dumps({"shoulder_pan": entry, "gripper": "nope", "wrist_roll": {"id": 5}}),
    )
    other = _by_id(_scan_lerobot(repo, calibration_root), "lerobot:SOFollower:other")
    assert [(p.name, p.address) for p in other.parts] == [(n, a) for n, a, _ in SO_PARTS]
    assert all(p.calibration is None and p.calibration_source is None for p in other.parts)


def test_repo_code_is_parsed_never_executed(
    repo: Path, calibration_root: Path, tmp_path: Path
) -> None:
    marker = tmp_path / "pwned"
    evil = f'import os\nos.system("touch {marker}")\n' + _lerobot_source("Evil", "Robot", "../evil")
    _lerobot_file(repo, "src/evil.py", evil)
    _lerobot_file(repo, "src/broken.py", "def (:\n")
    _lerobot_file(repo, "src/huge.py", "x = 1\n" * (100 * 1024))
    _lerobot_file(repo, "src/nul.py", "x = '\x00'\n")
    matches = _scan_lerobot(repo, calibration_root)
    assert not marker.exists()
    evil_match = _by_id(matches, "lerobot:Evil")  # a traversal `name` never becomes a path
    assert evil_match.calibration_source is None and len(evil_match.parts) == 6


def test_calibration_files_per_class_are_capped(repo: Path, calibration_root: Path) -> None:
    for i in range(70):
        _lerobot_file(calibration_root, f"robots/so_follower/arm{i:02d}.json", "{}")
    follower = [m for m in _scan_lerobot(repo, calibration_root) if "SOFollower" in m.config_id]
    assert len(follower) == 64


def test_registers_and_scan_repo_reads_the_env_calibration_root(
    repo: Path, calibration_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HF_LEROBOT_CALIBRATION", str(calibration_root))
    registries = Registries(TransportRegistry(), DriverRegistry(), InterrogatorRegistry())
    register(registries)
    assert registries.repo_parsers.get("lerobot").parser_id == "lerobot"
    assert FOLLOWER_ID in {m.config_id for m in scan_repo(repo, registries.repo_parsers)}


def test_wire_identical_arms_match_both_configs_never_a_guess(
    repo: Path, calibration_root: Path
) -> None:
    bus = [
        BusMapEntry(protocol="feetech-sts", address=str(i), model="STS3215") for i in range(1, 7)
    ]
    matched = match_configs(bus, _scan_lerobot(repo, calibration_root))
    assert sorted(m.config_id for m in matched) == [
        FOLLOWER_ID,
        "lerobot:SOLeader:None",
        "lerobot:SOLeader:bee_leader_arm",
    ]


# Environment-dependent: runs only where the user's lerobot clone and HF calibration cache exist.
def test_real_lerobot_clone_yields_the_users_so101_pair() -> None:
    if not (REAL_CLONE / "src/lerobot/robots/so_follower/so_follower.py").is_file():
        pytest.skip("lerobot clone absent")
    if not (REAL_CALIBRATION / "robots/so_follower/my_awesome_follower_arm.json").is_file():
        pytest.skip("HF calibration cache absent")
    parser = LerobotConfigParser(calibration_root=REAL_CALIBRATION)
    matches = parser.scan(REAL_CLONE, iter_repo_files(REAL_CLONE))
    ids = {m.config_id for m in matches}
    assert {FOLLOWER_ID, "lerobot:SOLeader:bee_leader_arm", "lerobot:SOLeader:None"} <= ids
    follower = _by_id(matches, FOLLOWER_ID)
    assert follower.source == str(REAL_CLONE / "src/lerobot/robots/so_follower/so_follower.py")
    assert [(p.name, p.address, p.model) for p in follower.parts] == SO_PARTS
    assert follower.parts[0].calibration == SHOULDER_PAN_CALIBRATION
