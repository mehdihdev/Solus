"""Every fork lockfile must be installable under the setup rule of the ADR-031
amendment (2026-11-19): `pip install --require-hashes --only-binary=:all:`.

A pin whose release ships only an sdist (pyperclip 1.9.0 did) can never install,
on any Python, so a fork with one is dead on every customer machine. This asks
PyPI whether each pinned version has at least one wheel whose sha256 is among the
lock's hashes for it. Needs network; skipped offline (SOLUSDEV-329).
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

import pytest

MCP_ROOT = Path(__file__).resolve().parents[1]
LOCKS = sorted(MCP_ROOT.glob("*/requirements.lock.txt"))
_PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s;\\]+)")
_HASH = re.compile(r"--hash=sha256:([0-9a-f]{64})")


def _pins(lock: Path) -> dict[tuple[str, str], set[str]]:
    pins: dict[tuple[str, str], set[str]] = {}
    current: tuple[str, str] | None = None
    for line in lock.read_text().splitlines():
        match = _PIN.match(line)
        if match:
            current = (match.group(1).lower(), match.group(2))
            pins.setdefault(current, set())
        if current is not None:
            pins[current].update(_HASH.findall(line))
    return pins


def _wheel_hashes(name: str, version: str) -> set[str]:
    url = f"https://pypi.org/pypi/{name}/{version}/json"
    for attempt in range(3):  # PyPI reads occasionally time out or drop
        try:
            with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310 - fixed host
                files = json.load(response)["urls"]
            break
        except urllib.error.HTTPError:
            raise  # PyPI answered: a missing release is a real lockfile defect
        except OSError as exc:  # URLError, TimeoutError, RemoteDisconnected
            if attempt == 2:
                pytest.skip(f"pypi.org unreachable for {name}=={version}: {exc}")
    return {f["digests"]["sha256"] for f in files if f["filename"].endswith(".whl")}


def _online() -> bool:
    try:
        urllib.request.urlopen("https://pypi.org/simple/pip/", timeout=5).close()  # noqa: S310
    except OSError:
        return False
    return True


@pytest.mark.skipif(not _online(), reason="needs network access to pypi.org")
@pytest.mark.parametrize("lock", LOCKS, ids=lambda p: p.parent.name)
def test_every_pin_has_a_hashed_wheel(lock: Path) -> None:
    missing = [
        f"{name}=={version}"
        for (name, version), hashes in _pins(lock).items()
        if not (_wheel_hashes(name, version) & hashes)
    ]
    assert not missing, f"{lock.parent.name}: no pinned wheel for {missing}"
