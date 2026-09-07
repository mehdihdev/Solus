"""SOLUSDEV-250 — `scan_folder.dependencies` (docs/api/code-environment.md §3):
`requirements*.txt` (PEP 508; options/comments skipped, `-r` never followed),
`pyproject.toml` (`[project]` deps + optional groups, tomllib), `environment.yml`
(minimal line reader: conda `name=ver` → `==ver`, nested `- pip:` block; no
YAML library). Hostile lines, the 256 KiB file cap, the 500-entry cap, and the
redaction-safety pin (no wire string ≥ 40 chars)."""

from pathlib import Path
from typing import Any

import pytest

from .local_paths import overlay_module  # isort: skip

deps = overlay_module("deps")
scan = overlay_module("scan")

NO_TOOLS = {"kicad": False, "altium": False, "vscode": False}

REQUIREMENTS = """\
# a comment
-r other.txt
-c constraints.txt
-e .
--index-url https://pypi.example/simple
torch==2.1.0
numpy>=1.24,<2  # trailing comment
Requests[security, socks]>=2.31 ; python_version < "3.13"
Flask_Cors (>=4.0)
uvicorn[standard]
git+https://github.com/org/repo.git#egg=repo
./local/pkg
name @ https://example.com/name-1.0.whl
weird;name==1
  pydantic \\
    ~=2.0
"""


