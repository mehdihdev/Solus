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

    # keys come from the environment (the ROOT .env is loaded automatically)
    python3 scripts/seed-provider-keys.py
    python3 scripts/seed-provider-keys.py --only anthropic

Values are never printed, logged, or echoed — only the ref name and a length.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "packages" / "api" / "src"))

#: env var(s) a developer sets  ->  the SecretStore ref the code reads by name.
#: The env names are the vendors' own, which is what people already have
#: exported (Google's docs say GEMINI_API_KEY, so both spellings are accepted;
#: first non-empty wins). Refs: `orchestration/providers.py` constants plus
#: `agent/tools/mcp_servers.py`'s `required_secrets`. The mapping is pinned by
#: `packages/api/tests/test_seed_script.py`.
SEED_KEYS = {
    "anthropic": (("ANTHROPIC_API_KEY",), "anthropic_api_key"),
    "openai": (("OPENAI_API_KEY",), "openai_api_key"),
    "google": (("GOOGLE_API_KEY", "GEMINI_API_KEY"), "google_api_key"),
    "brave": (("BRAVE_API_KEY",), "brave_api_key"),
}


def resolve_value(env_names: tuple[str, ...]) -> tuple[str, str] | None:
    """First non-empty env var wins; returns (env name, stripped value)."""
    for env_name in env_names:
        value = (os.environ.get(env_name) or "").strip()
        if value:
            return env_name, value
    return None


async def seed(only: str | None) -> int:
    from dotenv import load_dotenv
    from solus_api.connectors.secrets import build_secret_store
    from solus_api.core.config import Settings
    from solus_api.core.db import build_engine, build_sessionmaker

    # The same file the API reads, so "it works for the app" and "it works here"
    # cannot diverge. That is the ROOT .env — the one file — not a per-package
    # copy. Pointing at packages/api/.env was why this reported
    # "$ANTHROPIC_API_KEY is not set" while the key sat in the root file all along.
    load_dotenv(REPO_ROOT / ".env")
    settings = Settings(_env_file=REPO_ROOT / ".env")  # type: ignore[call-arg]
    engine = build_engine(settings.database_url)
    store = build_secret_store(settings, build_sessionmaker(engine))
    backend = type(store).__name__
    print(f"backend: {backend}")
    if backend == "InMemorySecretStore":
        print(
            "\nRefusing to write: an in-memory store is discarded when this script\n"
            "exits, so the API would still fail. Set SOLUS_SECRETS_KEY (a Fernet key)\n"
            "in the root .env, then try again.",
            file=sys.stderr,
        )
        return 2

    wrote = 0
    for key, (env_names, ref) in SEED_KEYS.items():
        if only and key != only:
            continue
        resolved = resolve_value(env_names)
        if resolved is None:
            wanted = "/".join(f"${e}" for e in env_names)
            print(f"  {ref:20s} skipped — {wanted} is not set")
            continue
        env_name, value = resolved
        await store.put(ref, value)
        print(f"  {ref:20s} stored from ${env_name} ({len(value)} chars)")
        wrote += 1

    await engine.dispose()
    if not wrote:
        print(
            "\nNothing to do. Set at least one of: "
            + ", ".join(e for envs, _ in SEED_KEYS.values() for e in envs)
        )
        return 1
    print("\nDone. No restart needed — the store is read per call.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=sorted(SEED_KEYS), help="seed one key")
    args = parser.parse_args()
    return asyncio.run(seed(args.only))


if __name__ == "__main__":
    raise SystemExit(main())
