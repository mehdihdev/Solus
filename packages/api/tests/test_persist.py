"""RBT-05: confirmed robots persist through the FP-02 fingerprint seam — define once.

No new identity type: everything below rides `CanonicalPart`/`ModalityMatch`/
`ingest_output` and lands in the same `kind="canonical_part"` rows FP-02 owns.
"""

import uuid

from solus_api.fingerprint import (
    MatchState,
    Modality,
    ModalityMatch,
    SourceRef,
)
from solus_api.livebench.persist import (
    ConfirmedMapping,
    persist_confirmed_robot,
    recognize_robot,
)
from solus_api.models import GraphEntity, Project, Team
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _project(db: AsyncSession, suffix: str) -> Project:
    team = Team(name=f"T-{suffix}-{uuid.uuid4().hex[:6]}")
    db.add(team)
    await db.flush()
    project = Project(team_id=team.id, name=f"P-{suffix}")
    db.add(project)
    await db.flush()
    return project


def _bus(ref: str, model: str) -> ModalityMatch:
    return ModalityMatch(
        modality=Modality.BUS_ENUMERATION,
        source_ref=SourceRef(source_connector="dynamixel", external_ref=ref),
        confidence=0.92,
        state=MatchState.MATCHED,
        evidence={"matched_on": "model_register", "value": model, "note": "self-asserted"},
    )


def _firmware(path: str) -> ModalityMatch:
    return ModalityMatch(
        modality=Modality.FIRMWARE_SYMBOL,
        source_ref=SourceRef(source_connector="repo", external_ref=path),
        confidence=0.55,
        state=MatchState.LOW_CONFIDENCE,
        evidence={"matched_on": "firmware_symbol", "value": "servo_elbow", "note": "code intent"},
    )


def _telemetry(ref: str) -> ModalityMatch:
    return ModalityMatch(
        modality=Modality.TELEMETRY_CHANNEL,
        source_ref=SourceRef(source_connector="active-id", external_ref=ref),
        confidence=0.9,
        state=MatchState.MATCHED,
        evidence={"matched_on": "active_correlation", "value": "8.3σ", "note": "observed"},
    )


ELBOW = ConfirmedMapping(
    part_number="XM430-W350",
    manufacturer="ROBOTIS",
    function_name="elbow",
    evidence=[_bus("ttyUSB0/id:3", "1020"), _firmware("src/arm.ino:11"), _telemetry("ch1")],
)


async def _canonicals(db: AsyncSession, project_id: uuid.UUID) -> list[GraphEntity]:
    rows = await db.scalars(
        select(GraphEntity).where(
            GraphEntity.project_id == project_id,
            GraphEntity.kind == "canonical_part",
            GraphEntity.deleted_at.is_(None),
        )
    )
    return list(rows)


async def test_confirmed_mapping_persists_as_one_canonical_part(db: AsyncSession) -> None:
    project = await _project(db, "persist")

    report = await persist_confirmed_robot(db, project_id=project.id, confirmed=[ELBOW])

    assert report.persisted == ["XM430W350"]
    (row,) = await _canonicals(db, project.id)
    assert row.canonical_key == "XM430W350"  # normalized base, matching FP-02
    modalities = row.attrs["fingerprint"]["modalities"]
    # All three modalities reconcile into the ONE canonical entity...
    kinds = {key.split(":")[0] for key in modalities}
    assert kinds == {"bus_enumeration", "firmware_symbol", "telemetry_channel"}
    # ...and the user's confirmation rides the seam as evidence, no new type.
    confirmations = [
        entry
        for entry in modalities.values()
        if entry["evidence"].get("matched_on") == "user_confirmation"
    ]
    assert len(confirmations) == 1
    assert confirmations[0]["evidence"]["value"] == "elbow"


async def test_persist_is_idempotent_define_once(db: AsyncSession) -> None:
    project = await _project(db, "idem")

    await persist_confirmed_robot(db, project_id=project.id, confirmed=[ELBOW])
    await persist_confirmed_robot(db, project_id=project.id, confirmed=[ELBOW])

    assert len(await _canonicals(db, project.id)) == 1


async def test_partless_confirmations_are_reported_never_invented(db: AsyncSession) -> None:
    # A tier-3 user-named channel has NO part identity; fabricating a part number
    # would poison the MPN namespace. It is reported, not silently persisted.
    project = await _project(db, "partless")
    nameless = ConfirmedMapping(
        part_number=None,
        manufacturer=None,
        function_name="shoulder",
        evidence=[_telemetry("serial:/dev/ttyACM0/ch2")],
    )

    report = await persist_confirmed_robot(db, project_id=project.id, confirmed=[nameless])

    assert report.persisted == []
    assert report.skipped_no_part_identity == ["shoulder"]
    assert await _canonicals(db, project.id) == []


