# HANDOFF — Onshape FeatureScript MCP (user-side connection)

Written for an agent with **no prior context**. Everything needed is here or cited by
`file:line`. Branch: `featurescript-mcp` (off the `SOLUSDEV-167` work, which is complete,
green, and unpushed on its own branch). No ticket number was given — rename the branch if
one exists.

---

## 1. The ask

Onshape Labs ships a **hosted** FeatureScript MCP server. Let **our users** connect *their
own* Onshape account's server so SOL can use it — not a developer key in our AI client.

```
URL:       https://fs-mcp.labs.onshape.app/mcp
Transport: HTTP (MCP streamable-http)
Requires:  an Onshape account, signed in, subscribed via the Onshape App Store
```

Requirements, verbatim from the brief:

- **Subscription happens during the Onshape connection step.** One connect, FeatureScript
  comes with it. If programmatic subscription is possible: do it idempotently and
  **disclose** it. If not: detect the missing subscription, deep-link, and **detect
  completion** so the user returns to a working connection.
- A subscription failure (permission, plan tier, non-admin) gives a **clear, actionable
  message naming what is needed** — never opaque, never a silently degraded connection.
- **Disconnecting Solus must not unsubscribe them.**
- **Not a separate tile** — it is part of Onshape.
- **Per-user credentials.** Operate as the *customer*, never a developer key. `SecretStore`,
  never `os.environ`. *"A key that lives in `.env` and is never seeded into the Fernet store
  has already broken this project twice."*
- **Registered through MCP-01's `MCPTool` kind** into the W0-04 registry, inheriting routing,
  metering and the **never-raises invariant**.
- **Keyless-safe:** builds and tests with no credentials.
- **FeatureScript edits are destructive.** Every mutating op routes through the existing
  `confirmation_refusal` gate, and the approval card shows the **FeatureScript diff** — what
  changes, in which feature — not just a tool name. Server-side args: what is displayed is
  what executes. No bypass for "safe-looking" script operations.
- **Generalise the transport.** The next hosted server must be a config entry, not another
  integration.

### Standing rules
Never push, never open an MR, never self-approve. Don't edit `.env*` — report SecretStore
refs the human must set. Do not weaken the destructive-action gate or the never-raises
invariant. If acceptance can't be met with what exists, **say so plainly rather than faking
the gate**.

---

## 2. Approved decisions (do not re-litigate)

