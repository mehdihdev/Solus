# GitLab Connector — setup & required env (SOLUSDEV-104)

The GitLab connector mirrors the GitHub one (`docs/integrations/github-setup.md`)
on the same runtime: OAuth or PAT auth, repo-tree sync into code entities, and
W0-08 committed-export surfacing. Works against gitlab.com or a self-hosted
instance.

## 1. Register a GitLab OAuth application

GitLab → **Preferences → Applications** (or an instance/group-level application).

| Field        | Value                                  |
| ------------ | -------------------------------------- |
| Name         | `Solus (local dev)`                    |
| Redirect URI | `http://127.0.0.1:53682/auth/callback` |
| Confidential | yes                                    |
| Scopes       | `read_api`, `read_user`                |

The redirect URI is the same desktop loopback the GitHub flow uses. Copy the
**Application ID** and **Secret**.

Alternatively, a **personal access token** with `read_api` scope can be supplied
directly when connecting a source (`POST /sources` with `token`) — no OAuth app
needed.

## 2. Env block — add to `packages/api/.env`

```bash
# --- GitLab connector (SOLUSDEV-104) ---
SOLUS_GITLAB_CLIENT_ID=your-application-id
SOLUS_GITLAB_CLIENT_SECRET=your-application-secret
# Self-hosted instances only (default: https://gitlab.com). The OAuth app must
# be registered on this instance.
# SOLUS_GITLAB_BASE_URL=https://gitlab.example.com
```

The secret store (`SOLUS_SECRETS_KEY` / AWS) and the rest of the connector
runtime env are shared with GitHub — see `github-setup.md` §2–4.

## What lands in the graph

Identical mapping to GitHub (shared `code_host` module): one `code_repo` root,
`code_module` directories, `code_file` blobs, `contains` relations, and
Gerber/STEP/netlist/SPICE files surfaced as cross-domain `design_export`
entities. GitLab specifics handled by the connector: nested namespaces
(`group/subgroup/project`), URL-encoded project paths, and the paginated
recursive tree endpoint (bounded; truncation surfaces as a sync warning).
