"""The launcher resolves only this checkout's app ports without executing env text."""

import importlib.util
import os
import shutil
import socket
import subprocess
from pathlib import Path
from types import ModuleType

import pytest


@pytest.fixture
def ports() -> ModuleType:
    path = Path(__file__).resolve().parents[3] / "scripts/dev_ports.py"
    spec = importlib.util.spec_from_file_location("dev_ports", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_port_defaults_and_environment_precedence(ports: ModuleType, tmp_path: Path) -> None:
    config = tmp_path / ".env"
    config.write_text("VITE_API_BASE_URL=http://127.0.0.1:8123\nVITE_DEV_PORT=5210\n")
    assert ports.resolve_ports(config, {}) == (8123, 5210)
    assert ports.resolve_ports(config, {"VITE_DEV_PORT": "5211"}) == (8123, 5211)
    assert ports.resolve_ports(tmp_path / "absent", {}) == (8000, 5173)


def test_compose_database_only_matches_its_local_published_port(
    ports: ModuleType, tmp_path: Path
) -> None:
    config = tmp_path / ".env"
    config.write_text("SOLUS_DATABASE_URL=postgresql+asyncpg://u:p@db.example:5432/private\n")
    assert ports.database_mode(config, {}) == "external"
    assert (
        ports.database_mode(config, {"SOLUS_DATABASE_URL": "postgresql://localhost:5433/db"})
        == "external"
    )
    assert (
        ports.database_mode(config, {"SOLUS_DATABASE_URL": "postgresql://localhost:5432/db"})
        == "compose"
    )


@pytest.mark.parametrize(
    "value",
    ["0", "65536", "$(touch /tmp/should-never-run)", "${OTHER_PORT}", "abc"],
)
def test_invalid_port_is_refused_without_env_evaluation(
    ports: ModuleType, tmp_path: Path, value: str
) -> None:
    config = tmp_path / ".env"
    config.write_text(f"VITE_DEV_PORT='{value}'\n")
    with pytest.raises(ValueError, match="port"):
        ports.resolve_ports(config, {})


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com:8000",
        "http://user:secret@localhost:8000",
        "http://localhost:5173",
        "http://localhost:0",
    ],
)
def test_nonlocal_or_overlapping_api_is_refused(
    ports: ModuleType, tmp_path: Path, url: str
) -> None:
    with pytest.raises(ValueError):
        ports.resolve_ports(tmp_path / "absent", {"VITE_API_BASE_URL": url})


def test_bind_probe_detects_an_occupied_port_without_process_information(ports: ModuleType) -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        with pytest.raises(OSError):
            ports.check_available(listener.getsockname()[1])


def test_bind_probe_also_detects_ipv6_localhost_listener(ports: ModuleType) -> None:
    if not socket.has_ipv6:
        pytest.skip("IPv6 unavailable")
    with socket.socket(socket.AF_INET6) as listener:
        try:
            listener.bind(("::1", 0))
        except OSError:
            pytest.skip("IPv6 loopback unavailable")
        listener.listen()
        with pytest.raises(OSError):
            ports.check_available(listener.getsockname()[1])