async def test_unconfirmed_stays_explicitly_unlinked(db: AsyncSession) -> None:
    project = await _project(db, "unconf")
    stray = SourceRef(source_connector="serial", external_ref="/dev/ttyACM0/ch5")

    report = await persist_confirmed_robot(
        db, project_id=project.id, confirmed=[ELBOW], unconfirmed=[stray]
    )

    assert report.unconfirmed_recorded == 1
    (row,) = await _canonicals(db, project.id)
    # The stray channel never becomes a canonical row and never links.
    assert row.canonical_key == "XM430W350"


async def test_reconnect_recognizes_without_reconfirmation(db: AsyncSession) -> None:
    project = await _project(db, "recog")
    await persist_confirmed_robot(db, project_id=project.id, confirmed=[ELBOW])

    outcome = await recognize_robot(
        db, project_id=project.id, observed={"ttyUSB0/id:3": "XM430-W350"}
    )

    assert outcome.recognized is True
    assert outcome.changed == {}
    assert outcome.added == set()
    assert outcome.missing == set()


async def test_changed_configuration_is_detected_and_reproposed(db: AsyncSession) -> None:
    project = await _project(db, "changed")
    await persist_confirmed_robot(db, project_id=project.id, confirmed=[ELBOW])

    outcome = await recognize_robot(
        db,
        project_id=project.id,
        observed={"ttyUSB0/id:3": "XL330-M288", "ttyUSB0/id:9": "XM540-W270"},
    )

    assert outcome.recognized is False  # re-propose, never silently keep
    assert outcome.changed == {"ttyUSB0/id:3": ("XM430W350", "XL330M288")}
    assert outcome.added == {"ttyUSB0/id:9"}


async def test_missing_hardware_is_named(db: AsyncSession) -> None:
    project = await _project(db, "missing")
    await persist_confirmed_robot(db, project_id=project.id, confirmed=[ELBOW])

    outcome = await recognize_robot(db, project_id=project.id, observed={})

    assert outcome.recognized is False
    assert outcome.missing == {"ttyUSB0/id:3"}


def test_no_parallel_identity_mechanism() -> None:
    """Review guard: persistence rides the fingerprint seam and nothing else."""
    from pathlib import Path

    import solus_api.livebench.persist as persist_module

    source = Path(persist_module.__file__).read_text()
    imports = [
        line for line in source.splitlines() if line.strip().startswith(("import ", "from "))
    ]
    fingerprint_imports = [line for line in imports if "fingerprint" in line]
    assert fingerprint_imports, "persistence must go through the fingerprint seam"
    assert not any("CREATE TABLE" in line or "Table(" in line for line in source.splitlines())


async def test_confirmed_part_converges_with_fp02_on_one_canonical_key(db: AsyncSession) -> None:
    # Security H3: a Dynamixel confirmed via RBT-03 must reconcile onto the SAME
    # canonical row FP-02 already owns — not fork a second identity per hyphen.
    from solus_api.fingerprint import CanonicalPart
    from solus_api.fingerprint.config import default_fingerprint_config
    from solus_api.fingerprint.ingest import ingest
    from solus_api.fingerprint.normalize import canonical_uuid, normalize_mpn

    project = await _project(db, "converge")
    base = normalize_mpn("XM430-W350", default_fingerprint_config())
    assert base is not None
    fp_part = CanonicalPart(
        canonical_id=canonical_uuid(base.base),
        part_number=base.base,
        manufacturer="ROBOTIS",
        modalities=[_bus("ttyUSB0/id:3", "1020")],
        confidence=0.92,
    )
    await ingest(db, fp_part, project_id=project.id)

    await persist_confirmed_robot(db, project_id=project.id, confirmed=[ELBOW])

    # One canonical row, not two: the confirmed robot merged into FP-02's entity.
    rows = await _canonicals(db, project.id)
    assert len(rows) == 1
    assert rows[0].canonical_key == "XM430W350"


async def test_over_long_part_number_is_skipped_not_raised(db: AsyncSession) -> None:
    project = await _project(db, "overlong")
    huge = ConfirmedMapping(
        part_number="A" + "1" * 200,  # normalizes to something > 64 chars
        manufacturer=None,
        function_name="mystery",
        evidence=[_bus("ttyUSB0/id:1", "999")],
    )

    report = await persist_confirmed_robot(db, project_id=project.id, confirmed=[huge])

    assert report.persisted == []
    assert "mystery" in report.skipped_no_part_identity
    assert await _canonicals(db, project.id) == []
