"""allowlist.yaml and solus/roster.py agree, and both obey the bridge model
(SOLUSDEV-102 ALT-4). Mirrors the kicad fork's shape test.

The yaml is the human-ratified law; the roster is what the trimming registrar
enforces in-process. This test pins their equality so they can never drift,
and re-checks the ServerAllowlist model constraints the cloud ingress gate
applies (extra fields forbidden, reasons on every confirmation-gated tool).
"""

from typing import Any

import yaml

# The bootstrap module must run before the overlay import — keep it first.
from .altium_paths import FORK_DIR, UPSTREAM_SRC, overlay_module  # isort: skip

from solus_api.agent.tools.untrusted import SAFE_REMOTE_NAME
from solus_api.bridge.allowlist import COMPOSED_NAME_MAX, ServerAllowlist

ALLOWLIST_PATH = FORK_DIR / "allowlist.yaml"

#: Meta-dispatch pair that would bypass any allowlist (SECURITY_REVIEW.md);
#: they must never appear in the yaml or any roster.
FORBIDDEN_META_TOOLS = frozenset({"tool_catalog", "tool_invoke"})

_roster = overlay_module("roster")


def _allowlist_data() -> dict[str, Any]:
    data = yaml.safe_load(ALLOWLIST_PATH.read_text())
    assert isinstance(data, dict)
    return data


def _yaml_tool_names() -> set[str]:
    return {tool["name"] for tool in _allowlist_data()["tools"]}


def test_allowlist_validates_against_the_bridge_model() -> None:
    model = ServerAllowlist.model_validate(_allowlist_data())
    assert model.server == "altium" == FORK_DIR.name


def test_tool_names_are_safe_and_within_the_composed_bound() -> None:
    for name in sorted(_yaml_tool_names()):
        assert SAFE_REMOTE_NAME.fullmatch(name), name
        assert len("altium") + 1 + len(name) <= COMPOSED_NAME_MAX, name


def test_every_confirmation_gated_tool_carries_a_reason() -> None:
    for tool in _allowlist_data()["tools"]:
        if tool.get("requires_confirmation"):
            assert tool.get("reason"), f"{tool['name']} lacks a reason"


def test_roster_mirrors_the_allowlist_exactly() -> None:
    assert _roster.FULL_ROSTER == _yaml_tool_names()


def test_write_roster_matches_the_confirmation_gated_set() -> None:
    gated = {
        tool["name"] for tool in _allowlist_data()["tools"] if tool.get("requires_confirmation")
    }
    assert _roster.WRITE_ROSTER == gated
    assert not _roster.WRITE_ROSTER & _roster.EXPOSED_UPSTREAM_TOOLS
    assert not _roster.WRITE_ROSTER & _roster.SOLUS_AUTHORED_TOOLS


def test_roster_partitions_are_disjoint_and_cover_full_roster() -> None:
    parts = (
        _roster.EXPOSED_UPSTREAM_TOOLS,
        _roster.SOLUS_AUTHORED_TOOLS,
        _roster.WRITE_ROSTER,
    )
    union: frozenset[str] = frozenset().union(*parts)
    assert union == _roster.FULL_ROSTER
    assert sum(len(part) for part in parts) == len(union), "partitions overlap"


def test_pending_tools_are_a_subset_of_full_roster() -> None:
    assert _roster.PENDING_TOOLS <= _roster.FULL_ROSTER
    assert _roster.registered_roster() == _roster.FULL_ROSTER - _roster.PENDING_TOOLS


def test_meta_dispatch_tools_are_nowhere() -> None:
    assert not FORBIDDEN_META_TOOLS & _yaml_tool_names()
    assert not FORBIDDEN_META_TOOLS & _roster.FULL_ROSTER


def test_exposed_upstream_tools_exist_upstream() -> None:
    """Every exposed upstream name is defined in the vendored tree — a
    re-vendor that drops one must fail here, not at customer runtime."""
    tools_dir = UPSTREAM_SRC / "eda_agent" / "tools"
    corpus = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in sorted(tools_dir.glob("*.py"))
    )
    for name in sorted(_roster.EXPOSED_UPSTREAM_TOOLS):
        assert f"def {name}(" in corpus, f"upstream no longer defines {name}"
