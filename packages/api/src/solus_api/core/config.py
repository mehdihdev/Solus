"""Application settings. All secrets come from the environment (CLAUDE.md §7)."""

import logging
import uuid
from functools import cached_property
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _split_csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


#: `<root>/packages/api/src/solus_api/core/config.py` -> `<root>`. The install is
#: editable in both the dev venv and the image (`uv sync --package solus-api`
#: leaves a `.pth`), so this anchor holds as `/app` in the container too.
#:
#: PUBLIC because it is the one authoritative repo-root anchor: anything that
#: needs the root `.env` (the single env file) must resolve it this way rather
#: than by a CWD-relative path, which silently reads nothing from a subdirectory.
REPO_ROOT = Path(__file__).resolve().parents[5]


class Settings(BaseSettings):
    """Runtime configuration, sourced from `SOLUS_*` environment variables."""

    # ANCHORED, not CWD-relative. A bare `.env` is resolved against the process's
    # working directory, and every launcher cd's into a subdirectory first
    # (`pnpm dev:api`, `make dev-api`, `scripts/dev-all.sh`) — so the API read
    # `packages/api/.env` and the real root file was invisible to it. That is one
    # bug that surfaced as many: no secret store, no Redis, no Stripe key, no
    # OAuth credentials — each degrading quietly rather than failing. The repo
    # root is the ONE env file; `REPO_ROOT` is the same `__file__` anchor
    # `bridge_allowlist_root` already relies on, so this holds in the container
    # (`/app`) too. Env vars still win over the file, which is how dev-all.sh
    # injects the Stripe CLI's signing secret.
    model_config = SettingsConfigDict(
        env_prefix="SOLUS_", env_file=REPO_ROOT / ".env", extra="ignore"
    )

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
    #: A7-01: who may frame `/panel`. Set on that response only — `frame-ancestors`
    #: is a no-op on JSON, and a global policy would break the CDN-loaded Swagger UI.
    panel_frame_ancestors: str = "https://*.onshape.com https://onshape.com"

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
    # It is a RUNAWAY-CLIENT guard, not an abuse control: keyed per bearer
    # token per process, so a determined caller multiplies it by tokens x
    # instances. ADR-019's Redis budgets are the abuse control.
    #
    # SOLUSDEV-234: reads and writes are separate budgets. One desktop session
    # is a polling-heavy client — the Live Bench widget alone is 2 req/s, the
    # bridge/sources/extensions/widget pollers add ~1/s, and a workspace load
    # pages the whole graph in 500-row bursts. The former single 120/min was
    # below that steady state, so a healthy client 429'd itself after ~30s.
    # Reads get 1200/min (20 req/s, ~10x normal load); writes KEEP 120/min,
    # because that budget is the interim burst bound on model-calling POSTs
    # (orchestration/gates.py: the frequency cap fails open without Redis).
    rate_limit_per_minute: int = 1200
    write_rate_limit_per_minute: int = 120
    # A7-01 `/panel/pair/start`: unauthenticated, one shared bucket behind the
    # ALB, and a DB insert per call — its own knob, so the read budget above
    # can never drag it up by accident.
    panel_pair_rate_limit_per_minute: int = 120
    # MO-04 classify preview: fired on typing pauses, so it gets its own
    # generous separate bucket (never counts against the global budget above).
    classify_rate_limit_per_minute: int = 600
    # SOLUSDEV-216 GitHub App webhook: unauthenticated (the HMAC is the credential) and every
    # delivery from GitHub shares one source IP behind the ALB, so it gets its OWN path bucket
    # sized for GitHub volume. Failed-signature attempts are throttled separately per source IP
    # inside the route; valid deliveries are never counted against that.
    github_app_webhook_rate_limit_per_minute: int = 1200
    github_app_webhook_bad_signature_per_minute: int = 60

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
    # ADR-024 explicit development exception. UUIDs are Solus User.id values;
    # no account is exempt by default and only app_env == "dev" enables it.
    development_unlimited_credit_user_ids: str = ""
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

    # GitHub App for team organizations (SOLUSDEV-216, ADR-039); see
    # docs/integrations/github-setup.md. Separate from the OAuth App above. Every field is
    # optional: until all are present the org feature reports unconfigured and stays hidden.
    github_app_id: str | None = None
    github_app_slug: str | None = None
    github_app_client_id: str | None = None
    github_app_client_secret: SecretStr | None = None
    # PEM, inline (literal "\n" escapes accepted) or as a file path (read once).
    github_app_private_key: SecretStr | None = None
    github_app_private_key_path: str | None = None
    github_app_webhook_secret: SecretStr | None = None

    # GitLab OAuth application (SOLUSDEV-104). base_url supports self-hosted
    # instances; the OAuth app is registered on that instance.
    gitlab_client_id: str | None = None
    gitlab_client_secret: str | None = None
    gitlab_base_url: str = "https://gitlab.com"

    # Onshape "Integrated Cloud App" OAuth application (SOLUSDEV-96 / CAD-01),
    # registered in Onshape Developer Settings. OAuth ONLY: an Onshape API key
    # pair authenticates the DEVELOPER, not the customer, so it can never reach
    # a customer's documents.
    onshape_client_id: str | None = None
    onshape_client_secret: str | None = None
    #: SOLUSDEV-167 (ADR-019 amended). Onshape's real cap is 2,500/user/YEAR
    #: on Free/Standard; the self-imposed default sits below it so we degrade
    #: before the provider does — our count is a floor on our own spend, never
    #: a remaining balance, so leaving headroom is the honest posture.
    onshape_annual_call_allowance: int = 2500
    #: ADR-038 §4. Whose annual pool Onshape charges. A PRIVATE OAuth app's REST
    #: successes are billed to the app OWNER (one pool for every Solus user);
    #: `user` meters per connected account and exists only to verify billing.
    onshape_quota_pool: Literal["owner", "user"] = "owner"
    #: ADR-038 §4. `app_store` once the OAuth app is publicly listed: annual-limit
    #: metering stops degrading work (Onshape exempts public apps); per-endpoint
    #: rate limits and the 402 latch stay enforced.
    onshape_app_distribution: Literal["private", "app_store"] = "private"
    #: ADR-038 §2. Seconds after the LAST change hint before an Onshape export runs,
    #: so a burst of edits costs one export instead of several aborted ones.
    onshape_quiet_period_seconds: int = Field(default=90, ge=0, le=600)
    #: ADR-038 §2. Sent as `X-Session-ID` on Solus's Onshape writes and registered as
    #: the webhook `externalSessionId`, so Onshape can tell Solus's own edits apart.
    onshape_session_id: str = "solus-api"
    #: Fraction of the allowance above which DEFERRABLE work (the sweep, agent
    #: turns) pauses. A user's explicit action still reaches the provider.
    integration_degrade_ratio: float = 0.7
    #: SOLUSDEV-241 (I1) — the integration cache windows. A human's sync trusts
    #: a recorded change signal for `signal_ttl` (the sweep cadence, so the
    #: sweep is what moves it); the sweep itself reuses one younger than
    #: `signal_sweep_reuse` so two projects tracking one document cost one
    #: probe per sweep; a webhook doorbell never trusts one. Listings move only
    #: on an explicit refresh or a doorbell — the long TTL is storage hygiene,
    #: not a poll. Payloads are keyed by change token so their TTL is hygiene too.
    integration_signal_ttl_seconds: int = 3600
    integration_signal_sweep_reuse_seconds: int = 300
    integration_listing_ttl_seconds: int = 7 * 24 * 3600
    integration_payload_ttl_seconds: int = 30 * 24 * 3600
    integration_cache_max_payload_bytes: int = 8 * 1024 * 1024
    #: An explicit listing refresh inside this window is served from the cache:
    #: one provider walk per window per ACCOUNT, however many members share it.
    integration_listing_refresh_cooldown_seconds: int = 60

    # Where the OAuth callback sends the user back to (the desktop app deep
    # link or a local page). Defaults to the renderer dev origin. Renamed from
    # `github_oauth_redirect_app` in CAD-01: it was always provider-agnostic
    # (GitLab already used it) and Onshape made the GitHub name actively
    # misleading. Env var: SOLUS_OAUTH_REDIRECT_APP.
    oauth_redirect_app: str = "http://localhost:5173/#/onboarding"
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
    #
    # ANCHORED, not relative. A relative default globs against the CWD, and the
    # repo's own `make dev-api` runs from `packages/api/` — so the default only
    # worked when you happened to launch from the root. It failed silently: an
    # empty allowlist drops every companion-advertised tool as "not allowlisted"
    # rather than erroring, so the bridge simply appears to have nothing on it.
    bridge_allowlist_root: str = str(REPO_ROOT / "integrations" / "mcp")
    # SOLUSDEV-72: the only directory MCAP-replay sessions may read recordings
    # from. Unset (the default) refuses MCAP sessions outright — an unbounded
    # server-side file read keyed off a request body is not a feature (§7).
    bench_data_root: str | None = None
    bridge_control_frame_max_bytes: int = 16_384
    #: `hello` alone is sized apart from the other control frames. It carries
    #: the FULL tool inventory — every advertised tool's JSON schema, for every
    #: running fork — so it grows with the number of vendored integrations, not
    #: with anything a caller sends. Two forks plus the built-in `machine`
    #: server measured 22 KB live (SOLUSDEV-252), and under the 16 KB control
    #: cap that read as `expected_hello` → close 4400 "update required": the
    #: bridge refused every real companion and blamed the protocol version.
    bridge_hello_frame_max_bytes: int = 262_144
    bridge_tool_call_max_bytes: int = 262_144
    bridge_tool_result_max_bytes: int = 1_048_576
    bridge_msg_rate_per_second: float = 20.0
    bridge_msg_burst: int = 100
    # MCP-05: credential_submit writes hit Secrets Manager — bucket them well
    # below the general frame rate so one companion can't burn write quota.
    bridge_credential_submit_rate_per_minute: float = 6.0
    bridge_credential_submit_burst: int = 3
    #: SOLUSDEV-167: unsolicited local-change frames. A design change is a
    #: human saving a file, so a handful a minute is generous; past that the
    #: sensor is malfunctioning and the answer is to stop scheduling work.
    bridge_change_rate_per_minute: int = 12
    bridge_change_burst: int = 4
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
    # --- Durable CAD derivative store (ADR-038 §1) ---
    # Write-once, revision-keyed Onshape derivatives. Its OWN bucket (or local root),
    # never the artifact bucket: artifacts expire after an hour by design.
    cad_store_local_root: str | None = None
    cad_store_s3_bucket: str | None = None
    cad_store_max_object_bytes: int = Field(default=256 * 1024 * 1024, ge=1024 * 1024, le=1024**3)
    # Bridge-upload artifacts are a hand-off buffer, not a document store (§4.2):
    # the ARQ sweep soft-deletes rows past this TTL and deletes their bytes.
    artifact_ttl_seconds: int = 3600
    # §4.5 upload-route budgets. PROVISIONAL pending the F13 security pass —
    # the setting NAMES are the contract, not these values.
    artifact_uploads_per_minute_per_user: int = 30
    # --- Client-originated data events (API.md §2.13; ADR-011; SOLUSDEV-235) ---
    # Batches per user per minute on POST /events; the desktop host batches bridge
    # refusals every 2 s, so this is generous for honest clients and tight for abuse.
    client_event_batches_per_minute_per_user: int = 30
    artifact_upload_bytes_per_hour_per_team: int = 67_108_864

    # --- Extensions (SOLUSDEV-235 / ADR-035, docs/api/extensions.md §3, §12) ---
    # Solus staff — the ONLY identity allowed to set `extensions.verified`.
    # Comma-separated user UUIDs from env / Secrets Manager (no schema column;
    # docs/schemas/extensions.md §8.4). Evaluated by `deps.require_staff`; never
    # returned by any route. Malformed entries fail at startup, not at first use.
    staff_user_ids: str = ""
    # Explicit existing staff account used to provision shipped Store releases.
    first_party_publisher_id: uuid.UUID | None = None
    # §12 write-group budgets. PROVISIONAL pending the Phase 4 security pass —
    # the setting NAMES are the contract, not these values.
    extension_publishes_per_hour_per_user: int = 10
    extension_bundle_downloads_per_minute_per_user: int = 30
    extension_install_writes_per_minute_per_user: int = 60
    extension_storage_writes_per_minute_per_install: int = 120
    extension_policy_writes_per_minute_per_team: int = 30
    # Phase 4 L3: per-user read windows on the two routes that serve stored
    # bytes/values on demand (store assets; extension storage values).
    extension_asset_downloads_per_minute_per_user: int = 240
    extension_storage_reads_per_minute_per_user: int = 240

    @field_validator("github_app_private_key", mode="before")
    @classmethod
    def _normalise_private_key_newlines(cls, raw: object) -> object:
        """Env files carry the PEM on one line with literal `\\n` escapes."""
        if isinstance(raw, str):
            return raw.replace("\\n", "\n")
        if isinstance(raw, SecretStr):
            return SecretStr(raw.get_secret_value().replace("\\n", "\n"))
        return raw

    @cached_property
    def github_app_private_key_pem(self) -> str | None:
        """The App's PEM: the inline key, else the file at the configured path (read once)."""
        if self.github_app_private_key is not None:
            inline = self.github_app_private_key.get_secret_value()
            if inline.strip():
                return inline
        if not self.github_app_private_key_path:
            return None
        try:
            return Path(self.github_app_private_key_path).read_text() or None
        except OSError as exc:
            logging.getLogger("solus.config").error(
                "GitHub App private key file unreadable: %s", type(exc).__name__
            )
            return None

    @property
    def github_app_configured(self) -> bool:
        """True only when every GitHub App credential is present (key inline or by path)."""
        secrets = (self.github_app_client_secret, self.github_app_webhook_secret)
        return bool(
            self.github_app_id
            and self.github_app_slug
            and self.github_app_client_id
            and all(s is not None and s.get_secret_value() for s in secrets)
            and self.github_app_private_key_pem
        )

    @field_validator("staff_user_ids")
    @classmethod
    def _staff_user_ids_are_uuids(cls, raw: str) -> str:
        for item in _split_csv(raw):
            uuid.UUID(item)  # raises ValueError → pydantic ValidationError
        return raw

    @property
    def staff_user_id_set(self) -> set[uuid.UUID]:
        """Parsed staff ids (validated at construction)."""
        return {uuid.UUID(item) for item in _split_csv(self.staff_user_ids)}

    @field_validator("development_unlimited_credit_user_ids")
    @classmethod
    def _development_credit_ids_are_uuids(cls, raw: str) -> str:
        for item in _split_csv(raw):
            uuid.UUID(item)
        return raw

    @property
    def development_unlimited_credit_user_id_set(self) -> set[uuid.UUID]:
        """Validated explicit account identities; never emails or implicit staff."""
        return {uuid.UUID(item) for item in _split_csv(self.development_unlimited_credit_user_ids)}

    @property
    def cors_origin_list(self) -> list[str]:
        """Parsed, non-empty CORS origins."""
        return _split_csv(self.cors_origins)
