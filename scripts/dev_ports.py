"""Resolve dev app ports from the root env without evaluating shell expressions."""

import errno
import os
import socket
import sys
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values


def _port(value: str) -> int:
    if not value.isascii() or not value.isdecimal() or not 1 <= int(value) <= 65535:
        raise ValueError("invalid configured app port")
    return int(value)


def resolve_ports(path: Path, environ: Mapping[str, str]) -> tuple[int, int]:
    config = dotenv_values(path, interpolate=False)
    api_url = environ.get("VITE_API_BASE_URL", config.get("VITE_API_BASE_URL"))
    url = urlsplit(api_url or "http://127.0.0.1:8000")
    if (
        url.scheme != "http"
        or url.hostname not in {"localhost", "127.0.0.1"}
        or url.username is not None
        or url.password is not None
        or url.query
        or url.fragment
    ):
        raise ValueError("dev launcher requires a local HTTP API URL without credentials")
    api = _port(str(80 if url.port is None else url.port))
    desktop = _port(environ.get("VITE_DEV_PORT", config.get("VITE_DEV_PORT") or "5173"))
    if api == desktop:
        raise ValueError("API and desktop ports must differ")
    return api, desktop


def database_mode(path: Path, environ: Mapping[str, str]) -> str:
    config = dotenv_values(path, interpolate=False)
    value = environ.get("SOLUS_DATABASE_URL", config.get("SOLUS_DATABASE_URL"))
    url = urlsplit(value or "postgresql+asyncpg://localhost:5432/solus")
    if url.scheme not in {"postgresql", "postgresql+asyncpg"} or not url.hostname:
        raise ValueError("invalid database configuration")
    port = _port(str(5432 if url.port is None else url.port))
    return "compose" if url.hostname in {"localhost", "127.0.0.1"} and port == 5432 else "external"


def check_available(port: int) -> None:
    """Detect listeners even when the OS hides their PID from lsof."""
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", port))
    if socket.has_ipv6:
        try:
            with socket.socket(socket.AF_INET6) as probe:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                probe.bind(("::1", port))
        except OSError as error:
            if error.errno not in {errno.EAFNOSUPPORT, errno.EADDRNOTAVAIL}:
                raise


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--check-port":
        try:
            check_available(_port(sys.argv[2]))
        except (OSError, ValueError):
            sys.exit("[dev:all] configured port cannot be bound — refusing to start")
        sys.exit(0)
    try:
        path = Path(__file__).resolve().parents[1] / ".env"
        resolved = resolve_ports(path, os.environ)
        database = database_mode(path, os.environ)
    except ValueError:
        # A malformed URL can contain a secret: never echo its exception or value.
        sys.exit("[dev:all] invalid local API URL or app ports in this checkout's configuration")
    print(*resolved, database)
