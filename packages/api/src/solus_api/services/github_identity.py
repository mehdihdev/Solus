"""Verified GitHub identity of a Solus user (ADR-039 section 6, docs/api/github-orgs.md).

A GitHub numeric id is trusted ONLY when proven server-side:

1. a live, connected GitHub `AccountConnection` of that user (its `account_external_id`), else
2. the Supabase admin identity (needs the service-role key), else
3. nothing.

JWT claims (`user_metadata`, `app_metadata`, `identities`) are user-editable or
provider-supplied and are never read here. Matching is by numeric id, never login or email.
"""

from __future__ import annotations

import re
import uuid
from typing import Final, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.models import AccountConnection, ConnectionStatus, Membership, SourceType, User


class GitHubIdentityAdmin(Protocol):
    async def github_identity(self, user_supabase_id: str) -> int | None: ...


_MAX_ID: Final = 2**63 - 1
#: GitHub logins: letters, digits and single inner hyphens, at most 39 characters. Underscores
#: are allowed for Enterprise Managed User logins (`name_shortcode`).
GITHUB_LOGIN_PATTERN: Final = re.compile(r"(?=.{1,39}$)[A-Za-z0-9_]+(?:-[A-Za-z0-9_]+)*")


def parse_github_id(raw: str | None) -> int | None:
    """A positive ASCII-decimal id that fits a BigInteger, or None."""
    if raw is None or not (raw.isascii() and raw.isdigit()):
        return None
    value = int(raw)
    return value if 0 < value <= _MAX_ID else None


async def verified_github_id(
    session: AsyncSession, user: User, *, admin: GitHubIdentityAdmin | None
) -> int | None:
    """The GitHub id proven for `user`, or None. Connection first, Supabase admin second."""
    rows = await session.scalars(
        select(AccountConnection.account_external_id)
        .where(
            AccountConnection.user_id == user.id,
            AccountConnection.provider == SourceType.GITHUB,
            AccountConnection.status == ConnectionStatus.CONNECTED,
        )
        .order_by(AccountConnection.created_at, AccountConnection.id)
    )
    for raw in rows:
        parsed = parse_github_id(raw)
        if parsed is not None:
            return parsed
    if admin is None:
        return None
    return await admin.github_identity(user.supabase_user_id)


async def github_ids_for_team_members(
    session: AsyncSession, team_id: uuid.UUID
) -> dict[int, uuid.UUID]:
    """`{github_id: user_id}` for the team's LIVE members with a connected GitHub account.

    One query. Connection-based only: the Supabase admin API is per-user, so it is not used
    for bulk matching. If two members claim one id, the earliest connection wins."""
    rows = await session.execute(
        select(AccountConnection.account_external_id, AccountConnection.user_id)
        .join(Membership, Membership.user_id == AccountConnection.user_id)
        .where(
            Membership.team_id == team_id,
            Membership.deleted_at.is_(None),
            AccountConnection.provider == SourceType.GITHUB,
            AccountConnection.status == ConnectionStatus.CONNECTED,
        )
        .order_by(AccountConnection.created_at, AccountConnection.id)
    )
    mapping: dict[int, uuid.UUID] = {}
    for raw, user_id in rows:
        parsed = parse_github_id(raw)
        if parsed is not None:
            mapping.setdefault(parsed, user_id)
    return mapping
