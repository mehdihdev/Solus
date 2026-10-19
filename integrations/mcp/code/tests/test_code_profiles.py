"""SOLUSDEV-317 — environment profiles (docs/api/code-command-execution.md §2.4):
the fixed capture argv, filtering of the env -0 diff, atomic 0600/0700 storage
under ~/.solus (HOME is ALWAYS a temp dir here), tolerant loading, listing
without values, deletion, and applying a profile to a child environment."""

import hashlib
import json
import os
import stat
from pathlib import Path

import pytest

from code_paths import overlay_module  # isort: skip

profiles = overlay_module("profiles")
execute = overlay_module("execute")


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    fake = tmp_path / "home"
    fake.mkdir()
    monkeypatch.setenv("HOME", str(fake))
    return fake


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    return root.resolve()


def _env0(values: dict[str, str]) -> bytes:
    return b"".join(f"{k}={v}".encode() + b"\0" for k, v in values.items())


def test_capture_script_and_argv_are_the_fixed_constants() -> None:
    assert profiles.CAPTURE_SCRIPT == (
        'source "$1" >/dev/null 2>&1 </dev/null || exit 97; exec /usr/bin/env -0'
    )
    assert profiles.capture_argv("/opt/ros/jazzy/setup.bash") == [
        "/bin/bash",
        "--noprofile",
        "--norc",
        "-c",
        profiles.CAPTURE_SCRIPT,
        "solus-profile",
        "/opt/ros/jazzy/setup.bash",
    ]


def test_workspace_key_is_sixteen_hex_of_the_realpath(ws: Path, tmp_path: Path) -> None:
    link = tmp_path / "link"
    link.symlink_to(ws)
    expected = hashlib.sha256(os.path.realpath(ws).encode()).hexdigest()[:16]
    assert profiles.workspace_key(ws) == expected == profiles.workspace_key(link)


@pytest.mark.parametrize("name", ["ros", "a", "ros_2-humble", "0" * 32])
def test_valid_names(name: str) -> None:
    assert profiles.name_error(name) is None


@pytest.mark.parametrize("name", ["", "Ros", "-x", "_x", "a" * 33, "a/b", "a.json", 3, None])
def test_invalid_names(name: object) -> None:
    assert profiles.name_error(name) is not None


def test_parse_env0_handles_values_with_equals_and_newlines() -> None:
    assert profiles.parse_env0(b"A=1\0B=x=y\0C=line1\nline2\0") == {
        "A": "1",
        "B": "x=y",
        "C": "line1\nline2",
    }
    assert profiles.parse_env0(b"garbage-without-equals\0") is None


def test_filter_keeps_new_and_changed_and_drops_the_dangerous() -> None:
    base = {"PATH": "/usr/bin:/bin", "HOME": "/h", "LANG": "C"}
    captured = {
        "PATH": "/opt/ros/jazzy/bin:/usr/bin:/bin",
        "HOME": "/h",
        "LANG": "C",
        "ROS_DISTRO": "jazzy",
        "AMENT_PREFIX_PATH": "/opt/ros/jazzy",
        "LD_LIBRARY_PATH": "/opt/ros/jazzy/lib",
        "DYLD_LIBRARY_PATH": "/opt/ros/jazzy/lib",
        "LD_PRELOAD": "/evil.so",
        "LD_AUDIT": "x",
        "DYLD_INSERT_LIBRARIES": "x",
        "BASH_ENV": "x",
        "ENV": "x",
        "PROMPT_COMMAND": "x",
        "PYTHONSTARTUP": "x",
        "MY_API_TOKEN": "x",
        "db_password": "x",
        "AWS_REGION": "x",
        "GH_HOST": "x",
        "SSH_AUTH_SOCK": "x",
        "SESSION_ID": "x",
        "bad-name": "x",
        "HUGE": "v" * 8193,
        "TMPDIR": "/elsewhere",
        "VIRTUAL_ENV": "/x",
        "SHLVL": "1",
        "PWD": "/w",
        "_": "/usr/bin/env",
    }
    kept, dropped = profiles.filter_capture(captured, base)
    assert kept == {
        "PATH": "/opt/ros/jazzy/bin:/usr/bin:/bin",
        "ROS_DISTRO": "jazzy",
        "AMENT_PREFIX_PATH": "/opt/ros/jazzy",
        "LD_LIBRARY_PATH": "/opt/ros/jazzy/lib",
        "DYLD_LIBRARY_PATH": "/opt/ros/jazzy/lib",
    }
    assert "HOME" not in dropped and "LANG" not in dropped, "unchanged names are not reported"
    assert set(dropped) == set(captured) - set(kept) - {"HOME", "LANG"}
    assert dropped == sorted(dropped)


