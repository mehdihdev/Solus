# Cowork QA: GitHub organizations in teams (SOLUSDEV-216)

**What this feature does.** A Solus **collaborative team** links a GitHub **organization** through the **Solus GitHub App**. Once linked:

- Any team member can add the org's repositories to the team's projects without signing in to GitHub themselves.
- Pushes to those repos trigger syncs.
- Admins see the org's member list and can **suggest** invites.

GitHub membership never grants Solus access by itself.

Mark each checkbox **PASS** or **FAIL** and add a note on every FAIL: what you saw, a screenshot, and the time.

---

## 0. Setup (do once)

### 0.1 Accounts and GitHub

You need two GitHub accounts and two GitHub orgs.

| Who          | GitHub                                                                                     | Solus                                              |
| ------------ | ------------------------------------------------------------------------------------------ | -------------------------------------------------- |
| **Owner**    | `qa-owner`: **owner** of org `solus-qa-org`                                                | Signs in to Solus with an email. BASIC or PRO plan |
| **Member**   | `qa-member`: **member** (not owner) of `solus-qa-org`, with read access to repo `bms` only | A second Solus account                             |
| **Outsider** | (none needed)                                                                              | A third Solus account, in a different team         |

Repositories in `solus-qa-org`:

- `vcu-firmware`: private, any files.
- `bms`: private.
- `docs-site`: public.

A second org, `solus-qa-org-2`, owned by `qa-owner` with one repo, is used for the "linked elsewhere" check.

### 0.2 Solus server

These need a human:

- **GitHub App registered.** Follow `docs/integrations/github-setup.md` → "GitHub App for team organizations". Callback `http://localhost:53682/auth/callback`; **Request user authorization during installation** ON; permissions Contents R, Metadata R, Org Members R; events Push, Repository, Organization, Member.
- **App env vars set:** `SOLUS_GITHUB_APP_ID`, `_SLUG`, `_CLIENT_ID`, `_CLIENT_SECRET`, `_WEBHOOK_SECRET` and `_PRIVATE_KEY` (or `_PRIVATE_KEY_PATH`).
- **Webhook URL** reachable over public HTTPS (a tunnel is fine) at `<API>/api/v1/webhooks/github/app`. Without it, §6 cannot be run. Everything else still works, and syncs fall back to the hourly sweep.
- **Migration applied:** `alembic upgrade head` (revision `a21600000001`).
- **Services running:** API, worker (ARQ + Redis) and the desktop app.

### 0.3 Solus state

- [ ] Owner creates a collaborative team **"QA Robotics"** (Home → New team) and creates a project **"Rover"** in it.
- [ ] Owner invites Member to QA Robotics by email; Member accepts. Member is now a **member** role.
- [ ] Outsider has their own collaborative team **"Other Team"** with a project **"Other"**.

---

## 1. Link the organization

| #   | Steps                                                                                           | Expected                                                                                                                                                                                                                                                | ✓   |
| --- | ----------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --- |
| 1.1 | Owner: Home on **QA Robotics**                                                                  | A **GITHUB ORGANIZATION** card under MEMBERS reads "Link your GitHub organization so everyone on the team can add its repos…", with a **Link organization** button                                                                                      | [ ] |
| 1.2 | Member: Home on QA Robotics                                                                     | The card says no organization is linked and to ask a team admin. **No button**                                                                                                                                                                          | [ ] |
| 1.3 | Owner: switch to their **personal** team                                                        | **No** GitHub organization card at all                                                                                                                                                                                                                  | [ ] |
| 1.4 | Owner: back on QA Robotics, click **Link organization**                                         | The system browser opens GitHub's install page for the Solus App. The card shows a linking/progress state                                                                                                                                               | [ ] |
| 1.5 | On GitHub, choose `solus-qa-org`, **All repositories**, Install, then approve the authorization | The browser shows the loopback "you can close this" page. In Solus the card becomes **linked**: avatar, `solus-qa-org · Organization · 3 repos`, "Linked by <Owner name> · just now · all repositories", **Members on GitHub**, **Manage on GitHub ↗** | [ ] |
| 1.6 | Click **Manage on GitHub ↗**                                                                   | It opens the org's installation settings page on github.com in the browser                                                                                                                                                                              | [ ] |
| 1.7 | Team activity on Home                                                                           | A "linked GitHub organization" activity row appears                                                                                                                                                                                                     | [ ] |
| 1.8 | Member's Home (open in a second window or machine)                                              | The card updates to linked **without a manual refresh** (live update), and shows no ⋯ unlink menu                                                                                                                                                       | [ ] |

