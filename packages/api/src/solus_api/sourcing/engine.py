"""The sourcing job (SOLUSDEV-246 ST5): one metered model call, parsed as data.

`run_request` never raises: every failure settles the request (and its Job)
as `failed` with a Solus-authored error, never a provider's text. The model
call goes through the orchestration gateway (routing, budget gates, credit
debit for `created_by`); the answer is parsed by `candidates.parse_candidates`
and filtered by `rules.apply_rules` — the model proposes, Solus decides.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.agent.prompt import new_nonce
from solus_api.connectors.secrets import SecretStore
from solus_api.models import Job, JobStatus, SourcingRequest, utcnow
from solus_api.orchestration.config import OrchestrationConfig
from solus_api.orchestration.enums import InteractionContext
from solus_api.orchestration.gates import (
    FrequencyCapExceededError,
    InsufficientCreditsError,
    TrialCapReachedError,
)
from solus_api.orchestration.gateway import complete
from solus_api.orchestration.providers import ProviderAdapter
from solus_api.sourcing.candidates import RequirementSpec, parse_candidates, sourcing_prompt
from solus_api.sourcing.rules import SourcingRules, apply_rules
from solus_api.sourcing.service import load_rules
from solus_api.sourcing.torque import Load, TorqueResult

logger = logging.getLogger("solus.sourcing")

#: Output budget for the candidate answer. Claude 5 models think before answering and the
#: thinking tokens count against `max_tokens` (a live run at 3000 came back with ZERO text
#: after 3000 billed output tokens), so the cap must leave room for eight fully-keyed
#: candidates AFTER the model's own reasoning. `parse_candidates` salvages a cut-off array.
MAX_TOKENS = 12000
PREFERENCE_KEYS = ("mechanical", "electrical", "unitsStandards", "freeText")
PREFERENCE_CAP = 800


def _torque(request: SourcingRequest) -> TorqueResult | None:
    raw = request.torque
    if not isinstance(raw, dict):
        return None
    try:
        return TorqueResult(
            static_torque_nm=float(raw["static_torque_nm"]),
            required_torque_nm=float(raw["required_torque_nm"]),
            safety_factor=float(raw["safety_factor"]),
            loads=tuple(
                Load(
                    name=str(load["name"]),
                    mass_kg=float(load["mass_kg"]),
                    lever_arm_m=float(load["lever_arm_m"]),
                )
                for load in raw.get("loads", [])
            ),
            unknown=tuple(str(u) for u in raw.get("unknown", [])),
            assumptions=tuple(str(a) for a in raw.get("assumptions", [])),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _preferences(spec: dict[str, Any]) -> dict[str, str] | None:
    raw = spec.get("preferences")
    if not isinstance(raw, dict):
        return None
    out = {
        k: str(raw[k])[:PREFERENCE_CAP]
        for k in PREFERENCE_KEYS
        if isinstance(raw.get(k), str) and raw[k].strip()
    }
    return out or None


class _NoRequesterError(Exception):
    """`created_by` is NULL (the user was deleted before the job ran)."""


def _error(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


async def _settle_job(session: AsyncSession, request: SourcingRequest, status: JobStatus) -> None:
    if request.job_id is None:
        return
    job = await session.scalar(select(Job).where(Job.id == request.job_id))
    if job is None:
        return
    job.status = status
    job.progress = 100 if status is JobStatus.SUCCEEDED else job.progress
    job.finished_at = utcnow()
    if status is JobStatus.FAILED:
        job.error = request.error


async def _run(
    session: AsyncSession,
    request: SourcingRequest,
    *,
    secret_store: SecretStore,
    adapters: Mapping[str, ProviderAdapter] | None,
    config: OrchestrationConfig | None,
    redis: Any,
    enqueue: Any,
) -> None:
    spec = RequirementSpec.model_validate(
        {k: v for k, v in request.spec.items() if k not in ("preferences", "assembly_name")}
    )
    rules = await load_rules(session, request.project_id)
    prompt = sourcing_prompt(
        new_nonce(),
        spec=spec,
        torque=_torque(request),
        rules=rules,
        preferences=_preferences(request.spec),
        assembly_name=(request.spec.get("assembly_name") if request.assembly_entity_id else None),
    )
    completion = await complete(
        prompt,
        secret_store=secret_store,
        context=InteractionContext.COMPATIBILITY_RESEARCH,
        config=config,
        adapters=adapters,
        user_id=request.created_by,
        session=session,
        redis=redis,
        enqueue=enqueue,
        max_tokens=MAX_TOKENS,
    )
    candidates = parse_candidates(completion.text)
    if not candidates:
        # "Why did this user's sourcing return nothing?" must be answerable from logs (CLAUDE.md
        # §6) WITHOUT shipping the team's part names to CloudWatch: shape, size and a digest at
        # WARNING; the head of the answer only at DEBUG (security review M4).
        text = completion.text
        logger.warning(
            "sourcing: request %s parsed 0 candidates "
            "(model %s, %d chars, starts %r, fenced=%s, sha=%s)",
            request.id,
            completion.model.model_name,
            len(text),
            text.lstrip()[:1],
            "```" in text,
            hashlib.sha256(text.encode()).hexdigest()[:12],
        )
        logger.debug("sourcing: request %s answer head=%r", request.id, text[:300])
    included, excluded = apply_rules(candidates, rules)
    request.candidates = [c.payload() for c in included]
    request.excluded = [{"candidate": c.payload(), "reasons": reasons} for c, reasons in excluded]
    request.rules = rules.payload()
    request.model = completion.model.model_name
    request.status = JobStatus.SUCCEEDED


async def run_request(
    sessionmaker: async_sessionmaker[AsyncSession],
    request_id: uuid.UUID,
    *,
    secret_store: SecretStore,
    adapters: Mapping[str, ProviderAdapter] | None = None,
    config: OrchestrationConfig | None = None,
    redis: Any = None,
    enqueue: Any = None,
) -> JobStatus | None:
    """Run one request to completion. Returns its final status, or None for an
    unknown id. Never raises."""
    async with sessionmaker() as session:
        request = await session.scalar(
            select(SourcingRequest).where(SourcingRequest.id == request_id)
        )
        if request is None:
            logger.warning("sourcing: request %s not found", request_id)
            return None
        if request.status is not JobStatus.QUEUED:
            # Idempotent: a re-delivered or retried job never buys a second model call.
            logger.info("sourcing: request %s already %s", request_id, request.status.value)
            return request.status
        request.status = JobStatus.RUNNING
        await session.commit()
        try:
            if request.created_by is None:
                # The gateway gates and meters by user; with no requester there is nobody to
                # gate or bill, so the call must not happen (security review M1).
                raise _NoRequesterError
            await _run(
                session,
                request,
                secret_store=secret_store,
                adapters=adapters,
                config=config,
                redis=redis,
                enqueue=enqueue,
            )
        except _NoRequesterError:
            request.status = JobStatus.FAILED
            request.error = _error("unknown_requester", "The requesting user no longer exists.")
        except InsufficientCreditsError:
            request.status = JobStatus.FAILED
            request.error = _error("insufficient_credits", "Not enough credits to run sourcing.")
        except (FrequencyCapExceededError, TrialCapReachedError):
            request.status = JobStatus.FAILED
            request.error = _error("rate_limited", "Sourcing is rate-limited right now; try later.")
        except Exception:  # noqa: BLE001 — never raise out of a job; never surface provider text
            logger.exception("sourcing: request %s failed", request_id)
            request.status = JobStatus.FAILED
            request.error = _error("model_unavailable", "Solus could not reach a model.")
        request.finished_at = utcnow()
        await _settle_job(session, request, request.status)
        await session.commit()
        return request.status


__all__ = ["MAX_TOKENS", "SourcingRules", "run_request"]
