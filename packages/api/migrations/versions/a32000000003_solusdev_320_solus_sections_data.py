"""SOLUSDEV-320: move every `.solus` row into the seven-section tree.

Revision ID: a32000000003
Revises: a32000000002

The frozen sibling `migrations/solus_sections_remap.py` does the data work (counts per
old section before/after, node and edge attrs, retired section nodes); this revision then
narrows CHECK `solussection` to the seven new values. Downgrade reverses the map, un-retires
what this revision retired and restores the widened CHECK of a32000000002.
"""

import sys
from collections.abc import Sequence
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "a32000000003"
down_revision: str | None = "a32000000002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_SECTIONS = ("hardware", "details", "docs", "code")
NEW_SECTIONS = (
    "goals",
    "constraints",
    "documentation",
    "errors",
    "environment",
    "members",
    "history",
)
_LIVE_CONFIGS = sa.text(
    "SELECT count(*) FROM solus_entries WHERE kind = 'config' AND deleted_at IS NULL"
)
_STALE = sa.text("SELECT count(*) FROM solus_entries WHERE section IN :olds").bindparams(
    sa.bindparam("olds", expanding=True)
)


def _remap_module() -> Any:
    # The revision runs from both repository-root pytest and API-root Alembic.
    # Resolve this frozen sibling directly, without depending on the process cwd.
    name = "solus_sections_remap_320"
    spec = spec_from_file_location(
        name, Path(__file__).resolve().parents[1] / "solus_sections_remap.py"
    )
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _swap_section_check(values: Sequence[str]) -> None:
    op.drop_constraint("solussection", "solus_entries", type_="check")
    op.create_check_constraint(
        "solussection", "solus_entries", sa.column("section").in_(list(values))
    )


def upgrade() -> None:
    bind = op.get_bind()
    live_configs = bind.scalar(_LIVE_CONFIGS)
    _remap_module().remap_sections(bind)
    stale = bind.scalar(_STALE, {"olds": list(OLD_SECTIONS)})
    if stale:
        raise RuntimeError(f"{stale} solus_entries rows still carry a retired section")
    if bind.scalar(_LIVE_CONFIGS) != live_configs:
        raise RuntimeError("the remap changed the number of live config entries")
    _swap_section_check(NEW_SECTIONS)


def downgrade() -> None:
    _swap_section_check((*OLD_SECTIONS, *NEW_SECTIONS))  # widen first, then move the rows back
    _remap_module().restore_sections(op.get_bind())