### 1A. Link refusals

| #    | Steps                                                                                                                                                                                                                  | Expected                                                                                                                                                                                                                                                                    | ✓   |
| ---- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --- |
| 1A.1 | Promote Member to **admin** in Solus. As Member, start **Link organization** on a fresh team (create "QA Two"), and install as `qa-member` on `solus-qa-org`. GitHub will ask for an owner's approval or let them pick | Either GitHub requests owner approval: Solus shows "Waiting for an org owner to approve Solus on GitHub…" and nothing is linked. Or, if GitHub lets the flow complete: Solus refuses with "Only an owner of this organization on GitHub can link it…" and nothing is linked | [ ] |
| 1A.2 | Owner: on team **QA Two** (Owner is admin there), Link organization and choose `solus-qa-org` again                                                                                                                    | Refused: "This organization is linked to another Solus team — unlink it there first, then link it here."                                                                                                                                                                    | [ ] |
| 1A.3 | Owner: on QA Robotics (already linked), use any path that would link again (e.g. the API, or a second Link click if the button is visible)                                                                             | Refused as already linked. The card does not change                                                                                                                                                                                                                         | [ ] |
| 1A.4 | On a BASIC user at the integration limit (4 integrations already), click Link organization                                                                                                                             | The plan-limit refusal with **Upgrade**                                                                                                                                                                                                                                     | [ ] |
| 1A.5 | Start Link organization, then close the GitHub tab without installing                                                                                                                                                  | After the wait, the card returns to the unlinked state with a cancelled/failed note. No partial link                                                                                                                                                                        | [ ] |
| 1A.6 | Server with the App env vars removed: open Home on a collaborative team                                                                                                                                                | The card says GitHub organizations aren't set up on this server. No Link button                                                                                                                                                                                             | [ ] |

---

## 2. Add an org repo to a project (no personal sign-in)

| #   | Steps                                                                                                                                 | Expected                                                                                                                                                                    | ✓   |
| --- | ------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --- |
| 2.1 | **Member** (never signed in to GitHub in Solus): open project **Rover** → Connect → **GitHub**                                        | The picker shows a section **FROM SOLUS-QA-ORG (TEAM)** listing `vcu-firmware`, `bms` and `docs-site`, plus a **YOUR ACCOUNT** section offering "Use my own GitHub account" | [ ] |
| 2.2 | Member picks `vcu-firmware`                                                                                                           | **No GitHub sign-in or browser opens.** The step rail has no "Sign in" step. The source connects and the graph builds (index step completes)                                | [ ] |
| 2.3 | Project Rover → sources                                                                                                               | A GitHub source for `solus-qa-org/vcu-firmware` is connected and synced                                                                                                     | [ ] |
| 2.4 | Note: Member only has GitHub access to `bms`, yet picked `vcu-firmware`                                                               | Expected and allowed. The **team's** installation grants access; this is the point of the feature                                                                           | [ ] |
| 2.5 | Member: connect `vcu-firmware` again in Rover                                                                                         | No duplicate source. The existing one is reused                                                                                                                             | [ ] |
| 2.6 | Outsider: open project **Other** → Connect → GitHub                                                                                   | **No** team section (Other Team has no installation). The wizard is exactly as before                                                                                       | [ ] |
| 2.7 | Owner: on GitHub, change the installation to **Only select repositories** → `bms` only. Back in Solus, open Connect → GitHub in Rover | The team section lists only `bms`, possibly after the webhook (§6) or a refresh                                                                                             | [ ] |
| 2.8 | Owner: Home card                                                                                                                      | The scope reads "selected repositories" and the repo count updates                                                                                                          | [ ] |
| 2.9 | Owner: personal GitHub path still works. In a project, choose **Use my own GitHub account**                                           | The normal GitHub sign-in runs, as before this feature                                                                                                                      | [ ] |

---

## 3. Team-owned: the linker leaves

