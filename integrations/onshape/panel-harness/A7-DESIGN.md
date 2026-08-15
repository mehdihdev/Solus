# A7-01 — Onshape panel: what is built, and the two decisions that gate the rest

Step 0 (the message-capture harness) shipped earlier. This records where step 1 stands now that an
HTTPS origin exists, and why it stops where it does.

## The origin is no longer the blocker

`*.solusforge.com` is issued and live on the ALB, so `panel.solusforge.com` needs only a Squarespace
CNAME and an ALB host-rule when there is something to serve. TLS is verified
(`ssl_verify=0`, `CN=solusforge.com`, Amazon RSA 2048).

## Built

**`external_ref` prefix filter** on `GET /projects/{id}/entities` (`routers/entities.py`).

The panel receives a document id and an element id and nothing finer. Entities are keyed
`{document_id}:{element_id}:{occurrence_path}` (`connectors/mechanical.py`), so
`?external_ref_prefix=docA:elem1:` is the panel's only join. LIKE-escaped and anchored: an
`external_ref` is connector-derived, and an unescaped `%` would return the whole project to a caller
that asked about one document.

## ⛔ Decision 1 — face granularity (yours)

The graph has **no face or edge key**, deliberately: `connectors/onshape_refs.py` explains that
deterministic ids are microversion-scoped and exist inside a single request, which is why they are
never tool arguments. So "user clicks a face → Solus says something about it" has **nothing to join
on**, however cleanly the `SELECTION` payload is eventually captured.

Three ways out, none of which I should pick for you:

| Option                                            | Cost                                                                     | Consequence                                                                                                                                  |
| ------------------------------------------------- | ------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------- |
| **Ingest at face granularity**                    | Multiplies graph rows by 1–2 orders of magnitude; every sync gets slower | Contradicts `onshape_refs.py`'s premise — stored face ids go stale at the next microversion, so rows would need invalidation on every change |
| **Resolve face → part server-side at query time** | One extra `bodydetails` call per click                                   | Keeps the graph as-is and keeps ids request-scoped. Costs a live Onshape round-trip per interaction                                          |
| **Panel points INTO Onshape only**                | Nothing                                                                  | The direction that already works: Solus lists what it knows, highlights it in the viewport. No inbound join needed at all                    |

The third is the only one buildable today with zero unverified assumptions, and it is genuinely
useful — "Solus knows this document and can point at things in your viewport". The first two are
product decisions about what the graph is for.

## ⛔ Decision 2 — session binding (yours; I will not invent an auth path)

The iframe loads inside Onshape with **no Solus session**. Onshape appends `{$userId}`, but that is
an _Onshape_ user id in a query string — it is an identifier, not an authentication, and treating it
as one would be a trivially forgeable auth bypass. So the panel cannot render team-scoped data yet.

What exists that could become a pairing flow, for whoever decides:

- `OAuthState` (`models.py:862-881`) is already the right shape: **authenticated mint → short-lived
  opaque code → unauthenticated redeem that resolves to a user → single-use delete**
  (`routers/integrations.py:183-193`, `:301`). A device-link is that table with `source_id` swapped
  for nothing and the redeem returning a scoped panel token.
- The API accepts **only** `Authorization: Bearer` (`deps.py:52`) — no cookie extractor exists
  anywhere, so an iframe cannot ride an ambient session even in principle. It must hold a token.
- `deps.py:172-185` **auto-provisions** a user, team, subscription and trial credits on first sight
  of any valid token. A panel presenting a token from an unknown user would silently create an
  account. Any pairing design has to account for that.

Until this is decided, the honest v1 renders "Open Solus and link this document" rather than
guessing at identity.

## What step 1 looks like once Decision 2 lands

Outbound-only, and it needs nothing from Decision 1:

1. Extension: Location `Element right panel`, Context `Part Studio`.
2. Action URL carries the ids explicitly — an element right panel receives **none** of them for
   free: `?documentId={$documentId}&workspaceOrVersion={$workspaceOrVersion}&workspaceOrVersionId={$workspaceOrVersionId}&elementId={$elementId}`
   (`{$name}`, not `${name}`; `{$workspaceOrVersionId}`, not the deprecated `{$workspaceId}`).
3. Panel lists parts via `?external_ref_prefix={documentId}:{elementId}:` — the join built above.
4. Clicking a row sends `requestSelectionHighlight` with a `selectionId` the **server** fetched from
   `get_body_details` (`onshape_ops.py`), so no deterministic id is ever held by the browser or
   guessed by a model.
5. Fire-and-forget the highlight; ignore the response. Nothing depends on the undocumented inbound
   payload, which is exactly why this direction is buildable and the other is not.

## Hosting, when it is time

Cheapest path that reuses what exists: an ALB **host-based rule** for `panel.solusforge.com`
forwarding to the same target group, with the API serving the page. That inherits the ALB, the
wildcard cert and the existing health check — no S3, no CloudFront, no second origin to secure.

Two things to get right at that point: the API sets no `X-Frame-Options`/`frame-ancestors` today, so
framing by Onshape works by default but is **unasserted** — it should be asserted deliberately
rather than left to chance. And `SOLUS_CORS_ORIGINS` already includes `https://panel.solusforge.com`
(task definition `solus-api:4`), because the panel is a genuine cross-origin browser caller.
