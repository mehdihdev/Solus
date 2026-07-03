# COWORK QA — Connector Framework + GitHub Connector (SOLUSDEV-103)

End-to-end test plan for the connector runtime and the GitHub connector,
including the onboarding "connect GitHub + pull a repo" flow. Written to be run
against a running app with nothing but this file.

## Required setup state

- [ ] Postgres reachable (`make db-up`) or `SOLUS_DATABASE_URL` set; API running (`pnpm dev:api`).
- [ ] Desktop app running (`pnpm dev:desktop`).
- [ ] `packages/api/.env` filled per `docs/integrations/github-setup.md`:
      `SOLUS_GITHUB_CLIENT_ID`, `SOLUS_GITHUB_CLIENT_SECRET`, `SOLUS_SECRETS_KEY`.
- [ ] Renderer `VITE_SUPABASE_*` configured and you can sign in with a real account
      (dev-bypass mode has no account to attach a token to → GitHub real-connect
      is unavailable and tiles fall back to simulated).
- [ ] A GitHub account with at least one repository. For full coverage, one repo
      should contain a committed design export (e.g. a `.gbr`, `.step`, `.net`, or
      `.cir` file).

## Flow 1 — Connect GitHub in onboarding and pull a repo

1. Sign in; reach `/onboarding`. **Expected:** About step shows.
2. Enter a description, choose "connect", continue to the Connect step.
   **Expected:** a project is provisioned silently (the connect step has a real
   project to attach sources to).
3. Click **Connect** on the GitHub tile. **Expected:** the system browser opens
   GitHub's authorize page for the Solus OAuth App.
4. Approve access. **Expected:** browser shows "You're signed in — return to
   Solus"; the tile advances and a repo picker appears.
5. Pick a repository. **Expected:** tile shows a syncing state, then
   "Connected — N entities indexed" within a few seconds.
6. Finish onboarding → workspace. **Expected:** the project's source list shows
   the GitHub source as `connected` with a recent `last_synced_at`.

### Verify the graph landed (API or graph view)

7. `GET /api/v1/projects/{pid}/entities` (or the graph view). **Expected:** a
   `code_repo` entity, `code_file` entities for files, `code_module` for dirs.
8. If the repo had a committed export: filter `?type=design_export`.
   **Expected:** the Gerber/STEP/netlist/SPICE file appears as a `design_export`
   entity with `export_kind` in its properties and the right domain
   (electrical/mechanical).
9. `GET /api/v1/projects/{pid}/sources/{sid}/syncs`. **Expected:** one
   `succeeded` sync with non-zero `entities_created` and `relations_created`.

## Flow 2 — Re-sync reconciles changes

10. In GitHub, add a file and delete one in the connected repo.
11. Trigger sync again (re-connect / sync button, or `POST .../sync`).
    **Expected:** new file appears as an entity; deleted file's entity is gone;
    the sync shows `entities_created`/`entities_updated`/`relations_deleted`
    reflecting the delta (no duplicate entities).

## Flow 3 — Disconnect

12. Disconnect the source with retain OFF (default).
    **Expected:** source removed; its entities/relations removed from the graph;
    the stored token is deleted.
13. Re-connect, sync, then disconnect with `?retain_entities=true`.
    **Expected:** source removed but entities remain, now `origin: "manual"` with
    `source_id: null`.

## Edge cases & failure paths

- [ ] **Cancel OAuth:** close the browser / deny access. **Expected:** tile shows
      an error state; no source left in `connected`; onboarding still usable.
- [ ] **Invalid repo / no access:** sync a repo the token can't read.
      **Expected:** source goes `error`, `last_error` explains why; sync is
      `failed`; app does not crash.
- [ ] **Token revoked:** revoke the OAuth grant in GitHub, then sync.
      **Expected:** sync fails with an auth error recorded; no partial corruption.
- [ ] **Re-sync idempotency:** sync twice with no repo change.
      **Expected:** second sync creates 0 new entities (all "updated"/unchanged),
      no duplicates.
- [ ] **Secrets never exposed:** inspect every source API response.
      **Expected:** no `token` or `secret_ref` field anywhere.

## Cross-tenant isolation (security — must pass)

- [ ] As user B (not a member of user A's team/project), call every source and
      entity route for A's project/source ids. **Expected:** `404` on all (no
      existence leak), never another team's data.
- [ ] As user B, attempt `oauth/exchange` with user A's `state`.
      **Expected:** `404` (state is bound to its owner).
- [ ] `oauth/start` with a `redirect_uri` pointing at an external host.
      **Expected:** `400 invalid_redirect_uri`.

## Cross-feature interactions

- [ ] Triggering a sync creates a Job (`kind: sync`); `GET /api/v1/jobs/{id}`
      reflects its final status.
- [ ] Project detail / source list `entity_count` matches the number of entities
      the sync created.
- [ ] (If `SOLUS_REDIS_URL` set + worker running) a sync enqueues to ARQ rather
      than running inline; the scheduled change-detection sweep enqueues syncs
      for sources whose head commit changed.

## Sign-off

- [ ] Flows 1–3 pass.
- [ ] All edge cases behave as described.
- [ ] All cross-tenant isolation checks return 404 / 400 as specified.