def test_save_is_atomic_private_and_loads_back(ws: Path, home: Path) -> None:
    saved = profiles.save(
        ws, "ros", "/opt/ros/jazzy/setup.bash", None, {"ROS_DISTRO": "jazzy", "PATH": "/a:/b"}
    )
    directory = home / ".solus" / "code-profiles" / profiles.workspace_key(ws)
    path = directory / "ros.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE((home / ".solus").stat().st_mode) == 0o700
    data = json.loads(path.read_text())
    assert data["schema_version"] == 1 and data["name"] == "ros" and data["extends"] is None
    assert data["vars"] == {"ROS_DISTRO": "jazzy", "PATH": "/a:/b"}
    assert data["setup_file"] == "/opt/ros/jazzy/setup.bash" and data["captured_at"]
    assert [p.name for p in directory.iterdir()] == ["ros.json"], "no temp file left behind"
    loaded = profiles.load(ws, "ros")
    assert loaded.digest == hashlib.sha256(path.read_bytes()).hexdigest() == saved.digest
    assert dict(loaded.variables) == {"ROS_DISTRO": "jazzy", "PATH": "/a:/b"}


@pytest.mark.parametrize(
    "content",
    [
        b"{not json",
        b"[]",
        json.dumps({"schema_version": 2, "name": "ros", "vars": {}}).encode(),
        json.dumps({"schema_version": 1, "name": "other", "vars": {}}).encode(),
        json.dumps(
            {
                "schema_version": 1,
                "name": "ros",
                "setup_file": "/x.sh",
                "extends": None,
                "captured_at": "t",
                "vars": {"LD_PRELOAD": "/evil.so"},
            }
        ).encode(),
        json.dumps(
            {
                "schema_version": 1,
                "name": "ros",
                "setup_file": "/x.sh",
                "extends": None,
                "captured_at": "t",
                "vars": {"A": 1},
            }
        ).encode(),
    ],
)
def test_corrupt_or_tampered_profiles_refuse_without_raising(
    ws: Path, home: Path, content: bytes
) -> None:
    directory = home / ".solus" / "code-profiles" / profiles.workspace_key(ws)
    directory.mkdir(parents=True)
    (directory / "ros.json").write_bytes(content)
    result = profiles.load(ws, "ros")
    assert isinstance(result, str) and "ros" in result
    assert profiles.list_profiles(ws) == []


def test_missing_profile_and_symlinked_profile_refuse(ws: Path, home: Path, tmp_path: Path) -> None:
    assert "no profile" in profiles.load(ws, "ros")
    profiles.save(ws, "real", "/x.sh", None, {"A": "1"})
    directory = home / ".solus" / "code-profiles" / profiles.workspace_key(ws)
    (directory / "ros.json").symlink_to(directory / "real.json")
    assert isinstance(profiles.load(ws, "ros"), str)
    assert isinstance(profiles.load(ws, "../x"), str)


