"""Application settings. All secrets come from the environment (CLAUDE.md §7)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, sourced from `SOLUS_*` environment variables."""

    model_config = SettingsConfigDict(env_prefix="SOLUS_", env_file=".env", extra="ignore")

    app_env: str = "dev"
    api_version: str = "0.1.0"
    build_sha: str = "dev"

    database_url: str = "postgresql+asyncpg://localhost:5432/solus"
    redis_url: str | None = None

    # Comma-separated origins allowed to call the API from a browser/renderer.
    # The Electron renderer dev server (electron-vite) defaults to :5173.
    cors_origins: str = "http://localhost:5173,http://localhost:4173"

    # Dev convenience only: create tables from the ORM metadata on startup when
    # there are no migrations yet. MUST stay false in any shared/prod env —
    # schema there is owned by migrations, never create_all.
    auto_create_tables: bool = False

    # Supabase Auth JWT validation (ADR-009). No default: the app must not
    # start without a verification secret.
    supabase_jwt_secret: str
    supabase_jwt_audience: str = "authenticated"

    # Interim in-process limiter until the ADR-019 budget system lands (Phase 5).
    rate_limit_per_minute: int = 120

    invite_ttl_days: int = 7
    trial_days: int = 30

    # --- Connector framework (SOLUSDEV-103) ---
    # Secret store selection. Prod/staging with aws_region set → AWS Secrets
    # Manager. Otherwise a Fernet key (secrets_key) → local encrypted store.
    # Neither → in-memory dev fallback (tokens lost on restart; logs a warning).
    secrets_key: str | None = None
    aws_region: str | None = None
    secrets_backend: str | None = None  # force "aws" | "local" | "memory" (optional)

    # GitHub OAuth App (ADR-009 names GitHub OAuth as a supported method).
    # Registered at github.com/settings/developers; callback must point at
    # `${api}/api/v1/integrations/github/oauth/callback`.
    github_client_id: str | None = None
    github_client_secret: str | None = None
    # Where the OAuth callback sends the user back to (the desktop app deep
    # link or a local page). Defaults to the renderer dev origin.
    github_oauth_redirect_app: str = "http://localhost:5173/#/onboarding"
    # Public base URL the provider redirects to for the callback (this API).
    public_api_base_url: str = "http://localhost:8000"
    # Run source syncs inline in the request instead of dispatching to ARQ /
    # background tasks. For tests and bare local dev only — prod uses the worker.
    sync_inline: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        """Parsed, non-empty CORS origins."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
