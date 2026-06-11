from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from solus_api.config import settings


def create_app() -> FastAPI:
    """Application factory. Keeps app construction testable and importable."""
    app = FastAPI(title="Solus API", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        """Liveness probe. Used by you locally and by App Runner in production."""
        return {"status": "ok"}

    return app


app = create_app()
