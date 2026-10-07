# Cowork QA — Onshape mirror (ADR-038, SOLUSDEV-312)

Verifies that Solus keeps Onshape data fresh while spending far fewer Onshape
API calls, and that teammates still see CAD changes. Mark each row PASS / FAIL
and write down what you saw. Several rows (marked **LIVE**) confirm Onshape
behaviour that could only be assumed in tests — those results matter most.

---

## 0. Setup

| #   | Requirement                                                                                                                                                                           | How to check                                      | ☐   |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- | --- |
| 0.1 | API + worker + Redis running against a **public HTTPS** API URL (staging, or a tunnel such as ngrok/cloudflared pointing at local `:8000`) with `SOLUS_PUBLIC_API_BASE_URL` set to it | `GET <url>/readyz` → `redis`/`queue` `configured` | ☐   |
| 0.2 | CAD store configured (`SOLUS_CAD_STORE_S3_BUCKET` or `SOLUS_CAD_STORE_LOCAL_ROOT`)                                                                                                    | API log at startup: "durable CAD store enabled"   | ☐   |
| 0.3 | The Solus Onshape OAuth app registered (see `docs/integrations/onshape-setup.md`); you can see its owner's **API usage** page in Onshape (Company/My Account settings → Developer)    | Page opens                                        | ☐   |
| 0.4 | Two Solus accounts **A** and **B** in one team, both with Onshape connected (read+write for A)                                                                                        | Home → Connections shows Onshape for both         | ☐   |
| 0.5 | One Onshape document **"QA Mirror"** with 3 Part Studios, 2 Assemblies, 1 Drawing, tracked as a source in project **"Mirror"**                                                        | Workspace shows the parts after the first sync    | ☐   |
| 0.6 | Note the Onshape API usage figure now: **\_\_**                                                                                                                                       | —                                                 | ☐   |

## 1. Webhooks (LIVE)

| #   | Step                                                                 | Expected                                                                               | ☐   |
| --- | -------------------------------------------------------------------- | -------------------------------------------------------------------------------------- | --- |
| 1.1 | After the first sync, check the source / API logs                    | A webhook was registered for "QA Mirror" (log line or source health "webhook healthy") | ☐   |
| 1.2 | In Onshape, change a dimension in Part Studio 1 and **stop editing** | Within ~2 minutes B's Workspace graph updates (no Sync now pressed)                    | ☐   |
| 1.3 | Make 10 quick edits over ~2 minutes, then stop                       | ONE sync runs ~90 s after the last edit (one "synced" change, not ten)                 | ☐   |
| 1.4 | Keep editing continuously for 12 minutes                             | A sync still happens within ~10 minutes of the first edit (no indefinite wait)         | ☐   |
| 1.5 | Press **Sync now** during an editing burst                           | It syncs immediately (not delayed by 90 s)                                             | ☐   |
| 1.6 | With API logs at debug, make one edit                                | Log shows a `translation.complete` delivery and few or no translation status polls     | ☐   |

## 2. Export granularity (LIVE — the cross-tab verification ADR-038 asks for)

| #   | Step                                                                                                                                           | Expected                                                                                                                                                                                                            | ☐   |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --- |
| 2.1 | Edit only the **Drawing**; wait for sync                                                                                                       | No STEP exports run (logs); graph unchanged; usage rises by only a few calls                                                                                                                                        | ☐   |
| 2.2 | Edit only **Assembly 1**                                                                                                                       | Only the 2 assemblies re-export; Part Studios do not                                                                                                                                                                | ☐   |
| 2.3 | Edit **Part Studio 2**                                                                                                                         | Part Studios and assemblies re-export (expected and correct)                                                                                                                                                        | ☐   |
| 2.4 | In Onshape, open the document's element list via API Explorer `GET /documents/d/{did}/w/{wid}/elements` before and after editing Part Studio 2 | Only Part Studio 2's `microversionId` changes. **Record the result** — if every element's id changes, granularity silently degrades to document level; if Part Studio 2's id does NOT change, report a CRITICAL bug | ☐   |
| 2.5 | Change a **Variable Studio** variable used by Part Studio 1                                                                                    | Part Studio 1's geometry in Solus updates after sync                                                                                                                                                                | ☐   |
| 2.6 | Change a part's **part number** in Onshape                                                                                                     | The part number updates in Solus after sync                                                                                                                                                                         | ☐   |

