"""Presence flashing participates in the existing central confirmation gate."""

from typing import Any
from uuid import UUID

from solus_api.agent.tools.shapes import ToolDescriptor, ToolErrorCode
from solus_api.agent.tools.tool import InProcessTool, ToolException
from solus_api.core.errors import APIError
from solus_api.hardware.presence import PresenceService


class PresenceFlashTool(InProcessTool):
    """A firmware action must never fall back to plan-ID-only consent."""

    requires_complete_preview = True


def make_presence_tool(service: PresenceService) -> InProcessTool:
    async def invoke(args: dict[str, Any]) -> dict[str, Any]:
        try:
            return await service.execute(UUID(args["plan_id"]))
        except APIError as exc:
            raise ToolException(
                exc.message, code=ToolErrorCode.TOOL_ERROR, retryable=False
            ) from None

    async def preview(args: dict[str, Any]) -> list[dict[str, Any]]:
        return await service.preview(UUID(args["plan_id"]))

    return PresenceFlashTool(
        ToolDescriptor(
            name="hardware.flash_presence",
            description=(
                "Flash a prepared presence plan onto its reviewed local MCU. "
                "Never flash driver boards."
            ),
            params={
                "type": "object",
                "properties": {"plan_id": {"type": "string", "format": "uuid"}},
                "required": ["plan_id"],
                "additionalProperties": False,
            },
            returns={"type": "object"},
            requires_confirmation=True,
            timeout_seconds=150,
            consent_summary=(
                "Erase and replace this board firmware with the complete reviewed presence source."
            ),
        ),
        invoke,
        preview,
    )
