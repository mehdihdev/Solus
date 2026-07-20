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

    # Supabase Admin API (service-role) for account-lifecycle actions
    # (SOLUSDEV-82): revoke sessions + delete the auth user on account deletion.
    # The service-role key is highly privileged — env/Secrets Manager only, never
    # logged or returned. Absent ⇒ the admin client no-ops (dev/tests): local data
    # is still removed, but the Supabase session/auth-user is left intact.
    supabase_url: str | None = None
    supabase_service_role_key: str | None = None

    # Interim in-process limiter until the ADR-019 budget system lands (Phase 5).
    rate_limit_per_minute: int = 120
    # MO-04 classify preview: fired on typing pauses, so it gets its own
    # generous separate bucket (never counts against the global budget above).
    classify_rate_limit_per_minute: int = 600

    invite_ttl_days: int = 7
    trial_days: int = 30

    # --- Billing (SOLUSDEV-83 / ADR-024) ---
    # The webhook secret is a highly privileged secret — env / Secrets Manager
    # only, never logged or returned. Absent ⇒ the webhook rejects (503) and no
    # live billing happens; the credit primitives still run locally for
    # tests/dev. No Stripe API key yet: it arrives with checkout-session
    # creation (deferred); the never-read stripe_secret_key field was removed
    # in SOLUSDEV-152.
    stripe_webhook_secret: str | None = None
    # Bounded free-trial credit grant written at signup — the trial's hard cost
    # cap (ADR-024: "bounded credit grant, never unlimited"). PROVISIONAL: at the
    # models.yaml default of 100 credits/$ and margin 2.0, 1000 credits ≈ $5 of
    # real model spend. Calibrate from pilot data before production.
    trial_credit_grant: int = 1000
    # Stripe price-id → credits granted, for credit-pack purchases
    # (checkout.session.completed). Provisional; empty until real Stripe prices
    # exist. Parsed from a JSON env var, e.g. SOLUS_STRIPE_PACK_CREDITS='{"price_x":1000}'.
    stripe_pack_credits: dict[str, int] = {}
    # Max Stripe webhook body we will parse, bytes — bound untrusted input.
    stripe_webhook_max_bytes: int = 262144

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

    # GitLab OAuth application (SOLUSDEV-104). base_url supports self-hosted
    # instances; the OAuth app is registered on that instance.
    gitlab_client_id: str | None = None
    gitlab_client_secret: str | None = None
    gitlab_base_url: str = "https://gitlab.com"
    # Where the OAuth callback sends the user back to (the desktop app deep
    # link or a local page). Defaults to the renderer dev origin.
    github_oauth_redirect_app: str = "http://localhost:5173/#/onboarding"
    # Public base URL the provider redirects to for the callback (this API).
    public_api_base_url: str = "http://localhost:8000"
    # Run source syncs inline in the request instead of dispatching to ARQ /
    # background tasks. For tests and bare local dev only — prod uses the worker.
    sync_inline: bool = False
    # FP-01 LLM escalation (spec Part E). Off by default: the deterministic
    # matcher is fully functional without it. Read by the CALLER (FP-02 wiring)
    # to decide whether to build+pass an escalator — match() never reads this.
    fingerprint_llm_enabled: bool = False
    # FP-02 embedding write. Off by default and keyless-safe: ingestion is fully
    # functional with embedding NULL. Read by the CALLER (the future trigger
    # router) to decide whether to build+pass an EmbedFn — scan_project() never
    # reads this. The provider-backed EmbedFn awaits the MO-01 gateway embedding
    # extension (docs/api/gateway-embeddings.md).
    fingerprint_embedding_enabled: bool = False
    # FP-03 vision extraction (STRETCH/SCAFFOLD). Off by default and keyless-
    # inert. Read by the CALLER (the future trigger router) to decide whether to
    # run identify_from_image over photo artifacts and merge photo_observations
    # into the scan — visual.py and match() never read this.
    fingerprint_vision_enabled: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        """Parsed, non-empty CORS origins."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
