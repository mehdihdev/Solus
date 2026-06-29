"""DB session dependency wiring."""

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine


def test_app_state_holds_engine(app: FastAPI, engine: AsyncEngine) -> None:
    assert app.state.engine is engine
    assert app.state.sessionmaker is not None


async def test_readyz_exercises_session(client: AsyncClient) -> None:
    resp = await client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json()["data"]["checks"]["database"] == "ok"
