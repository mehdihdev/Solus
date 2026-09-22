"""Platform restrictions are catalog data, independent of the API host OS."""

import pytest
from solus_api.routers.integrations import list_local_tools


@pytest.fixture(scope="session")
def _schema() -> None:
    """These catalog unit tests never access the database."""


async def test_local_tools_publishes_fusion_platform_restrictions() -> None:
    result = await list_local_tools(None)  # type: ignore[arg-type]
    fusion = next(tool for tool in result["data"] if tool["type"] == "fusion")
    assert fusion["supported_platforms"] == ["darwin", "win32"]
