"""Ratchet tests for the ADR-026 config-only invariants.

1. Model identity lives ONLY in models.yaml — no model-name-shaped literal may
   appear in any Python source file under solus_api.
2. All model usage flows through the gateway — provider SDKs may only be
   imported by the adapter module (orchestration/providers.py).
"""

import re
from pathlib import Path

import solus_api

SRC_ROOT = Path(solus_api.__file__).resolve().parent

# Matches concrete model identifiers (claude-sonnet-5, gemini-2.5-flash, gpt-4o)
# — the digit requirement keeps prose like "Gemini-class" or bare provider names
# ("anthropic", "google", "openai") from matching.
_MODEL_LITERAL = re.compile(r"(?:claude|gemini)-[\w.\-]*\d|gpt-\d", re.IGNORECASE)

_PROVIDER_SDK_IMPORT = re.compile(
    r"^\s*(?:import|from)\s+(anthropic|openai|google)\b", re.MULTILINE
)

# The sanctioned SDK surfaces: the streaming adapters and the SYS-02 embedding
# adapter (docs/api/gateway-embeddings.md — a sibling registry, same key seam).
_ADAPTER_MODULES = {
    SRC_ROOT / "orchestration" / "providers.py",
    SRC_ROOT / "orchestration" / "embeddings.py",
}


def _src_files() -> list[Path]:
    files = sorted(SRC_ROOT.rglob("*.py"))
    assert files, f"no sources found under {SRC_ROOT}"
    return files


def test_no_hardcoded_model_names_outside_config() -> None:
    offenders: list[str] = []
    for path in _src_files():
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            if _MODEL_LITERAL.search(line):
                offenders.append(f"{path.relative_to(SRC_ROOT)}:{lineno}: {line.strip()}")
    assert not offenders, (
        "Model names are config (models.yaml), never code (ADR-026). Offenders:\n"
        + "\n".join(offenders)
    )


def test_provider_sdks_imported_only_by_adapter_module() -> None:
    offenders: list[str] = []
    for path in _src_files():
        if path in _ADAPTER_MODULES:
            continue
        match = _PROVIDER_SDK_IMPORT.search(path.read_text())
        if match:
            offenders.append(f"{path.relative_to(SRC_ROOT)}: imports {match.group(1)}")
    assert not offenders, (
        "All model usage flows through the gateway; provider SDKs may only be "
        "imported in orchestration/providers.py. Offenders:\n" + "\n".join(offenders)
    )
