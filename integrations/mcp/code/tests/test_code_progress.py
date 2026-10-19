"""Bounded line-preserving progress without command replay."""

import sys
import time
from pathlib import Path

import pytest
from code_paths import overlay_module

execute = overlay_module("execute")


def test_runner_emits_before_completion_and_keeps_final_tail(tmp_path: Path) -> None:
    chunks = []
    start = time.monotonic()
    token = execute.OUTPUT_CALLBACK.set(
        lambda stream, text: chunks.append((stream, text, time.monotonic() - start))
    )
    try:
        result = execute.default_runner(
            [
                sys.executable,
                "-c",
                "import time; print('first',flush=True); time.sleep(.4); print('last')",
            ],
            tmp_path,
            {},
            3,
        )
    finally:
        execute.OUTPUT_CALLBACK.reset(token)
    assert chunks[0][:2] == ("stdout", "first\n")
    assert chunks[0][2] < 0.3
    assert result.stdout == b"first\nlast\n"


def test_lines_are_never_split_and_oversized_line_is_suppressed(tmp_path: Path) -> None:
    chunks = []
    token = execute.OUTPUT_CALLBACK.set(lambda stream, text: chunks.append((stream, text)))
    try:
        result = execute.default_runner(
            [
                sys.executable,
                "-c",
                "import sys; sys.stdout.write('x'*20000+'\\nlast'); sys.stderr.write('error\\n')",
            ],
            tmp_path,
            {},
            3,
        )
    finally:
        execute.OUTPUT_CALLBACK.reset(token)
    assert result.exit_code == 0
    assert ("stdout", "last") not in chunks
    assert ("stderr", "error\n") in chunks
    assert not any("xxx" in text for _, text in chunks)
    assert any("suppressed" in text for _, text in chunks)


def test_callback_failure_never_replays_or_changes_result(tmp_path: Path) -> None:
    def fail(stream: str, text: str) -> None:
        raise RuntimeError("disconnected")

    token = execute.OUTPUT_CALLBACK.set(fail)
    try:
        result = execute.default_runner([sys.executable, "-c", "print('done')"], tmp_path, {}, 3)
    finally:
        execute.OUTPUT_CALLBACK.reset(token)
    assert result.exit_code == 0 and result.stdout == b"done\n"


def test_progress_budget_is_bounded() -> None:
    progress = overlay_module("progress")
    chunks = []
    observer = progress.LineOutput(lambda stream, text: chunks.append((stream, text)))
    observer.feed("stdout", b"ok\n" * 2000)
    observer.finish()
    assert len(chunks) <= 256
    assert "truncated" in chunks[-1][1]


def test_line_buffer_handles_split_unicode_and_partial_secret_line() -> None:
    progress = overlay_module("progress")
    chunks = []
    observer = progress.LineOutput(lambda stream, text: chunks.append((stream, text)))
    observer.feed("stdout", "é".encode()[:1])
    observer.feed("stdout", "é".encode()[1:] + b" Authorization: Bearer ")
    assert chunks == []
    observer.feed("stdout", b"placeholder\n")
    assert chunks == [("stdout", "é Authorization: Bearer placeholder\n")]


def test_cancellation_kills_command_without_waiting_for_timeout(tmp_path: Path) -> None:
    import threading

    cancelled = threading.Event()
    cancelled.set()
    token = execute.CANCEL_EVENT.set(cancelled)
    started = time.monotonic()
    try:
        result = execute.default_runner(
            [sys.executable, "-c", "import time; time.sleep(30)"], tmp_path, {}, 30
        )
    finally:
        execute.CANCEL_EVENT.reset(token)
    assert result.timed_out and time.monotonic() - started < 2


def test_unicode_output_byte_budget_and_partial_final_decoder() -> None:
    progress = overlay_module("progress")
    chunks = []
    observer = progress.LineOutput(lambda stream, text: chunks.append((stream, text)))
    observer.feed("stdout", (("界" * 2000 + "\n") * 200).encode())
    observer.finish()
    assert sum(len(text.encode()) for _, text in chunks) <= 256 * 1024
    assert "truncated" in chunks[-1][1]
    chunks.clear()
    observer = progress.LineOutput(lambda stream, text: chunks.append((stream, text)))
    observer.feed("stderr", b"partial\xc3")
    observer.finish()
    assert chunks == [("stderr", "partial�")]


async def test_async_queue_is_bounded_and_reports_overflow() -> None:
    import json

    progress = overlay_module("progress")
    chunks = []

    class Context:
        async def report_progress(self, sequence: float, *, message: str) -> None:
            chunks.append(json.loads(message or "null"))

    output = progress.AsyncOutput(Context())
    for _ in range(1000):
        output.output("stdout", "line\n")
    assert output.pending.qsize() == 16 and output.overflow.is_set()
    output.finished.set()
    await output.publish()
    assert chunks[-1]["text"] == progress.TRUNCATED


@pytest.fixture
def base(tmp_path: Path) -> Path:
    (tmp_path / "home").mkdir()
    return tmp_path


