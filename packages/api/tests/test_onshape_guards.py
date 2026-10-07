"""Production-path guards raise ConnectorError, never a strippable `assert` (CLAUDE.md §7)."""

import httpx
import pytest
from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.onshape import OnshapeConnector


async def test_waiting_for_a_translation_without_a_cache_is_a_connector_error() -> None:
    connector = OnshapeConnector(client_id="id", client_secret="secret")
    async with httpx.AsyncClient() as client:
        with pytest.raises(ConnectorError) as raised:
            await connector._await_completion(client, "request1")
    assert raised.value.code == "unavailable"


async def test_admitting_a_call_without_a_meter_is_a_connector_error() -> None:
    connector = OnshapeConnector(client_id="id", client_secret="secret")
    with pytest.raises(ConnectorError) as raised:
        await connector._admit()
    assert raised.value.code == "unavailable"
