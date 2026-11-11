"""What crosses the wire: `{ok, dry_run, preview, fingerprint}` for every mutating tool,
`unsupported_on` for a missing capability, digest chunking, no absolute paths, never an
exception."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from integrations.mcp.gazebo.solus.adapters.adapter_base import CliError, Completed
from integrations.mcp.gazebo.solus.gazebo_server import (
    MUTATING_TOOLS,
    GazeboToolService,
    encode_result,
    wire_encode,
)
from integrations.mcp.gazebo.tests.conftest import Children

WORLD = '<sdf version="1.10"><world name="empty"/></sdf>\n'
CLASSIC_WORLD = '<sdf version="1.6"><world name="default"/></sdf>\n'
DIGEST = re.compile(r"^[0-9a-f]{64}$")


def _complete(preview: Any) -> bool:
    """The API's `_diff_rows` acceptance (bridge/tool.py), restated."""
    if not isinstance(preview, list) or not 1 <= len(preview) <= 40:
        return False
    for row in preview:
        if (
            not isinstance(row, dict)
            or set(row) != {"label", "before", "after"}
            or not isinstance(row["label"], str)
            or not row["label"].strip()
            or any(
                value is not None and (not isinstance(value, str) or len(value) > 400)
                for value in row.values()
            )
        ):
            return False
    return True


@pytest.fixture
def gz_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fixture_bins: Path, fake_children: Children
) -> GazeboToolService:
    monkeypatch.setenv("SOLUS_GAZEBO_PATH", str(fixture_bins / "gz8"))
    root = tmp_path / "worlds"
    root.mkdir()
    (root / "empty.sdf").write_text(WORLD)
    monkeypatch.setenv("SOLUS_SIM_ROOTS", str(root))
    workspace = tmp_path / "ws"
    workspace.mkdir()
    now = [0.0]
    return GazeboToolService(
        workspace, clock=lambda: now[0], sleep=lambda s: now.__setitem__(0, now[0] + s)
    )


def test_unsupported_cell_returns_unsupported_on_with_one_sentence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fixture_bins: Path
) -> None:
    monkeypatch.setenv("SOLUS_GAZEBO_PATH", str(fixture_bins / "classic11"))
    root = tmp_path / "worlds"
    root.mkdir()
    (root / "default.world").write_text(CLASSIC_WORLD)
    monkeypatch.setenv("SOLUS_SIM_ROOTS", str(root))
    service = GazeboToolService(tmp_path)
    probe = service.call("probe", {})
    assert probe["families"] == [{"name": "classic", "version": "11.15.1", "distro": None}]
    assert probe["capabilities"]["save_world"] is False
    sid = service.call("attach", {"family": "classic", "world": "default"})["session_id"]
    for dry_run in (True, False):
        result = service.call(
            "save_world", {"session_id": sid, "dest": "out.world", "dry_run": dry_run}
        )
        assert result == {
            "ok": False,
            "code": "unsupported_on",
            "family": "classic",
            "version": "11.15.1",
            "reason": result["reason"],
        }
        sentence = result["reason"]
        assert sentence.endswith(".") and sentence.count(". ") == 0, "one sentence"
        assert "GUI" in sentence
    assert not (root / "out.world").exists()


def test_every_mutating_tool_dry_runs_to_a_complete_preview(
    gz_service: GazeboToolService,
    fake_children: Children,
    tmp_path: Path,
    cold_simulator: Callable[[], None],
) -> None:
    created, signals = fake_children
    owned = gz_service.call("open_world", {"world_ref": "empty.sdf"})
    sid = owned["session_id"]
    dry_runs: dict[str, dict[str, Any]] = {
        "open_world": {"world_ref": "empty.sdf"},
        "spawn": {"session_id": sid, "model_sha256": "", "name": "arm1"},
        "set_joint_targets": {
            "session_id": sid,
            "model": "twolink",
            "targets": [{"joint": "shoulder", "position_rad": 0.25}],
        },
        "control": {"session_id": sid, "action": "pause"},
        "run_routine": {
            "session_id": sid,
            "model": "twolink",
            "routine": "sweep",
            "duration_s": 3.0,
            "sweep": {"joint": "elbow", "lower": -0.5, "upper": 0.5, "speed_rad_s": 0.5},
        },
        "stop": {"session_id": sid},
        "save_world": {"session_id": sid, "dest": "copy.sdf"},
    }
    assert set(dry_runs) == set(MUTATING_TOOLS)
    # open_world's dry run must not be refused as busy: it previews the action, the gate decides.
    gz_service.sessions.close()
    created.clear()
    signals.clear()
    sid = gz_service.call("attach", {"family": "gz", "world": "empty"})["session_id"]
    for name, args in dry_runs.items():
        if name == "stop":
            continue  # attached sessions refuse stop outright; covered below with an owned one
        if name == "spawn":
            # the model store answer precedes any preview: an unknown model is a refusal
            result = gz_service.call(
                name, {**args, "session_id": sid, "model_sha256": "a" * 64, "dry_run": True}
            )
            assert result["ok"] is False and "not verified" in result["reason"]
            continue
        result = gz_service.call(
            name,
            {**args, "session_id": sid, "dry_run": True}
            if "session_id" in args
            else {**args, "dry_run": True},
        )
        assert result["ok"] is True and result["dry_run"] is True, (name, result)
        assert _complete(result["preview"]), (name, result["preview"])
        assert DIGEST.match(result["fingerprint"]), name
        assert set(result) >= {"ok", "dry_run", "preview", "fingerprint"}
    cold_simulator()  # the user's world went away; Solus may start its own `empty` now
    owned = gz_service.call("open_world", {"world_ref": "empty.sdf"})
    stop = gz_service.call("stop", {"session_id": owned["session_id"], "dry_run": True})
    assert stop["ok"] and stop["dry_run"] and _complete(stop["preview"])
    assert DIGEST.match(stop["fingerprint"])
    assert len(created) == 1 and signals == [], "a dry run touched a process"
    assert not (tmp_path / "worlds" / "copy.sdf").exists(), "a dry run wrote a file"
    # Fingerprints bind the arguments: a different target is a different fingerprint.
    a = gz_service.call(
        "set_joint_targets", {**dry_runs["set_joint_targets"], "session_id": sid, "dry_run": True}
    )
    other = {
        "session_id": sid,
        "model": "twolink",
        "targets": [{"joint": "shoulder", "position_rad": 0.5}],
    }
    b = gz_service.call("set_joint_targets", {**other, "dry_run": True})
    assert a["fingerprint"] != b["fingerprint"]


