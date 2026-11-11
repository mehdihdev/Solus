from pathlib import Path

import pytest

from integrations.mcp.isaac.solus.controller import Controller


def test_missing_runtime_is_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOLUS_ISAAC_RUNTIME", raising=False)
    controller = Controller(tmp_path)
    assert controller.probe()["available"] is False
    with pytest.raises(ValueError, match="runtime unavailable"):
        controller.start(dry_run=True)


@pytest.mark.parametrize("value", ["relative/runtime", "", "https://example.test/runtime"])
def test_invalid_runtime_has_no_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("SOLUS_ISAAC_RUNTIME", value)
    assert Controller(tmp_path).probe()["available"] is False


def test_configured_runtime_is_captured_without_arm_assumption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "installation"
    for name in (
        "python.sh",
        "setup_python_env.sh",
        "VERSION",
        "kit/python/bin/python3",
        "apps/isaacsim.exp.base.python.kit",
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture")
    monkeypatch.setenv("SOLUS_ISAAC_RUNTIME", str(root))
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    controller = Controller(tmp_path)
    monkeypatch.setenv("SOLUS_ISAAC_RUNTIME", str(tmp_path / "other"))
    assert controller.probe()["available"] is True
    assert controller.start(dry_run=True)["dry_run"] is True


def test_companion_declares_only_runtime_setting() -> None:
    from solus_companion.config import _env_passthrough

    root = Path(__file__).resolve().parents[1]
    assert _env_passthrough(root, "isaac") == ("SOLUS_ISAAC_RUNTIME", "SOLUS_SIM_ROOTS")


def test_launcher_preserves_runtime_but_drops_python_poison(tmp_path: Path) -> None:
    import json
    import subprocess
    import sys

    interpreter = tmp_path / "capture-python"
    interpreter.write_text(
        f"#!{sys.executable}\nimport os, json\nprint(json.dumps(dict(os.environ)))\n"
    )
    interpreter.chmod(0o700)
    launcher = Path(__file__).resolve().parents[1] / "bin/launch"
    result = subprocess.run(
        ["/bin/sh", str(launcher)],
        env={
            "SOLUS_MCP_PYTHON": str(interpreter),
            "SOLUS_MCP_WORKSPACE": str(tmp_path),
            "SOLUS_ISAAC_RUNTIME": str(tmp_path / "installation"),
            "SOLUS_SIM_ROOTS": str(tmp_path / "stages"),
            "PYTHONPATH": "/poison",
            "AWS_SECRET_ACCESS_KEY": "test-poison",
        },
        capture_output=True,
        text=True,
        check=True,
    )
    captured = json.loads(result.stdout)
    assert captured["SOLUS_ISAAC_RUNTIME"] == str(tmp_path / "installation")
    assert captured["SOLUS_SIM_ROOTS"] == str(tmp_path / "stages")
    assert set(captured) == {
        "PATH",
        "LANG",
        "SOLUS_MCP_WORKSPACE",
        "SOLUS_ISAAC_RUNTIME",
        "SOLUS_SIM_ROOTS",
    }
    assert "PYTHONPATH" not in captured
    assert "AWS_SECRET_ACCESS_KEY" not in captured
