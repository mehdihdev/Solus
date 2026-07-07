# COWORK QA — GitLab Connector (SOLUSDEV-104)

The GitLab connector mirrors GitHub on the same runtime. Run the full flow
matrix in `COWORK_QA_connector-framework-github.md` substituting GitLab, plus
the GitLab-specific checks below.

## Required setup state

- [ ] Everything from the SOLUSDEV-103 QA setup (API, desktop app, secret store).
- [ ] `SOLUS_GITLAB_CLIENT_ID` / `SOLUS_GITLAB_CLIENT_SECRET` in
      `packages/api/.env` per `docs/integrations/gitlab-setup.md` (or a GitLab
      PAT with `read_api` scope for the token path).
- [ ] A GitLab account with at least one project; for full coverage one project
      under a **nested group** (`group/subgroup/project`) and one containing a
      committed design export (`.gbr`/`.step`/`.net`/`.cir`).

## GitLab-specific checks

1. **Catalog:** `GET /api/v1/integrations` lists `gitlab` with
   `auth_kind: "oauth"` and scopes including `read_api`.
2. **Token connect (PAT):** `POST /api/v1/projects/{pid}/sources` with
   `{"type": "gitlab", "name": "...", "config": {"repo": "<path>"}, "token": "<PAT>"}`.
   **Expected:** 201, status `connected`, `account_login` = your GitLab username;
   token never echoed back.
3. **OAuth flow:** `POST /api/v1/integrations/gitlab/oauth/start` → authorize in
   browser → source `connected` (same handshake as GitHub, including the desktop
   loopback exchange).
4. **Nested namespace:** connect a `group/subgroup/project` repo and sync.
   **Expected:** sync succeeds; `code_repo` entity name is the full path.
5. **Large project (pagination):** sync a project with >100 tree objects.
   **Expected:** all files land (the tree endpoint is paginated; nothing beyond
   the first 100 items is missing).
6. **Design exports:** identical `design_export` surfacing as GitHub (flow 1
   step 8 of the 103 QA file).
7. **Re-sync / detect changes:** push a commit, re-sync. **Expected:** delta
   reconciled, no duplicates; unchanged repo re-sync creates 0 new entities.
8. **Failure paths:** bad PAT → 400 `invalid_credentials`; nonexistent project
   path → sync `failed` with `repo_not_found`; revoked token → recorded auth
   failure, no crash.
9. **Isolation:** all cross-tenant checks from the 103 QA file repeated against
   a GitLab source → 404 for non-members.

## Sign-off

- [ ] Full 103 flow matrix passes with GitLab substituted.
- [ ] Checks 1–9 above pass.
