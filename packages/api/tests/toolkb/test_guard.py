"""SOLUS-TU-06 (SOLUSDEV-209) — the HARD tenancy ingestion guard.

Precision over recall. The canonical rejection is Onshape's per-document
``featurespecs``: vendor-LOOKING data that is actually a customer's imported
custom features, arriving in exactly the fields a real control would use. The
CTR-05 net cannot catch it (the prose is clean) — the guard's source allowlist
must. If the guard admits that, it admits anything.

Rejections must carry NO entry content: a rejected entry is by definition
suspect, so its prose — including its control_id — stays out of exceptions and
logs.
"""

import re
from pathlib import Path

import pytest
import solus_api
from solus_api.contracts.tool_knowledge import Provenance, ToolFamily, ToolKnowledge
from solus_api.toolkb.guard import (
    IngestContext,
    IngestRejectedError,
    RejectReason,
    approve,
    ingest,
    reject,
)
from solus_api.toolkb.schema import AcquisitionMethod, KnowledgeStatus, ToolKnowledgeEntry
from solus_api.toolkb.storage import query_entries
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


def _tk(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "tool": "kicad",
        "version_range": ">=8.0 <9.0",
        "surface": "menu",
        "control_id": "kicad.eeschema.place_net_label",
        "label": "Add Net Label",
        "effect": "create_feature",
        "description": "Places a named net label on the current wire.",
        "invocation": {"menu_path": ["Place", "Net Label"], "shortcut": "L"},
        "locator": None,
        "provenance": "vendor_docs",
    }
    fields.update(overrides)
    return fields


DOCS_CTX = IngestContext(
    acquired_via=AcquisitionMethod.DOCS,
    doc_url="https://docs.kicad.org/8.0/en/eeschema/eeschema.html",
)
OPERATOR_CTX = IngestContext(acquired_via=AcquisitionMethod.OPERATOR)
VISUAL_CTX = IngestContext(acquired_via=AcquisitionMethod.VISUAL)


def _probe(scope: str | None) -> IngestContext:
    return IngestContext(acquired_via=AcquisitionMethod.API_GEOMETRY, endpoint_scope=scope)  # type: ignore[arg-type]


async def _expect_reject(
    db: AsyncSession,
    entry: dict[str, object] | ToolKnowledge,
    ctx: IngestContext,
    reason: RejectReason,
) -> IngestRejectedError:
    with pytest.raises(IngestRejectedError) as info:
        await ingest(db, entry=entry, ctx=ctx)
    assert info.value.reason is reason
    count = await db.scalar(select(func.count()).select_from(ToolKnowledgeEntry))
    assert count == 0, "a rejected entry must never reach the table"
    return info.value


# ----------------------------------------------------------- rejection tests
async def test_onshape_per_document_featurespecs_rejected(db: AsyncSession) -> None:
    """THE canonical case: every field looks plausible, the prose passes the
    net, and the entry is still a customer's imported custom feature."""
    featurespec = _tk(
        tool="onshape",
        version_range=">=1.180",
        surface="panel",
        control_id="onshape.custom.gripper_generator",
        label="Gripper Generator",
        description="Generates a parametric gripper from a profile sketch.",
        invocation=None,
        provenance="observed_ui",
    )
    # sanity: the CTR-05 net alone would ADMIT this — that is exactly the trap
    ToolKnowledge.model_validate(featurespec)

    exc = await _expect_reject(
        db, featurespec, _probe("per_document"), RejectReason.PER_DOCUMENT_SOURCE
    )
    assert "gripper" not in str(exc).lower(), "rejected content must not leak into the error"


async def test_menu_path_customer_content_rejected(db: AsyncSession) -> None:
    poisoned = _tk(
        invocation={"menu_path": ["File", "Open Recent", "~/designs/arm_v3.f3d"], "shortcut": None}
    )
    exc = await _expect_reject(db, poisoned, DOCS_CTX, RejectReason.CONTRACT_VALIDATION)
    assert "arm_v3" not in str(exc), "rejected content must not leak into the error"


