"""`scripts/seed-provider-keys.py` — mapping ratchet, .env guard, --check shape.

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
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.orchestration.providers import (
    ANTHROPIC_API_KEY_NAME,
    GOOGLE_API_KEY_NAME,
    OPENAI_API_KEY_NAME,
)

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "seed-provider-keys.py"
VALUE = "placeholder-not-a-real-key-0123456789"  # test-only sentinel


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


def test_first_non_empty_source_entry_wins(script: ModuleType) -> None:
    names = ("GOOGLE_API_KEY", "GEMINI_API_KEY")
    assert script.resolve_value(names, {"GEMINI_API_KEY": "  gm-key  "}) == (
        "GEMINI_API_KEY",
        "gm-key",
    )
    assert script.resolve_value(names, {"GOOGLE_API_KEY": "gk-key", "GEMINI_API_KEY": "gm"}) == (
        "GOOGLE_API_KEY",
        "gk-key",
    )


def test_blank_and_none_values_are_skipped(script: ModuleType) -> None:
    assert script.resolve_value(("BRAVE_API_KEY",), {"BRAVE_API_KEY": "   "}) is None
    assert script.resolve_value(("BRAVE_API_KEY",), {"BRAVE_API_KEY": None}) is None
    assert script.resolve_value(("BRAVE_API_KEY",), {}) is None


def test_values_never_come_from_os_environ(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", VALUE)
    assert script.resolve_value(("ANTHROPIC_API_KEY",), {}) is None
    assert "os.environ" not in _SCRIPT.read_text()


def test_missing_root_env_exits_2_with_path(
    script: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(script, "REPO_ROOT", tmp_path)
    assert script.main([]) == 2
    out = capsys.readouterr()
    assert str(tmp_path / ".env") in out.err
    assert "copy env.example to .env" in out.err


async def test_seed_refs_upserts_and_prints_names_and_lengths_only(
    script: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    store = InMemorySecretStore()
    source = {"ANTHROPIC_API_KEY": VALUE, "BRAVE_API_KEY": ""}
    assert await script.seed_refs(store, source, only=None) == 0
    assert await script.seed_refs(store, source, only=None) == 0  # idempotent
    assert await store.get(ANTHROPIC_API_KEY_NAME) == VALUE
    out = capsys.readouterr().out
    assert VALUE not in out
    assert f"anthropic_api_key    stored from $ANTHROPIC_API_KEY ({len(VALUE)} chars)" in out
    assert "brave_api_key        skipped" in out
    assert await script.seed_refs(store, {}, only=None) == 1


async def test_seed_refs_only_filters(
    script: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    store = InMemorySecretStore()
    source = {"ANTHROPIC_API_KEY": VALUE, "OPENAI_API_KEY": VALUE}
    assert await script.seed_refs(store, source, only="openai") == 0
    assert await store.get(OPENAI_API_KEY_NAME) == VALUE
    with pytest.raises(KeyError):
        await store.get(ANTHROPIC_API_KEY_NAME)
    assert VALUE not in capsys.readouterr().out


async def test_check_refs_reports_names_only(
    script: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    store = InMemorySecretStore()
    await store.put(ANTHROPIC_API_KEY_NAME, VALUE)
    assert await script.check_refs(store, onshape_pair=False) == 1
    out = capsys.readouterr().out
    assert VALUE not in out
    assert f"anthropic_api_key    present ({len(VALUE)} chars)" in out
    assert "openai_api_key       MISSING" in out
    assert "brave_api_key        MISSING" in out
    assert "onshape" in out and "not set" in out

    for _envs, ref in script.SEED_KEYS.values():
        await store.put(ref, VALUE)
    assert await script.check_refs(store, onshape_pair=True) == 0
    out = capsys.readouterr().out
    assert VALUE not in out and "MISSING" not in out and "not set" not in out