1. **Live spike: done.** Results in §4.
2. **Pin the DCR client to `OAuth2Read` + `OAuth2Write`.** If the server ever refuses to
   issue a token without `OAuth2Delete` or `OAuth2ReadPII`, **stop and escalate** — those are
   forbidden on the record (`docs/integrations/onshape-setup.md:53-54`;
   `connectors/onshape.py:239-243`: Delete *"would let a confused agent wipe a customer's
   document"*). Verified in §4: it does not refuse.
3. **Not a `MCP_SERVER_CATALOG` entry.** Hosted servers get their own registry
   (`agent/tools/remote_mcp.py`, already written). This keeps the CAD-02 loopback invariant,
   the frozen `MCPServerSpec`, `list_local_tools` and ADR-031 untouched — **no ADR amendment
   needed**. Tools are still real `MCPTool` instances from live discovery.

---

## 3. Phase 0 — verified code facts (all re-read, cite these)

**HTTP transport exists.** `agent/tools/mcp_tool.py:34` imports `streamablehttp_client`; the
branch is `:133-138`. Everything downstream of `yield session` is transport-agnostic and needs
no work: `_map_result`, the untrusted-descriptor gate (`:257`), the 30s discovery bound
(`:60`, applied `:323`), and the never-raises funnel (`:233-248` → `registry.py:105-108`).

**Five gaps between loopback and remote — these are the work:**

1. **No auth headers.** `:135` passes `spec.url` and nothing else. The only credential field
   is `env` (`:88`), read at `:126` *inside* the stdio branch; a child-process environment
   cannot cross a network anyway.
2. **No per-user credential axis.** `mcp_tool.py:15-17`: *"SecretStore keys are a flat v1
   namespace — per-TENANT credential scoping must bind where the SOL-loop wiring constructs
   registries per request."* `MCPTool.__init__` (`:202-213`) takes no `user_id`/`team_id`.
3. **⚠ THE TRAP: `requires_confirmation=True` on a `url` spec SKIPS EVERY TOOL.**
   `_stdio_server_allowlist` returns `None` when `spec.command is None` (`:286-287`), so
   discovery falls through to `:357-362` — `_skip(..., "declares a destructive default with
   no consent text")`. An `MCPServerSpec` HTTP server today is **ungated or empty**, no third
   option. This is SEC-C1 and it is correct: the approval sentence must be Solus-authored.
   `remote_mcp.py` solves it by supplying per-tool consent text.
4. **CAD-02.** `tests/test_mcp_license.py:74-87` asserts `is_loopback_url(spec.url)` for
   **every** `MCP_SERVER_CATALOG` url spec — *"an SSRF primitive inside the customer's
   network"*. A cloud URL there **fails CI by design**. `companion/config.py:335` enforces the
   same. → hence decision 3.
5. **Auth failure misclassifies.** A 401 funnels to `TOOL_ERROR`/`retryable=True`/"is
   unavailable", so SOL would retry an expired grant instead of telling the user to reconnect.
   `UNAUTHORIZED` (`:151-159`) fires only on the pre-connect secret presence check.

**Other facts that will bite:**

- **No PKCE anywhere.** `grep -rn "code_verifier|code_challenge|pkce" packages/` → zero hits.
  `OAuthState` (`models.py:957-976`) carries `state, provider, source_id, user_id,
  redirect_uri, created_at, expires_at` — **nowhere to persist a `code_verifier`** across
  authorize→callback. fs-mcp's `/authorize` returns `400 code_challenge: Field required`.
- **`discover_mcp_tools` has no production caller.** `build_sol_registry`
  (`agent/runtime.py:73-150`) registers get_entity, builtin, onshape, integration and bridge
  tools — never an `MCPTool`. `docs/contracts/agent-tool.md:57` marks MCPTool *"Future"*,
  `:303` *"Documented, not built"*. **This path has never run in production.**
- **The approval card is inadequate today.** `mcp_tool.py:370` sets
  `description_trusted=False` and never sets `consent_summary`, so `confirmations.py:101-108`
  degrades the summary to the **bare tool name** and the diff to argument rows mangled by
  `_single_line` (`confirmations.py:128`, 500-char cap, non-printables stripped). Multi-line
  FeatureScript would render as one truncated run-on string.
- **The gate mechanics that DO work:** a tool object may expose an optional `preview(args)`
  returning `[{label, before, after}]`; `confirmations.py:249` builds it at park time and
  `:346` rebuilds it at decide time, refusing on divergence (*"THE R1 GUARANTEE"*). That is
  the hook the FeatureScript diff must use.
- **`mcp_servers.py:10-16` pre-committed the shape** (SOLUS-ONS-A1): Onshape was removed from
  the catalog because an API key pair *"authenticates the DEVELOPER, not the customer"*, and
  *"If Onshape's announced hosted server ever ships, it slots in behind those same
  operations."*
- Existing Onshape OAuth: scopes `("OAuth2Read",)` default with a read/write access-mode
  choice (`onshape.py:244-263`, persisted at `routers/integrations.py:192`). Tokens live 60
  min; the refresh token **rotates on every use**; stored at `source/{source_id}/onshape` and
  `…/refresh` (`connectors/runtime.py refresh_secret_ref`).
- Existing overlap: 12 Onshape operations (`onshape_ops.py:774-782`) + STEP-export sync. Zero
  `/featurescript` calls in `packages/`. The REST write path *structurally refuses* payloads
  it cannot derive from a live example (`onshape_ops.py:588-598`). FeatureScript authoring is
  genuinely new capability.

---

## 4. The live spike — hard data (already run, approved, do not repeat unnecessarily)

Run 2026-08-31 against the real server with a real subscribed account.

**Discovery documents** (unauthenticated GET, both 200):
```
/.well-known/oauth-protected-resource/mcp
  resource: https://fs-mcp.labs.onshape.app/mcp
  authorization_servers: ["https://fs-mcp.labs.onshape.app/"]   ← its OWN AS
  scopes_supported: [OAuth2Read, OAuth2Write, OAuth2Delete, OAuth2ReadPII]
  bearer_methods_supported: ["header"]

/.well-known/oauth-authorization-server
  authorization_endpoint /authorize · token_endpoint /token · registration_endpoint /register
  grant_types: [authorization_code, refresh_token]
  code_challenge_methods_supported: ["S256"]        ← PKCE REQUIRED
  token_endpoint_auth_methods: [client_secret_post, client_secret_basic]
  client_id_metadata_document_supported: true
```

`GET /mcp` unauthenticated → **401** with
`www-authenticate: Bearer error="invalid_token" … resource_metadata="…"`.

**DCR works for a third party.** `POST /register` → **201**, echoing
`"scope": "OAuth2Read OAuth2Write"` as requested.

**fs-mcp is an OAuth BROKER in front of Onshape SSO.** `GET /authorize` → **302** to
`https://oauth.onshape.com/oauth/authorize?client_id=H4HV5U7E6KS3Z5BRNOZMU2FHHPYMQUAS5JUL3UQ=
&scope=OAuth2Read+OAuth2Write&redirect_uri=https://fs-mcp.labs.onshape.app/auth-redirect&…`
— Onshape Labs' own app, **our requested scopes forwarded verbatim**. Delete/PII never
requested anywhere in the chain.

**Token exchange → 200:** `scope: "OAuth2Read OAuth2Write"` (granted == requested),
`expires_in: 3599`, refresh token present.

**`tools/list` → 14 tools**, server `featurescript 3.3.1`, protocol `2025-11-25`:

| tool | effect | schema |
|---|---|---|
| `whoami`, `get_api_usage`, `get_featurescript`, `list_feature_studios`, `read_featurescript_notes`, `search_featurescript_documentation`, `test_featurescript` | read | 67–474 B |
| `put_featurescript` | **overwrites an ENTIRE Feature Studio** | 426 B |
| `create_geometry` | branches a workspace, executes a feature | 1587 B |
| `create_feature_studio`, `test_feature`, `edit_featurescript_notes` | mutate | 291–434 B |
| `set_api_allocation` | changes which account is billed | 446 B |
| `logout` | ends the session | 178 B |

**The `$ref` / 64 KB risk is CLEARED:** zero `$ref` anywhere, largest schema 1,587 B against
`SCHEMA_BYTES_CAP = 64_000` (`agent/tools/untrusted.py:34`). `_descriptor_safe` skips none.

**Quota — a correction to an earlier inference.** `get_api_usage` says: *"Every tool call on
this server consumes Onshape API calls from an allocation included in the user's (or their
company's) subscription."* Live figures on the account:
```
used: 0 · limit: 2500 · remaining: 2500 · overageEnabled: false
cycle: 2026-07-19 → 2027-07-19 · consumingFrom: "self"
```
The **same** Onshape account (`62d6c785a83ae420933a2a95`, confirmed against
`sources.account_external_id`) had burned ~2,000 calls of the *private-app* allowance inside
this cycle, yet this counter reads 0. So it is a **separate 2,500/year allocation**, not the
one `connectors/quota.py` defends. Strong, but **inferred from one data point** — do not
state it as fact in user-facing copy, and consider metering it.

**SOLUSDEV-261 correction (2026-09-13):** the observation above is retained as
historical evidence, but the inferred separate annual entitlement is withdrawn.
The approved ADR-019/035 amendment separates the documented public-App-Store REST
exemption from independently observed MCP service restrictions. Solus no longer
assumes or enforces a hosted 2500/year allowance from this sample. See
[the current quota audit](ONSHAPE_QUOTA_AUDIT_SOLUSDEV-261.md).

**Programmatic App Store subscription: VERIFIED IMPOSSIBLE.** The public OpenAPI
(`1.220.87559`, 248 paths) has four purchase operations — `GET /accounts/purchases`,
`GET /accounts/plans/{planId}/purchases`, `POST …/consume`, `DELETE …` — **none creates one**.
The Billing guide: the only path is redirecting the browser to
`https://cad.onshape.com/billing/purchase?…`, where Onshape renders a confirmation and asks
for the password; free items still require it. Worse, that URL is scoped to *the calling app's
own* products (*"The clientId is your application's OAuth Client ID"*) and Solus is not the
publisher. **→ the deep-link + completion-detection fallback is mandatory, not optional.**

**Re-consent cost for existing users: ZERO.** fs-mcp is its own AS with its own token, so
connecting it never touches the existing Onshape grant.

**Fallback specifics:** deep link
`https://cad.onshape.com/appstore/apps/Onshape%20Labs/6a29aea7c03f8bf659841734`. **Do not
trust the return signal** — Onshape: *"do NOT assume that a fetch of the redirectUri with a
success=true query parameter actually indicates a purchase has occurred."* No webhook exists
(all 26 documented events are non-purchase). `GET /accounts/purchases` is useless — it returns
purchases *"for plans owned by the current application"* and we are a different client.
**Detect completion by capability probe**: attempt the handshake / a read-only tool and treat
failure as not-yet.

**Still UNVERIFIED:** whether Onshape Labs access is admin-gated (`onshape_labs.htm` says
*"Only Company Administrators can permit users or teams to access Onshape Labs"*, but the FS
MCP blog lists three prerequisites with no Labs step — two Onshape pages contradict each
other); subscription price/unit; purchase idempotency; and whether a cancel inside
`streamable_http_client`'s internal `anyio` task group surfaces as a `BaseExceptionGroup` that
`except Exception` at `mcp_tool.py:233` would **not** catch — that last one is the only thing
that could silently break the never-raises invariant, and it needs a test.

---

## 5. What is already built

`packages/api/src/solus_api/agent/tools/remote_mcp.py` — **complete, mypy-clean, uncommitted.**
Data-only registry of hosted servers:
- `RemoteAuth` protocol (`headers(user_id)`, resolved per invocation because tokens live ~1h).
- `RemoteAuthError(code, message, retryable)` — carries a human-actionable message.
- `RemoteMCPSpec` with Solus-authored `mutating_tools` / `read_only_tools` /
  `consent_prefix` / `connect_notice`, plus **`gate_unknown_tools=True`** so a tool the server
  adds later is gated as mutating by default (fail closed).
- `FS_MCP` populated from the live `tools/list` above, and `HOSTED_SERVERS` — **the next
  hosted server is one entry here**.

---

## 6. What remains, in order

1. **Auth-capable transport.** Thread optional headers into `_open_session` /
   `streamablehttp_client(spec.url, headers=…)` (the SDK already accepts `headers=` and
   `auth=` — `mcp/client/streamable_http.py:686-693`) and into `MCPTool`. Note
   `streamablehttp_client` is `@deprecated`; the replacement takes only `http_client`. Pick a
   shape deliberately.
2. **The OAuth client.** **Do not hand-roll one** — the pinned SDK ships
   `OAuthClientProvider(httpx.Auth)` at `mcp/client/auth/oauth2.py:217` implementing DCR +
   PKCE + refresh. The work is constructing it: a `TokenStorage` impl (protocol at
   `oauth2.py:72-88`, four methods) backed by `SecretStore`, a redirect handler, and a hosted
   callback route. Per-user token refs; one shared Solus DCR client is correct (the *client*
   is Solus, the *tokens* are the customer's — same shape as the existing Onshape OAuth).
   PKCE `code_verifier` needs somewhere to live across the redirect (see §3).
3. **Subscription detect → deep-link → capability probe**, wired into the Onshape connect
   step, with the disclosure copy from `FS_MCP.connect_notice`.
4. **Registration into the W0-04 registry** from the Onshape path (not the catalog), with
   per-tool `requires_confirmation` and `consent_summary` from `RemoteMCPSpec`.
5. **The FeatureScript diff.** Give the tool object a `preview(args)` that, for
   `put_featurescript`, fetches current source via `get_featurescript` and returns
   `{label, before, after}` — the real diff, in the feature being changed. Beware
   `_single_line`'s 500-char cap mangling multi-line script; that may need a widening in
   `confirmations.py`, done carefully.
6. **Tests + verification** against the brief's 8 acceptance items. Keyless-safe throughout.

---

## 7. Environment / housekeeping

- Redis: `make db-up` (compose file is `docker-compose.dev.yml`; plain `docker compose` fails).
- Test DB: never run two pytest processes at once — they deadlock on the shared test DB.
  Kill strays and `pg_terminate_backend` leftovers if a run hangs.
- Full API suite ≈ 11 min, 2,675 passing on the SOLUSDEV-167 branch.
- **Spike credentials** live only in this session's scratchpad (`dcr.json`, `token.json`,
  `pkce.json`) — never in the repo, never in `.env`. The access token has expired by now; the
  refresh token and DCR client secret may still be live. A fresh agent should re-run its own
  flow rather than reuse them, and the human may want the scratchpad shredded.
- A DCR client `01a5e3e8-fac9-4f01-a8e8-9d619cfa9ab6` ("Solus (SOLUSDEV spike)") now exists on
  Onshape's side from the approved spike registration.
