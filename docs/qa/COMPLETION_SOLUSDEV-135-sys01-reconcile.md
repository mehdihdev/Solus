# Completion — SOLUSDEV-135 (SYS-01): reconciled, CLOSE AS ALREADY-BUILT

**Status: no code written — every acceptance criterion is met by shipped LANE C / RUN-01 code**
(the LNK-03 precedent). Verified line-by-line on 2026-08-15 against
`SOLUSDEV-69-lane-e-sol-systems` at the main merge.

## Acceptance evidence

| SYS-01 acceptance                                  | Verdict | Evidence                                                                                                                                                                                                                                                                                                                                                                                   |
| -------------------------------------------------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Conversation service: create, append turns, stream | **MET** | `Conversation`/`ConversationTurn` (`models.py:1069,1090`), migration `b3d9c1a4e7f2` (+ merge head `ed51dbd874ff`); `agent/conversation.py:28` `ConversationService` — `create`/`append_turn`/`history` with a 20-turn bound; turns persisted DURING the stream via a fresh sessionmaker (`routers/sol.py:265`, user turn `:475`)                                                           |
| Tool registry wired for list/invoke (W0-04)        | **MET** | `agent/tools/registry.py:38` `ToolRegistry`; per-request `build_sol_registry` (`runtime.py:74`) — scope fixed by Solus code before any model sees data; `LlmRunner` loop (`runtime.py:467`, `MAX_MODEL_ROUNDS=5`); descriptors exposed on `GET /tools` (`sol.py:145`)                                                                                                                      |
| Auth/scope enforced on SOL endpoints               | **MET** | Every route carries `ProjectCtx` (`deps.py:376→351`; non-members get 404, no existence leak); conversations are owner-private (`conversation.py:53-57`) via `_owned_or_404`; `require_role(MEMBER)` on all mutating routes; `RequireVerified` on the destructive execution point `POST /confirmations/{id}` (`sol.py:583`); credits pre-flight 402 + frequency cap 429 on the stream route |
| Streaming transport to the client                  | **MET** | SSE `StreamingResponse` (`sol.py:568`) with `token/tool_call/tool_result/tool_confirmation/message/error/done` frames (`agent/stream.py`); 120 s turn wall-clock, 8-call tool cap, failure masking (never a traceback)                                                                                                                                                                     |
| Reference tool invocable end-to-end                | **MET** | `get_entity` always registered (`runtime.py:95`); Onshape tools via `build_onshape_tools`; proven by `tests/test_sol.py:172` `test_stream_invokes_reference_tool_end_to_end` — and by the SYS-04 live turn (4 successful Onshape tool calls)                                                                                                                                               |

`docs/api/API-implementation.md` already marks the SOL chat surface LIVE.

## Residual notes (recorded, not rebuilt)

1. **`RequireVerified` guards exactly one SOL route** — the destructive confirmation point.
   `POST …/messages` and `DELETE /conversations/{id}` allow MEMBER-with-unverified-email. This is
   LANE C's deliberate ADR-009 parity choice (rationale at `sol.py:594-597`); changing it is a
   product decision, not a gap in SYS-01.
2. The "systems layer" substance the ticket's title could imply — the real `SolSystems` — was
   never in SYS-01's acceptance and is SHIPPED under SYS-04 (SOLUSDEV-138).
3. The ticket's identifier hints (`SolConversation`, `agent/service.py`, `agent/llm_runner.py`)
   never existed; the real names are `Conversation`/`ConversationTurn`, `agent/conversation.py`,
   `agent/runtime.py`.

## Proposed Jira (NOT posted — decision 4)

Comment on SOLUSDEV-135, then transition IN REVIEW → Done:

> Reconciled against shipped code (Lane E Phase 0, 2026-08-15): all five acceptance criteria
> are met by the LANE C / RUN-01 implementation — conversation service with streamed turn
> persistence, W0-04 registry list/invoke through LlmRunner, ProjectCtx + role + verified-email
> gates on SOL endpoints, SSE transport with bounded turns, and the reference tool proven
> end-to-end in tests and a live turn. Closing as already-built (LNK-03 precedent); evidence
> table in docs/qa/COMPLETION_SOLUSDEV-135-sys01-reconcile.md. The real-SolSystems work this
> ticket's title hints at shipped under SOLUSDEV-138.
