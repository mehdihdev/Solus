# Account-owned hosted add-ons — SOLUSDEV-261

Implements the 2026-09-12 approved ADR-035 amendment. Extends API.md §2.1/2.4.
All routes require CurrentUser; account lookup is owner-only and connected-state
checked before reading any state or secrets. Mutations also require RequireVerified.
Unknown/wrong-provider servers and foreign/revoked accounts fail closed. No new
SourceType, schema migration, vendor endpoint discovery or token scope is introduced.

Base: `/api/v1/users/me/connections/{connection_id}/hosted/{server}`.

| Method/suffix | Request | Envelope data |
| --- | --- | --- |
| GET (base) | none | Existing hosted status: server, state, tool_count, checked_at, notice, subscribe_url, detail |
| POST `/oauth/start` | none | authorize_url, state, redirect_uri, notice; HTTP 201 |
| POST `/oauth/exchange` | strict `{state, code}` with existing length bounds | hosted status after capability probe |
| POST `/probe` | none | hosted status after capability probe |

Use existing pinned RemoteMCPSpec, DCR client, PKCE, TTL, scope minimization,
authenticated exchange, schema sanitation and allowlist policy. OAuthState binds
user + connection + server. Atomically consume the state before exchanging; a
concurrent replay cannot exchange twice. Revalidate account status before storing
a returned grant, including a revoke racing the remote request. Tokens never appear
in responses/logs; only SecretStore holds them. Config stores capability/inventory.

Account-bound Source routes read the account's authoritative hosted state. Source
route mutations resolve the connection and require its owner; teammates cannot
change another member's account grant. Legacy source-owned grants retain existing
behavior. Source deletion preserves account grants; account/user revoke/deletion
removes the hosted secret family and invalidates inventory for all attached Sources.
Tool invocation resolves the same connected Source and account as inventory and
checks the live grant on every call. Existing project/team and confirmation gates
remain mandatory. Account state must never be copied onto writable source config
as a new authorization authority.

A permanent invocation-time grant failure (`reconnect_required`, rejected scope
escalation, or missing grant) clears the same owner's cached hosted inventory and
sets status to `not_enabled` under the account lock. The status includes a fixed
reconnection instruction, never raw credential or vendor error text. Transient
transport failures do not revoke a working grant or clear its inventory.

Probe is an explicit connect/recovery action; the UI may perform bounded automatic
checks only while the user is completing this flow, stopping on ready, cancellation,
sign-out or timeout. The read-only status route performs no vendor request.
