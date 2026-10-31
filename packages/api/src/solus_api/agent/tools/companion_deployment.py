"""Provisioned companion deployment uses the existing central confirmation gate. Its card also
shows what the simulation ladder proposes first for the target it deploys to (SOLUSDEV-321 P4-T5,
R116): no one read gives the robot whose host topology holds a target, so the pre-check is about
the target itself."""

from typing import Any
from uuid import UUID

from solus_api.agent.confirmations import _MAX_PREVIEW_ROWS
from solus_api.agent.tools.shapes import ToolDescriptor, ToolErrorCode
from solus_api.agent.tools.simulate import precheck_rows
from solus_api.agent.tools.tool import InProcessTool, ToolException
from solus_api.core.errors import APIError
from solus_api.hardware.companion_deployment import CompanionDeploymentService


class CompanionDeploymentTool(InProcessTool):
    requires_complete_preview = True


def make_companion_deployment_tool(service: CompanionDeploymentService) -> InProcessTool:
    async def invoke(args: dict[str, Any]) -> dict[str, Any]:
        try:
            outcome = await service.execute(UUID(args["plan_id"]))
            if outcome["status"] != "succeeded":
                raise ToolException(
                    "Companion deployment failed; inspect the retained deployment outcome",
                    code=ToolErrorCode.TOOL_ERROR,
                    retryable=False,
                )
            return outcome
        except APIError as exc:
            raise ToolException(
                exc.message, code=ToolErrorCode.TOOL_ERROR, retryable=False
            ) from None

    async def preview(args: dict[str, Any]) -> list[dict[str, Any]]:
        rows = await service.preview(UUID(args["plan_id"]))
        plan = await service.plan(UUID(args["plan_id"]))
        advice = await precheck_rows(
            service.session,
            service.project_id,
            service.user_id,
            [UUID(plan.attrs["target_id"])],
            room=_MAX_PREVIEW_ROWS - len(rows),
        )
        return [*rows, *advice]

    return CompanionDeploymentTool(
        ToolDescriptor(
            name="hardware.deploy_companion",
            description="Deploy a reviewed offline companion bundle "
            "to its explicitly provisioned onboard target. No initial provisioning.",
            params={
                "type": "object",
                "properties": {"plan_id": {"type": "string", "format": "uuid"}},
                "required": ["plan_id"],
                "additionalProperties": False,
            },
            returns={"type": "object"},
            requires_confirmation=True,
            timeout_seconds=300,
            consent_summary=(
                "Install and restart the provisioned onboard companion, then verify its handshake."
            ),
        ),
        invoke,
        preview,
    )
