"""SOLUSDEV-168: PKCE verifier on oauth_states

The hosted FeatureScript server's authorization server requires PKCE
(`/authorize` returns `400 code_challenge: Field required`), and the verifier
must survive authorize→callback — two separate HTTP requests, possibly on two
workers. Nullable, because every connector that predates this has none.

Revision ID: 3f1c8a6d90e2
Revises: 07c4da2feccf
Create Date: 2026-08-31

"""

import sqlalchemy as sa
from alembic import op

revision = "3f1c8a6d90e2"
down_revision = "07c4da2feccf"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("oauth_states", sa.Column("code_verifier", sa.String(length=128), nullable=True))


def downgrade() -> None:
    op.drop_column("oauth_states", "code_verifier")
