# COWORK QA — SOLX-04 (SOLUSDEV-203): SOL connects a missing integration

Setup: Solus API from `packages/api` with migrated Postgres+pgvector, an authenticated member with an active plan and credits, and a real `ANTHROPIC_API_KEY` for conversational flows (Flows 2–4). Flow 1 needs no key.

**What shipped:** connecting a tool is a SOL action. SOL can list supported integrations with their connection state, connect committed-export providers (KiCad) after your explicit approval, point you at the in-app flow for OAuth providers (GitHub/GitLab), and verify a connection is live.

## Flow 1 — deterministic verification (no model key)

1. From `packages/api`: `env -u VIRTUAL_ENV uv run --no-sync pytest tests/test_connect_integration.py -q` → **10 passed** (includes the park→approve→execute e2e). ☐
2. `GET /api/v1/projects/{id}/sol/tools` → the list includes `solus.list_integrations`, `solus.connect_integration`, `solus.verify_integration`; only `connect` has `requires_confirmation: true`, and its params contain **no token/credential field**. ☐

## Flow 2 — discovery offers the connect inline

1. Ask SOL (do or guide mode): "what integrations can I connect?" ☐
2. **Expected:** the reply lists supported providers with connected/disconnected state; disconnected ones mention connecting via SOL. ☐

## Flow 3 — connect with approval (the destructive round-trip)

1. In **do** mode: "connect KiCad to this project". ☐
2. **Expected:** the stream shows a confirmation card (tool `solus.connect_integration`, the Solus-authored consent sentence, provider argument) — and NO source exists yet (check `GET /sources` or the Integrations screen). ☐
3. Approve it → the decide response is `ok: true`; the Integrations screen / `GET /sources` now shows KiCad **connected**. ☐
4. Ask "verify kicad is connected" → SOL confirms it is live. ☐
5. Repeat the connect request → SOL reports it is already connected; no duplicate source. ☐

## Flow 4 — OAuth providers are a next step, never automated

1. In do mode: "connect GitHub". ☐
2. **Expected:** no confirmation card creates a source; the reply directs you to the in-app Integrations flow, and asks you to come back for verification. SOL never asks for a token or password. ☐

## Edge cases

1. "Connect SolidWorks" → a clear unsupported-provider reply naming the supported roster. ☐
2. In **guide** mode: "connect KiCad" → SOL explains how but nothing parks and nothing connects (no confirmation card, no source). ☐
3. A planless/over-limit account: the connect attempt returns the plan next-step, not a crash. ☐
4. A second team member approving YOUR pending connect card → refused; nothing connects. ☐

## Cross-feature interactions

- After connecting KiCad via SOL, the normal sources UI shows it identically to a settings-connected source (same `source.connected` activity entry, `via: sol` in the payload). ☐
- Billing: each conversational turn meters as usual; the connect execution itself is not a model call and consumes no credits. ☐
