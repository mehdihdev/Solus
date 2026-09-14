"""Strict Uno compilation input, bounded snapshots and immutable artifact checks."""

import pytest
from pydantic import ValidationError

from code_paths import overlay_module  # isort: skip

compile_tool = overlay_module("arduino_compile")


@pytest.fixture
def sketch(tmp_path):
    root = tmp_path / "Blink"
    root.mkdir()
    (root / "Blink.ino").write_text("void setup() {}\nvoid loop() {}\n")
    return tmp_path


@pytest.mark.parametrize("value", ["", ".", "../x", "/tmp/x", "a/../x", "a\\b", "-bad", ".git/x"])
def test_invalid_sketch_arguments(value):
    with pytest.raises((ValidationError, compile_tool.ArduinoError)):
        compile_tool.CompileArgs.model_validate({"sketch": value, "fqbn": "arduino:avr:uno"})


def test_only_explicit_uno_and_strict_boolean_allowed():
    for args in [{"fqbn": "arduino:avr:nano"}, {"dry_run": "true"}, {"port": "/dev/ttyACM0"}]:
        with pytest.raises(ValidationError):
            compile_tool.CompileArgs.model_validate(
                {"sketch": "Blink", "fqbn": "arduino:avr:uno", **args}
            )


def test_source_snapshot_digest_binds_files_and_detects_changes(sketch):
    first = compile_tool.read_sketch(sketch, "Blink")
    (sketch / "Blink/local.h").write_text("#define TEST 1\n")
    second = compile_tool.read_sketch(sketch, "Blink")
    assert first.sha256 != second.sha256
    assert "local.h" in second.files


@pytest.mark.parametrize("name", ["sketch.yaml", "sketch.yml"])
def test_profile_refuses_before_execution(sketch, name):
    (sketch / "Blink" / name).write_text("default_port: /dev/ttyACM0")
    with pytest.raises(compile_tool.ArduinoError, match="profile_unsupported"):
        compile_tool.read_sketch(sketch, "Blink")


def test_symlinks_and_executable_scripts_refuse(sketch):
    link = sketch / "Blink/local.h"
    link.symlink_to("/etc/passwd")
    with pytest.raises(compile_tool.ArduinoError):
        compile_tool.read_sketch(sketch, "Blink")
    link.unlink()
    script = sketch / "Blink/build.sh"
    script.write_text("exit 0\n")
    script.chmod(0o755)
    with pytest.raises(compile_tool.ArduinoError):
        compile_tool.read_sketch(sketch, "Blink")


def test_primary_ino_required(sketch):
    (sketch / "Blink/Blink.ino").unlink()
    with pytest.raises(compile_tool.ArduinoError, match="invalid_sketch"):
        compile_tool.read_sketch(sketch, "Blink")


@pytest.fixture
def compiler(sketch, monkeypatch):
    runtime_module = overlay_module("arduino_toolchain")
    monkeypatch.setattr(runtime_module, "_application_root", lambda: sketch)
    monkeypatch.setattr(compile_tool, "verify_cli", lambda path: None)
    runtime = runtime_module.ArduinoRuntime()
    (runtime.root / "builds").mkdir(parents=True)
    (runtime.root / "data/packages").mkdir(parents=True)
    monkeypatch.setattr(
        runtime_module.ArduinoRuntime, "probe", lambda self: {"cli": {"available": True}}
    )
    monkeypatch.setattr(compile_tool, "verify_runtime", lambda *a, **kw: "a" * 64)
    monkeypatch.setattr(compile_tool, "_command", lambda *a, **kw: ("owned-sandbox-command",))

    def execute(argv, *, cwd, env, deadline, expect_json_success=False):
        assert expect_json_success is True
        assert (cwd / "source/Blink/Blink.ino").read_bytes() == (
            sketch / "Blink/Blink.ino"
        ).read_bytes()
        (cwd / "output/Blink.ino.hex").write_bytes(b":00000001FF\n")
        return {
            "ok": True,
            "started": True,
            "exit_code": 0,
            "reason": None,
            "stdout_tail": '{"success":true}',
            "stderr_tail": "",
            "stdout_truncated": False,
            "stderr_truncated": False,
            "timed_out": False,
        }

    monkeypatch.setattr(compile_tool, "run_bounded", execute)
    return sketch, runtime


def test_compile_preview_then_publish_and_verify_noop(compiler):
    root, runtime = compiler
    before = sorted(str(p) for p in root.rglob("*"))
    plan = compile_tool.arduino_compile(root, sketch="Blink", fqbn="arduino:avr:uno", dry_run=True)
    assert plan["dry_run"] and before == sorted(str(p) for p in root.rglob("*"))
    result = compile_tool.arduino_compile(root, sketch="Blink", fqbn="arduino:avr:uno")
    artifact = result["artifact_manifest"]
    assert result["ok"] and result["started"]
    assert (runtime.root / "builds" / artifact["build_id"] / "manifest.json").is_file()
    second = compile_tool.arduino_compile(root, sketch="Blink", fqbn="arduino:avr:uno")
    assert second["artifact_manifest"] == artifact and second["changed"] is False
    assert not second["started"]


