"""Native tests use a disposable runtime fixture, never a developer install."""

import pytest


@pytest.fixture(autouse=True)
def configured_runtime_fixture(tmp_path_factory, monkeypatch):
    root = tmp_path_factory.mktemp("isaac-runtime-fixture")
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
