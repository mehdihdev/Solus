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


@pytest.mark.parametrize(
    "suffix,source",
    [
        (
            ".json",
            b'{"parts":{"elbow":{"address":"06","model":"servo"}},"port":"/dev/private","calibration_file":"/home/private/cal.json"}',
        ),
        (
            ".yaml",
            b'parts:\n  elbow:\n    address: "06"\n    model: servo\n'
            b"port: /dev/private\ncalibration_file: /home/private/cal.json\n",
        ),
        (
            ".toml",
            b'port="/dev/private"\ncalibration_file="/home/private/cal.json"\n[parts.elbow]\naddress="06"\nmodel="servo"\n',
        ),
    ],
)
def test_config_bytes_pure_opaque_and_no_private_path_fields(
    suffix: str, source: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    from livebench.hardware.repo_config import extract_repo_config_bytes

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("bytes parser attempted I/O")

    monkeypatch.setattr(Path, "read_bytes", refuse)
    monkeypatch.setattr(Path, "read_text", refuse)
    monkeypatch.setattr("subprocess.run", refuse)
    matches = extract_repo_config_bytes(source, suffix=suffix, source_ref="review:config")
    assert len(matches) == 1 and matches[0].source == "review:config"
    assert matches[0].parts[0].address == "06"
    assert matches[0].port_hint is None and matches[0].calibration_source is None
    assert all(part.calibration_source is None for part in matches[0].parts)
    assert "/private" not in repr(matches)


@pytest.mark.parametrize(
    "suffix,source",
    [
        (".json", b"{}"),
        (".yaml", b"{}"),
        (".toml", b""),
    ],
)
def test_valid_empty_config_bytes_are_not_errors(suffix: str, source: bytes) -> None:
    from livebench.hardware.repo_config import extract_repo_config_bytes

    assert extract_repo_config_bytes(source, suffix=suffix, source_ref="review:empty") == []


@pytest.mark.parametrize(
    "suffix,source",
    [
        (".json", b'{"parts":'),
        (".yaml", b"parts: [a, "),
        (".toml", b"[broken"),
        (".json", bytes([255])),
        (".txt", b"{}"),
        (".json", b"{}" * (128 * 1024 + 1)),
        (".yaml", b"a: &a [*a]"),
        (".yaml", b"a: " + b"[" * 40 + b"0" + b"]" * 40),
        (".json", b'{"a":' + b"[" * 40 + b"0" + b"]" * 40 + b"}"),
        (".json", b"[]"),
    ],
    ids=lambda value: f"bytes-{len(value)}" if isinstance(value, bytes) else str(value)[:40],
)
def test_config_bytes_invalid_is_distinct_from_empty(suffix: str, source: bytes) -> None:
    from livebench.hardware.repo_config import extract_repo_config_bytes

    with pytest.raises(ValueError):
        extract_repo_config_bytes(source, suffix=suffix, source_ref="review:invalid")


def test_config_bytes_do_not_silently_truncate_overflow_or_accept_native_source() -> None:
    from livebench.hardware.repo_config import extract_repo_config_bytes

    source = json.dumps({"parts": {str(i): {"address": i} for i in range(257)}}).encode()
    with pytest.raises(ValueError):
        extract_repo_config_bytes(source, suffix=".json", source_ref="review:many")
    with pytest.raises(ValueError):
        extract_repo_config_bytes(b"{}", suffix=".json", source_ref="/home/private/config.json")


@pytest.mark.parametrize(
    "suffix,source",
    [
        (".json", b'{"value": NaN}'),
        (".json", b'{"value": Infinity}'),
        (".yaml", b"value: .nan"),
        (".toml", b"value=inf"),
    ],
)
def test_config_bytes_reject_nonfinite_scalars(suffix: str, source: bytes) -> None:
    from livebench.hardware.repo_config import extract_repo_config_bytes

    with pytest.raises(ValueError):
        extract_repo_config_bytes(source, suffix=suffix, source_ref="review:finite")


def test_config_bytes_unicode_and_maximum_opaque_ref_are_preserved() -> None:
    from livebench.hardware.repo_config import extract_repo_config_bytes

    source = json.dumps(
        {"parts": {"腕": {"address": "01", "model": "モーター"}}}, ensure_ascii=False
    ).encode()
    result = extract_repo_config_bytes(source, suffix=".json", source_ref="a" * 512)
    assert result[0].parts[0].name == "腕"
    assert result[0].source == "a" * 512
    assert len(result[0].config_id) <= 512


@pytest.mark.parametrize("address", [[], [1], {}, {"pin": 1}, True, None, 10**513])
def test_bytes_config_rejects_nonaddress_values_before_coercion(address: object) -> None:
    from livebench.hardware.repo_config import extract_repo_config_bytes

    source = json.dumps({"parts": {"motor": {"address": address}}}).encode()
    with pytest.raises(ValueError):
        extract_repo_config_bytes(source, suffix=".json", source_ref="review:address")


@pytest.mark.parametrize("value", ["!!set {a: null}", "!!binary YQ==", "2026-09-14"])
def test_yaml_non_json_scalars_cannot_become_addresses(value: str) -> None:
    from livebench.hardware.repo_config import extract_repo_config_bytes

    source = f"parts:\n  motor:\n    address: {value}\n".encode()
    with pytest.raises(ValueError):
        extract_repo_config_bytes(source, suffix=".yaml", source_ref="review:address")


def test_nested_address_is_refused_before_stringification() -> None:
    from livebench.hardware.repo_config import extract_repo_config_bytes

    source = json.dumps({"parts": {"motor": {"address": ["x" * 512] * 100}}}).encode()
    with pytest.raises(ValueError):
        extract_repo_config_bytes(source, suffix=".json", source_ref="review:address")


@pytest.mark.parametrize("address,expected", [("0x06", "0x06"), (0, "0"), (12.5, "12.5")])
def test_bytes_config_keeps_bounded_scalar_addresses(address: object, expected: str) -> None:
    from livebench.hardware.repo_config import extract_repo_config_bytes

    source = json.dumps({"parts": {"motor": {"address": address}}}).encode()
    matches = extract_repo_config_bytes(source, suffix=".json", source_ref="review:address")
    assert matches[0].parts[0].address == expected


def test_byte_config_preserves_all_supported_sections() -> None:
    from livebench.hardware.repo_config import extract_repo_config_bytes

    source = b'{"motors":{"elbow":{"id":1}},"sensors":{"imu":{"address":2}}}'
    matches = extract_repo_config_bytes(source, suffix=".json", source_ref="review:sections")
    assert {(part.name, part.address) for match in matches for part in match.parts} == {
        ("elbow", "1"),
        ("imu", "2"),
    }


@pytest.mark.parametrize(
    "source",
    [
        b'{"parts":{"elbow":{"id":1,"address":2}}}',
        b'{"motors":{"same":{"id":1}},"sensors":{"same":{"id":2}}}',
        b'{"parts":[{"name":"same","id":1},{"name":"same","id":2}]}',
    ],
)
def test_byte_config_refuses_ambiguous_aliases_or_part_names(source: bytes) -> None:
    from livebench.hardware.repo_config import extract_repo_config_bytes

    with pytest.raises(ValueError):
        extract_repo_config_bytes(source, suffix=".json", source_ref="review:ambiguous")


@pytest.mark.parametrize(
    "suffix,source",
    [
        (".json", b'{"parts":{"elbow":{"id":1,"id":2}}}'),
        (".json", b'{"parts":{"elbow":{"id":1}},"parts":{"imu":{"id":2}}}'),
        (".yaml", b"parts:\n  elbow:\n    id: 1\n    id: 2\n"),
        (".yaml", b"parts:\n  elbow: {id: 1}\n  elbow: {id: 2}\n"),
        (".toml", b"[parts.elbow]\nid=1\nid=2\n"),
    ],
)
def test_byte_config_rejects_duplicate_mapping_keys(suffix: str, source: bytes) -> None:
    from livebench.hardware.repo_config import extract_repo_config_bytes

    with pytest.raises(ValueError):
        extract_repo_config_bytes(source, suffix=suffix, source_ref="review:duplicates")


def test_byte_config_combined_section_count_cannot_exceed_budget() -> None:
    from livebench.hardware.repo_config import extract_repo_config_bytes

    source = json.dumps(
        {
            "motors": {f"m{i}": {"id": i} for i in range(129)},
            "sensors": {f"s{i}": {"id": i} for i in range(129)},
        }
    ).encode()
    with pytest.raises(ValueError):
        extract_repo_config_bytes(source, suffix=".json", source_ref="review:combined")


def test_byte_config_equal_address_aliases_remain_one_part() -> None:
    from livebench.hardware.repo_config import extract_repo_config_bytes

    matches = extract_repo_config_bytes(
        b'{"parts":{"motor":{"id":1,"address":"1"}}}', suffix=".json", source_ref="review:aliases"
    )
    assert len(matches[0].parts) == 1 and matches[0].parts[0].address == "1"


def test_verified_source_ids_bind_content_and_keep_opaque_provenance() -> None:
    from livebench.hardware.repo_config import parse_repo_sources

    registry = RepoParserRegistry.with_generic()
    source = {
        "source_ref": "source:fixture",
        "suffix": ".json",
        "content": b'{"motors":{"joint":{"id":1}}}',
    }
    [first] = parse_repo_sources([source], registry)
    [same] = parse_repo_sources([dict(source)], registry)
    [changed] = parse_repo_sources(
        [{**source, "content": b'{"motors":{"other":{"id":1}}}'}], registry
    )
    assert first.config_id == same.config_id != changed.config_id
    assert first.source == "source:fixture"
    assert first.parts[0].name == "joint"


def test_source_only_normalization_is_declaration_not_operational_calibration() -> None:
    from livebench.hardware.repo_config import parse_repo_sources

    [match] = parse_repo_sources(
        [
            {
                "source_ref": "source:fixture",
                "suffix": ".json",
                "content": b'{"motors":{"joint":{"id":1,"mode":"degrees"}}}',
            }
        ],
        RepoParserRegistry.with_generic(),
    )
    assert match.parts[0].calibration_mode is None
    assert match.params["declared_calibration_modes"] == {"1": "degrees"}