async def test_menu_path_homoglyph_rejected(db: AsyncSession) -> None:
    # fullwidth solidus + one-dot leader — NFKC normalization must defeat it
    poisoned = _tk(label="／home／mehdi／chassis․f3d")
    await _expect_reject(db, poisoned, DOCS_CTX, RejectReason.CONTRACT_VALIDATION)


async def test_document_scoped_control_id_rejected(db: AsyncSession) -> None:
    poisoned = _tk(control_id="d/9a1c2ef4b7d8aa00cc11ee22")
    await _expect_reject(db, poisoned, DOCS_CTX, RejectReason.CONTRACT_VALIDATION)


async def test_extra_field_rejected(db: AsyncSession) -> None:
    poisoned = _tk(notes="design review said the bracket flexes at 40N")
    exc = await _expect_reject(db, poisoned, DOCS_CTX, RejectReason.CONTRACT_VALIDATION)
    assert "bracket" not in str(exc)


async def test_provenance_mismatch_rejected(db: AsyncSession) -> None:
    # a probe result claiming to be vendor documentation
    await _expect_reject(db, _tk(), _probe("global"), RejectReason.PROVENANCE_MISMATCH)


async def test_docs_customer_document_url_rejected(db: AsyncSession) -> None:
    # a customer document offered as "vendor docs" — same host, wrong path
    entry = _tk(
        tool="onshape",
        control_id="onshape.sketch.line",
        label="Line",
        description="Draws a straight sketch line between two points.",
        invocation=None,
    )
    ctx = IngestContext(
        acquired_via=AcquisitionMethod.DOCS,
        doc_url="https://cad.onshape.com/documents/9a1c2ef4b7d8/w/e1f2",
    )
    await _expect_reject(db, entry, ctx, RejectReason.DOC_DOMAIN_NOT_ALLOWED)


async def test_docs_without_url_rejected(db: AsyncSession) -> None:
    ctx = IngestContext(acquired_via=AcquisitionMethod.DOCS)
    await _expect_reject(db, _tk(), ctx, RejectReason.DOC_DOMAIN_NOT_ALLOWED)


async def test_visual_unknown_control_rejected(db: AsyncSession) -> None:
    entry = _tk(
        control_id="kicad.eeschema.never_documented",
        provenance="observed_ui",
    )
    await _expect_reject(db, entry, VISUAL_CTX, RejectReason.UNKNOWN_CONTROL)


async def test_probe_without_scope_is_treated_as_per_document(db: AsyncSession) -> None:
    # "assume any per-document API mixes vendor and customer content until
    # proven otherwise" — an unstated scope gets the conservative treatment
    entry = _tk(control_id="kicad.eeschema.never_documented", provenance="observed_ui")
    await _expect_reject(db, entry, _probe(None), RejectReason.PER_DOCUMENT_SOURCE)


# ------------------------------------------------------------- accept paths
async def test_docs_path_publishes(db: AsyncSession) -> None:
    row = await ingest(db, entry=_tk(), ctx=DOCS_CTX)
    assert row.status is KnowledgeStatus.PUBLISHED
    assert row.confidence == 0.8
    assert row.provenance is Provenance.VENDOR_DOCS
    assert row.acquired_via is AcquisitionMethod.DOCS
    assert (row.version_min_key, row.version_max_key) == ("0008.0000.0000", "0009.0000.0000")

    served, _ = await query_entries(db, tool=ToolFamily.KICAD)
    assert [r.id for r in served] == [row.id]


async def test_probe_global_is_candidate(db: AsyncSession) -> None:
    entry = _tk(control_id="kicad.eeschema.brand_new_from_api", provenance="observed_ui")
    row = await ingest(db, entry=entry, ctx=_probe("global"))
    assert row.status is KnowledgeStatus.CANDIDATE
    assert row.confidence == 0.9
    served, _ = await query_entries(db, tool=ToolFamily.KICAD)
    assert served == [], "candidates are never served"


