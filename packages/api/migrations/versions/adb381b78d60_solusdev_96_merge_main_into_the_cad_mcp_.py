"""SOLUSDEV-96 merge main into the CAD MCP branch

Schema-empty by design. Two lanes added migrations from the same branchpoint
(`a7c5d2e91f04`): the CAD branch's panel bindings/pairings and main's
SOLUSDEV-102 cancellation lifecycle. Neither touches the other's tables, so
this only rejoins the chains — without it alembic has two heads and every
test that builds a schema fails.

Repeating the house precedent at `20af242f48a0`. Nothing is rewritten in
either lane's migration, so a database already carrying one head upgrades
cleanly through the other.

Revision ID: adb381b78d60
Revises: 2d49fdc410e4, a91b3c7e2d48
Create Date: 2026-08-10 22:27:51.491138
"""

from collections.abc import Sequence

revision: str = "adb381b78d60"
down_revision: str | Sequence[str] | None = ("2d49fdc410e4", "a91b3c7e2d48")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op: a mergepoint joins histories, it does not change the schema."""


def downgrade() -> None:
    """No-op, symmetrically."""
