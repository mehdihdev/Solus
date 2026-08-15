# Onshape panel message harness (SOLUS-ONS-A7, step 0)

A single dependency-free HTML page that logs **every** postMessage Onshape sends an element
right-panel extension, verbatim, so the inbound contract can be written down from observation
instead of guessed.

**It is not a product and is never shipped to customers.** It exists to be run once, by a human,
against a real Onshape session — the one thing an agent cannot do — and to turn a pile of
reverse-engineered guesses into a recorded fact.

---

## Why it exists

The outbound half of the bridge is documented: Onshape publishes which messages a panel may send.
The inbound half is not. The `SELECTION` push is _mentioned_ three times in the docs with **no
field list published anywhere**, and every field list circulating in blog posts and open-source
Onshape apps traces back to somebody reading Onshape's minified production bundle.

Building against that would be the same failure mode as a tool that returns plausible fabricated
data: it looks right, it is unattributable, and it breaks silently when the vendor reshuffles a
symbol. So this harness asserts nothing about the payloads. It prints them.

## What running it settles

Each of these is currently an open question that blocks design, not implementation:

- [ ] The `SELECTION` payload's actual field list — and whether it carries a usable id at all.
- [ ] Whether the id in a selection message is the **deterministic id** that feature parameters
      take. (Reverse-engineering shows a `getIdString()` call; a separate `getDeterministicId()`
      exists on the same object. These are **not** established to be the same thing, and the whole
      "clicked face → graph entity" idea rests on it.)
- [ ] Whether `SELECTION` fires at all when the extension's Context is Feature / Mate / Part
      rather than Part Studio / Assembly / Document.
- [ ] Whether a selection made **before** the panel opened is replayed on `applicationInit`.
- [ ] `stopRequest`'s reply field: the docs say `stoppedRequestId`, the bundle suggests
      `stoppedMessageId`. One of them is wrong.
- [ ] Whether `requestCameraProperties` is silently dropped for a right panel (expected, unproven).
- [ ] The `onshapeThemeChanged` payload values, and the panel's actual pixel width.
- [ ] Whether any message arrives from an origin other than `server`.
- [ ] The iframe's `sandbox` / `allow` attributes (read from devtools on the parent page).

## How to run

1. Serve this directory over plain HTTP on port 8000:

   ```
   python3 -m http.server 8000 --directory integrations/onshape/panel-harness
   ```

   `http://localhost:8000` is an accepted Action URL — Onshape's own Hello World uses it. (HTTPS is
   required for _redirect_ URLs and for production, not for a local action URL.)

2. Register an extension under an OAuth application (see the human checklist below), with:

   - **Location**: `Element right panel`
   - **Context**: `Part Studio` first, then repeat for `Assembly` and the others
   - **Action URL**, exactly:

     ```
     http://localhost:8000?documentId={$documentId}&workspaceOrVersion={$workspaceOrVersion}&workspaceOrVersionId={$workspaceOrVersionId}&elementId={$elementId}
     ```

   Two traps in that URL, both of which cost real debugging time:

   - The substitution syntax is `{$name}`, **not** `${name}`.
   - It is `{$workspaceOrVersionId}`. `{$workspaceId}` is deprecated.
   - An **Element right panel does not receive document/workspace/element ids automatically.**
     Only `server`, `companyId`, `userId`, `locale`, `clientId` are appended for you. (An Element
     _tab_ extension is the opposite — it gets the ids and supports no substitution. Any README or
     blog post claiming "Onshape passes documentId to the frame" is describing a tab.)

3. Open a Part Studio, start the extension from the right panel, and exercise it:
   select a face, an edge, a body, a feature-tree item, a mate; select something _before_ opening
   the panel; try a **version** rather than a workspace; run a full `stopRequest` round trip.

4. Click **Copy log as JSON** and paste the result into
   `docs/integrations/onshape-panel-messages.md`, alongside which build of Onshape it came from and
   the date. Record what you saw, including anything that contradicts this README.

## Human-only prerequisites

An agent cannot do any of these. They are the real critical path for A7.

- [ ] **Onshape developer access.** Check whether _Developer settings → OAuth applications →
      Create new OAuth application_ is available on the account. If not, request it — lead time
      unknown, and everything else queues behind it.
- [ ] **Decide app ownership.** An app created under Company/Classroom/Enterprise settings is owned
      by the company and consumes **the company's** API limits; one created under My Account
      consumes the user's. This is a billing decision, and ownership transfer later is possible but
      awkward.
- [ ] **Decide: new OAuth app, or an extension on the existing connector app?** Solus already has a
      registered Onshape OAuth application for the CAD-01 connector. Adding an extension to it
      changes what existing connector users see; a second app means a second client id, a second
      secret, and a second consent screen for the same person. Nobody has made this call.
- [ ] **Register the app** — `Type: Integrated Cloud App`. The **Primary format**
      (`com.solus.…`) is **immutable after creation**; choose it deliberately.
- [ ] **Capture the client secret.** It is shown exactly once and cannot be retrieved again. It
      goes straight into AWS Secrets Manager. An agent must never see, receive, or store it.
- [ ] **Run the harness** and commit the captured messages.

## What this does NOT settle, and cannot

**The graph has no face-level join.** Onshape entities are keyed at occurrence granularity
(`{scope}:{occurrence_path}` — see `connectors/mechanical.py`); nothing ingests face or edge
deterministic ids. So even a perfectly-captured `SELECTION` payload does not yet let Solus say
anything about the face a user clicked, because there is no row to join it to.

That is a design question, not a capture question, and it should be settled before anyone builds
the inbound direction: either ingest at face granularity (expensive, and it multiplies the graph),
or resolve face → part server-side at query time, or accept that the panel points _into_ Onshape
rather than reading _out_ of it.

The outbound direction has no such problem — Solus already knows the parts in a given
`document_id:element_id`, and `GET .../bodydetails` gives the server real `selectionId`s to
highlight with. That is why the first real panel should be outbound-only.
