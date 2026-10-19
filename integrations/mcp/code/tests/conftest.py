"""Deterministic sandbox probe for the `code` server's unit tests (SOLUSDEV-317).

Planning refuses everything when no OS sandbox is available, so unit tests pin
the probe to this platform's kind. Tests that really execute through the sandbox
are marked `real_sandbox`: they see the real probe and skip when it fails.
"""

import sys
from collections.abc import Iterator

import pytest

from code_paths import overlay_module  # isort: skip

sandbox = overlay_module("sandbox")
FAKE_KIND = "sandbox-exec" if sys.platform == "darwin" else "landlock-abi3"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "real_sandbox: executes through the real OS sandbox (skips without one)"
    )
    config.addinivalue_line("markers", "own_sandbox_probe: the test manages the probe itself")


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