| #   | Steps                                                                                       | Expected                                                                                 | ✓   |
| --- | ------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- | --- |
| 3.1 | Make Member an **owner** of QA Robotics, then Owner **leaves** QA Robotics (⋯ → Leave team) | Owner leaves successfully                                                                | [ ] |
| 3.2 | Member: Home on QA Robotics                                                                 | The card is still linked. "Linked by" shows the former owner's name or "a former member" | [ ] |
| 3.3 | Member: trigger a sync of the `vcu-firmware` source                                         | The sync **succeeds**. The installation belongs to the team, not the person              | [ ] |
| 3.4 | Re-invite Owner and make them owner again, for later sections                               | Done                                                                                     | [ ] |

---

## 4. Roster and suggested invites

| #   | Steps                                                                                                                                                                           | Expected                                                                                                                                                                           | ✓   |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --- |
| 4.1 | Owner: card → **Members on GitHub**                                                                                                                                             | A modal lists `qa-owner` and `qa-member` with avatars. Each is **On team** if that Solus user has a linked GitHub account matching the GitHub user, otherwise an **Invite** button | [ ] |
| 4.2 | Member (as a plain **member** role): the card                                                                                                                                   | There is no **Members on GitHub** button                                                                                                                                           | [ ] |
| 4.3 | Add a third GitHub user `qa-new` to `solus-qa-org`. Owner opens the roster and clicks **Invite** on `qa-new`                                                                    | A one-time join token is shown, as with email invites. The row becomes **Invited**                                                                                                 | [ ] |
| 4.4 | Close the modal before copying the token                                                                                                                                        | You are asked to confirm, because the token isn't shown again                                                                                                                      | [ ] |
| 4.5 | `qa-new` signs up to Solus, links their GitHub account `qa-new` (Home → Connected accounts → GitHub), then **Join team** with the token                                         | Joins QA Robotics as member                                                                                                                                                        | [ ] |
| 4.6 | A different Solus user, with **no** GitHub link or a different GitHub account, tries the same kind of token (create another GitHub-id invite and use it from the wrong account) | Refused: identity mismatch. They do not join                                                                                                                                       | [ ] |
| 4.7 | Owner: invite again on someone already **Invited**                                                                                                                              | Refused as already pending                                                                                                                                                         | [ ] |
| 4.8 | Email invites (regression): Owner invites `someone@example.com` by email                                                                                                        | Works exactly as before                                                                                                                                                            | [ ] |

---

## 5. Unlink

| #   | Steps                                    | Expected                                                                                                                                      | ✓   |
| --- | ---------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- | --- |
| 5.1 | Member (member role): ⋯ menu on the card | Not present                                                                                                                                   | [ ] |
| 5.2 | Owner: ⋯ → **Unlink**                    | The confirm names how many project sources it disconnects (e.g. "disconnects 1 project sources")                                              | [ ] |
| 5.3 | Cancel                                   | Nothing changes                                                                                                                               | [ ] |
| 5.4 | Unlink → confirm                         | The done step says N sources were disconnected and offers **Uninstall on GitHub ↗**. The card returns to unlinked. Activity shows "unlinked" | [ ] |
| 5.5 | Project Rover → sources                  | The `vcu-firmware` source is **disconnected**, with a message that the org was unlinked. Its graph data is kept                               | [ ] |
| 5.6 | Try to sync that source                  | Refused. It does not sync                                                                                                                     | [ ] |
| 5.7 | Re-link (§1.4–1.5)                       | Works. The old source stays disconnected until re-added                                                                                       | [ ] |

---

## 6. Webhook-driven behaviour (needs the public webhook URL)

