# SOLUSDEV-321 (P0-T2) ratchet — ONE token estimator. `orchestration/type_estimator.py`
# owns the chars-per-token heuristic; nothing else under `agent/` or `orchestration/`
# does its own char/token arithmetic (there used to be a private `len // 4` copy in
# context packing). Textual, like the other ratchets here: comments count, so reword a
# comment rather than whitelist it.
from __future__ import annotations

import re
from pathlib import Path

from solus_api.orchestration.config import TypeEstimatorConfig
from solus_api.orchestration.type_estimator import chars_for_tokens, estimate_tokens

_SRC = Path(__file__).resolve().parents[1] / "src" / "solus_api"
_OWNER = _SRC / "orchestration" / "type_estimator.py"
#: The config field (and its docstring) may NAME the knob; it never computes with it.
_KNOB_DECLARED_IN = _SRC / "orchestration" / "config.py"
_ARITHMETIC = re.compile(r"/\s*4\b|_CHARS_PER_TOKEN")  # `/ 4` and `// 4`, spaced or not
_KNOB = re.compile(r"\bchars_per_token\b")


def _swept() -> list[Path]:
    return sorted(
        path
        for root in ("agent", "orchestration")
        for path in (_SRC / root).rglob("*.py")
        if path != _OWNER
    )


def _offences(path: Path) -> list[str]:
    patterns = (_ARITHMETIC,) if path == _KNOB_DECLARED_IN else (_ARITHMETIC, _KNOB)
    return [
        f"{path.relative_to(_SRC)}:{number}: {line.strip()}"
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        if any(pattern.search(line) for pattern in patterns)
    ]


def test_single_estimator() -> None:
    swept = _swept()
    names = {str(path.relative_to(_SRC)) for path in swept}
    # The sweep must see the tree, or a wrong root would pass vacuously.
    assert {"agent/context.py", "agent/runtime.py", "orchestration/gateway.py"} <= names
    assert [offence for path in swept for offence in _offences(path)] == []


def test_the_ratchet_bites_on_the_old_copies() -> None:
    for line in (
        "return max(1, len(text) // _CHARS_PER_TOKEN)",
        "tokens = len(text) // 4",
        "tokens = len(text) / 4",
    ):
        assert _ARITHMETIC.search(line), line
    assert _KNOB.search("keep = limit * cfg.chars_per_token")
    assert not _ARITHMETIC.search("size // 1024 and ratio / 40")


def test_estimate_tokens_floors_at_one() -> None:
    config = TypeEstimatorConfig(chars_per_token=4)
    assert estimate_tokens("", config=config) == 1
    assert estimate_tokens("abc", config=config) == 1
    assert estimate_tokens("a" * 40, config=config) == 10


def test_chars_for_tokens_inverts_estimate_tokens_under_the_same_knob() -> None:
    for chars_per_token in (3, 4):
        config = TypeEstimatorConfig(chars_per_token=chars_per_token)
        assert chars_for_tokens(10, config=config) == 10 * chars_per_token
        assert estimate_tokens("x" * chars_for_tokens(10, config=config), config=config) == 10
