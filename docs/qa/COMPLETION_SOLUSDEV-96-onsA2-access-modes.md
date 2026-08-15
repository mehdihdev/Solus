# Completion Report — SOLUS-ONS-A2: connect-time access choice

**Status:** built, verified, on `SOLUSDEV-60/ons-a2-scope-choice`. Ends at the per-ticket gate.

## What this is

The customer decides, at connect time, whether Solus gets **read-only** or **read + edit** on their
CAD. Built as a **generic connector capability**, not an Onshape branch — Fusion, SolidWorks and
AutoCAD need exactly the same shape, and nothing in the frontend may branch on a provider id.

## Why a choice at all

An OAuth grant is **account-wide**. I verified this against Onshape's documentation: the scopes are
`OAuth2Read`, `OAuth2Write`, `OAuth2Delete`, `OAuth2Share`, `OAuth2Purchase`, `OAuth2ReadPII`, and
**there is no per-document, per-workspace or per-company grant and no share-with-app mechanism** —
the account UI offers only whole-grant revocation. You asked me to check for per-project scope;
there isn't one, and that is recorded rather than worked around.

So "may Solus edit my CAD?" is a real decision that belongs to the customer.

## The documented reversal, stated plainly

`docs/integrations/onshape-setup.md` §2 previously **forbade** `OAuth2Write`, on a security-review
finding I made last session. That section is now rewritten with the rationale, carrying a marked
note explaining what changed and why — not silently reversed:

> The risk is real and unchanged; what changed is the judgement about how to handle it. Withholding
> write made the read-only product safe and the actual product impossible.

The replacement controls are the ones you named: the customer chooses, `OAuth2Delete` is never
requested, and every write passes the confirmation gate.

**`OAuth2Delete` is deliberately never requested.** It covers destroying documents, workspaces and
elements. Feature deletion and assembly-instance deletion are both `OAuth2Write` — verified by
enumerating every operation in Onshape's OpenAPI spec requiring `Delete` (ten, none of them
features). So it buys nothing and would let a confused agent wipe a customer's document. A test
asserts no declared mode carries a `Delete` scope.

## What was built

- **`OAuthConnector.access_modes`** — declared metadata, `None` by default, surfaced verbatim by
  `GET /api/v1/integrations` beside `selection`.
- **`OAuthConnector.scopes_for(access)`** — resolves a mode to scopes. `None` → the declared
  **default**, never the widest, so an omitted choice can only ever under-grant. An **unknown mode
  raises** rather than defaulting; silently downgrading a typo would connect a source with powers
  the user did not choose, in either direction. The route maps it to `400 invalid_access_mode`.
- `authorize_url` gained `access` on the ABC; GitHub and GitLab ignore it.
- `POST /{provider}/oauth/start` takes an optional `access`; the granted mode is recorded on
  `Source.config["access"]` so "can Solus edit this?" is answerable without re-deriving it from the
  token.
- `docs/contracts/connector-interface.md` — **Edit 8**, documenting the capability the same way
  Edit 7 documented `selection`.

## Verification

- `ruff check .` clean · `mypy` clean over all 10 changed files · **1470 passed, 4 skipped**
  (was 1459) · desktop `typecheck` clean · `env-sync` 14 pass / 0 fail
- 11 new tests covering: both modes declared with `read` as default; write adds edit rights and
  nothing else; no `Delete` scope anywhere; a connector without a choice declares `None`; default
  fallback; unknown mode refused; the authorize URL carrying the chosen scopes; and the catalog
  surfacing it generically.
- `make gen-openapi` re-run; `openapi.json` and the desktop TS types include `access_modes`.

## Not in this ticket

- **No renderer UI yet.** The backend declares and accepts the choice; the connect flow does not
  yet *ask*. Until it does, every connect resolves to the default (`read`) — which is the safe
  direction, and exactly what shipped before. The picker is a small addition to the existing
  onboarding step, and it belongs with A5's confirmation UI work rather than half-built here.
- **No re-consent migration.** Existing Onshape sources keep their read-only grant and keep working;
  a team wanting edit reconnects. Worth a human decision on whether to prompt them.
