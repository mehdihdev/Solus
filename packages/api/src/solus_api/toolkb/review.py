"""SOLUS-TU-06 — operator review CLI: the mechanical "review level".

Run by Solus staff with production DB access (from packages/api):

    uv run python -m solus_api.toolkb.review list [--tool kicad]
    uv run python -m solus_api.toolkb.review show <id>
    uv run python -m solus_api.toolkb.review approve <id>
    uv run python -m solus_api.toolkb.review reject <id>

Approve/reject are the guard's functions — this module only renders. The
operating user is LOGGED, deliberately never stored: a person's identity must
not enter the cross-tenant table. A durable reviewer audit trail (server-only
table) is an open human decision — Phase 0 §7.1.

Per TU-03/TU-06, `visual` and `operator` entries NEVER auto-promote; an
`approve` here is the explicit human act that publishes them.
"""

import argparse
import asyncio
import getpass
import logging
import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from solus_api.contracts.tool_knowledge import ToolFamily
from solus_api.core.config import Settings
from solus_api.toolkb.guard import approve, reject
from solus_api.toolkb.schema import KnowledgeStatus, ToolKnowledgeEntry, to_contract

logger = logging.getLogger("solus.toolkb.review")


async def list_candidates(
    session: AsyncSession, tool: ToolFamily | None = None
) -> list[ToolKnowledgeEntry]:
    stmt = (
        select(ToolKnowledgeEntry)
        .where(
            ToolKnowledgeEntry.deleted_at.is_(None),
            ToolKnowledgeEntry.status == KnowledgeStatus.CANDIDATE,
        )
        .order_by(ToolKnowledgeEntry.created_at.asc())
    )
    if tool is not None:
        stmt = stmt.where(ToolKnowledgeEntry.tool == tool)
    return list((await session.execute(stmt)).scalars())


def format_row(row: ToolKnowledgeEntry) -> str:
    return (
        f"{row.id}  {row.tool.value:<10} {row.control_id:<44} "
        f"{row.status.value:<9} via={row.acquired_via.value:<12} conf={row.confidence:.2f}"
    )


async def show_entry(session: AsyncSession, entry_id: uuid.UUID) -> str:
    row = await session.get(ToolKnowledgeEntry, entry_id)
    if row is None or row.deleted_at is not None:
        raise LookupError(f"no live tool_knowledge entry {entry_id}")
    contract = to_contract(row)
    lines = [format_row(row), ""]
    lines += [f"  {name}: {value}" for name, value in contract.model_dump().items()]
    lines += [
        "",
        f"  confidence: {row.confidence:.2f}  confirms: {row.confirm_count}"
        f"  rejects: {row.reject_count}",
        f"  window: [{row.version_min_key}, {row.version_max_key or 'open'})",
        f"  created: {row.created_at:%Y-%m-%d %H:%M}  last_verified: {row.last_verified_at}",
    ]
    return "\n".join(lines)


async def _run(args: argparse.Namespace) -> int:
    # Through Settings, not raw os.environ: the database URL lives in the root
    # `.env` and is NOT exported into the process, so an os.environ read made this
    # operator CLI refuse to run while the app it inspects was working fine. Same
    # resolution every other entrypoint uses (ops/stripe_setup.py,
    # scripts/seed-provider-keys.py) — a real env var still wins over the file.
    url = Settings().database_url  # type: ignore[call-arg]  # env-populated, as every entrypoint
    if not url:
        print("No database URL configured (SOLUS_DATABASE_URL / root .env)")
        return 2
    engine = create_async_engine(url)
    operator = getpass.getuser()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            if args.command == "list":
                tool = ToolFamily(args.tool) if args.tool else None
                for row in await list_candidates(session, tool):
                    print(format_row(row))
            elif args.command == "show":
                print(await show_entry(session, args.entry_id))
            elif args.command == "approve":
                row = await approve(session, entry_id=args.entry_id)
                await session.commit()
                logger.info("operator=%s approved id=%s", operator, row.id)
                print(f"approved: {format_row(row)}")
            else:  # reject
                await reject(session, entry_id=args.entry_id)
                await session.commit()
                logger.info("operator=%s rejected id=%s", operator, args.entry_id)
                print(f"rejected: {args.entry_id}")
    finally:
        await engine.dispose()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="toolkb-review", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    list_cmd = sub.add_parser("list", help="pending candidates, oldest first")
    list_cmd.add_argument("--tool", choices=[t.value for t in ToolFamily], default=None)
    for name in ("show", "approve", "reject"):
        cmd = sub.add_parser(name)
        cmd.add_argument("entry_id", type=uuid.UUID)
    args = parser.parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
