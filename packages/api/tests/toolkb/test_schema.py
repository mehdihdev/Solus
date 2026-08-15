"""SOLUS-TU-04 (SOLUSDEV-207) — tool-knowledge KB schema + storage tests.

The table mirrors the CTR-05 boundary exactly (typed columns, no JSONB, no
customer-owned identifier anywhere) plus storage-side columns that are all
enum/number/timestamp — nothing storage adds can hold prose. The version model
derives sortable keys from the verbatim ``version_range`` so tool+version
lookups are pure btree and TU-07 staleness needs no schema rewrite.
"""

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from solus_api.contracts import tool_knowledge as ctr
from solus_api.models import EMBEDDING_DIM, utcnow
from solus_api.toolkb.schema import (
    INITIAL_CONFIDENCE,
    AcquisitionMethod,
    KnowledgeStatus,
    ToolKnowledgeEntry,
    to_contract,
    version_key,
    version_keys,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

type EntryFactory = Callable[..., ToolKnowledgeEntry]

FIXTURES = Path(ctr.__file__).resolve().parents[4] / "shared-types" / "fixtures" / "tool-knowledge"
CONTRACT_FIXTURES = ("fusion-extrude.json", "kicad-net-label.json")


# --------------------------------------------------------------- version keys
class TestVersionKey:
    def test_pads_components(self) -> None:
        assert version_key("2.1") == "0002.0001.0000"
        assert version_key("10.5.3") == "0010.0005.0003"
        assert version_key("9") == "0009.0000.0000"

    def test_component_cap(self) -> None:
        # ponytail: 4-digit components — breaks ordering at version 10000; widen the pad then.
        with pytest.raises(ValueError):
            version_key("10000.0")

    def test_rejects_garbage(self) -> None:
        with pytest.raises(ValueError):
            version_key("banana")


class TestVersionKeys:
    @pytest.mark.parametrize(
        ("version_range", "expected"),
        [
            (">=2.0 <3.0", ("0002.0000.0000", "0003.0000.0000")),
            (">=2.0", ("0002.0000.0000", None)),
            ("<3.0", ("0000.0000.0000", "0003.0000.0000")),
            # bare / "=" — equality window at stated precision
            ("2.0", ("0002.0000.0000", "0002.0001.0000")),
            ("=2.1", ("0002.0001.0000", "0002.0002.0000")),
            ("2", ("0002.0000.0000", "0003.0000.0000")),
            # exclusive lower bumps at full patch precision
            (">2.1", ("0002.0001.0001", None)),
            # inclusive upper bumps at stated precision
            ("<=2.1", ("0000.0000.0000", "0002.0002.0000")),
            ("~2.1", ("0002.0001.0000", "0002.0002.0000")),
            ("~2.1.4", ("0002.0001.0004", "0002.0002.0000")),
            ("~2", ("0002.0000.0000", "0003.0000.0000")),
            ("^2.1", ("0002.0001.0000", "0003.0000.0000")),
            # npm caret with major 0 bumps the leftmost non-zero STATED
            # component (review finding: this was <1.0.0 — 10x too wide)
            ("^0.2.3", ("0000.0002.0003", "0000.0003.0000")),
            ("^0.0.3", ("0000.0000.0003", "0000.0000.0004")),
            ("^0", ("0000.0000.0000", "0001.0000.0000")),
            ("^0.0", ("0000.0000.0000", "0000.0001.0000")),
            (">=8.0 <9.0", ("0008.0000.0000", "0009.0000.0000")),
        ],
    )
    def test_window(self, version_range: str, expected: tuple[str, str | None]) -> None:
        assert version_keys(version_range) == expected

    def test_empty_window_rejected(self) -> None:
        with pytest.raises(ValueError, match="empty version window"):
            version_keys(">=3.0 <2.0")

    def test_unsupported_operator_rejected(self) -> None:
        with pytest.raises(ValueError):
            version_keys("~^2")

    def test_garbage_rejected(self) -> None:
        with pytest.raises(ValueError):
            version_keys("latest")

    def test_windows_are_queryable_lexicographically(self) -> None:
        low, high = version_keys(">=8.0 <9.0")
        assert high is not None
        assert low <= version_key("8.0.6") < high
        assert not (low <= version_key("9.0.1") < high)
        assert not (low <= version_key("7.9.9"))


def test_initial_confidence_covers_every_acquisition_method() -> None:
    assert set(INITIAL_CONFIDENCE) == set(AcquisitionMethod)
    assert all(0.0 < value <= 1.0 for value in INITIAL_CONFIDENCE.values())


# ------------------------------------------------------------------- helpers
async def _expect_integrity_error(db: AsyncSession, row: ToolKnowledgeEntry) -> None:
    db.add(row)
    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()


# ------------------------------------------------------------------ DB tests
async def test_write_read_full_entry(db: AsyncSession, make_entry: EntryFactory) -> None:
    row = make_entry(
        locator_x=0.31,
        locator_y=0.06,
        locator_w=0.04,
        locator_h=0.05,
        embedding=[0.25] * EMBEDDING_DIM,
    )
    db.add(row)
    await db.flush()
    db.expunge_all()

    loaded = (await db.execute(select(ToolKnowledgeEntry))).scalar_one()
    assert loaded.tool is ctr.ToolFamily.KICAD
    assert loaded.version_range == ">=8.0 <9.0"
    assert loaded.surface is ctr.UiSurface.MENU
    assert loaded.control_id == "kicad.eeschema.place_net_label"
    assert loaded.effect is ctr.ControlEffect.CREATE_FEATURE
    assert loaded.menu_path == ["Place", "Net Label"]
    assert loaded.shortcut == "L"
    assert loaded.provenance is ctr.Provenance.VENDOR_DOCS
    assert loaded.status is KnowledgeStatus.PUBLISHED
    assert loaded.acquired_via is AcquisitionMethod.DOCS
    assert loaded.confidence == 0.8
    assert loaded.confirm_count == 0 and loaded.reject_count == 0
    assert loaded.last_verified_at is None
    assert (loaded.locator_x, loaded.locator_y) == (0.31, 0.06)
    # pgvector reads back numpy.ndarray, not list (models.py note)
    assert list(loaded.embedding) == pytest.approx([0.25] * EMBEDDING_DIM)


@pytest.mark.parametrize("fixture_name", CONTRACT_FIXTURES)
async def test_contract_fixture_round_trips(
    db: AsyncSession, make_entry: EntryFactory, fixture_name: str
) -> None:
    original = ctr.ToolKnowledge.model_validate(json.loads((FIXTURES / fixture_name).read_text()))
    low, high = version_keys(original.version_range)
    invocation = original.invocation
    locator = original.locator
    row = make_entry(
        tool=original.tool,
        version_range=original.version_range,
        surface=original.surface,
        control_id=original.control_id,
        label=original.label,
        effect=original.effect,
        description=original.description,
        menu_path=None if invocation is None else invocation.menu_path,
        shortcut=None if invocation is None else invocation.shortcut,
        locator_x=None if locator is None else locator.x,
        locator_y=None if locator is None else locator.y,
        locator_w=None if locator is None else locator.w,
        locator_h=None if locator is None else locator.h,
        provenance=original.provenance,
        version_min_key=low,
        version_max_key=high,
    )
    db.add(row)
    await db.flush()
    db.expunge_all()

    loaded = (await db.execute(select(ToolKnowledgeEntry))).scalar_one()
    assert to_contract(loaded).model_dump() == original.model_dump()


def test_to_contract_reruns_the_boundary_validators(make_entry: EntryFactory) -> None:
    # A row that somehow held customer-shaped prose must fail at materialization,
    # not reach a tenant's Guide panel.
    poisoned = make_entry(label="~/designs/arm_v3.f3d")
    with pytest.raises(ValueError):
        to_contract(poisoned)


async def test_confidence_range_check(db: AsyncSession, make_entry: EntryFactory) -> None:
    await _expect_integrity_error(db, make_entry(confidence=1.5))


async def test_counts_nonnegative_check(db: AsyncSession, make_entry: EntryFactory) -> None:
    await _expect_integrity_error(db, make_entry(reject_count=-1))


async def test_menu_path_cardinality_check(db: AsyncSession, make_entry: EntryFactory) -> None:
    await _expect_integrity_error(db, make_entry(menu_path=[f"Menu{i}" for i in range(9)]))


async def test_locator_all_or_none_check(db: AsyncSession, make_entry: EntryFactory) -> None:
    await _expect_integrity_error(db, make_entry(locator_x=0.5))


async def test_locator_bounds_check(db: AsyncSession, make_entry: EntryFactory) -> None:
    await _expect_integrity_error(
        db, make_entry(locator_x=1.5, locator_y=0.1, locator_w=0.1, locator_h=0.1)
    )


async def test_identity_unique_among_live_rows(db: AsyncSession, make_entry: EntryFactory) -> None:
    db.add(make_entry())
    await db.flush()
    await _expect_integrity_error(db, make_entry())


async def test_soft_deleted_identity_can_be_readded(
    db: AsyncSession, make_entry: EntryFactory
) -> None:
    first = make_entry()
    db.add(first)
    await db.flush()
    first.deleted_at = utcnow()
    await db.flush()

    db.add(make_entry())
    await db.flush()  # would raise if the unique index were not partial