| #   | Steps                                                                                             | Expected                                                                                                                                                                            | ✓   |
| --- | ------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --- |
| 6.1 | Push a commit to `vcu-firmware` on the branch the source tracks                                   | Within ~a minute the source shows a new sync (sync history: trigger webhook)                                                                                                        | [ ] |
| 6.2 | Push to a **different branch**                                                                    | No sync                                                                                                                                                                             | [ ] |
| 6.3 | On GitHub: **Suspend** the Solus App installation                                                 | The card shows the warn row "Suspended on GitHub — syncs paused…". The source shows an error that the installation is suspended. The wizard team section says "Suspended on GitHub" | [ ] |
| 6.4 | **Unsuspend**                                                                                     | The card returns to linked and the source recovers to connected                                                                                                                     | [ ] |
| 6.5 | On GitHub: remove `vcu-firmware` from the installation's repo access                              | Only the `vcu-firmware` source goes into error ("repo access removed"). Other sources are untouched                                                                                 | [ ] |
| 6.6 | Rename `bms` → `bms-v2` on GitHub (if a `bms` source exists)                                      | That source shows an honest rename error. Its config is not silently rewritten                                                                                                      | [ ] |
| 6.7 | Remove `qa-member` from `solus-qa-org` on GitHub (Member's Solus account has their GitHub linked) | Team owners/admins get a notification and an activity row that the person left the GitHub org. **Member is NOT removed from the Solus team**                                        | [ ] |
| 6.8 | On GitHub: **Uninstall** the App from `solus-qa-org`                                              | The card returns to unlinked and the sources disconnect, as in §5                                                                                                                   | [ ] |
| 6.9 | GitHub App settings → Advanced → redeliver a recent delivery                                      | Processed once. No duplicate sync                                                                                                                                                   | [ ] |

---

## 7. Permission and tenancy boundaries (API-level, use the browser devtools or curl with each user's token)

| #    | Check                                                                                                                                                                    | Expected                                                                             | ✓   |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------ | --- |
| 7.1  | Outsider calls `GET /api/v1/teams/<QA Robotics id>/github/installation`                                                                                                  | 404                                                                                  | [ ] |
| 7.2  | Outsider calls `GET /api/v1/teams/<QA Robotics id>/github/repos`                                                                                                         | 404                                                                                  | [ ] |
| 7.3  | Member (member role) calls `GET …/github/members`                                                                                                                        | 403                                                                                  | [ ] |
| 7.4  | Viewer role calls `GET …/github/installation` and `…/repos`                                                                                                              | 200 for both. Viewers can see                                                        | [ ] |
| 7.5  | Viewer tries to add a team repo source to a project                                                                                                                      | 403                                                                                  | [ ] |
| 7.6  | Outsider, on project **Other**, `POST /api/v1/projects/<Other id>/sources {type:"github", name:"x", installation:true, config:{repo:"solus-qa-org/bms", branch:"main"}}` | 409 `installation_missing`. Another team's installation is never reachable           | [ ] |
| 7.7  | `POST …/sources` with both `installation:true` and a `connection_id`                                                                                                     | 400 `credential_conflict`                                                            | [ ] |
| 7.8  | `POST …/sources` with `installation:true` and a repo not in the installation                                                                                             | 400 `repo_not_in_installation`                                                       | [ ] |
| 7.9  | `PATCH` a team-repo source with `secret_ref` or `installation_id` in the body                                                                                            | 422. Not patchable                                                                   | [ ] |
| 7.10 | `POST /api/v1/webhooks/github/app` with a bad or no `X-Hub-Signature-256`                                                                                                | 401                                                                                  | [ ] |
| 7.11 | Any API response from §1–§6                                                                                                                                              | Never contains a GitHub token (`ghs_`, `ghu_`), a private key, or the webhook secret | [ ] |

---

## 8. SOL mode copy

| #   | Steps                                                                                         | Expected                                                                       | ✓   |
| --- | --------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ | --- |
| 8.1 | Settings → SOL mode **Guide**: view the card (unlinked and linked), a refusal, and the roster | Explanatory sentences (why an org owner approves on GitHub, what linking does) | [ ] |
| 8.2 | Switch to **Expert**                                                                          | The same states in terse copy                                                  | [ ] |
| 8.3 | Wizard team section errors (e.g. suspended) in both modes                                     | Named, honest messages; never a silent failure                                 | [ ] |

---

## 9. Regression spot checks

- [ ] Personal GitHub OAuth connect flow (Home → Connected accounts → GitHub) still works end to end. Its callback uses `localhost:53682`.
- [ ] A personal account with more than 100 repos: the repo picker lists **all** of them (the list was capped at 100 before).
- [ ] Team members list and counts: a member who left doesn't appear and isn't counted.
- [ ] GitLab, Onshape and KiCad connect flows are unchanged.

---

## Known limitations (not bugs)

- **GHES:** GitHub Enterprise Server is supported by the data model and minter, but the agent's code-file reader and branch/commit browsing still call github.com.
- **Roster matching:** the roster's **On team** status relies on teammates having linked their GitHub account in Solus. Without that, a teammate shows **Invite**.
- **Team repo list:** the wizard's team section shows the first page of repos (up to 100) with no search yet.