def test_list_returns_names_never_values_and_delete_removes(ws: Path, home: Path) -> None:
    assert profiles.list_profiles(ws) == []
    profiles.save(ws, "ros", "/opt/ros/jazzy/setup.bash", None, {"B": "secretish", "A": "1"})
    profiles.save(ws, "ws", "install/setup.bash", "ros", {"C": "3"})
    listed = profiles.list_profiles(ws)
    assert [entry["name"] for entry in listed] == ["ros", "ws"]
    assert listed[0]["variables"] == ["A", "B"] and listed[1]["extends"] == "ros"
    assert set(listed[0]) == {"name", "setup_file", "extends", "captured_at", "variables"}
    assert "secretish" not in json.dumps(listed)
    assert profiles.delete(ws, "ros") == {"ok": True, "name": "ros", "reason": None}
    assert profiles.delete(ws, "ros")["ok"] is False
    assert profiles.delete(ws, "../etc")["ok"] is False
    assert [entry["name"] for entry in profiles.list_profiles(ws)] == ["ws"]


def test_apply_keeps_solus_controlled_names_and_prepends_the_venv(ws: Path) -> None:
    base = {"PATH": "/venv/bin:/usr/bin:/bin", "HOME": "/h", "TMPDIR": "/t", "VIRTUAL_ENV": "/v"}
    variables = (
        ("PATH", "/opt/ros/bin:/usr/bin:/bin"),
        ("HOME", "/evil"),
        ("TMPDIR", "/evil"),
        ("VIRTUAL_ENV", "/evil"),
        ("ROS_DISTRO", "jazzy"),
    )
    env = profiles.apply(base, variables, "/venv/bin")
    assert env == {
        "PATH": "/venv/bin:/opt/ros/bin:/usr/bin:/bin",
        "HOME": "/h",
        "TMPDIR": "/t",
        "VIRTUAL_ENV": "/v",
        "ROS_DISTRO": "jazzy",
    }
    assert profiles.apply(base, variables, None)["PATH"] == "/opt/ros/bin:/usr/bin:/bin"
    assert profiles.apply(base, (("A", "1"),), None)["PATH"] == base["PATH"]


def test_setup_file_resolution(ws: Path, tmp_path: Path) -> None:
    (ws / "install").mkdir()
    (ws / "install" / "setup.bash").write_text("export A=1\n")
    (ws / "big.sh").write_bytes(b"#" * (256 * 1024 + 1))
    (ws / "notes.txt").write_text("")
    outside = tmp_path / "outside.sh"
    outside.write_text("")
    (ws / "link.sh").symlink_to(outside)
    assert profiles.resolve_setup_file(ws, "install/setup.bash") == str(
        ws / "install" / "setup.bash"
    )
    for bad in ("big.sh", "notes.txt", "link.sh", "../outside.sh", "missing.sh", str(outside)):
        result = profiles.resolve_setup_file(ws, bad)
        assert isinstance(result, profiles.Refusal), bad
    assert isinstance(
        profiles.resolve_setup_file(ws, "/opt/ros/../../etc/profile"), profiles.Refusal
    )
    assert isinstance(profiles.resolve_setup_file(ws, 5), profiles.Refusal)


def _outcome(stdout: bytes, exit_code: int | None = 0, timed_out: bool = False) -> object:
    return execute.Outcome(exit_code, stdout, b"", timed_out)


def test_finish_capture_stores_filtered_vars_and_reports_names_only(ws: Path, home: Path) -> None:
    base = {"PATH": "/usr/bin:/bin", "HOME": str(home)}
    captured = {
        **base,
        "PATH": "/opt/ros/jazzy/bin:/usr/bin:/bin",
        "ROS_DISTRO": "jazzy",
        "ROS_TOKEN": "s3cr3t",
    }
    result = profiles.finish_capture(
        ws, "ros", "/opt/ros/jazzy/setup.bash", None, _outcome(_env0(captured)), base
    )
    assert result == {
        "ok": True,
        "name": "ros",
        "variables": ["PATH", "ROS_DISTRO"],
        "dropped": ["ROS_TOKEN"],
        "path_entries": 3,
        "reason": None,
    }
    assert "s3cr3t" not in json.dumps(result)
    assert dict(profiles.load(ws, "ros").variables)["ROS_DISTRO"] == "jazzy"