@pytest.mark.real_sandbox
async def test_actual_stdio_mcp_reports_output_before_final_result(base: Path) -> None:
    import asyncio
    import json

    from code_paths import FORK_DIR
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    tmp_path = base / "ws"
    binary = tmp_path / ".venv" / "bin"
    binary.mkdir(parents=True)
    (binary / "python").symlink_to(sys.executable)
    (binary.parent / "pyvenv.cfg").write_text("home = /usr/bin\nversion = 3.12\n")
    (tmp_path / "sample.py").write_text(
        "import time\nprint('early',flush=True)\ntime.sleep(.7)\nprint('done')\n"
    )
    chunks = []

    async def progress(progress: float, total: float | None, message: str | None) -> None:
        chunks.append(json.loads(message or "null"))

    params = StdioServerParameters(
        command=sys.executable,
        args=[str(FORK_DIR / "solus" / "server.py")],
        env={
            "SOLUS_MCP_WORKSPACE": str(tmp_path),
            "PATH": "/usr/bin:/bin",
            # HOME is never the workspace (§9.4): a separate temp home.
            "HOME": str(base / "home"),
        },
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        result_task = asyncio.create_task(
            session.call_tool("run", {"script": "sample.py"}, progress_callback=progress)
        )
        for _ in range(100):
            if chunks:
                break
            await asyncio.sleep(0.01)
        assert chunks and not result_task.done()
        result = await result_task
    assert not result.isError
    assert chunks[0] == {"stream": "stdout", "text": "early\n"}
    assert result.structuredContent is not None
    assert result.structuredContent["stdout_tail"] == "early\ndone\n"


def test_oversized_secret_prefix_suppresses_rest_of_stream() -> None:
    progress = overlay_module("progress")
    chunks = []
    observer = progress.LineOutput(lambda stream, text: chunks.append((stream, text)))
    observer.feed("stdout", b"api_key=" + b" " * 2048 + b"\nexample-value\n")
    observer.feed("stderr", b"safe diagnostic\n")
    observer.finish()
    assert not any("example-value" in text for _, text in chunks)
    assert ("stderr", "safe diagnostic\n") in chunks


def test_already_cancelled_execution_never_launches_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    cancelled = threading.Event()
    cancelled.set()
    calls = []
    monkeypatch.setattr(execute.subprocess, "Popen", lambda *args, **kwargs: calls.append(args))
    token = execute.CANCEL_EVENT.set(cancelled)
    try:
        result = execute.default_runner(
            [sys.executable, "-c", "print('must not run')"], tmp_path, {}, 30
        )
    finally:
        execute.CANCEL_EVENT.reset(token)
    assert calls == [] and result.timed_out


def test_post_exit_spool_drain_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import io
    from types import SimpleNamespace

    reads = []

    class EndlessSpool(io.BytesIO):
        def read(self, size: int | None = -1) -> bytes:
            reads.append(size)
            if len(reads) > 40:
                raise RuntimeError("unbounded post-exit spool scan")
            return b"x" * 8192

    handles = iter([io.BytesIO(), io.BytesIO(), EndlessSpool(), io.BytesIO()])
    monkeypatch.setattr(execute, "open", lambda *args, **kwargs: next(handles), raising=False)
    monkeypatch.setattr(
        execute.subprocess,
        "Popen",
        lambda *args, **kwargs: SimpleNamespace(
            poll=lambda: 0, wait=lambda: 0, returncode=0, pid=2**22 + 4321, kill=lambda: None
        ),
    )
    # Popen is faked module-wide, so the tree's (always fresh) kill-time snapshot reads
    # an empty table instead of running /bin/ps through the fake.
    tracker = execute.TreeTracker
    monkeypatch.setattr(execute, "TreeTracker", lambda pid: tracker(pid, table=dict))
    chunks = []
    token = execute.OUTPUT_CALLBACK.set(lambda stream, text: chunks.append((stream, text)))
    try:
        result = execute.default_runner(["unused"], tmp_path, {}, 30)
    finally:
        execute.OUTPUT_CALLBACK.reset(token)
    assert result.exit_code == 0 and len(reads) <= 32


def test_post_exit_drain_raw_budget_and_deadline_drop_partial_context() -> None:
    import io

    progress = overlay_module("progress")
    chunks = []

    class GrowingSpool:
        reads = 0

        def read(self, size: int) -> bytes:
            self.reads += 1
            return (b"x" * 2000 + b"\n") * 4

    reader = GrowingSpool()
    observer = progress.LineOutput(lambda stream, text: chunks.append((stream, text)))
    execute._drain_output(observer, "stdout", reader, time.monotonic() + 10, None)
    assert reader.reads == 32 and observer.discard["stdout"]
    assert chunks[-1][1] == progress.TRUNCATED
    chunks.clear()
    observer = progress.LineOutput(lambda stream, text: chunks.append((stream, text)))
    observer.feed("stdout", b"unfinished")
    execute._drain_output(observer, "stdout", io.BytesIO(b"other"), 0, None)
    observer.finish()
    assert chunks == [("stdout", progress.TRUNCATED)]
