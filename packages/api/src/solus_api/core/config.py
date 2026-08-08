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

    # Sentry error capture (SYS-02). Absent → sentry_sdk.init never runs and every
    # capture_* call is a documented SDK no-op — keyless environments stay silent.
    sentry_dsn: str | None = None

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
    # One-time starting credits granted when a paid plan first becomes live for
    # a user (ADR-023/024, amended 2026-08-08). Keyed by PlanType value; missing
    # key = no grant (enterprise is custom per deal). PROVISIONAL like the trial
    # grant: BASIC 2,500 (≈ the $25 pack), PRO 10,000 (4×). Calibrate post-pilot.
    plan_credit_grants: dict[str, int] = {"basic": 2500, "pro": 10000}
    # Stripe price-id → credits granted, for credit-pack purchases
    # (checkout.session.completed). Provisional; empty until real Stripe prices
    # exist. Parsed from a JSON env var, e.g. SOLUS_STRIPE_PACK_CREDITS='{"price_x":1000}'.
    stripe_pack_credits: dict[str, int] = {}
    # Stripe price-id → whole-dollar display price for the same packs, so the
    # UI can show "$10" beside "1,000 credits". Display-only — the charged
    # amount is always the Stripe Price itself; unmapped packs show creditless.
    stripe_pack_usd: dict[str, int] = {}
    # Max Stripe webhook body we will parse, bytes — bound untrusted input.
    stripe_webhook_max_bytes: int = 262144

    # --- Stripe Checkout (SOLUSDEV-83 follow-up) — the outbound money-in surface.
    # The Stripe SECRET API KEY is NOT a setting: it lives in the SecretStore under
    # "stripe_api_key" (like the LLM provider keys), never in config, env, or logs.
    # Maps "<plan>:<interval>" → Stripe recurring Price id, e.g.
    # {"basic:month": "price_...", "pro:year": "price_..."}. Empty until real
    # Prices exist; checkout for an unmapped plan returns 503 billing_unconfigured.
    stripe_plan_prices: dict[str, str] = {}
    # Free-trial length applied to a NEW Stripe subscription (trial_period_days).
    # Config, not hardcoded — this is the single place that resolves the ADR-024
    # "one month" vs the 14-day code/API drift; calibrate here. 0 disables it.
    stripe_trial_days: int = 14
    # Where Stripe returns the user after Checkout / the billing portal. The
    # `checkout=`/`portal=` markers are load-bearing (SOLUSDEV-114): the desktop
    # opens Stripe in an in-app window and closes it when the top frame navigates
    # to a marker URL (main/checkoutReturn.ts) — the URL itself never loads, so
    # it doesn't need to resolve. Keep the markers on any environment override.
    stripe_checkout_success_url: str = "http://localhost:5173/#/billing?checkout=success"
    stripe_checkout_cancel_url: str = "http://localhost:5173/#/billing?checkout=cancel"
    stripe_billing_portal_return_url: str = "http://localhost:5173/#/billing?portal=return"

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

    # --- Local bridge channel (SOLUSDEV-154 / BRG-02) ---
    # Every contract tunable is config, never hardcoded (bridge-protocol §6/§7).
    # Allowlist root: one allowlist.yaml per vendored fork (ADR-031); tests
    # point this at a fixture directory.
    bridge_allowlist_root: str = "integrations/mcp"
    bridge_control_frame_max_bytes: int = 16_384
    bridge_tool_call_max_bytes: int = 262_144
    bridge_tool_result_max_bytes: int = 1_048_576
    bridge_msg_rate_per_second: float = 20.0
    bridge_msg_burst: int = 100
    # MCP-05: credential_submit writes hit Secrets Manager — bucket them well
    # below the general frame rate so one companion can't burn write quota.
    bridge_credential_submit_rate_per_minute: float = 6.0
    bridge_credential_submit_burst: int = 3
    bridge_connect_rate_per_minute: int = 30
    bridge_max_inflight: int = 8
    bridge_max_team_sessions: int = 10
    bridge_idle_timeout_seconds: float = 60.0
    bridge_hello_timeout_seconds: float = 10.0
    # Membership re-check cadence per live session — satisfies the contract's
    # ≤30 s revocation bound by polling; a Redis push seam replaces it when the
    # API goes multi-instance.
    bridge_revocation_poll_seconds: float = 15.0
    # Phase 4 C1 (SOLUSDEV-100 security fix): `bridge.service.dispatch()` awaits
    # the wire directly, bypassing `ToolRegistry.invoke`'s own timeout bound —
    # this is the acquirer's OWN bound around that dispatch, so a stalled
    # companion session can never hang a sync indefinitely. Matches
    # `agent.tools.registry.DEFAULT_TIMEOUT_SECONDS`'s default by convention
    # (not imported, to keep config.py dependency-free of the tools package).
    bridge_tool_timeout_seconds: float = 30.0

    # --- Artifacts (SOLUSDEV-100 T4c / docs/api/artifacts.md) ---
    # Hard upload cap (§4.4) — over → 413, enforced against Content-Length
    # before reading and again while streaming.
    artifact_max_bytes: int = 8_388_608
    # Advisory threshold below which a tool result SHOULD inline instead of
    # minting an artifact — read by callers (bridge/tool code), not this surface.
    artifact_inline_max_bytes: int = 524_288
    # Local filesystem backend root (dev). S3 wins when both are set.
    artifact_local_root: str | None = None
    artifact_s3_bucket: str | None = None
    # Bridge-upload artifacts are a hand-off buffer, not a document store (§4.2):
    # the ARQ sweep soft-deletes rows past this TTL and deletes their bytes.
    artifact_ttl_seconds: int = 3600
    # §4.5 upload-route budgets. PROVISIONAL pending the F13 security pass —
    # the setting NAMES are the contract, not these values.
    artifact_uploads_per_minute_per_user: int = 30
    artifact_upload_bytes_per_hour_per_team: int = 67_108_864

    @property
    def cors_origin_list(self) -> list[str]:
        """Parsed, non-empty CORS origins."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