## 3. Call usage

| #   | Step                                                                                                         | Expected                                                                                                                                 | ☐   |
| --- | ------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------- | --- |
| 3.1 | Leave everything idle for 2 hours (webhooks healthy)                                                         | Onshape API usage rises by **0–2** calls (daily health check only)                                                                       | ☐   |
| 3.2 | In Solus, read Home → Connections → Onshape quota                                                            | Shows "estimated", `pool: owner`, and a by-purpose breakdown (sync, webhook, agent_read…)                                                | ☐   |
| 3.3 | Compare Solus's count with Onshape's usage page after a few syncs                                            | Solus's number is ≤ Onshape's (it's a floor, labelled estimated) and moves together                                                      | ☐   |
| 3.4 | **Billing check (LIVE):** have **B** (not the app owner) run several syncs; watch the **owner's** usage page | The OWNER's usage rises (confirms owner-pool billing). If B's own usage rises instead, set `SOLUS_ONSHAPE_QUOTA_POOL=user` and report it | ☐   |

## 4. SOL in Guide / Build

| #   | Step                                                          | Expected                                                                                                                             | ☐   |
| --- | ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ | --- |
| 4.1 | Ask SOL (Guide) "what parts and variables are in QA Mirror?"  | Correct answer; usage rises by ~5 calls or fewer                                                                                     | ☐   |
| 4.2 | Ask a follow-up about the same document in the same chat turn | Little or no additional usage                                                                                                        | ☐   |
| 4.3 | Ask for body details of a complex part (several pages)        | All pages returned; usage rises by one fetch, not one per page                                                                       | ☐   |
| 4.4 | Build mode: ask SOL to change a variable                      | Approval card shows the document name and the concrete change; after approval Onshape reflects it and SOL confirms it read it back   | ☐   |
| 4.5 | After 4.4, immediately ask SOL to read that variable          | It reports the NEW value (never a cached old one)                                                                                    | ☐   |
| 4.6 | **Self-echo (LIVE):** after SOL's write, watch logs           | Ideally no webhook-triggered sync for SOL's own edit beyond the normal post-write sync. Record whether Onshape still sent a delivery | ☐   |

## 5. Storage and revocation

| #   | Step                                                                                         | Expected                                                                                                      | ☐   |
| --- | -------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- | --- |
| 5.1 | Add "QA Mirror" to a **second project** on the same Onshape account                          | Its first sync exports nothing new (served from the CAD store)                                                | ☐   |
| 5.2 | Track a document with a very large Part Studio (STEP > 8 MiB) and sync twice without changes | Second sync does no export                                                                                    | ☐   |
| 5.3 | Inspect the bucket/folder                                                                    | Objects live under `cad/<hash>/<uuid>` — no document names, emails or ids in keys; S3 objects show SSE-AES256 | ☐   |
| 5.4 | Revoke the Onshape connection in Home                                                        | The account's `cad/<hash>/` objects are deleted                                                               | ☐   |

## 6. Failure paths

| #   | Step                                                                                                                              | Expected                                                           | ☐   |
| --- | --------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ | --- |
| 6.1 | Delete the webhook in Onshape (API Explorer `DELETE /webhooks/{id}`), wait for the daily check (or ask an engineer to trigger it) | Source falls back to hourly sweep; next sync re-registers          | ☐   |
| 6.2 | Stop the worker for 10 minutes while editing, then start it                                                                       | Changes are picked up (recovery) without a retry storm in logs     | ☐   |
| 6.3 | Set `SOLUS_ONSHAPE_APP_DISTRIBUTION=app_store` and push usage past 70 % (engineer can seed the ledger)                            | Background syncs keep running; with `private` they pause at 70 %   | ☐   |
| 6.4 | Remove CAD store settings and restart                                                                                             | Everything still works (Redis-only cache); log says store disabled | ☐   |

## Cross-feature

| #   | Check                                                                                    | ☐   |
| --- | ---------------------------------------------------------------------------------------- | --- |
| X.1 | Real-time team sync (SOLUSDEV-312): B's graph/sources update live after A's Onshape edit | ☐   |
| X.2 | Bench scene CAD meshes refresh after a Part Studio edit                                  | ☐   |
| X.3 | GitHub/KiCad sources unaffected                                                          | ☐   |