def test_wire_encode_chunks_declared_digest_fields_only() -> None:
    digest = "0123456789abcdef" * 4
    encoded = wire_encode(
        {"fingerprint": digest, "sha256": digest, "nested": {"sha256": digest}, "other": digest}
    )
    chunked = ":".join(digest[i : i + 16] for i in range(0, 64, 16))
    assert encoded["fingerprint"] == encoded["sha256"] == chunked
    assert encoded["nested"]["sha256"] == chunked
    assert encoded["other"] == digest


@pytest.mark.usefixtures("cold_simulator")
def test_results_never_carry_absolute_paths(
    gz_service: GazeboToolService, tmp_path: Path, fake_children: Children
) -> None:
    results = [
        gz_service.call("probe", {}),
        gz_service.call("list_worlds", {}),
        gz_service.call("open_world", {"world_ref": "missing.sdf"}),
        gz_service.call("open_world", {"world_ref": "empty.sdf", "dry_run": True}),
        gz_service.call("open_world", {"world_ref": "empty.sdf"}),
    ]
    sid = results[-1]["session_id"]
    results.append(
        gz_service.call("spawn", {"session_id": sid, "model_sha256": "b" * 64, "name": "x"})
    )
    results.append(
        gz_service.call("save_world", {"session_id": sid, "dest": "o.sdf", "dry_run": True})
    )
    text = json.dumps(results)
    assert str(tmp_path) not in text
    assert "/home/" not in text and "/tmp/" not in text


def test_cli_failures_and_unexpected_errors_are_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fixture_bins: Path
) -> None:
    monkeypatch.setenv("SOLUS_GAZEBO_PATH", str(fixture_bins / "gz8"))

    def failing(argv: list[str], timeout: float) -> Completed:
        if argv[1:3] == ["service", "-l"]:
            return Completed(tuple(argv), 0, "/world/empty/control\n", "")
        raise CliError(argv, f"{Path(argv[0]).name} exploded at /home/someone/secret")

    service = GazeboToolService(tmp_path, run=failing)
    sid = service.call("attach", {"family": "gz", "world": "empty"})["session_id"]
    result = service.call("list_models", {"session_id": sid})
    assert result["ok"] is False and result["code"] == "cli_failed"
    assert "/home/" not in result["reason"] and "exploded" in result["reason"]

    def crashing(argv: list[str], timeout: float) -> Completed:
        raise RuntimeError("bug")

    crashed = GazeboToolService(tmp_path, run=crashing).call("list_worlds", {})
    assert crashed["ok"] is False and crashed["code"] == "internal_error"


def test_encode_result_turns_an_unserializable_result_into_internal_error_not_is_error() -> None:
    """Wire serialization is inside the never-raises guard: a NaN that slipped through becomes
    `{ok: false, code: internal_error}` (isError stays False), never a raised ValueError."""
    good = encode_result({"ok": True, "sha256": "0123456789abcdef" * 4})
    assert good.isError is False and good.structuredContent is not None
    assert good.structuredContent["sha256"].count(":") == 3
    bad = encode_result({"ok": True, "samples": [{"position": float("nan")}]})
    assert bad.isError is False and bad.structuredContent is not None
    assert bad.structuredContent["ok"] is False
    assert bad.structuredContent["code"] == "internal_error"
    assert json.loads(bad.content[0].text) == bad.structuredContent  # type: ignore[union-attr]
