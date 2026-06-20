from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration from environment variables (and a local .env).

    Database connection is assembled from separate components so it works with
    AWS RDS-managed secrets (which store username/password/host/etc. as separate
    JSON fields). Locally, the components default to the docker-compose database.
    Secrets are never hardcoded in real values (CLAUDE.md §7).
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database components (RDS secret injects these as separate env vars in prod;
    # locally they default to docker-compose values).
    db_user: str = "solus"
    db_password: str = "solus"
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "solus"

    redis_url: str = "redis://localhost:6379/0"
    api_cors_origins: str = "http://localhost:5173,http://localhost:3000"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.api_cors_origins.split(",") if o.strip()]


settings = Settings()