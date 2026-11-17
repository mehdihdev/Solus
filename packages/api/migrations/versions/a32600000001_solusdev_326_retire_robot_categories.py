"""SOLUSDEV-326: retire `robot_category` nodes; a robot contains its parts directly.

Revision ID: a32600000001
Revises: a32200000004

The frozen sibling `migrations/robot_categories_retire.py` re-points category edges to the
robot root, retires the category nodes and runs its own post-checks (no live category, no live
`contains` edge touching one, the same owned (robot, part) pairs). One-way: the downgrade
restores nothing and never raises; `attrs.moved_from`, `moved_by` and `retired_by` keep what a
manual recovery needs.
"""

import sys
from collections.abc import Sequence
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from alembic import op

revision: str = "a32600000001"
down_revision: str | None = "a32200000004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The revision runs from both repository-root pytest and API-root Alembic.
    # Resolve this frozen sibling directly, without depending on the process cwd.
    name = "solus_robot_categories_retire_326"
    spec = spec_from_file_location(
        name, Path(__file__).resolve().parents[1] / "robot_categories_retire.py"
    )
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    module.retire_categories(op.get_bind())


def downgrade() -> None:
    # One-way data step: the category nodes stay retired (see the module docstring).
    pass
