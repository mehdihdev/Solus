"""R2 repo config as a first-class source: structured config in the user's repo names parts,
addresses, models and calibration — with provenance — through a parser registry. The generic
readers know shapes, not vendors; a vendor idiom is a plugin parser."""

import json
import os
from pathlib import Path
from typing import ClassVar

import pytest
from livebench.hardware.repo_config import (
    MAX_SCAN_FILES,
    GenericStructuredParser,
    RepoConfigMatch,
    RepoConfigParser,
    RepoParserRegistry,
    RepoPartDecl,
    iter_repo_files,
    match_configs,
    scan_repo,
)
from solus_api.hardware.config import BusMapEntry, CalibrationMode


def _repo_file(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_generic_parser_reads_a_motors_map_from_yaml_json_and_toml(tmp_path: Path) -> None:
    _repo_file(
        tmp_path,
        "config/arm.yaml",
        "port: /dev/ttyACM0\nmotors:\n  shoulder_pan: {id: 1, model: STS3215}\n"
        "  gripper: {id: 6, model: STS3215, mode: range_0_100}\n",
    )
    _repo_file(
        tmp_path,
        "config/base.json",
        json.dumps({"parts": [{"name": "left", "address": "0x10", "model": "ODrive S1"}]}),
    )
    _repo_file(
        tmp_path,
        "config/drone.toml",
        '[actuators]\nmotor_1 = {address = "servo:1", model = "ESC"}\n',
    )
    matches = scan_repo(tmp_path, RepoParserRegistry.with_generic())
    by_source = {m.source.rsplit("/", 1)[-1]: m for m in matches}
    arm = by_source["arm.yaml"]
    assert arm.port_hint == "/dev/ttyACM0"
    assert [(p.name, p.address, p.model) for p in arm.parts] == [
        ("shoulder_pan", "1", "STS3215"),
        ("gripper", "6", "STS3215"),
    ]
    assert arm.parts[1].calibration_mode is CalibrationMode.RANGE_0_100
    assert by_source["base.json"].parts[0].address == "0x10"
    assert by_source["drone.toml"].parts[0].name == "motor_1"
    assert all(m.parser_id == "generic-structured" for m in matches)


def test_generic_parser_ignores_files_without_a_parts_shape(tmp_path: Path) -> None:
    _repo_file(tmp_path, "pyproject.toml", "[project]\nname = 'x'\n")
    _repo_file(tmp_path, "notes.yaml", "a: 1\n")
    _repo_file(tmp_path, "broken.json", "{not json")
    assert scan_repo(tmp_path, RepoParserRegistry.with_generic()) == []


def test_scan_skips_vendor_dirs_and_is_bounded(tmp_path: Path) -> None:
    _repo_file(tmp_path, "node_modules/x/arm.yaml", "motors:\n  a: {id: 1}\n")
    _repo_file(tmp_path, ".git/arm.yaml", "motors:\n  a: {id: 1}\n")
    _repo_file(tmp_path, ".venv/arm.yaml", "motors:\n  a: {id: 1}\n")
    for i in range(MAX_SCAN_FILES + 5):
        _repo_file(tmp_path, f"many/f{i}.txt", "x")
    _repo_file(tmp_path, "zzz/arm.yaml", "motors:\n  a: {id: 1}\n")
    matches = scan_repo(tmp_path, RepoParserRegistry.with_generic())
    assert len(matches) <= 1  # the walk stops at the bound; nothing under vendor dirs


def test_a_parser_that_raises_never_kills_the_scan(tmp_path: Path) -> None:
    class _Broken:
        parser_id: ClassVar[str] = "broken"

        def scan(self, root: Path, files: list[Path]) -> list[RepoConfigMatch]:
            raise RuntimeError("boom")

    _repo_file(tmp_path, "arm.yaml", "motors:\n  a: {id: 1}\n")
    registry = RepoParserRegistry.with_generic()
    registry.register(_Broken)
    parser: RepoConfigParser = registry.get("broken")
    assert parser.parser_id == "broken"
    assert [m.parser_id for m in scan_repo(tmp_path, registry)] == ["generic-structured"]
    with pytest.raises(ValueError):
        registry.register(_Broken)


def _config_match(config_id: str, addresses: list[tuple[str, str, str | None]]) -> RepoConfigMatch:
    return RepoConfigMatch(
        config_id=config_id,
        parser_id="test",
        label=config_id,
        source=f"/repo/{config_id}.yaml",
        protocol_hint="feetech-sts",
        parts=[RepoPartDecl(name=n, address=a, model=m) for n, a, m in addresses],
    )


def test_match_configs_requires_the_exact_address_set_and_compatible_models() -> None:
    bus = [
        BusMapEntry(protocol="feetech-sts", address="1", model="STS3215"),
        BusMapEntry(protocol="feetech-sts", address="2", model="STS3215"),
    ]
    two = _config_match("two", [("a", "1", "STS3215"), ("b", "2", None)])
    three = _config_match("three", [("a", "1", "STS3215"), ("b", "2", None), ("c", "3", None)])
    wrong_model = _config_match("wrong", [("a", "1", "XL330"), ("b", "2", None)])
    assert [m.config_id for m in match_configs(bus, [three, two, wrong_model])] == ["two"]


def test_match_configs_returns_every_plausible_config_never_a_single_guess() -> None:
    bus = [BusMapEntry(protocol="feetech-sts", address=str(i), model="STS3215") for i in (1, 2)]
    leader = _config_match("leader", [("a", "1", "STS3215"), ("b", "2", "STS3215")])
    follower = _config_match("follower", [("a", "1", "STS3215"), ("b", "2", "STS3215")])
    assert [m.config_id for m in match_configs(bus, [leader, follower])] == ["leader", "follower"]


def test_generic_parser_is_the_only_builtin_and_names_no_vendor() -> None:
    import re

    registry = RepoParserRegistry.with_generic()
    assert [p.parser_id for p in registry.all()] == [GenericStructuredParser.parser_id]
    import livebench.hardware.repo_config as module

    source = Path(module.__file__).read_text().lower()
    assert re.search(r"\b(feetech|dynamixel|lerobot|sts3215|px4|odrive|mavlink)\b", source) is None


# ── review fixes: the walk never follows a link or reads a non-file ─────────────


def test_scan_never_follows_symlinks_or_reads_special_files(tmp_path: Path) -> None:
    root, outside = tmp_path / "repo", tmp_path / "outside"
    _repo_file(outside, "secret.yaml", "motors:\n  a: {id: 1}\n")
    good = _repo_file(root, "arm.yaml", "motors:\n  a: {id: 1}\n")
    (root / "leak.yaml").symlink_to(outside / "secret.yaml")
    (root / "vendor").symlink_to(outside, target_is_directory=True)
    os.mkfifo(root / "pipe.yaml")
    assert iter_repo_files(root) == [good]
    assert [m.source for m in scan_repo(root, RepoParserRegistry.with_generic())] == [str(good)]


def test_skipped_entries_count_against_the_walk_budget(tmp_path: Path) -> None:
    for i in range(30):
        os.mkfifo(tmp_path / f"p{i:02d}")
    _repo_file(tmp_path, "zzz.yaml", "x")
    assert iter_repo_files(tmp_path, max_files=2) == []  # junk exhausted the budget first
