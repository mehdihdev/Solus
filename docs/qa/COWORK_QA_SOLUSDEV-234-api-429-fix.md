# COWORK QA — SOLUSDEV-234: API 429 Error Fix

## What changed

The desktop app used to hit `429 Too Many Requests` from Solus's own API after roughly 30 seconds
of normal clicking, after which every screen showed offline/error states until the minute rolled
over. Two fixes:

1. **API budgets split by method**: reads (GET) now get 1200 requests/minute per signed-in
   token (`SOLUS_RATE_LIMIT_PER_MINUTE`); writes keep their own 120/minute bucket
   (`SOLUS_WRITE_RATE_LIMIT_PER_MINUTE`). CORS preflights are no longer counted, and a `429` now
   carries CORS headers so the desktop can read it.
2. **Desktop API client**: concurrent identical GETs share one network request, and a `429` on a
   GET pauses further GETs until the server's `Retry-After` elapses (mutations are never held
   back). Both are scoped to the signed-in token.

## Required setup

- API running locally with default settings (no `SOLUS_RATE_LIMIT_PER_MINUTE` override) and its
  console visible so request lines are readable.
- Desktop app signed in to a team with at least one project that has a synced source (a few
  hundred entities is ideal so the graph pages in 500-row bursts).
- Optional for path 3: a second API start with `SOLUS_RATE_LIMIT_PER_MINUTE=20` to force 429s.

## Paths

### 1. Sustained navigation never 429s (the reported bug)

1. Open the project workspace. Watch the API console.
2. For 3 minutes, click continuously between: Graph, Live Bench, Extensions, Settings, the activity
   feed, and back to the workspace. Focus several entities in the Context Model so the Live Bench
   widget polls.
   - Expected: every request line in the API console is `200`/`204`/`404`; **no `429` line at
     any point**. The UI never shows "Solus can't reach its API" or error banners.
3. Leave the workspace open and idle for 2 more minutes with a Live Bench widget focused.
   - Expected: still no `429`.

- [ ] Pass  - [ ] Fail — notes:

### 2. Duplicate reads are coalesced

1. On the workspace screen (sources, bridge, extensions, widgets all polling), watch the API
   console for 30 seconds.
   - Expected: each polled path (`/sources`, `/bridge`, `/extensions`, `/widget-layout`,
     `/bench/sessions?status=active`) appears roughly once per its poll period. The
     back-to-back duplicate pairs of the same path (previously visible in the log) are gone.
2. Change something that triggers a refetch (e.g. enable/disable an extension).
   - Expected: the list updates promptly; coalescing does not serve stale data.

- [ ] Pass  - [ ] Fail — notes:

### 3. Forced 429 recovers gracefully (edge case)

1. Restart the API with `SOLUS_RATE_LIMIT_PER_MINUTE=20`. Reopen the workspace and click around
   until requests start failing.
   - Expected: the API console shows a **small number** of `429` lines, then goes quiet — the
     desktop stops sending GETs rather than logging a 429 every poll tick. UI panels show their
     error/offline state.
2. Wait for the minute boundary (the `Retry-After` value).
   - Expected: polling resumes on its own; panels recover without a restart or manual refresh.
3. While paused, perform a mutation (e.g. rename the project, toggle an extension).
   - Expected: the request is sent to the server (a line appears in the console) — mutations are
     never suppressed client-side. It may itself return `429`, shown as a normal error.
4. Restore the default limit afterwards.

- [ ] Pass  - [ ] Fail — notes:

### 4. Write budget is independent of reads (edge case)

1. With the API at `SOLUS_RATE_LIMIT_PER_MINUTE=20` (path 3) and reads paused, perform 3–4
   mutations in a row (rename project, toggle extensions).
   - Expected: each mutation reaches the server and succeeds (writes have their own budget).
2. Restart with default read limit and `SOLUS_WRITE_RATE_LIMIT_PER_MINUTE=3`; perform 4 mutations
   quickly.
   - Expected: the 4th shows a "too many" style error; navigation and polling keep working
     (reads are unaffected by the exhausted write budget).

- [ ] Pass  - [ ] Fail — notes:

### 5. Sign-out / sign-in on the same machine shares nothing (security)

1. While the workspace is polling, sign out and immediately sign in as a different user.
   - Expected: the new user's screens show only their own data (credits, settings, teams). No
     flash of the previous account's values.

- [ ] Pass  - [ ] Fail — notes:

### 6. Cross-feature: SOL classify preview is unaffected

1. Type in the SOL box and pause repeatedly (the classify preview fires on typing pauses).
   - Expected: preview keeps working; it has its own separate budget and is not paused by, nor
     pauses, the general read budget.

- [ ] Pass  - [ ] Fail — notes:

## Out of scope (observed in the same log, separate tickets)

The companion supervisor errors for `altium`, `kicad` (`.venv/bin/python3: No such file or
directory`) and `fusion` are missing local MCP virtualenvs / an unreachable remote server, not
rate limiting. They do not affect these paths.
