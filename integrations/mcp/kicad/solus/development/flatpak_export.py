"""Fixed native captures and bounded stdin snapshots inside KiCad's namespace.

Flatpak 1.14 cannot forward host FDs. Its helper receives only captured bytes,
materializes them in container-private temporary storage, and inherits an
anonymous output FD into the pinned CLI. Workspace capabilities cannot access
these private directories; arbitrary same-user OS code is outside this boundary.
"""

import base64
import json
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

MAX_EXPORT_BYTES = 32 * 1024 * 1024
MAX_REPORT_BYTES = 8 * 1024 * 1024
MAX_PAYLOAD_BYTES = 45 * 1024 * 1024
ERC = [
    "sch",
    "erc",
    "--format",
    "json",
    "--units",
    "mm",
    "--severity-all",
    "--exit-code-violations",
]
NETLIST = ["sch", "export", "netlist", "--format", "kicadxml"]


def _capture(source: str, cli: str, prefix: list[str], maximum: int) -> tuple[int, bytes] | None:
    if not Path(source).is_absolute() or not source.endswith(".kicad_sch") or "\0" in source:
        return None
    try:
        with tempfile.TemporaryFile() as output:
            descriptor = output.fileno()
            fd_root = "/proc/self/fd" if Path("/proc/self/fd").is_dir() else "/dev/fd"
            result = subprocess.run(  # noqa: S603 — pinned binary and fixed operation
                [cli, *prefix, "--output", f"{fd_root}/{descriptor}", source],
                pass_fds=(descriptor,),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
                check=False,
            )
            if result.returncode not in ((0, 5) if prefix == ERC else (0,)):
                return None
            output.seek(0)
            data = output.read(maximum + 1)
            return (result.returncode, data) if len(data) <= maximum else None
    except (OSError, subprocess.SubprocessError):
        return None


def capture_netlist(source: str) -> bytes | None:
    result = _capture(source, "/app/bin/kicad-cli", NETLIST, MAX_EXPORT_BYTES)
    return result[1] if result else None


def capture_erc(source: str, cli: str = "/app/bin/kicad-cli") -> tuple[int, bytes] | None:
    return _capture(source, cli, ERC, MAX_REPORT_BYTES)


def encode_snapshot(source: str, files: dict[str, bytes]) -> bytes:
    return json.dumps(
        {
            "source": source,
            "files": {name: base64.b64encode(raw).decode("ascii") for name, raw in files.items()},
        },
        separators=(",", ":"),
    ).encode()


def _decode_snapshot(payload: bytes) -> tuple[str, dict[str, bytes]]:
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise ValueError("snapshot too large")
    body = json.loads(payload)
    if not isinstance(body, dict) or set(body) != {"source", "files"}:
        raise ValueError("invalid snapshot")
    entries = body["files"]
    if not isinstance(entries, dict) or not 1 <= len(entries) <= 64:
        raise ValueError("invalid sheets")
    files: dict[str, bytes] = {}
    total = 0
    for name, encoded in entries.items():
        path = PurePosixPath(name)
        if (
            not name
            or path.is_absolute()
            or str(path) != name
            or ".." in path.parts
            or any(c in name for c in "\\:$\0")
            or not name.endswith(".kicad_sch")
            or not isinstance(encoded, str)
        ):
            raise ValueError("invalid sheet path")
        raw = base64.b64decode(encoded, validate=True)
        total += len(raw)
        if len(raw) > MAX_REPORT_BYTES or total > MAX_EXPORT_BYTES:
            raise ValueError("snapshot too large")
        files[name] = raw
    source = body["source"]
    if not isinstance(source, str) or source not in files:
        raise ValueError("missing root sheet")
    return source, files


def capture_snapshot(payload: bytes, *, erc: bool = False) -> tuple[int, bytes] | None:
    try:
        source, files = _decode_snapshot(payload)
        with tempfile.TemporaryDirectory(prefix="solus-kicad-") as directory:
            root = Path(directory)
            for name, raw in files.items():
                path = root / name
                path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                path.write_bytes(raw)
            if erc:
                return capture_erc(str(root / source))
            data = capture_netlist(str(root / source))
            return (0, data) if data is not None else None
    except (OSError, ValueError, TypeError):
        return None


def main() -> None:
    if sys.argv[1:] not in (["netlist"], ["erc"]):
        raise SystemExit(2)
    result = capture_snapshot(
        sys.stdin.buffer.read(MAX_PAYLOAD_BYTES + 1), erc=sys.argv[1] == "erc"
    )
    if result is None:
        raise SystemExit(1)
    code, data = result
    sys.stdout.buffer.write(data)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
