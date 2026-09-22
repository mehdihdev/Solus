"""Only fixed quota diagnoses survive failed complete previews."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from solus_api.agent.confirmations import _build_preview
from solus_api.agent.tools.onshape_tools import _tool_error
from solus_api.connectors.contracts import ConnectorError


@pytest.mark.parametrize("code", ["quota_degraded", "quota_exhausted"])
async def test_quota_preview_retains_only_static_safe_reason(code):
    error = _tool_error(ConnectorError(code, "secret upstream payload"), preview_only=True)
    tool = SimpleNamespace(preview=AsyncMock(side_effect=error), requires_complete_preview=True)
    failures = []
    assert await _build_preview(tool, {}, quota_failures=failures) == []
    assert len(failures) == 1
    assert "quota" in failures[0].lower()
    assert "secret" not in failures[0]


async def test_untyped_preview_error_is_not_exposed_as_quota():
    tool = SimpleNamespace(preview=AsyncMock(side_effect=RuntimeError("secret quota_degraded")))
    failures = []
    assert await _build_preview(tool, {}, force_complete=True, quota_failures=failures) == []
    assert failures == []


def test_run_quota_error_never_claims_nothing_executed():
    from solus_api.agent.confirmations import QuotaPreviewUnavailable

    error = _tool_error(
        ConnectorError("quota_degraded", "Quota prevented readback; inspect the action outcome.")
    )
    assert not isinstance(error, QuotaPreviewUnavailable)
    assert "Nothing was executed" not in str(error)


async def test_successful_native_post_then_quota_refusal_retains_uncertain_outcome():
    import httpx
    import respx
    from test_onshape_fastened_repair import BASE, fixture, invoke

    with respx.mock:
        fixture()

        def post(request):
            respx.get(BASE + "/features").respond(402, json={})
            return httpx.Response(200, json={"success": True})

        route = respx.post(BASE + "/features/featureid/joint%2B%2F").mock(side_effect=post)
        with pytest.raises(ConnectorError) as error:
            await invoke()
        assert error.value.code == "mutation_unverified"
        assert "Nothing was executed" not in _tool_error(error.value).message
        assert route.call_count == 1


@pytest.mark.parametrize("stage", [1, 2])
async def test_build_quota_refusal_in_either_preview_never_executes(stage):
    from solus_api.agent.tools.shapes import ToolCall, ToolErrorCode
    from test_build_execution_policy import ROWS, dispatch_fixture, tool_fixture

    failure = _tool_error(ConnectorError("quota_degraded", "untrusted"), preview_only=True)
    preview = AsyncMock(side_effect=([ROWS] if stage == 2 else []) + [failure])
    _, registry, handler, _ = tool_fixture(preview=preview)
    _, dispatch = dispatch_fixture(registry)
    result = await dispatch(
        ToolCall(tool="onshape.create_circle_sketch", args={"n": 1}, call_id="quota")
    )
    assert not result.ok and result.error.code == ToolErrorCode.UNAVAILABLE
    assert "conservation threshold" in result.error.message
    assert "untrusted" not in result.error.message
    handler.assert_not_awaited()


@pytest.mark.parametrize("approval", [False, True])
async def test_confirmation_quota_refusal_never_parks_or_executes(engine, approval):
    from solus_api.agent.confirmations import decide_confirmation, request_confirmation
    from solus_api.agent.tools.shapes import ToolCall, ToolErrorCode
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from test_build_execution_policy import ROWS, tool_fixture
    from test_confirmations import _scope

    maker = async_sessionmaker(engine, expire_on_commit=False)
    project_id, team_id, user_id = await _scope(maker)
    preview = AsyncMock(return_value=ROWS)
    _, registry, handler, _ = tool_fixture(preview=preview)
    if not approval:
        preview.side_effect = _tool_error(
            ConnectorError("quota_exhausted", "secret"), preview_only=True
        )
    async with maker() as session:
        parked = await request_confirmation(
            session,
            registry,
            ToolCall(tool="onshape.create_circle_sketch", args={"n": 1}),
            project_id=project_id,
            team_id=team_id,
            user_id=user_id,
        )
        await session.commit()
        if approval:
            assert parked.confirmation_id is not None
            preview.side_effect = _tool_error(
                ConnectorError("quota_exhausted", "secret"), preview_only=True
            )
            result = await decide_confirmation(
                session,
                registry,
                parked.confirmation_id,
                approve=True,
                project_id=project_id,
                user_id=user_id,
            )
        else:
            assert parked.confirmation_id is None
            result = parked.result
    assert not result.ok and result.error.code == ToolErrorCode.UNAVAILABLE
    assert "quota is exhausted" in result.error.message and "secret" not in result.error.message
    handler.assert_not_awaited()