def _write(root: Path, rel: str, content: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _by_name(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {entry["name"]: entry for entry in entries}


# --- requirements*.txt ---------------------------------------------------------


def test_requirements_txt_parses_pep508_and_skips_options() -> None:
    found = deps.parse_requirements_txt(REQUIREMENTS)
    assert [(e["name"], e["specifier"], e["extras"], e["line"]) for e in found] == [
        ("torch", "==2.1.0", [], 6),
        ("numpy", ">=1.24,<2", [], 7),
        ("requests", ">=2.31", ["security", "socks"], 8),
        ("flask-cors", ">=4.0", [], 9),
        ("uvicorn", "", ["standard"], 10),
        ("name", "", [], 13),
        ("weird", "", [], 14),
        ("pydantic", "~=2.0", [], 15),
    ]


def test_referenced_requirements_files_are_never_followed(tmp_path: Path) -> None:
    _write(tmp_path, "requirements.txt", "-r other.txt\nflask==3.0\n")
    _write(tmp_path, "other.txt", "secret-package==9.9\n")
    result = scan.scan_folder(tmp_path, tools=dict(NO_TOOLS))
    assert [e["name"] for e in result["dependencies"]] == ["flask"]
    assert [e["parts"] for e in result["files"]] == [["requirements.txt"]]


@pytest.mark.parametrize(
    "line",
    [
        "$(rm -rf /)",
        "`whoami`",
        "../../etc/passwd",
        "name; rm -rf /",
        "torch==2.1.0 --hash=sha256:" + "a" * 64,
        "name==",
        "==1.0",
        "-",
        "name>>1",
        "name[extra",
        "\x00binary\x00",
        "a" * 40 + "==1.0",
    ],
)
def test_hostile_requirement_lines_are_dropped_or_defanged(line: str) -> None:
    found = deps.parse_requirements_txt(line + "\n")
    for entry in found:
        assert entry["name"] in {"name", "torch"}
        assert entry["specifier"] in {"", "==2.1.0"}
        for text in (entry["name"], entry["specifier"], *entry["extras"]):
            assert len(text) < 40 and "\x00" not in text and " " not in text


def test_hostile_line_with_option_tail_keeps_only_the_requirement() -> None:
    found = deps.parse_requirements_txt("torch==2.1.0 --hash=sha256:" + "a" * 64 + "\n")
    assert found == []  # `--hash` is not a specifier: the line is malformed, not parsed


def test_specifier_is_capped_and_kept_under_the_redaction_threshold() -> None:
    long_pin = "==" + ".".join(str(i) for i in range(40))  # base64-ish, > 40 chars
    (entry,) = deps.parse_requirements_txt(f"pkg{long_pin}\n")
    assert len(entry["specifier"]) == 39
    assert entry["specifier"] == long_pin[:39]
    mixed = ",".join(f">={i}" for i in range(60))  # not base64-ish: `>` and `,`
    (entry,) = deps.parse_requirements_txt(f"pkg{mixed}\n")
    assert len(entry["specifier"]) == deps.MAX_SPECIFIER_CHARS


def test_extras_are_normalised_deduplicated_and_capped() -> None:
    extras = ",".join(f"E_{i}" for i in range(12)) + ",e-0,bad extra"
    (entry,) = deps.parse_requirements_txt(f"pkg[{extras}]==1\n")
    assert entry["extras"] == [f"e-{i}" for i in range(deps.MAX_EXTRAS)]


def test_names_are_pep503_normalised() -> None:
    assert deps.normalize_name("Flask_Cors..Thing-X") == "flask-cors-thing-x"


# --- pyproject.toml --------------------------------------------------------------


PYPROJECT = """\
[project]
name = "policy"
dependencies = [
  "torch>=2.3",
  "numpy",
  42,
]

[project.optional-dependencies]
dev = ["pytest>=8", "ruff"]
sim = ["mujoco==3.1.0"]

[tool.poetry.dependencies]
ignored = "^1.0"
"""


def test_pyproject_parses_project_and_optional_dependencies() -> None:
    found = deps.parse_pyproject(PYPROJECT)
    assert [(e["name"], e["specifier"], e["line"]) for e in found] == [
        ("torch", ">=2.3", 4),
        ("numpy", "", 5),
        ("pytest", ">=8", 10),
        ("ruff", "", 10),
        ("mujoco", "==3.1.0", 11),
    ]


@pytest.mark.parametrize(
    "text",
    ["not toml [[[", "[project]\ndependencies = 'nope'\n", "project = 1\n", "", "[[" * 5000],
)
def test_pyproject_malformed_yields_nothing(text: str) -> None:
    assert deps.parse_pyproject(text) == []


# --- environment.yml -------------------------------------------------------------


ENVIRONMENT = """\
name: robot
channels:
  - conda-forge
dependencies:
  - python=3.11
  - conda-forge::numpy>=1.24  # channel prefix
  - "pytorch=2.1.0=cuda118"
  - pip
  - pip:
    - torch==2.1.0
    - -r requirements.txt
    - opencv-python-headless
  - scipy
prefix: /opt/conda/envs/robot
  - not-a-dependency==1
"""


def test_environment_yml_conda_and_pip_blocks() -> None:
    found = deps.parse_environment_yml(ENVIRONMENT)
    assert [(e["name"], e["specifier"], e["line"]) for e in found] == [
        ("python", "==3.11", 5),
        ("numpy", ">=1.24", 6),
        ("pytorch", "==2.1.0", 7),
        ("pip", "", 8),
        ("torch", "==2.1.0", 10),
        ("opencv-python-headless", "", 12),
        ("scipy", "", 13),
    ]


@pytest.mark.parametrize(
    "text",
    [
        "dependencies:\n  - !!python/object/apply:os.system ['id']\n",
        "dependencies: [a, b]\n",
        "  dependencies:\n  - hidden==1\n",
        "dependencies:\n  - {name: x}\n  - - nested\n",
        "\t- tab==1\n",
        "",
    ],
)
def test_environment_yml_hostile_or_odd_shapes_never_raise(text: str) -> None:
    found = deps.parse_environment_yml(text)
    assert all(entry["name"] not in {"hidden", "nested"} for entry in found)


# --- bounds & collection ---------------------------------------------------------


def test_file_over_256_kib_is_skipped(tmp_path: Path) -> None:
    huge = "small==1\n" + "x" * (256 * 1024)
    _write(tmp_path, "requirements.txt", huge)
    _write(tmp_path, "requirements-dev.txt", "kept==1\n")
    result = scan.scan_folder(tmp_path, tools=dict(NO_TOOLS))
    assert [e["name"] for e in result["dependencies"]] == ["kept"]
    assert result["truncated_dependencies"] is False


def test_exactly_256_kib_is_parsed(tmp_path: Path) -> None:
    body = "kept==1\n"
    _write(tmp_path, "requirements.txt", body + "#" * (256 * 1024 - len(body)))
    assert [
        e["name"] for e in scan.scan_folder(tmp_path, tools=dict(NO_TOOLS))["dependencies"]
    ] == ["kept"]


def test_dependencies_cap_at_500_then_truncated(tmp_path: Path) -> None:
    _write(tmp_path, "a/requirements.txt", "".join(f"pkg{i}==1\n" for i in range(300)))
    _write(tmp_path, "b/requirements.txt", "".join(f"other{i}==1\n" for i in range(300)))
    result = scan.scan_folder(tmp_path, tools=dict(NO_TOOLS))
    assert len(result["dependencies"]) == deps.MAX_DEPENDENCIES == 500
    assert result["truncated_dependencies"] is True
    assert result["dependencies"][0]["parts"] == ["a", "requirements.txt"]
    assert result["dependencies"][-1]["parts"] == ["b", "requirements.txt"]


def test_exactly_500_is_not_truncated(tmp_path: Path) -> None:
    _write(tmp_path, "requirements.txt", "".join(f"pkg{i}==1\n" for i in range(500)))
    result = scan.scan_folder(tmp_path, tools=dict(NO_TOOLS))
    assert len(result["dependencies"]) == 500 and result["truncated_dependencies"] is False


def test_scan_entry_shape_and_sources(tmp_path: Path) -> None:
    _write(tmp_path, "isaac/requirements.txt", "a\nb\ntorch==2.1.0\n")
    _write(tmp_path, "pyproject.toml", '[project]\ndependencies=["torch>=2.3"]\n')
    _write(tmp_path, "environment.yml", "dependencies:\n  - numpy=1.26\n")
    _write(tmp_path, "Pipfile", '[packages]\nrequests = "*"\n')
    _write(tmp_path, "notes/requirements.md", "torch==0\n")
    result = scan.scan_folder(tmp_path, tools=dict(NO_TOOLS))
    assert result["dependencies"] == [
        {
            "parts": ["environment.yml"],
            "ecosystem": "python",
            "name": "numpy",
            "specifier": "==1.26",
            "extras": [],
            "line": 2,
        },
        {
            "parts": ["isaac", "requirements.txt"],
            "ecosystem": "python",
            "name": "a",
            "specifier": "",
            "extras": [],
            "line": 1,
        },
        {
            "parts": ["isaac", "requirements.txt"],
            "ecosystem": "python",
            "name": "b",
            "specifier": "",
            "extras": [],
            "line": 2,
        },
        {
            "parts": ["isaac", "requirements.txt"],
            "ecosystem": "python",
            "name": "torch",
            "specifier": "==2.1.0",
            "extras": [],
            "line": 3,
        },
        {
            "parts": ["pyproject.toml"],
            "ecosystem": "python",
            "name": "torch",
            "specifier": ">=2.3",
            "extras": [],
            "line": 2,
        },
    ]
    walked = ["/".join(entry["parts"]) for entry in result["files"]]
    assert walked == ["environment.yml", "isaac/requirements.txt", "pyproject.toml"]
    assert all(entry["tool"] == "python" for entry in result["files"])


def test_dependency_files_move_the_digest(tmp_path: Path) -> None:
    _write(tmp_path, "requirements.txt", "torch==2.1.0\n")
    before = scan.folder_digest(tmp_path)["digest"]
    _write(tmp_path, "requirements.txt", "torch==2.3.0\n")
    assert scan.folder_digest(tmp_path)["digest"] != before


def test_unreadable_or_vanished_file_yields_nothing(tmp_path: Path) -> None:
    assert deps.parse_dependency_file(tmp_path / "gone.txt", ["requirements.txt"]) == []
    assert deps.parse_dependency_file(tmp_path, []) == []
    assert deps.parse_dependency_file(tmp_path / "x", ["README.md"]) == []


def test_parser_exception_is_swallowed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def boom(_text: str) -> list[Any]:
        raise RuntimeError("parser exploded")

    monkeypatch.setattr(deps, "parser_for", lambda _name: boom)
    _write(tmp_path, "requirements.txt", "a==1\n")
    assert deps.parse_dependency_file(tmp_path / "requirements.txt", ["requirements.txt"]) == []


def test_no_dependency_string_is_redaction_shaped(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "requirements.txt",
        "a-very-long-package-name-that-keeps-going-forever-and-ever==1\n"
        "pkg==" + ".".join(["12345"] * 20) + "\n"
        "ok[" + ",".join(f"extra-{i}" for i in range(20)) + "]>=1.0\n",
    )
    result = scan.scan_folder(tmp_path, tools=dict(NO_TOOLS))

    def strings(value: Any) -> list[str]:
        if isinstance(value, dict):
            return [s for item in value.values() for s in strings(item)]
        if isinstance(value, list):
            return [s for item in value for s in strings(item)]
        return [value] if isinstance(value, str) else []

    for text in strings(result["dependencies"]):
        assert len(text) < 40, text
    assert [e["name"] for e in result["dependencies"]] == ["pkg", "ok"]
