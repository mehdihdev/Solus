"""SOLUSDEV-321 P6 — `collect_ros_packages`: one record per ROS package, its texts bounded and read
without following a link; a colcon workspace counts only `src/`; and the scan's digest moves when a
launch file does (docs/api/local-folder.md §4)."""

import json
from pathlib import Path
from typing import Any

import pytest

from .local_paths import overlay_module  # isort: skip

ros = overlay_module("ros")
scan = overlay_module("scan")
server = overlay_module("server")

NO_TOOLS = {"kicad": False, "altium": False, "vscode": False}


def _put(root: Path, rel: str, text: str = "x = 1\n") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _package_xml(name: str) -> str:
    return f'<?xml version="1.0"?>\n<package format="3"><name>{name}</name></package>\n'


def _ros_workspace(root: Path) -> None:
    _put(root, "src/talker_py/package.xml", _package_xml("talker_py"))
    _put(root, "src/talker_py/setup.py", "from setuptools import setup\n\nsetup()\n")
    _put(root, "src/talker_py/talker_py/__init__.py", "")
    _put(root, "src/talker_py/talker_py/talker.py", "TOPIC = 'chatter'\n")
    _put(root, "src/talker_py/launch/talker.launch.py", "def generate_launch_description():\n")
    _put(root, "src/listener_py/package.xml", _package_xml("listener_py"))
    _put(root, "src/listener_py/launch/listener.launch.xml", "<launch/>\n")
    _put(root, "src/listener_py/launch/params.yaml", "rate: 10\n")
    _put(root, "src/listener_py/README.md", "never shipped")
    # colcon's install space holds a share copy of every manifest and launch file
    _put(root, "install/talker_py/share/talker_py/package.xml", _package_xml("talker_py"))
    _put(root, "install/talker_py/share/talker_py/launch/talker.launch.py", "copy = 1\n")


def _packages_of(root: Path) -> list[dict[str, Any]]:
    _, manifests, _ = scan._collect(root)
    found: list[dict[str, Any]] = ros.collect_ros_packages(root, manifests)
    return found


def _path_of(item: dict[str, Any]) -> str:
    return "/".join(item["parts"])


def test_collect_ros_packages_and_colcon(tmp_path: Path) -> None:
    _ros_workspace(tmp_path)
    assert ros.is_colcon(tmp_path)

    packages = _packages_of(tmp_path)

    assert [_path_of(package["manifest"]) for package in packages] == [
        "src/listener_py/package.xml",
        "src/talker_py/package.xml",
    ]
    listener, talker = packages
    assert [_path_of(item) for item in listener["files"]] == [
        "src/listener_py/launch/listener.launch.xml",
        "src/listener_py/launch/params.yaml",
    ]
    # launch files and setup.py first, so a cap keeps them; then the package's modules
    assert [_path_of(item) for item in talker["files"]] == [
        "src/talker_py/launch/talker.launch.py",
        "src/talker_py/setup.py",
        "src/talker_py/talker_py/__init__.py",
        "src/talker_py/talker_py/talker.py",
    ]
    assert talker["manifest"]["text"] == _package_xml("talker_py")
    assert talker["files"][0]["text"] == "def generate_launch_description():\n"
    assert talker["incomplete"] is False and listener["incomplete"] is False
    assert set(talker) == {"manifest", "files", "incomplete"}

    # without an install/ or build/ beside src/ it is no colcon workspace: every manifest counts
    (tmp_path / "install").rename(tmp_path / "share-copy")
    assert not ros.is_colcon(tmp_path)
    assert "share-copy/talker_py/share/talker_py/package.xml" in [
        _path_of(package["manifest"]) for package in _packages_of(tmp_path)
    ]


