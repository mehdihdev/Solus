"""`scripts/seed-provider-keys.py` mapping ratchet.

The failure mode this pins: a key sits in the root `.env` while the code reads
it through a SecretStore ref nothing ever seeds — every SOL turn then fails on
what looks like a code bug. The script's mapping must therefore cover every
ref the code reads that a developer sources from an env var, under the exact
env names a developer actually has on disk.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from solus_api.agent.tools.mcp_servers import WEB_SEARCH
from solus_api.orchestration.providers import (
    ANTHROPIC_API_KEY_NAME,
    GOOGLE_API_KEY_NAME,
    OPENAI_API_KEY_NAME,
)

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "seed-provider-keys.py"


@pytest.fixture(scope="module")
def script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("seed_provider_keys", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_env_sourced_ref_is_seedable(script: ModuleType) -> None:
    refs = {ref for _envs, ref in script.SEED_KEYS.values()}
    assert refs == {
        ANTHROPIC_API_KEY_NAME,
        OPENAI_API_KEY_NAME,
        GOOGLE_API_KEY_NAME,
        *WEB_SEARCH.required_secrets,
    }


def test_env_names_match_what_developers_have(script: ModuleType) -> None:
    by_key = {key: envs for key, (envs, _ref) in script.SEED_KEYS.items()}
    assert by_key["anthropic"] == ("ANTHROPIC_API_KEY",)
    assert by_key["openai"] == ("OPENAI_API_KEY",)
    # Google's own docs tell people to export GEMINI_API_KEY; accept both.
    assert by_key["google"] == ("GOOGLE_API_KEY", "GEMINI_API_KEY")
    assert by_key["brave"] == ("BRAVE_API_KEY",)


def test_first_non_empty_env_wins(script: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "  gm-key  ")
    assert script.resolve_value(("GOOGLE_API_KEY", "GEMINI_API_KEY")) == (
        "GEMINI_API_KEY",
        "gm-key",
    )
    monkeypatch.setenv("GOOGLE_API_KEY", "gk-key")
    assert script.resolve_value(("GOOGLE_API_KEY", "GEMINI_API_KEY")) == (
        "GOOGLE_API_KEY",
        "gk-key",
    )


def test_blank_values_are_skipped(script: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRAVE_API_KEY", "   ")
    assert script.resolve_value(("BRAVE_API_KEY",)) is None