async def test_probe_per_document_known_control_is_candidate(db: AsyncSession) -> None:
    # geometry for a control vendor docs already name — allowed, still staged
    entry = _tk(provenance="observed_ui")
    row = await ingest(db, entry=entry, ctx=_probe("per_document"))
    assert row.status is KnowledgeStatus.CANDIDATE


async def test_operator_may_introduce_new_control(db: AsyncSession) -> None:
    entry = _tk(control_id="kicad.eeschema.highlight_net", provenance="operator_authored")
    row = await ingest(db, entry=entry, ctx=OPERATOR_CTX)
    assert row.status is KnowledgeStatus.CANDIDATE
    assert row.confidence == 0.7


async def test_visual_known_control_is_low_confidence_candidate(db: AsyncSession) -> None:
    entry = _tk(provenance="observed_ui")
    row = await ingest(db, entry=entry, ctx=VISUAL_CTX)
    assert row.status is KnowledgeStatus.CANDIDATE
    assert row.confidence == 0.5


async def test_typed_contract_instance_is_accepted(db: AsyncSession) -> None:
    row = await ingest(db, entry=ToolKnowledge.model_validate(_tk()), ctx=DOCS_CTX)
    assert row.status is KnowledgeStatus.PUBLISHED


async def test_duplicate_ingest_is_idempotent(db: AsyncSession) -> None:
    first = await ingest(db, entry=_tk(), ctx=DOCS_CTX)
    second = await ingest(db, entry=_tk(), ctx=DOCS_CTX)
    assert second.id == first.id
    count = await db.scalar(select(func.count()).select_from(ToolKnowledgeEntry))
    assert count == 1


async def test_embedding_is_best_effort(db: AsyncSession) -> None:
    async def good(text: str) -> list[float] | None:
        return [0.5] * 1536

    async def broken(text: str) -> list[float] | None:
        raise RuntimeError("provider down")

    with_vector = await ingest(db, entry=_tk(), ctx=DOCS_CTX, embed=good)
    assert with_vector.embedding is not None

    entry = _tk(control_id="kicad.eeschema.place_wire")
    without = await ingest(db, entry=entry, ctx=DOCS_CTX, embed=broken)
    assert without.embedding is None  # degraded, never raised


# ------------------------------------------------------------ review level
async def test_approve_flips_status_and_stamps_verification(db: AsyncSession) -> None:
    entry = _tk(provenance="observed_ui")
    row = await ingest(db, entry=entry, ctx=_probe("global"))
    approved = await approve(db, entry_id=row.id)
    assert approved.status is KnowledgeStatus.PUBLISHED
    assert approved.last_verified_at is not None
    served, _ = await query_entries(db, tool=ToolFamily.KICAD)
    assert [r.id for r in served] == [row.id]


async def test_approve_published_or_missing_errors(db: AsyncSession) -> None:
    import uuid

    row = await ingest(db, entry=_tk(), ctx=DOCS_CTX)  # docs → already published
    with pytest.raises(ValueError, match="published"):
        await approve(db, entry_id=row.id)
    with pytest.raises(LookupError):
        await approve(db, entry_id=uuid.uuid4())


async def test_reject_soft_deletes(db: AsyncSession) -> None:
    entry = _tk(provenance="observed_ui")
    row = await ingest(db, entry=entry, ctx=_probe("global"))
    await reject(db, entry_id=row.id)
    assert row.deleted_at is not None
    served, _ = await query_entries(db, tool=ToolFamily.KICAD)
    assert served == []