def test_only_what_the_reader_needs_ships(tmp_path: Path) -> None:
    """R135: the manifest, the launch files, the setup files and the modules of the package's own
    module directory ship; a dotfile, a test, a credential-shaped name and a stray module outside
    the module directory never do."""
    _ros_workspace(tmp_path)
    package = "src/talker_py"
    for rel in (
        ".flake8",
        ".env",
        "talker_py/.notes.py",
        "talker_py/secrets.py",
        "talker_py/api_token.py",
        "tests/test_talker.py",
        "talker_py/test/test_node.py",
        "tools/debug.py",
        "talker_py/certs/device.pem.py",
    ):
        _put(tmp_path, f"{package}/{rel}", "SECRET = 'value'\n")
    _put(tmp_path, f"{package}/setup.cfg", "[options.entry_points]\n")

    talker = _packages_of(tmp_path)[1]

    assert [_path_of(item) for item in talker["files"]] == [
        "src/talker_py/launch/talker.launch.py",
        "src/talker_py/setup.cfg",
        "src/talker_py/setup.py",
        "src/talker_py/talker_py/__init__.py",
        "src/talker_py/talker_py/talker.py",
    ]
    assert "SECRET" not in str(talker)
    assert ros.SECRET_NAME.search("Credentials.yaml") and ros.SECRET_NAME.search("id.KEY")


def test_a_credential_named_directory_is_never_walked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R135 follow-up: the credential pattern applies to EVERY path component, so a
    `credentials/` directory under the module directory is neither walked nor shipped, and the
    widened pattern refuses an `apikey.py`; the node beside them still ships."""
    _ros_workspace(tmp_path)
    module = tmp_path / "src/talker_py/talker_py"
    _put(module, "credentials/config.py", "SECRET = 'value'\n")
    _put(module, "credentials/nested/deep.py", "SECRET = 'value'\n")
    _put(module, "apikey.py", "SECRET = 'value'\n")
    _put(module, "node.py", "NODE = 1\n")
    _, manifests, _ = scan._collect(tmp_path)  # the scan's own walk sees everything; ours must not
    walked: list[str] = []
    scandir = ros.os.scandir

    def spy(path: Any) -> Any:
        walked.append(str(path))
        return scandir(path)

    monkeypatch.setattr(ros.os, "scandir", spy)
    talker = ros.collect_ros_packages(tmp_path, manifests)[1]
    monkeypatch.undo()

    shipped = [_path_of(item) for item in talker["files"]]
    assert "src/talker_py/talker_py/node.py" in shipped
    assert not any("credentials" in path or "apikey" in path for path in shipped)
    assert not any("credentials" in path for path in walked)
    assert "SECRET" not in str(talker)
    for name in ("passwd", "API_KEY.txt", "private.pem", "auth.py", "id_ed25519", "store.p12"):
        assert ros.SECRET_NAME.search(name), name


def test_a_package_at_the_folder_root_is_collected(tmp_path: Path) -> None:
    _put(tmp_path, "package.xml", _package_xml("solo"))
    _put(tmp_path, "launch/solo.launch.xml", "<launch/>\n")
    (package,) = _packages_of(tmp_path)
    assert package["manifest"]["parts"] == ["package.xml"]
    assert [_path_of(item) for item in package["files"]] == ["launch/solo.launch.xml"]


def test_links_oversize_files_and_a_dtd_never_ship(tmp_path: Path) -> None:
    _ros_workspace(tmp_path)
    outside = _put(tmp_path / "outside", "secret.launch.py", "stolen = 1\n")
    (tmp_path / "src/talker_py/launch/linked.launch.py").symlink_to(outside)
    (tmp_path / "src/talker_py/linked_dir").symlink_to(tmp_path / "outside")
    _put(tmp_path, "src/talker_py/talker_py/big.py", "x" * (ros.MAX_FILE_BYTES + 1))
    _put(tmp_path, "src/hostile/package.xml", '<!DOCTYPE p [<!ENTITY e "x">]><package/>')

    packages = {_path_of(package["manifest"]): package for package in _packages_of(tmp_path)}

    assert "src/hostile/package.xml" not in packages
    talker = packages["src/talker_py/package.xml"]
    shipped = [_path_of(item) for item in talker["files"]]
    assert not any("linked" in path or "big.py" in path for path in shipped)
    assert "stolen" not in str(talker)
    assert talker["incomplete"] is True  # the oversized module was left out, and says so


def test_the_file_cap_leaves_the_package_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ros_workspace(tmp_path)
    monkeypatch.setattr(ros, "MAX_FILES", 2)
    talker = _packages_of(tmp_path)[1]
    assert [_path_of(item) for item in talker["files"]] == [
        "src/talker_py/launch/talker.launch.py",
        "src/talker_py/setup.py",
    ]
    assert talker["incomplete"] is True


def test_the_total_budget_stops_the_reads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Room for the first package's manifest and one launch file: its yaml is cut (and the package
    says so), and the next package, whose manifest no longer fits, is not shipped at all."""
    _ros_workspace(tmp_path)
    budget = len(_package_xml("listener_py")) + len("<launch/>\n") + 1
    monkeypatch.setattr(ros, "MAX_TOTAL_BYTES", budget)

    packages = _packages_of(tmp_path)

    (listener,) = packages
    assert [_path_of(item) for item in listener["files"]] == [
        "src/listener_py/launch/listener.launch.xml"
    ]
    assert listener["incomplete"] is True
    shipped = sum(len(item["text"]) for p in packages for item in [p["manifest"], *p["files"]])
    assert shipped <= budget


