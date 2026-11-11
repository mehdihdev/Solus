"""The adapter protocol's shared pieces: the `Unsupported` wire shape, the scrubbed child
environment, the text-format parser, and the argv guards every adapter shares."""

from __future__ import annotations

import math
import os
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from integrations.mcp.gazebo.solus.adapters import adapter_for
from integrations.mcp.gazebo.solus.adapters.adapter_base import (
    Adapter,
    CliError,
    Completed,
    Unsupported,
    WorldPose,
    check_name,
    decimate,
    fmt_float,
    parse_text_format,
    passthrough_names,
    redact_paths,
    run_argv,
    sim_child_env,
    stderr_detail,
    text_items,
)
from integrations.mcp.gazebo.solus.family_detect import Family


def test_unsupported_carries_family_version_sentence_and_wire_shape() -> None:
    error = Unsupported("classic", "11.15.1", "Classic 11 has no save-world service.")
    assert (error.family, error.version, error.sentence) == (
        "classic",
        "11.15.1",
        "Classic 11 has no save-world service.",
    )
    assert error.wire() == {
        "ok": False,
        "code": "unsupported_on",
        "family": "classic",
        "version": "11.15.1",
        "reason": "Classic 11 has no save-world service.",
    }
    assert str(error) == "Classic 11 has no save-world service."


