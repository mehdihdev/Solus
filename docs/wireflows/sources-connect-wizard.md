# Connect Wizard — Wireflow (SOLUSDEV-165)

The guided connect experience for sources, replacing the inline in-tile flow on
BOTH surfaces that offer connections: the per-project **Sources page**
(`features/project/SourcesScreen.tsx`) and **onboarding step 1**
(`features/onboarding/ConnectStep.tsx`). Documents the flow **exactly as
implemented**. One implementation serves both surfaces:
`ConnectCatalog` (tiles + wizard) → `ConnectWizardModal` (presentation) →
`useConnectWizard` (glue) → the unchanged flow engines
(`runOAuthConnect` / `runEdaConnect`).

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
| idle, export-file     | `Choose export file` → hidden `.xml,.net` input → flow                                                                                                                                                                                         |
| busy + `accessModes`  | radio grant choice (descriptions shown, connector default pre-selected) → Continue                                                                                                                                                             |
| busy + `selectable`   | `SelectionPicker` (single dropdown / multi checkboxes; empty multi allowed)                                                                                                                                                                    |
| busy + `configFields` | one input per field; credential-shaped names (key/secret/token/license/password/passphrase/credential) render masked — on-screen hygiene only, real secrets must use SecretStore refs, never `config_fields`; Continue disabled until complete |
| busy otherwise        | spinner + live engine label                                                                                                                                                                                                                    |
| error                 | honest error + Retry (OAuth → `begin()` again; export-file → the file picker again)                                                                                                                                                                                                       |
| done                  | real result ("Connected — N entities indexed") + Done                                                                                                                                                                                          |

## Flows

1. **Tile click** (Sources page catalog / onboarding grid) → wizard opens at
   step 0. Tiles are pure launchers (`ConnectTile`): identity, logo, live
   status footer. Clicking an errored tile reopens the wizard on the error.
2. **OAuth**: Connect → (grant choice if offered) → browser handshake →
   token exchange → pick/enter what to track → sync + poll → done.
3. **Committed export**: Choose file (validated ≤8 MB, non-empty by the
   engine) → parse + sync → done.
4. **Done** → `onConnected` fires (Sources page refreshes its connected list;
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
  visible on the Sources page, where the confirmed Disconnect already lives.
- A flow that **completed successfully anyway** (the handshake finished before
  the abort landed) keeps its source and reports through `onConnected` —
  finished work is never silently discarded.
- Closing on an **error** keeps the error state so the tile stays retryable.
- Closing on **done** just closes.

## Guards (honest, never faked)

- No linked project → tile errors "Solus API unreachable — retry once you are
  back online." without starting a flow.
- OAuth without the desktop bridge → "<name> connect needs the desktop app."

## Files

`connectSteps.ts` (+test) · `integrationLogos.ts` (+test) ·
`ConnectWizardModal.tsx` (+test) · `useConnectWizard.ts` (+test) ·
`ConnectCatalog.tsx` (+test) · `ConnectTile.tsx` (launcher, +test) ·
engine stage emissions in `oauthConnect.ts` / `edaConnect.ts` /
`accessChoiceStep.ts` / `selectionConfigureStep.ts` / `fieldsConfigureStep.ts` ·
`onboardingStore.ts` (`stage`, `clearConnection`) · wizard CSS in
`assets/main.css` (`cw-*`).