def test_the_ros_part_fits_its_frame_budget_as_encoded(tmp_path: Path) -> None:
    """P6 fix 1 (m9): the frame is ASCII-escaped JSON, so a 2-byte character costs 6 (`\\u00e9`).
    Four 30 KiB launch files are 120 KiB of UTF-8, within MAX_TOTAL_BYTES, but three times that
    once encoded. The packages are kept in order within ROS_FRAME_BUDGET_BYTES: the first that
    does not fit keeps its manifest, marked incomplete, the rest are dropped, and the scan
    itself still answers inside the cloud's 1 MiB frame."""
    launch = "é" * (15 * 1024)
    for n in range(4):
        _put(tmp_path, f"pkg{n}/package.xml", _package_xml(f"pkg{n}"))
        _put(tmp_path, f"pkg{n}/launch/up.launch.py", launch)
    assert 4 * len(launch.encode()) <= ros.MAX_TOTAL_BYTES
    assert 4 * len(json.dumps(launch)) > ros.ROS_FRAME_BUDGET_BYTES

    result = scan.scan_folder(tmp_path, tools=dict(NO_TOOLS))

    packages = result["ros"]
    assert [_path_of(package["manifest"]) for package in packages] == [
        f"pkg{n}/package.xml" for n in range(3)
    ]
    assert [(package["incomplete"], len(package["files"])) for package in packages] == [
        (False, 1),
        (False, 1),
        (True, 0),
    ]
    assert len(json.dumps(packages, separators=(",", ":"))) <= ros.ROS_FRAME_BUDGET_BYTES
    assert len(json.dumps(result, separators=(",", ":"))) < 1024 * 1024


def test_the_scan_ships_ros_and_a_launch_edit_moves_both_digests(tmp_path: Path) -> None:
    _ros_workspace(tmp_path)
    first = scan.scan_folder(tmp_path, tools=dict(NO_TOOLS))
    assert [_path_of(package["manifest"]) for package in first["ros"]] == [
        "src/listener_py/package.xml",
        "src/talker_py/package.xml",
    ]
    assert scan.folder_digest(tmp_path)["digest"] == first["digest"]

    # an .xml launch file is no tool file, so only the ROS fold sees the edit
    _put(tmp_path, "src/listener_py/launch/listener.launch.xml", "<launch><node/></launch>\n")
    second = scan.scan_folder(tmp_path, tools=dict(NO_TOOLS))
    assert second["digest"] != first["digest"]
    assert scan.folder_digest(tmp_path)["digest"] == second["digest"]


def test_a_folder_without_ros_keeps_its_digest_and_ships_an_empty_list(tmp_path: Path) -> None:
    _put(tmp_path, "tools/flash.py", "print(1)\n")
    result = scan.scan_folder(tmp_path, tools=dict(NO_TOOLS))
    assert result["ros"] == []
    files, _, _ = scan._collect(tmp_path)
    assert result["digest"] == scan.compute_digest(files, None)


def test_the_empty_scan_carries_an_empty_ros_list() -> None:
    assert server._empty_scan()["ros"] == []