@pytest.mark.parametrize(
    ("outcome", "reason"),
    [
        (execute.Outcome(97, b"", b"", False), "could not be sourced"),
        (execute.Outcome(3, b"", b"", False), "exit 3"),
        (execute.Outcome(None, b"", b"", True), "timed out"),
        (execute.Outcome(0, b"A=" + b"x" * (256 * 1024), b"", False), "too large"),
        (execute.Outcome(0, b"nonsense", b"", False), "unparseable"),
        (
            execute.Outcome(
                0, b"".join(f"V{i}=1".encode() + b"\0" for i in range(257)), b"", False
            ),
            "256",
        ),
    ],
)
def test_finish_capture_refusals_store_nothing(
    ws: Path, home: Path, outcome: object, reason: str
) -> None:
    result = profiles.finish_capture(ws, "ros", "/x.sh", None, outcome, {"PATH": "/usr/bin"})
    assert result["ok"] is False and reason in result["reason"]
    assert result["variables"] == [] and result["dropped"] == []
    assert profiles.list_profiles(ws) == []


def test_real_capture_script_sources_a_setup_file(ws: Path, home: Path) -> None:
    """The fixed script runs under a real bash; the setup file is an argument."""
    import subprocess

    setup = ws / "setup.bash"
    setup.write_text('export ROS_DISTRO=jazzy\nexport PATH="/opt/x/bin:$PATH"\necho noise\n')
    base = {"PATH": "/usr/bin:/bin", "HOME": str(home)}
    completed = subprocess.run(
        profiles.capture_argv(str(setup)), capture_output=True, env=base, cwd=ws, timeout=30
    )
    outcome = execute.Outcome(completed.returncode, completed.stdout, completed.stderr, False)
    result = profiles.finish_capture(ws, "ros", str(setup), None, outcome, base)
    assert result["ok"] is True, result
    assert result["variables"] == ["PATH", "ROS_DISTRO"]


# --- §9.8: one loader/option-injection list, applied at capture AND at spawn ----------

INJECTION = (
    "LD_PRELOAD",
    "LD_AUDIT",
    "DYLD_INSERT_LIBRARIES",
    "GCONV_PATH",
    "BASH_ENV",
    "ENV",
    "PROMPT_COMMAND",
    "PYTHONSTARTUP",
    "NODE_OPTIONS",
    "PERL5OPT",
    "RUBYOPT",
    "JAVA_TOOL_OPTIONS",
    "_JAVA_OPTIONS",
)


def test_one_loader_list_drops_option_injection_and_keeps_search_paths() -> None:
    assert set(INJECTION) <= profiles.LOADER_NAMES
    assert not hasattr(execute, "LOADER_INJECTION"), "a single list, in profiles.py"
    for name in INJECTION:
        assert not profiles.allowed_variable(name), name
    assert profiles.allowed_variable("PYTHONPATH")
    assert profiles.allowed_variable("LD_LIBRARY_PATH")
    kept, dropped = profiles.filter_capture(
        {"NODE_OPTIONS": "--require=/x", "PYTHONPATH": "/opt/ros/lib"}, {}
    )
    assert kept == {"PYTHONPATH": "/opt/ros/lib"} and dropped == ["NODE_OPTIONS"]


def test_child_env_never_carries_an_injection_name(tmp_path: Path) -> None:
    plan_module = overlay_module("plan")
    profile = profiles.Profile(
        name="p",
        setup_file="/opt/ros/setup.bash",
        extends=None,
        captured_at="x",
        variables=tuple((name, "x") for name in (*INJECTION, "PYTHONPATH")),
        digest="d",
    )
    plan = plan_module.Plan(action="exec", ok=True, argv=["/bin/true"], profile=profile)
    env = execute.child_env(tmp_path, plan)
    assert not set(INJECTION) & set(env) and env["PYTHONPATH"] == "x"