def test_child_env_is_scrubbed_plus_named_passthrough(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GZ_CONFIG_PATH", "/opt/gz/share")
    monkeypatch.setenv("GAZEBO_MASTER_URI", "http://127.0.0.1:11345")
    monkeypatch.setenv("SOLUS_SECRET_TOKEN", "never")
    monkeypatch.setenv("HOME", "/home/someone")
    monkeypatch.setenv("PYTHONPATH", "/evil")
    env = sim_child_env()
    assert env["PATH"] == "/usr/bin:/bin" and env["LANG"] == "C.UTF-8"
    assert env["GZ_CONFIG_PATH"] == "/opt/gz/share"
    assert env["GAZEBO_MASTER_URI"] == "http://127.0.0.1:11345"
    assert "SOLUS_SECRET_TOKEN" not in env and "PYTHONPATH" not in env and "HOME" not in env
    assert set(env) - {"PATH", "LANG"} <= set(passthrough_names())
    assert sim_child_env(Path("/tmp/x"))["HOME"] == "/tmp/x"
    # The allowlist is read from solus/env.allow, the launcher's own list.
    # GZ_IP / IGN_IP: on a multi-homed host gz-transport advertises the first non-loopback
    # interface and local service calls time out unless the machine owner pins it (P9-T6).
    assert {
        "SOLUS_GAZEBO_PATH",
        "LD_LIBRARY_PATH",
        "IGN_PARTITION",
        "GZ_IP",
        "IGN_IP",
        "GAZEBO_IP",
    } <= set(passthrough_names())


def test_parse_text_format_nested_repeated_strings_and_debug_markers() -> None:
    text = (
        "goo.gle/debugstr   \n"
        'name: "twolink"\nid: 10\nis_static: false\n'
        'joint {\n  name: "twolink::shoulder"\n  angle: 1.5\n  type: REVOLUTE\n}\n'
        'joint {\n  name: "twolink::elbow"\n  angle: -0.25\n}\n'
        "pose {\n  position {\n    x: 1e-3\n  }\n}\n"
        "data: \"<sdf version=\\'1.10\\'>\\n  <world/>\\n</sdf>\\n\"\n"
    )
    doc = parse_text_format(text)
    assert doc["name"] == "twolink" and doc["id"] == 10 and doc["is_static"] is False
    joints = text_items(doc, "joint")
    assert [j["name"] for j in joints] == ["twolink::shoulder", "twolink::elbow"]
    assert joints[0]["angle"] == 1.5 and joints[0]["type"] == "REVOLUTE"
    assert doc["pose"]["position"]["x"] == 0.001
    assert doc["data"] == "<sdf version='1.10'>\n  <world/>\n</sdf>\n"
    assert text_items(doc, "missing") == [] and text_items(doc, "name") == ["twolink"]


def test_parse_text_format_bounds_depth_and_tolerates_junk() -> None:
    deep = "a {" * 20 + "x: 1" + "}" * 20
    with pytest.raises(ValueError):
        parse_text_format(deep, max_depth=16)
    assert parse_text_format("stray tokens\nk: v\n}}}\n")["k"] == "v"
    assert parse_text_format("") == {}


@pytest.mark.parametrize(
    ("literal", "expected"),
    [
        ('"\\x"', "\\x"),  # \x with no hex digits: literal
        ('"\\u12"', "\\u12"),  # \u is not a protobuf escape: literal
        ('"\\"', "\\"),  # a trailing backslash
        ('"\\400"', "\\400"),  # octal above 377: literal, never '?'
        ('"\\101\\x42\\t\\"\\\\"', 'AB\t"\\'),
        ('"\\303\\251"', "\u00e9"),  # octal bytes decode as UTF-8
        ('"\\377"', "\ufffd"),  # a lone invalid byte is replaced, never raised
    ],
)
def test_parse_text_format_never_raises_on_malformed_escapes(literal: str, expected: str) -> None:
    assert parse_text_format(f"a: {literal}")["a"] == expected


def test_redact_paths_and_stderr_detail_drop_absolute_paths() -> None:
    line = "Error: File [/home/u/.solus/sim/models/abc/model.urdf] does not exist."
    assert redact_paths(line) == "Error: File [model.urdf] does not exist."
    assert redact_paths('"/tmp/solus-sdf-x/model.urdf": no') == '"model.urdf": no'
    assert redact_paths("no paths here") == "no paths here"
    two_lines = "warn\nError: File [/a/b/c.sdf] missing\n"
    assert stderr_detail(two_lines) == "Error: File [c.sdf] missing"
    assert stderr_detail("   ") == "no output"
    assert stderr_detail("", "no SDF produced") == "no SDF produced"
    assert len(stderr_detail("/x/" + "y" * 500)) <= 200


@pytest.mark.parametrize("bad", ["-x", "--pos-t", "a b", 'a"b', "a{b}", "a:b", "a\\b", "", "a/b"])
def test_check_name_refuses_option_shapes_and_text_format_metacharacters(bad: str) -> None:
    with pytest.raises(ValueError):
        check_name(bad)
    assert check_name("twolink") == "twolink"
    assert check_name("joint_1.v2-a") == "joint_1.v2-a"


def test_fmt_float_refuses_non_finite_and_prints_plain_decimals() -> None:
    assert fmt_float(0.7) == "0.7" and fmt_float(-1.0) == "-1.0" and fmt_float(3) == "3.0"
    for bad in (math.inf, -math.inf, math.nan):
        with pytest.raises(ValueError):
            fmt_float(bad)


def test_pose_quaternion_and_decimate() -> None:
    x, y, z, w = WorldPose().quaternion()
    assert (x, y, z, w) == (0.0, 0.0, 0.0, 1.0)
    x, y, z, w = WorldPose(rpy=(0.0, 0.0, 0.5)).quaternion()
    assert math.isclose(z, 0.24740395925452294) and math.isclose(w, 0.9689124217106447)
    assert decimate(list(range(10)), 4) == [0, 3, 6, 9]
    assert decimate([1, 2], 5) == [1, 2] and decimate([], 3) == []


def test_run_argv_returns_completed_and_raises_cli_error_on_missing_or_slow_binary(
    tmp_path: Path,
) -> None:
    done = run_argv(["/bin/echo", "hello"], 5.0)
    assert isinstance(done, Completed)
    assert (done.returncode, done.stdout) == (0, "hello\n") and done.argv == ("/bin/echo", "hello")
    with pytest.raises(CliError):
        run_argv([str(tmp_path / "missing")], 1.0)
    slow = tmp_path / "slow"
    slow.write_text("#!/bin/sh\nsleep 5\n")
    slow.chmod(0o755)
    with pytest.raises(CliError) as excinfo:
        run_argv([str(slow)], 0.2)
    assert "timed out" in str(excinfo.value)


# --- the §5 review-focus test: no adapter ever builds an option out of a user string ----------

_FAMILIES = ("gz8", "ign6", "classic11")
_HOSTILE = ("-x", "--pos-t", "-m", "sh -c id", "a;b", "$(id)", "`id`", "a b")


def _every_method(adapter: Adapter, tmp_path: Path) -> list[Callable[[str], object]]:
    world_sdf = tmp_path / "m.sdf"
    world_sdf.write_text("<sdf/>")
    return [
        lambda s: adapter.scene(s),
        lambda s: adapter.spawn("empty", world_sdf, s, WorldPose()),
        lambda s: adapter.spawn(s, world_sdf, "ok", WorldPose()),
        lambda s: adapter.joint_state("empty", s, None, 0.0),
        lambda s: adapter.joint_state("empty", "twolink", [s], 0.0),
        lambda s: adapter.set_targets("empty", s, {"shoulder": 0.1}),
        lambda s: adapter.set_targets("empty", "twolink", {s: 0.1}),
        lambda s: adapter.control(s, "pause"),
        lambda s: adapter.save_world(s, tmp_path, "out.sdf"),
        lambda s: adapter.save_world("empty", tmp_path, s),
        lambda s: adapter.telemetry_argv(s),
    ]


@pytest.mark.parametrize("fixture", _FAMILIES)
@pytest.mark.parametrize("hostile", _HOSTILE)
def test_argv_never_contains_a_shell_or_user_string_as_option(
    fixture_family: Callable[[str], Family],
    fixture: str,
    hostile: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def refusing_run(argv: list[str], timeout: float) -> Completed:
        calls.append(list(argv))
        return Completed(tuple(argv), 0, "", "")

    def refusing_popen(argv: list[str], *args: object, **kwargs: object) -> object:
        calls.append(list(argv))
        raise AssertionError("a hostile name reached Popen")

    monkeypatch.setattr(subprocess, "Popen", refusing_popen)
    adapter = adapter_for(fixture_family(fixture), run=refusing_run)
    for method in _every_method(adapter, tmp_path):
        with pytest.raises((ValueError, Unsupported)):
            method(hostile)
    assert calls == [], f"{fixture}: a hostile string reached a subprocess: {calls}"


@pytest.mark.parametrize("fixture", _FAMILIES)
def test_every_argv_starts_with_the_pinned_binary_and_never_a_shell(
    fixture_family: Callable[[str], Family], fixture: str, tmp_path: Path
) -> None:
    calls: list[list[str]] = []
    family = fixture_family(fixture)

    def recording_run(argv: list[str], timeout: float) -> Completed:
        calls.append(list(argv))
        return run_argv(argv, timeout)

    adapter = adapter_for(family, run=recording_run)
    adapter.running_worlds()
    adapter.set_targets("empty" if fixture != "classic11" else "default", "twolink", {"j": 0.5})
    try:
        adapter.control("empty" if fixture != "classic11" else "default", "step", steps=3)
    except CliError:
        pass
    assert calls, "nothing ran"
    for argv in calls:
        assert Path(argv[0]).parent == family.bin_dir, argv
        assert all(a not in ("sh", "bash", "-c", "/bin/sh") for a in argv[1:]), argv
        assert all("\n" not in a for a in argv), argv
    assert "SHELL" not in sim_child_env() and os.environ.get("PATH") == "/usr/bin:/bin"
