# Connect Wizard — Wireflow (SOLUSDEV-165)

The guided connect experience for sources, replacing the inline in-tile flow on
BOTH surfaces that offer connections: **Home › Connected accounts**
(`features/workspace/ConnectedAccountsCard.tsx`; the per-project Sources page it
replaced is retired, SOLUSDEV-244 — see `home.md`) and **onboarding step 1**
(`features/onboarding/ConnectStep.tsx`). Documents the flow **exactly as
implemented**. One implementation serves both surfaces:
`ConnectCatalog` (tiles + wizard) → `ConnectWizardModal` (presentation) →
`useConnectWizard` (glue) → the unchanged flow engines
(`runOAuthConnect` / `runEdaConnect`).

Amended SOLUSDEV-168: the **Add-ons ride the connect** section below. The rail
table and the action-area table are unchanged by that work.

## Layout (modal, 520 px, over the current page)

```
                                    [X]
   ┌─────┐   · · · · · ·   ┌─────┐
   │  S  │   (link dots)   │logo │        ← Solus ↔ integration link
   └─────┘                 └─────┘
   ( Sign in ) ( Pick repositories ) ( Build graph )   ← step rail
              Step headline
     SOL-mode instruction (Guide/Expert)
            [ action area ]
```

- **Link animation**: 6 dots between the Solus "S" mark and the integration
  logo. Busy = travelling pulse (`cw-dot-travel`, staggered delays) + gentle
  breathe on both endpoint marks; done = solid `--ok`; error = `--err`; idle =
  muted. Transform/opacity only, tokens only, all animation disabled under
  `prefers-reduced-motion`.
- **Logos**: bundled from `assets/integrations/<lowercase-provider-id>.svg`
  (png accepted, svg preferred — `integrationLogos.ts`). A provider without an
  asset falls back to its letter mark, so unknown connectors still render.

## The step rail is DERIVED, never hardcoded

`connectSteps.ts` builds the rail from what the connector **declares** in the
live registry (`GET /integrations`) — no provider ids anywhere:

| Connector shape                            | Rail                                         |
| ------------------------------------------ | -------------------------------------------- |
| `oauth` + `selection`                      | Sign in → Pick \<plural noun\> → Build graph |
| `oauth` + `config_fields`                  | Sign in → Enter details → Build graph        |
| `oauth` + `access_modes` (>1 mode)         | Choose access → Sign in → … → Build graph    |
| `auth_kind none` + `export` (KiCad/Altium) | Choose export → Build graph                  |

The live engine `stage` (`access`/`authorize`/`link`/`configure`/`index`, on
busy `ConnectionState`s) positions the current step; `link` maps onto the
Sign-in step. Completed steps show a check; the current step is the accent
chip (`aria-current="step"`).

## Copy (ADR-016 — SOL mode)