# ------------------------------------------------- review-finding regressions
@pytest.mark.parametrize("version_range", ["==2.0", "<<2.0", ">=3.0 <2.0", "10000.0"])
async def test_version_range_passing_contract_regex_but_unsupported_is_rejected(
    db: AsyncSession, version_range: str
) -> None:
    # These pass the CTR-05 regex but not the key grammar — must reject
    # with a sanitized reason, never surface a ValueError/500.
    entry = _tk(version_range=version_range)
    ToolKnowledge.model_validate(entry)  # sanity: the contract admits it
    await _expect_reject(db, entry, DOCS_CTX, RejectReason.CONTRACT_VALIDATION)


async def test_rejection_traceback_carries_no_input(db: AsyncSession) -> None:
    import traceback

    poisoned = _tk(
        invocation={"menu_path": ["File", "Open Recent", "~/designs/arm_v3.f3d"], "shortcut": None}
    )
    with pytest.raises(IngestRejectedError) as info:
        await ingest(db, entry=poisoned, ctx=DOCS_CTX)
    await db.rollback()
    # `from None` must keep the pydantic error (whose str embeds the input)
    # out of anything a logger would format.
    rendered = "".join(traceback.format_exception(info.value))
    assert "arm_v3" not in rendered


async def test_docs_ingest_overtakes_lower_trust_candidate(db: AsyncSession) -> None:
    squat = _tk(provenance="operator_authored", description="An operator's guess at what it does.")
    first = await ingest(db, entry=squat, ctx=OPERATOR_CTX)
    assert first.status is KnowledgeStatus.CANDIDATE

    docs = _tk(provenance="vendor_docs")
    second = await ingest(db, entry=docs, ctx=DOCS_CTX)
    # same row, upgraded in place — the docs CONTENT replaces the squatter's
    assert second.id == first.id
    assert second.status is KnowledgeStatus.PUBLISHED
    assert second.provenance is Provenance.VENDOR_DOCS
    assert second.acquired_via is AcquisitionMethod.DOCS
    assert second.confidence == 0.8
    assert second.description == "Places a named net label on the current wire."
    count = await db.scalar(select(func.count()).select_from(ToolKnowledgeEntry))
    assert count == 1


async def test_docs_does_not_downgrade_docs(db: AsyncSession) -> None:
    first = await ingest(db, entry=_tk(), ctx=DOCS_CTX)
    changed = _tk(description="A newer description from the same docs page.")
    second = await ingest(db, entry=changed, ctx=DOCS_CTX)
    # docs→docs stays plain idempotent (updates are TU-07's re-verification)
    assert second.id == first.id
    assert second.description == "Places a named net label on the current wire."


async def test_lost_insert_race_converges_on_the_winner(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from solus_api.toolkb import guard as guard_module

    winner = await ingest(db, entry=_tk(), ctx=DOCS_CTX)

    # Simulate the race: the loser's pre-insert lookup misses the winner's
    # row, so it attempts the insert and hits the partial unique index.
    real_find = guard_module._find_live
    calls = {"n": 0}

    async def racy_find(session: AsyncSession, tk: object) -> object:
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return await real_find(session, tk)  # type: ignore[arg-type]

    monkeypatch.setattr(guard_module, "_find_live", racy_find)
    loser = await ingest(db, entry=_tk(), ctx=DOCS_CTX)
    assert loser.id == winner.id
    count = await db.scalar(select(func.count()).select_from(ToolKnowledgeEntry))
    assert count == 1


# ---------------------------------------------------------------- tripwire
def test_no_entry_construction_outside_guard() -> None:
    """The guard is the ONLY write path — mechanically, like illegal.ts."""
    src_root = Path(solus_api.__file__).resolve().parent
    construction = re.compile(r"(?<!class )ToolKnowledgeEntry\(")
    offenders = [
        str(path.relative_to(src_root))
        for path in sorted(src_root.rglob("*.py"))
        if not (path.parent.name == "toolkb" and path.name == "guard.py")
        and construction.search(path.read_text())
    ]
    assert offenders == [], f"ToolKnowledgeEntry constructed outside toolkb/guard.py: {offenders}"
