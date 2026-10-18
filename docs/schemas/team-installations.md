# Team installations: GitHub App linked to a team (SOLUSDEV-216, ADR-039)

## `team_installations`

| Column | Type | Notes |
|---|---|---|
| `id` | UUIDv7 PK | |
| `team_id` | FK teams ON DELETE CASCADE | Must be a COLLABORATIVE team (enforced in the service layer) |
| `provider` | String(32) | `"github"`. Kept generic for a later GitLab-group ADR |
| `external_installation_id` | BigInteger | GitHub's installation id |
| `account_login` | String(255) | Display only, untrusted |
| `account_external_id` | BigInteger | GitHub numeric account id |
| `account_type` | String(32) | `Organization` or `User` |
| `account_avatar_url` | String(512) | Nullable |
| `repository_selection` | String(16) | `all` or `selected` |
| `status` | String(16) | `active`, `suspended` or `revoked` |
| `api_base_url` | String(255) | Default `https://api.github.com`. Per-row so GHES is not foreclosed |
| `web_base_url` | String(255) | Default `https://github.com` |
| `linked_by` | FK users ON DELETE SET NULL | Nullable. The installation outlives the user |
| `linked_at` | timestamptz | |
| `suspended_at` | timestamptz | Nullable |
| `revoked_at` | timestamptz | Nullable |
| `created_at`, `updated_at`, `deleted_at` | | ADR-027 timestamps and soft delete |

**Indexes and constraints:**
- Partial unique `(provider, external_installation_id) WHERE deleted_at IS NULL`: one live team per installation.
- Partial unique `(team_id, provider) WHERE deleted_at IS NULL`: one live installation per team per provider.
- No secret, token or key column. Tokens are minted on demand (ADR-039 §3).

## `sources.installation_id`

- Nullable FK to `team_installations.id`, ON DELETE SET NULL, with an index.
- When set, `secret_ref = "github-app/installation/{team_installation_id}"` and `connection_id` is NULL.
- A source carries either an installation or a connection, never both. This is enforced in the service layer and backed by a CHECK constraint.

## `invites` (extended)

| Column | Change |
|---|---|
| `email` | Becomes NULLABLE |
| `github_user_id` | New. BigInteger, nullable |
| `github_login` | New. String(255), nullable, display only |

- CHECK: exactly one of `email` and `github_user_id` is set.
- Partial index on `(team_id, github_user_id) WHERE status = 'pending'`.

## `github_webhook_deliveries`

| Column | Type | Notes |
|---|---|---|
| `delivery_id` | String(64) PK | The `X-GitHub-Delivery` header |
| `received_at` | timestamptz | Indexed |

- Holds no payload.
- Pruned after 7 days by the worker's existing hourly cron.
