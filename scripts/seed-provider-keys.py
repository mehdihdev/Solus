#!/usr/bin/env python3
"""Seed every env-sourced SecretStore ref, so SOL and its tools can run locally.

WHY THIS EXISTS. Provider and tool API keys "are NOT env vars" — they are
SecretStore refs (`anthropic_api_key`, `openai_api_key`, `google_api_key`,
`brave_api_key`) that adapters read by name at call time. That is the right
posture and it stays. What was missing is anything that actually performs the
write: nothing in the repo ever set those refs, so a fresh checkout could never
run a SOL turn. It failed at the first message with

    ProviderCredentialsMissingError: No API key for provider 'anthropic'

which reads like a misconfiguration and is really a missing step. This is the
step, made executable (`make seed-secrets`).

It does **not** move keys onto an env-var path at runtime: nothing here is
imported by the app. A developer runs it once; the value lands encrypted in
whatever backend `build_secret_store` selects, and the API reads it from there
exactly as it does in production.

    # keys come from the ROOT .env only (never the process environment)
    make seed-secrets
    uv run --package solus-api python scripts/seed-provider-keys.py --only anthropic
    uv run --package solus-api python scripts/seed-provider-keys.py --check

Values are never printed, logged, or echoed — only the ref name and a length.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from solus_api.connectors.secrets import SecretStore

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "packages" / "api" / "src"))

#: env name(s) a developer writes in the root .env  ->  the SecretStore ref the
#: code reads by name. The env names are the vendors' own (Google's docs say
#: GEMINI_API_KEY, so both spellings are accepted; first non-empty wins). Refs:
#: `orchestration/providers.py` constants plus `agent/tools/mcp_servers.py`'s
#: `required_secrets`. Pinned by `packages/api/tests/test_seed_script.py`.
SEED_KEYS = {
    "anthropic": (("ANTHROPIC_API_KEY",), "anthropic_api_key"),
    "openai": (("OPENAI_API_KEY",), "openai_api_key"),
    "google": (("GOOGLE_API_KEY", "GEMINI_API_KEY"), "google_api_key"),
    "brave": (("BRAVE_API_KEY",), "brave_api_key"),
}


def resolve_value(
    env_names: tuple[str, ...], source: Mapping[str, str | None]
) -> tuple[str, str] | None:
    """First non-empty entry of `source` wins; returns (env name, stripped value)."""
    for env_name in env_names:
        value = (source.get(env_name) or "").strip()
        if value:
            return env_name, value
    return None


async def seed_refs(store: SecretStore, source: Mapping[str, str | None], only: str | None) -> int:
    """Upsert each resolvable ref into `store` (any SecretStore); 1 if nothing written."""
    wrote = 0
    for key, (env_names, ref) in SEED_KEYS.items():
        if only and key != only:
            continue
        resolved = resolve_value(env_names, source)
        if resolved is None:
            wanted = "/".join(f"${e}" for e in env_names)
            print(f"  {ref:20s} skipped — {wanted} is not set in the root .env")
            continue
        env_name, value = resolved
        await store.put(ref, value)
        print(f"  {ref:20s} stored from ${env_name} ({len(value)} chars)")
        wrote += 1
    if not wrote:
        print(
            "\nNothing to do. Set at least one of: "
            + ", ".join(e for envs, _ in SEED_KEYS.values() for e in envs)
        )
        return 1
    print("\nDone. No restart needed — the store is read per call.")
    return 0


async def check_refs(store: SecretStore, *, onshape_pair: bool) -> int:
    """Report each ref present/MISSING by name (length only); 0 iff all present."""
    missing = 0
    for _key, (_env_names, ref) in SEED_KEYS.items():
        try:
            value = await store.get(ref)
        except Exception:  # noqa: BLE001 — not found or backend down: both "missing"
            print(f"  {ref:20s} MISSING")
            missing += 1
        else:
            print(f"  {ref:20s} present ({len(value)} chars)")
    # Settings fields, not SecretStore refs — reported, never seeded.
    state = "set" if onshape_pair else "not set (SOLUS_ONSHAPE_CLIENT_ID/_SECRET)"
    print(f"  {'onshape oauth pair':20s} {state}")
    return 1 if missing else 0


async def run(only: str | None, check: bool) -> int:
    env_path = REPO_ROOT / ".env"
    if not env_path.is_file():
        print(
            f"root .env not found: {env_path}\ncopy env.example to .env and fill it in",
            file=sys.stderr,
        )
        return 2
    from dotenv import dotenv_values
    from solus_api.connectors.secrets import build_secret_store
    from solus_api.core.config import Settings
    from solus_api.core.db import build_engine, build_sessionmaker

    # The same file the API reads — the ROOT .env, not a per-package copy — so
    # "it works for the app" and "it works here" cannot diverge.
    settings = Settings(_env_file=env_path)  # type: ignore[call-arg]
    engine = build_engine(settings.database_url)
    store = build_secret_store(settings, build_sessionmaker(engine))
    backend = type(store).__name__
    print(f"backend: {backend}")
    if backend == "InMemorySecretStore":
        print(
            "\nRefusing: an in-memory store is discarded when this script exits, so\n"
            "the API would still fail. Set SOLUS_SECRETS_KEY (a Fernet key) in the\n"
            "root .env, then try again.",
            file=sys.stderr,
        )
        return 2
    try:
        if check:
            onshape_pair = bool(settings.onshape_client_id and settings.onshape_client_secret)
            return await check_refs(store, onshape_pair=onshape_pair)
        return await seed_refs(store, dotenv_values(env_path), only)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=sorted(SEED_KEYS), help="seed one key")
    parser.add_argument(
        "--check", action="store_true", help="report present/missing refs; no writes"
    )
    args = parser.parse_args(argv)
    return asyncio.run(run(args.only, args.check))


if __name__ == "__main__":
    raise SystemExit(main())