@pytest.mark.parametrize("busy_port", [8123, 5210])
def test_busy_app_port_refuses_before_starting_services(tmp_path: Path, busy_port: int) -> None:
    root = Path(__file__).resolve().parents[3]
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copyfile(root / "scripts/dev-all.sh", scripts / "dev-all.sh")
    (tmp_path / ".env").write_text("VITE_SUPABASE_URL=https://example.invalid\n")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    log = tmp_path / "commands"
    for name, body in {
        "uv": "echo '8123 5210'",
        "docker": 'echo docker >> "$COMMAND_LOG"',
        "pnpm": 'echo pnpm >> "$COMMAND_LOG"',
        "lsof": (
            'echo "$*" >> "$COMMAND_LOG"; '
            'case "$*" in *":$BUSY_PORT "*) echo 12345; exit 0;; *) exit 1;; esac'
        ),
    }.items():
        path = binaries / name
        path.write_text(f"#!/bin/sh\n{body}\n")
        path.chmod(0o700)
    result = subprocess.run(
        ["bash", str(scripts / "dev-all.sh")],
        env={
            **os.environ,
            "PATH": f"{binaries}:/usr/bin:/bin",
            "COMMAND_LOG": str(log),
            "BUSY_PORT": str(busy_port),
        },
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 1
    assert f"port {busy_port} is occupied" in result.stdout
    commands = log.read_text().splitlines()
    assert commands == [
        "-nP -t -iTCP:8123 -sTCP:LISTEN",
        *(["-nP -t -iTCP:5210 -sTCP:LISTEN"] if busy_port == 5210 else []),
    ]


@pytest.mark.parametrize("failure", ["foreign", "startup", "readiness"])
def test_database_failure_prevents_application_start(tmp_path: Path, failure: str) -> None:
    root = Path(__file__).resolve().parents[3]
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copyfile(root / "scripts/dev-all.sh", scripts / "dev-all.sh")
    (tmp_path / ".env").write_text("VITE_SUPABASE_URL=https://example.invalid\n")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    log = tmp_path / "commands"
    for name, body in {
        "uv": 'case "$*" in *--check-port*) exit 0;; *) echo "8123 5210 compose";; esac',
        "docker": (
            'echo "docker $*" >> "$COMMAND_LOG"; '
            'case "$*" in *"up -d db"*) [ "$FAILURE" != startup ];; *) exit 1;; esac'
        ),
        "pnpm": 'echo pnpm >> "$COMMAND_LOG"',
        "lsof": (
            'if [ "$FAILURE" = foreign ]; then '
            'case "$*" in *:5432*) echo 12345; exit 0;; esac; fi; exit 1'
        ),
        "seq": "echo 1",
        "sleep": "exit 0",
    }.items():
        path = binaries / name
        path.write_text(f"#!/bin/sh\n{body}\n")
        path.chmod(0o700)
    result = subprocess.run(
        ["bash", str(scripts / "dev-all.sh")],
        env={
            **os.environ,
            "PATH": f"{binaries}:/usr/bin:/bin",
            "COMMAND_LOG": str(log),
            "FAILURE": failure,
        },
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 1
    commands = log.read_text()
    assert "pnpm" not in commands
    if failure == "foreign":
        assert "up -d" not in commands
        assert "occupied outside" in result.stdout
    elif failure == "readiness":
        assert "did not become ready" in result.stdout


def test_bind_probe_reuses_time_wait_socket(ports: ModuleType) -> None:
    with socket.socket() as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        with socket.create_connection(("127.0.0.1", port)) as client:
            accepted, _ = server.accept()
            accepted.close()
            client.recv(1)
    ports.check_available(port)


@pytest.mark.parametrize(
    "failure",
    ["schema", "api", "desktop", "unhealthy", "reload", "stdin", "worker", "redis_disabled"],
)
def test_dependency_and_api_failures_stop_launcher(tmp_path: Path, failure: str) -> None:
    root = Path(__file__).resolve().parents[3]
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copyfile(root / "scripts/dev-all.sh", scripts / "dev-all.sh")
    (tmp_path / "packages/api").mkdir(parents=True)
    (tmp_path / ".env").write_text("VITE_SUPABASE_URL=https://example.invalid\n")
    (tmp_path / "docker-compose.local.yml").write_text("services: {}\n")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    log = tmp_path / "commands"
    for name, body in {
        "node": 'case "$*" in *process.execPath*) echo "$NODE_PATH";; *) exit 0;; esac',
        "uv": (
            'echo "uv $*" >> "$COMMAND_LOG"; '
            'case "$*" in '
            "*dev_ports.py*--check-port*) exit 0;; "
            '*dev_ports.py*) echo "8123 5210 compose";; '
            '*--redis-mode*) if [ "$FAILURE" = redis_disabled ]; then echo disabled; '
            "else echo compose; fi;; "
            '*--schema*) [ "$FAILURE" != schema ];; '
            '*--ready*) if [ "$FAILURE" = unhealthy ] && grep -q pnpm "$COMMAND_LOG"; '
            "then exit 1; fi; "
            'if [ "$FAILURE" = reload ]; then '
            'checks=$(grep -c -- --ready "$COMMAND_LOG"); '
            'if [ "$checks" -ge 2 ] && [ "$checks" -le 3 ]; then exit 1; fi; fi; '
            '[ "$FAILURE" != api ];; '
            '*uvicorn*) if [ "$FAILURE" = api ]; then exit 7; else exec /bin/sleep 2; fi;; '
            '*"arq solus_api.worker_main.WorkerSettings"*) if [ "$FAILURE" = worker ]; '
            "then exit 8; else exec /bin/sleep 2; fi;; "
            "*) exit 0;; esac"
        ),
        "docker": (
            'echo "docker $*" >> "$COMMAND_LOG"; '
            'case "$*" in *pg_isready*) '
            'if [ "$FAILURE" = stdin ] && read -r line; then exit 1; fi;; esac; exit 0'
        ),
        "pnpm": (
            'echo pnpm >> "$COMMAND_LOG"; '
            'if [ "$FAILURE" = unhealthy ] || [ "$FAILURE" = worker ]; then /bin/sleep 2; '
            'elif [ "$FAILURE" = reload ]; then /bin/sleep 0.5; fi; exit 9'
        ),
        "lsof": "exit 1",
        "sleep": "/bin/sleep 0.01",
        "seq": "echo 1 2",
    }.items():
        path = binaries / name
        path.write_text(f"#!/bin/sh\n{body}\n")
        path.chmod(0o700)
    result = subprocess.run(
        ["bash", str(scripts / "dev-all.sh")],
        env={
            **os.environ,
            "PATH": f"{binaries}:/usr/bin:/bin",
            "NODE_PATH": str(binaries / "node"),
            "SOLUS_NODE_BIN": str(binaries / "node"),
            "COMMAND_LOG": str(log),
            "FAILURE": failure,
        },
        capture_output=True,
        text=True,
        input="terminal input\n" * 10,
        timeout=10,
        check=False,
    )
    assert result.returncode != 0
    commands = log.read_text()
    assert "-f docker-compose.local.yml" in commands
    assert "redis" in commands
    assert "--schema" in commands
    if failure in {"schema", "api"}:
        assert "pnpm" not in commands
    else:
        assert commands.index("--ready") < commands.index("pnpm")
    worker_command = "arq solus_api.worker_main.WorkerSettings"
    if failure in {"schema", "api", "redis_disabled"}:
        assert worker_command not in commands
    else:
        assert worker_command in commands
        assert result.stdout.index("starting background job worker") < result.stdout.index(
            "starting desktop app"
        )
    if failure == "worker":
        assert "background job worker stopped" in result.stdout
    if failure == "unhealthy":
        assert "API remained unhealthy" in result.stdout
    if failure == "reload":
        assert commands.count("--ready") > 3
        assert "API remained unhealthy" not in result.stdout


@pytest.fixture
def dependencies() -> ModuleType:
    path = Path(__file__).resolve().parents[3] / "scripts/dev_dependencies.py"
    spec = importlib.util.spec_from_file_location("dev_dependencies", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", "disabled"),
        ("redis://localhost:6379/0", "compose"),
        ("redis://localhost:6380/0", "external"),
        ("rediss://localhost:6379/0", "external"),
        ("redis://redis.example:6379/0", "external"),
    ],
)
def test_redis_respects_external_and_disabled_config(
    dependencies: ModuleType,
    tmp_path: Path,
    value: str,
    expected: str,
) -> None:
    assert dependencies.redis_mode(tmp_path / "absent", {"SOLUS_REDIS_URL": value}) == expected


@pytest.mark.parametrize("value", ["http://localhost", "redis://localhost:0", "redis://"])
def test_redis_rejects_invalid_config(dependencies: ModuleType, tmp_path: Path, value: str) -> None:
    with pytest.raises(ValueError):
        dependencies.redis_mode(tmp_path / "absent", {"SOLUS_REDIS_URL": value})


def test_readiness_ignores_proxy_and_refuses_redirects(
    dependencies: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import Mock

    response = Mock(status_code=302)
    get = Mock(return_value=response)
    monkeypatch.setattr(dependencies.httpx, "get", get)
    assert not dependencies.ready("8123")
    get.assert_called_once_with("http://127.0.0.1:8123/readyz", timeout=1, trust_env=False)
    response.status_code = 200
    assert dependencies.ready("8123")
    assert not dependencies.ready("0")
    assert not dependencies.ready("example.com")


@pytest.mark.asyncio
@pytest.mark.parametrize("current", [True, False])
async def test_schema_check_never_mutates_and_always_disposes(
    dependencies: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    current: bool,
) -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    import solus_api.core.config as config

    monkeypatch.setattr(
        config, "Settings", lambda: SimpleNamespace(database_url="unused", redis_url=None)
    )
    script = Mock()
    script.get_heads.return_value = ["head"]
    monkeypatch.setattr(dependencies, "ScriptDirectory", Mock(return_value=script))
    connection = AsyncMock()
    connection.run_sync.side_effect = [{"head"} if current else set(), current]
    context = AsyncMock()
    context.__aenter__.return_value = connection
    engine = Mock()
    engine.connect.return_value = context
    engine.dispose = AsyncMock()
    monkeypatch.setattr(dependencies, "create_async_engine", Mock(return_value=engine))
    if current:
        await dependencies.check_dependencies()
    else:
        with pytest.raises(ValueError, match="schema"):
            await dependencies.check_dependencies()
    engine.dispose.assert_awaited_once()
    assert connection.run_sync.await_count == 2
    connection.execute.assert_not_called()
