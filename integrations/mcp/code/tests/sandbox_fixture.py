"""Deterministic sandbox probe for the `code` server's unit tests (SOLUSDEV-317).

Not a conftest.py: a second top-level `conftest` module would shadow
packages/api/tests/conftest.py for mypy. Each test module that plans or executes
imports the two autouse fixtures below (`from sandbox_fixture import *`-style,
by name), which makes them apply to every test in that module.

Planning refuses everything when no OS sandbox is available, so unit tests pin
the probe to this platform's kind. Tests that really execute through the sandbox
are marked `real_sandbox`: they see the real probe and skip when it fails.
"""

import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from code_paths import overlay_module  # isort: skip

sandbox = overlay_module("sandbox")
FAKE_KIND = "sandbox-exec" if sys.platform == "darwin" else "landlock-abi3"


def real_sandbox_kind() -> str | None:
    return sandbox.probe()[0]  # type: ignore[no-any-return]


@pytest.fixture(autouse=True)
def pinned_sandbox_probe(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    sandbox.available.cache_clear()
    if request.node.get_closest_marker("own_sandbox_probe") is not None:
        pass
    elif request.node.get_closest_marker("real_sandbox") is not None:
        if real_sandbox_kind() is None:
            pytest.skip("no OS sandbox on this machine")
    else:
        monkeypatch.setattr(sandbox, "available", lambda: (FAKE_KIND, "available"))
    yield


@pytest.fixture(autouse=True)
def test_writable_roots(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """Fixtures live under the system temp dir, which the §9.5 program check treats as
    writable. Unless a test opts in to the real roots, the check sees the HOME caches
    plus a dedicated scratch dir instead (the sandbox itself is unchanged)."""
    if request.node.get_closest_marker("real_writable_roots") is not None:
        return
    scratch = str(tmp_path_factory.mktemp("sandbox-writable").resolve())

    def roots(home: Path | None = None, tmpdir: Path | None = None) -> list[str]:
        base = home if home is not None else sandbox.default_home()
        return [scratch, *(os.path.realpath(base / cache) for cache in sandbox.HOME_CACHES)]

    monkeypatch.setattr(sandbox, "writable_roots", roots)
