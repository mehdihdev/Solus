"""SOLUSDEV-322 P6-T2 — `sim.generate_model`: the CAD twin becomes a simulation model, by card.

A static card (`requires_confirmation=True`, complete preview): its preview IS the gap report
(`simulation/model_job.gap_report`) — one row per property the model will state (`<link>.mass`,
`<joint>.frame`, `<joint>.limits`, `<joint>.actuated`, `<link>.sensor_site`) and one per gap, each
naming where the missing fact is set. The person sees exactly what the model will and will not
know before anything runs. Approval enqueues `run_generate_sim_model` (ARQ, `connectors/worker.py`)
through the same enqueue `simulate` uses; the job runs off the request path and the result is the
`simulation_model` entity the job registers. Nothing is generated when no mate can move: the card
is refused with the reason, and nothing is parked. The tool names no simulator.
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, Any, Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.agent.preview_refusal import PreviewRefusal
from solus_api.agent.tools.isaac_models import EntityId
from solus_api.agent.tools.registry import ToolRegistry
from solus_api.agent.tools.shapes import ToolDescriptor, ToolErrorCode
from solus_api.agent.tools.sim_assets import refusal_sentence
from solus_api.agent.tools.tool import ToolException
from solus_api.core.errors import APIError
from solus_api.simulation.model_job import (
    JOB,
    Enqueue,
    GenerateModelRequest,
    GenerateRefusedError,
    gap_report,
    gather,
)

logger = logging.getLogger("solus.agent.tools.sim_generate")

NAME: Final = "sim.generate_model"
_MAX_ROWS: Final = 50
_LABEL_CAP: Final = 200
_VALUE_CAP: Final = 500
_NO_QUEUE: Final = (
    "No job queue is configured on this server: a model is generated only as its bounded job, "
    "never in a SOL request."
)


class GenerateModelArgs(BaseModel):
    """`robot_id` and a model name that is a plain label (never an option, never path syntax)."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    robot_id: EntityId
    name: Annotated[str, Field(pattern=r"^[A-Za-z0-9_][A-Za-z0-9_ .-]{0,119}$")]
    source_entity_id: EntityId | None = None


def _parse_generate_args(args: dict[str, Any]) -> GenerateModelArgs:
    try:
        return GenerateModelArgs.model_validate(args)
    except ValidationError:
        raise ToolException(
            "Invalid arguments: robot_id (the robot entity), name (a plain label of at most 120 "
            "characters) and an optional source_entity_id (the CAD assembly).",
            code=ToolErrorCode.INVALID_ARGS,
            retryable=False,
        ) from None


def _report_value(value: Any, unit: str | None) -> str:
    if isinstance(value, float):
        text = f"{value:.6g}"
    elif isinstance(value, dict):
        text = ", ".join(f"{key} {_report_value(item, None)}" for key, item in value.items())
    elif isinstance(value, list):
        text = "[" + ", ".join(_report_value(item, None) for item in value) + "]"
    else:
        text = str(value)
    return f"{text} {unit}" if unit else text


def _bounded_text(text: str, cap: int) -> str:
    clean = "".join(ch if ch.isprintable() else " " for ch in text)
    return clean if len(clean) <= cap else clean[: cap - 1] + "…"


def gap_report_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    """The gap report as the card's rows: properties first, then gaps, bounded to the card."""
    rows = [
        {
            "label": _bounded_text(p["name"], _LABEL_CAP),
            "before": None,
            "after": _bounded_text(
                f"{_report_value(p['value'], p['unit'])} ({p['source']})", _VALUE_CAP
            ),
        }
        for p in report["properties"]
    ] + [
        {
            "label": _bounded_text(g["name"], _LABEL_CAP),
            "before": None,
            "after": _bounded_text(f"GAP — set in {g['set_in']}", _VALUE_CAP),
        }
        for g in report["gaps"]
    ]
    if len(rows) > _MAX_ROWS:
        more = len(rows) - (_MAX_ROWS - 1)
        rows = rows[: _MAX_ROWS - 1] + [
            {"label": f"… and {more} more rows", "before": None, "after": None}
        ]
    return rows


class SimGenerateTool:
    """`sim.generate_model`, bound to one project and person (the module docstring)."""

    requires_complete_preview = True

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        project_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        enqueue_sim: Enqueue | None,
    ) -> None:
        self.sessions, self.project_id, self.user_id = sessions, project_id, user_id
        self.enqueue_sim = enqueue_sim
        self._descriptor = ToolDescriptor(
            name=NAME,
            description=(
                "Generate a simulation model (URDF and the physics scene) of a robot from its CAD "
                "import: the moving mates with a known mate frame and known limits become joints, "
                "masses come from the CAD's cached mass properties or a material density, the bus "
                "map marks what is actuated. The card lists every property the model will state "
                "and every gap (and where to set it); the person approves, then the model is "
                "generated as a background job and registered as a simulation_model entity."
            ),
            params=GenerateModelArgs.model_json_schema(),
            returns={"type": "object"},
            requires_confirmation=True,
            consent_summary="Generate the shown simulation model from the robot's CAD import",
        )

    @property
    def descriptor(self) -> ToolDescriptor:
        return self._descriptor

    def _request(self, parsed: GenerateModelArgs) -> GenerateModelRequest:
        return GenerateModelRequest(
            project_id=str(self.project_id),
            robot_id=parsed.robot_id,
            name=parsed.name,
            requested_by=str(self.user_id),
            source_entity_id=parsed.source_entity_id,
        )

    async def _report(self, parsed: GenerateModelArgs) -> dict[str, Any]:
        try:
            async with self.sessions() as session:
                return gap_report(await gather(session, self._request(parsed)))
        except GenerateRefusedError as exc:
            sentence = refusal_sentence({"reason": str(exc)})
            raise PreviewRefusal(f"{sentence} Nothing was parked.") from None
        except APIError as exc:  # 404/409/422 from the scene: Solus-composed messages
            raise PreviewRefusal(
                f"{exc.message} Nothing was parked.", code=ToolErrorCode.NOT_FOUND
            ) from None

    async def preview(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        report = await self._report(_parse_generate_args(args))
        if not any(name.endswith(".frame") for name in (p["name"] for p in report["properties"])):
            raise PreviewRefusal(
                "No moving mate has its mate frame, so no joint can be generated; the gaps name "
                "where the frames are set. Nothing was parked."
            )
        return gap_report_rows(report)

    async def invoke(self, args: dict[str, Any]) -> dict[str, Any]:
        """Only ever after the person approved the card (the confirmation flow runs it)."""
        parsed = _parse_generate_args(args)
        if self.enqueue_sim is None:
            raise ToolException(_NO_QUEUE, code=ToolErrorCode.UNAVAILABLE, retryable=False)
        report = await self._report(parsed)
        request = self._request(parsed).model_dump(mode="json")
        try:
            job_id = await self.enqueue_sim(JOB, str(self.project_id), request)
        except Exception:  # another system: never its text
            logger.warning("model generation not queued project=%s", self.project_id, exc_info=True)
            raise ToolException(
                "The model generation could not be queued; try again.",
                code=ToolErrorCode.UNAVAILABLE,
                retryable=True,
            ) from None
        return {
            "status": "queued",
            "job_id": job_id,
            "robot_id": parsed.robot_id,
            "name": parsed.name,
            "gaps": report["gaps"],
        }


def register_sim_generate(
    registry: ToolRegistry,
    sessions: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    enqueue_sim: Enqueue | None,
) -> None:
    registry.register(
        SimGenerateTool(sessions, project_id, user_id=user_id, enqueue_sim=enqueue_sim)
    )
