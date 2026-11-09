"""Academic plan routes (ADR-042, SOLUSDEV-319): status, send a code, verify it.

Every route acts on the authenticated caller's own rows; no route takes a user id. The
rules and limits live in `billing/academic.py`."""

from typing import Any

from fastapi import APIRouter

from solus_api.billing.academic import AcademicPlanService
from solus_api.core.responses import envelope
from solus_api.deps import AcademicMailerDep, CurrentUser, SessionDep, SettingsDep
from solus_api.schemas import AcademicCodeCreate, AcademicVerifyCreate

router = APIRouter(prefix="/api/v1/billing/academic", tags=["billing"])


@router.get("")
async def get_academic(user: CurrentUser, session: SessionDep, settings: SettingsDep) -> Any:
    """The caller's academic status (none / pending / active / expired)."""
    status = await AcademicPlanService(session, settings).status(user.id)
    return envelope(status.model_dump(mode="json"))


@router.post("/code", status_code=202)
async def send_academic_code(
    body: AcademicCodeCreate,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    mailer: AcademicMailerDep,
) -> Any:
    """Email a 6-digit code to an academic address (rate-limited; see the service)."""
    status = await AcademicPlanService(session, settings).send_code(user, body.email, mailer)
    return envelope(status.model_dump(mode="json"))


@router.post("/verify")
async def verify_academic_code(
    body: AcademicVerifyCreate, user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> Any:
    """Check the code; on a match the caller's plan becomes Academic."""
    status = await AcademicPlanService(session, settings).verify(user, body.code)
    return envelope(status.model_dump(mode="json"))