Step instructions come from `stepInstruction(step, ctx, solMode)`:
**Guide** teaches ("Your browser opens GitHub's own sign-in page. Solus never
sees your password…"), **Expert** is terse ("Sign in via your browser.").
Live engine copy (progress labels, the real result string, honest errors) is
always shown verbatim — never fabricated.

## Action area by state

| State                 | Action area                                                                                                                                                                                                                                    |
| --------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| idle, oauth           | `Connect <name>` primary button → `begin()`                                                                                                                                                                                                    |
| idle, export-file     | `Choose export file` (KiCad: `Choose netlist / board file`, multi-select, hint line) → hidden file input (`.xml,.net`; KiCad adds `.kicad_pcb`) → files are content-sniffed: netlist (XML or S-expression) → `config.export`, board → `config.board`; a `.kicad_sch`/`.kicad_pro` fails fast with guidance before any source is created (SOLUSDEV-252) → flow                                                                                                                                                                                         |
| busy + `accessModes`  | radio grant choice (descriptions shown, connector default pre-selected) → Continue                                                                                                                                                             |
| busy + `selectable`   | `SelectionPicker` (single dropdown / multi checkboxes; empty multi allowed)                                                                                                                                                                    |
| busy + `configFields` | one input per field; credential-shaped names (key/secret/token/license/password/passphrase/credential) render masked — on-screen hygiene only, real secrets must use SecretStore refs, never `config_fields`; Continue disabled until complete |
| busy otherwise        | spinner + live engine label                                                                                                                                                                                                                    |
| error                 | honest error + Retry (OAuth → `begin()` again; export-file → the file picker again)                                                                                                                                                                                                       |
| done                  | real result ("Connected — N entities indexed") + Done                                                                                                                                                                                          |

## Flows

1. **Next-step click** (a Home row's button / an onboarding tile) → wizard opens at
   step 0. Tiles are pure launchers (`ConnectTile`): identity, logo, live
   status footer. Clicking an errored tile reopens the wizard on the error.
2. **OAuth**: Connect → (grant choice if offered) → browser handshake →
   token exchange → pick/enter what to track → sync + poll → done.
3. **Committed export**: Choose file (validated ≤8 MB, non-empty by the
   engine) → parse + sync → done.
4. **Done** → `onConnected` fires (Home refreshes its accounts and the project's sources;
   onboarding recounts toward "Build context model").

## Cancel contract (close mid-flight)

Closing the wizard (X or backdrop) while a flow is in flight — from the moment
`begin()`/`pickFile()` runs, even before the first progress write — **cancels
the attempt** (`useConnectWizard.close`, per-attempt latches):

- Pending and future in-wizard inputs resolve null (`useOAuthConnect.cancel`),
  and the browser handshake is aborted (`bridge.cancelOAuth` →
  `oauthLoopback.cancelActiveOAuth`) so the flow always settles now — nothing
  parks forever and no token is minted for an abandoned handshake.
- The tile's connection entry is forgotten immediately (back to "Connect"),
  and the cancelled attempt's further progress writes are suppressed — they
  can never resurrect the forgotten tile state or clobber a newer attempt.
- **Cancel never deletes anything.** For multi-selection connectors the
  backend REUSES the existing connected source, so the flow's `sourceId` can
  name live, populated graph data — auto-deleting it would violate the §7
  no-unconfirmed-destruction rule. A genuinely half-configured source stays
  visible under its tool's row on Home, where the confirmed Disconnect already lives.
- A flow that **completed successfully anyway** (the handshake finished before
  the abort landed) keeps its source and reports through `onConnected` —
  finished work is never silently discarded.
- Closing on an **error** keeps the error state so the tile stays retryable.
- Closing on **done** just closes.

## Add-ons ride the connect, without becoming a step (SOLUSDEV-168)

A vendor-hosted MCP add-on — the Onshape Labs FeatureScript server, and every hosted
server after it (ADR-035) — is enabled **as part of this connect**, not on a button
afterwards: the brief is *"one connect, FeatureScript comes with it"*. It runs inside the
`link` stage, immediately after the account is linked, while the browser still holds the
vendor session from the handshake that just finished — so its own sign-in is usually a
redirect the user barely sees.

It adds **no** rail step, **no** new `ConnectStage` and **no** action-area state. The rail
still runs `access → authorize → link → configure → index` and still lands on `done`
whether or not the add-on turned on: **failing to enable an add-on is never a failed
connection**, and inventing a rail step for something that may legitimately not happen
would make the flow look like it went wrong when it did not. On success the `done` copy
gains a suffix (`Connected — 12 entities indexed · FeatureScript enabled`); on failure it
is simply absent.

**The RECOVERY path, not the primary one:** an add-on block under the connected source on
Home (`HostedAddOnRow`, rendered by the source item under the tool's row), driven entirely by
`source.config.hosted.<server>.state` — server-backed, so it is correct for every teammate
and survives every navigation. Three states: `not_connected` (the disclosure + *Enable*),
`subscription_required` (the vendor's own reason + *Open … App Store* + *I've subscribed —
check again*), and `ready`.

It exists because the in-connect attempt can legitimately not succeed — most often because
the customer has not bought the vendor's app yet, which is a browser purchase Solus cannot
drive and cannot detect the completion of except by re-probing. Three reasons that recovery
surface must be durable rather than wizard-resident, each load-bearing:

- **The cancel contract.** Closing the wizard cancels the attempt. Subscribing is an
  external browser purchase that can wait on a company administrator — no state parked in
  the wizard would survive it.
- **Wizard-resident state does not survive navigation** (the wizard is modal), so nothing
  durable may be parked in it.
- **A teammate never opens this wizard.** For a `multi`-selection connector the backend
  REUSES the project's existing source, so someone joining a project where Onshape is
  already connected would never reach a wizard-only affordance.

## Disclosure (SOLUSDEV-168)

A connector that carries a hosted add-on declares it in the live registry
(`GET /integrations` → `hosted: {server, display_name, notice, subscribe_url}`), exactly
the way `selection` and `access_modes` are declared. Enabling a third-party app on
someone's account is a trust cost even when it is free, so the notice is **stated, never
implied**, and it renders **verbatim** — backend-authored consent copy is never paraphrased
by the renderer. Per ADR-016 only the mode-aware LEAD-IN changes (`noticeLead`): Expert mode
gets to be terse, it does not get to hide what a connection turns on.

## A linked account skips the sign-in (SOLUSDEV-241 / I1)

OAuth binds at ACCOUNT scope. Home (H2) carries a **Connected accounts** card
(`features/workspace/ConnectedAccountsCard.tsx`): every OAuth connector from the live
registry with a *Connect* action that opens THIS wizard in account mode (`projectId: null`)
— rail `[Choose access →] Sign in`, done copy "Connected as <login>" — plus each linked
account with the projects that use it and a confirmed *Revoke* that names those projects
("Disconnects Onshape in Rover and Arm").

On Home, when the user already has a CONNECTED account for the row's provider,
the wizard **reuses it**: the rail drops `access` and `authorize` and reads
`Pick <plural noun> → Build graph`, the idle action area says *Connect <name>* over
"Using your linked account · <login>", and `begin()` goes `POST /projects/{p}/sources
{type, connection_id}` (no browser handshake) → the unchanged configure + index steps. The
engine stage for that bind is `link`. A user with no linked account sees exactly the old
rail; the wizard never asks twice for a grant it already holds.

Teammates never see another member's accounts (they are owner-only); they use the shared
grant through the project's source exactly as before, and the picker they open is served
from the same account-keyed cache.

## Guards (honest, never faked)

- No linked project → tile errors "Solus API unreachable — retry once you are
  back online." without starting a flow.
- OAuth without the desktop bridge → "<name> connect needs the desktop app."

## Files

`connectSteps.ts` (+test) · `integrationLogos.ts` (+test) ·
`accountConnect.ts` (+test, account-mode engine) · `useAccountConnections.ts` (+test) ·
`ConnectedAccountsCard.tsx` (+test, Home) ·
`ConnectWizardModal.tsx` (+test) · `useConnectWizard.ts` (+test) ·
`ConnectCatalog.tsx` (+test) · `ConnectTile.tsx` (launcher, +test) ·
engine stage emissions in `oauthConnect.ts` / `edaConnect.ts` /
`accessChoiceStep.ts` / `selectionConfigureStep.ts` / `fieldsConfigureStep.ts` ·
`onboardingStore.ts` (`stage`, `clearConnection`) · wizard CSS in
`assets/main.css` (`cw-*`).
