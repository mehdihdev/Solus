"""ERC success requires an actual complete report, never the netlist fallback."""

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from test_overlay_support import SOLUS  # noqa: F401  # isort: skip
from solus.development.erc import check_erc
from solus.development.schematic import create_schematic


def _setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: Any, exitcode: int = 0
) -> list[list[str]]:
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(tmp_path))
    create_schematic("erc.kicad_sch", "ERC", True)
    monkeypatch.setattr("solus.development.erc.detect_kicad_cli", lambda: "/fixed/cli")
    calls = []

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append(argv)
        Path(argv[-2]).write_text(json.dumps(body))
        return subprocess.CompletedProcess(argv, exitcode, b"", b"")

    monkeypatch.setattr(subprocess, "run", run)
    return calls


def test_erc_validates_actual_report_and_fixed_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _setup(
        tmp_path,
        monkeypatch,
        {
            "coordinate_units": "mm",
            "included_severities": ["error", "warning"],
            "ignored_checks": [],
            "sheets": [{"violations": []}],
        },
    )
    result = check_erc("erc.kicad_sch")
    assert result["checked"] and result["passed"]
    assert result["errors"] == result["warnings"] == 0
    assert calls[0][1:10] == [
        "sch",
        "erc",
        "--format",
        "json",
        "--units",
        "mm",
        "--severity-all",
        "--exit-code-violations",
        "--output",
    ]


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"sheets": []},
        {
            "coordinate_units": "mm",
            "included_severities": ["error"],
            "sheets": [{"violations": []}],
        },
        {
            "coordinate_units": "mm",
            "included_severities": ["error", "warning"],
            "sheets": [{"violations": None}],
        },
    ],
)
def test_malformed_or_partial_report_never_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: Any
) -> None:
    _setup(tmp_path, monkeypatch, body)
    result = check_erc("erc.kicad_sch")
    assert result["checked"] is False and result["passed"] is None


def test_erc_violations_are_not_process_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup(
        tmp_path,
        monkeypatch,
        {
            "coordinate_units": "mm",
            "included_severities": ["error", "warning"],
            "ignored_checks": [],
            "sheets": [
                {
                    "violations": [
                        {
                            "severity": "error",
                            "description": "Pin not connected",
                            "items": [{"description": "R1 pin1", "pos": {"x": 20, "y": 16.19}}],
                        }
                    ]
                }
            ],
        },
        5,
    )
    result = check_erc("erc.kicad_sch")
    assert result["checked"] and result["passed"] is False and result["errors"] == 1
    assert result["violations"][0]["items"][0]["x_mm"] == 20


def test_non_string_severities_are_a_failed_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup(
        tmp_path,
        monkeypatch,
        {"coordinate_units": "mm", "included_severities": [{}], "sheets": [{"violations": []}]},
    )
    result = check_erc("erc.kicad_sch")
    assert result["passed"] is None


def test_absent_cli_is_unchecked_not_passed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup(tmp_path, monkeypatch, {})
    monkeypatch.setattr("solus.development.erc.detect_kicad_cli", lambda: None)
    result = check_erc("erc.kicad_sch")
    assert result["checked"] is False and result["passed"] is None
    assert result["reason"] == "cli_unavailable"


def test_timeout_does_not_pass_or_leave_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup(tmp_path, monkeypatch, {})

    def timeout(*args: Any, **kwargs: Any) -> Any:
        raise subprocess.TimeoutExpired("fixed cli", 30)

    monkeypatch.setattr(subprocess, "run", timeout)
    result = check_erc("erc.kicad_sch")
    assert result["checked"] is False and result["passed"] is None
    assert not list(tmp_path.glob(".solus-erc-*"))


def test_report_for_a_changed_file_is_not_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup(
        tmp_path,
        monkeypatch,
        {
            "coordinate_units": "mm",
            "included_severities": ["error", "warning"],
            "sheets": [{"violations": []}],
        },
    )
    original_run = subprocess.run

    def race(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        result = original_run(argv, **kwargs)
        with (tmp_path / "erc.kicad_sch").open("ab") as file:
            file.write(b" ")
        return result

    monkeypatch.setattr(subprocess, "run", race)
    result = check_erc("erc.kicad_sch")
    assert result["reason"] == "stale_plan" and result["passed"] is None


def test_erc_uses_exact_private_snapshot_and_discards_process_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup(
        tmp_path,
        monkeypatch,
        {
            "coordinate_units": "mm",
            "included_severities": ["error", "warning"],
            "sheets": [{"violations": []}],
        },
    )
    original = (tmp_path / "erc.kicad_sch").read_bytes()
    fake_run = subprocess.run

    def inspect(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        assert Path(argv[-1]) != tmp_path / "erc.kicad_sch"
        assert Path(argv[-1]).read_bytes() == original
        assert kwargs["stdout"] == subprocess.DEVNULL and kwargs["stderr"] == subprocess.DEVNULL
        return fake_run(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", inspect)
    assert check_erc("erc.kicad_sch")["passed"] is True


def test_erc_native_output_cannot_be_redirected_before_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = {
        "coordinate_units": "mm",
        "included_severities": ["error", "warning"],
        "sheets": [{"violations": []}],
    }
    _setup(tmp_path, monkeypatch, body)
    external = tmp_path / "external"
    external.mkdir()
    sentinel = external / "report.json"
    sentinel.write_bytes(b"SENTINEL")

    def redirect(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        output = Path(argv[-2])
        if str(output).startswith(("/proc/self/fd/", "/dev/fd/")):
            assert int(output.name) in kwargs["pass_fds"]
        else:
            output.parent.rename(output.parent.with_name(output.parent.name + "-moved"))
            output.parent.symlink_to(external, target_is_directory=True)
        output.write_text(json.dumps(body))
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", redirect)
    result = check_erc("erc.kicad_sch")
    assert sentinel.read_bytes() == b"SENTINEL"
    assert result["checked"] and result["passed"]