def test_exit_zero_with_unsuccessful_json_never_publishes(compiler, monkeypatch):
    root, runtime = compiler
    monkeypatch.setattr(
        compile_tool,
        "run_bounded",
        lambda *a, **kw: {
            "ok": False,
            "started": True,
            "exit_code": 0,
            "reason": "compilation_unverified",
            "stdout_tail": '{"success":false}',
            "stderr_tail": "",
            "stdout_truncated": False,
            "stderr_truncated": False,
            "timed_out": False,
        },
    )
    result = compile_tool.arduino_compile(root, sketch="Blink", fqbn="arduino:avr:uno")
    assert not result["ok"] and result["exit_code"] == 0
    assert "artifact_manifest" not in result
    assert not list((runtime.root / "builds").glob("*/manifest.json"))


def test_changed_source_after_compiler_does_not_publish(compiler, monkeypatch):
    root, runtime = compiler
    execute = compile_tool.run_bounded

    def mutate(*args, **kwargs):
        result = execute(*args, **kwargs)
        (root / "Blink/Blink.ino").write_text("changed")
        return result

    monkeypatch.setattr(compile_tool, "run_bounded", mutate)
    result = compile_tool.arduino_compile(root, sketch="Blink", fqbn="arduino:avr:uno")
    assert not result["ok"] and "artifact_manifest" not in result
    assert not list((runtime.root / "builds").glob("*/manifest.json"))


def test_empty_directories_count_toward_snapshot_bound(sketch, monkeypatch):
    monkeypatch.setattr(compile_tool, "MAX_SOURCE_ENTRIES", 3)
    for name in ("a", "b", "c", "d"):
        (sketch / "Blink" / name).mkdir()
    with pytest.raises(compile_tool.ArduinoError, match="resource_limit"):
        compile_tool.read_sketch(sketch, "Blink")


def test_failed_attempt_cleanup_allows_another_approved_attempt(compiler, monkeypatch):
    root, runtime = compiler
    execute = compile_tool.run_bounded
    monkeypatch.setattr(
        compile_tool,
        "run_bounded",
        lambda *a, **kw: {
            "ok": False,
            "started": True,
            "exit_code": 1,
            "reason": "command_failed",
            "stdout_tail": "",
            "stderr_tail": "failure",
            "stdout_truncated": False,
            "stderr_truncated": False,
            "timed_out": False,
        },
    )
    failed = compile_tool.arduino_compile(root, sketch="Blink", fqbn="arduino:avr:uno")
    assert not failed["ok"] and not list((runtime.root / "builds").iterdir())
    monkeypatch.setattr(compile_tool, "run_bounded", execute)
    succeeded = compile_tool.arduino_compile(root, sketch="Blink", fqbn="arduino:avr:uno")
    assert succeeded["ok"] and not list((runtime.root / "builds").glob(".pending-*"))


def test_atomic_publication_never_replaces_existing_directory(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (target / "keep.txt").write_text("keep")
    with pytest.raises(compile_tool.ArduinoError, match="stale_state"):
        compile_tool._publish_noreplace(source, target)
    assert (target / "keep.txt").read_text() == "keep" and source.is_dir()


def test_artifact_summary_precedes_logs_and_preserves_raw_manifest(compiler):
    import re

    root, _ = compiler
    result = compile_tool.arduino_compile(root, sketch="Blink", fqbn="arduino:avr:uno")
    assert next(iter(result)) == "artifact_summary"
    summary = result["artifact_summary"]
    assert re.fullmatch(r"[0-9a-f]{16}(?::[0-9a-f]{16}){3}", summary["manifest_fingerprint"])
    assert (
        summary["manifest_fingerprint"].replace(":", "")
        == result["artifact_manifest"]["manifest_sha256"]
    )


def test_cleanup_never_erases_swapped_real_directory(tmp_path):
    import os

    job = tmp_path / "attempt"
    job.mkdir()
    (job / "owned.tmp").write_text("owned")
    parent_fd = compile_tool.open_directory(tmp_path)
    job_fd = compile_tool.open_directory(job)
    job.rename(tmp_path / "moved-owned-attempt")
    job.mkdir()
    (job / "keep.txt").write_text("not owned by this attempt")
    try:
        compile_tool._cleanup_job("attempt", parent_fd, job_fd)
    finally:
        os.close(job_fd)
        os.close(parent_fd)
    assert (job / "keep.txt").read_text() == "not owned by this attempt"
    assert not list((tmp_path / "moved-owned-attempt").iterdir())


def test_partial_snapshot_copy_is_cleaned_without_blocking_next_attempt(compiler, monkeypatch):
    root, runtime = compiler
    original = compile_tool._prepare_job

    def fail_copy(job, *args):
        (job / "partial.tmp").write_text("partial")
        raise compile_tool.ArduinoError("stale_state")

    monkeypatch.setattr(compile_tool, "_prepare_job", fail_copy)
    with pytest.raises(compile_tool.ArduinoError, match="stale_state"):
        compile_tool.arduino_compile(root, sketch="Blink", fqbn="arduino:avr:uno")
    assert not list((runtime.root / "builds").iterdir())
    monkeypatch.setattr(compile_tool, "_prepare_job", original)
    assert compile_tool.arduino_compile(root, sketch="Blink", fqbn="arduino:avr:uno")["ok"]
