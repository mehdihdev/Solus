"""API image inputs must include the contracts imported by widget capabilities."""

import shlex
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_api_contracts_are_locked_runtime_dependencies():
    manifest = tomllib.loads((ROOT / "packages/api/pyproject.toml").read_text())
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    api = next(package for package in lock["package"] if package["name"] == "solus-api")
    assert "solus-contracts" in manifest["project"]["dependencies"]
    assert "solus-contracts" not in manifest["dependency-groups"]["dev"]
    assert {"name": "solus-contracts"} in api["dependencies"]
    assert manifest["tool"]["uv"]["sources"]["solus-contracts"] == {"workspace": True}


def test_image_copies_contract_inputs_before_their_install_layers():
    instructions = [
        shlex.split(line)
        for line in (ROOT / "infrastructure/docker/api.Dockerfile").read_text().splitlines()
        if line.startswith(("COPY ", "RUN uv sync "))
    ]
    dependency_install = instructions.index(
        [
            "RUN",
            "uv",
            "sync",
            "--frozen",
            "--no-dev",
            "--no-install-workspace",
            "--package",
            "solus-api",
        ]
    )
    source_install = instructions.index(
        ["RUN", "uv", "sync", "--frozen", "--no-dev", "--package", "solus-api"]
    )
    manifest_copy = instructions.index(
        ["COPY", "packages/contracts/python/pyproject.toml", "./packages/contracts/python/"]
    )
    source_copy = instructions.index(
        [
            "COPY",
            "packages/contracts/python/solus_contracts",
            "./packages/contracts/python/solus_contracts",
        ]
    )
    assert manifest_copy < dependency_install < source_copy < source_install


def test_image_ships_runtime_customer_shape_rules_after_dependency_install():
    dockerfile = (ROOT / "infrastructure/docker/api.Dockerfile").read_text()
    relative = "packages/shared-types/fixtures/tool-knowledge/customer-shapes.json"
    assert (ROOT / relative).is_file()
    copy = dockerfile.index(f"COPY {relative} ./{relative}")
    assert dockerfile.index("RUN uv sync --frozen --no-dev --package solus-api") < copy
    assert copy < dockerfile.index("RUN useradd")
