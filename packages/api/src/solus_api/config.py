from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration.

    Values are read from environment variables (and a local .env file).
    Anything not set falls back to the local-dev default below, so the app
    runs out of the box against docker-compose. Secrets are NEVER hardcoded
    here in real values (CLAUDE.md §7) — the defaults are local-only.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://solus:solus@localhost:5432/solus"
    redis_url: str = "redis://localhost:6379/0"
    api_cors_origins: str = "http://localhost:5173,http://localhost:3000"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.api_cors_origins.split(",") if o.strip()]


settings = Settings()
