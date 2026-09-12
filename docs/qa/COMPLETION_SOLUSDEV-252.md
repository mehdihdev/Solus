# Completion report — SOLUSDEV-252: SOL S1 · S2 · S3 · S5 (combined)

**Branch:** `SOLUSDEV-252-sol-p1` · **Worktree:** `/home/beeboss/sol_p1` · **Box:** `bee-dgx`, Linux aarch64, X11
**Isolation:** DB `solus_sol_p1` (dump of `solus`, never shared), API `:8100`, desktop dev server `:5273`
(`VITE_DEV_PORT`), Redis `redis://localhost:6379/1`. The other agent's worktree (`/home/beeboss/Solus`,
`:8000`/`:5173`, DB `solus`) was never touched.

Governing docs: DECISIONS.md ADR-016/018/019/026/029/031/034/035/036; `docs/contracts/model-orchestration.md`
(amended, tier-1); `docs/contracts/orb-overlay.md` (unchanged); `docs/api/solus.md`; `docs/wireflows/sol-page.md`;
new tier-1 docs `docs/architecture/sol-window.md` + `docs/wireflows/sol-window.md`. **`docs/design/SPEC.md` is a
GitLab CI YAML committed under the wrong path (commits `eeab469`, `4fa1ce8`) — there is no SOL §5; the ticket
prompt served as the spec.** Plan + Phase 0 report: `~/.claude/plans/sol-s1-cuddly-shell.md` (copied below in
brief).

Decisions taken in-chat (2026-09-07): Ctrl+Space flips the **action mode** `guide|do`, shown as Guide | Build
(ADR-016 Guide/Expert untouched); the native key hook is used wherever its self-test passes, else the
Ctrl+Shift+C circle-mode fallback; routing puts `gpt-6-astra` on both hard cells, `claude-fable-5-1` on
`code_standard`, `gpt-5.6-sol` / `gpt-5.6-luna` on standard / trivial general; Brave is integrated as the
vendored official MCP server (ADR-031 Pattern 1, cloud-side launch).

---

## Phase 0 — audit (no changes)

- **Seeder root cause:** `make seed-secrets` ran `uv run python` from the repo root, whose uv workspace project
  declares no dependencies → `ModuleNotFoundError: No module named 'dotenv'` on any checkout not synced with
  `--all-packages`. Also: no guard for a missing root `.env`; `brave_api_key` never reached the Brave child
  (no `env=` on the catalog entry). `openai_api_key` had never been stored.
- **OpenAI adapter:** Chat Completions, refused every tool conversation → no SOL turn could reach OpenAI.
  `gpt-6-astra` reachable with the key (live `models.list`, 119 models); catalog prices for the 5.6 family
  were stale.
- **I3 (environment detection):** does not exist on any branch.
- **Orb:** removable; the LANE D overlay depends only on the CTR-06 contract through the preload bridge.
- **Platform:** `uiohook-napi@1.5.5`'s `linux-arm64` prebuild is an x86-64 ELF (sha256 identical to
  `linux-x64`; upstream issue #48). This box is that cell.
- **Alembic:** single head `b4c5d6e7f8a9`.

## Phase 1 — S1 (commits `a1a5a72`, `77f4c54`)

Built: `OpenAIAdapter` on the Responses API (function tools, `reasoning.effort`, `max_output_tokens`, no
temperature, `store=false`, `include=["reasoning.encrypted_content"]`, stateless replay of provider items
across rounds, cached-token usage, incomplete responses billed, truncated streams raise, auth errors carry no
key material); catalog/matrix per the decisions with verified prices (OpenAI + Anthropic pages, 2026-09-07;
`gpt-6-astra` window 922K verified; `claude-fable-5-1` $10/$50, cache read $0.25); `providers:` stanza with
`azure` as config only (a catalog entry naming it loads; dispatch raises `UnknownProviderError` until an
adapter exists); SOL runtime routes complexity from the live message (`estimate_from`), "think harder" bumps
one tier and is an explicit override, the model is pinned per turn from round 2; classify preview and the
desktop expose `sol-reasoner-1` + an effort label only (renderer ratchet `noModelNames.test.ts`); seeder:
`uv run --package solus-api`, `.env` guard, `dotenv_values` only (no `os.environ`), `--check`; startup check
logs missing SecretStore refs by name. Tool-name cap 128 → 64 (OpenAI's limit).

Live gate on `:8100` / `solus_sol_p1` (driver: scratchpad `live_sol_turn.py`, user on trial):

| Turn                                         | Route                                                   | Ledger                                  |
| -------------------------------------------- | ------------------------------------------------------- | --------------------------------------- |
| "What is I2C?"                               | `gpt-5.6-luna` / `openai_trivial`                       | −1 credit, 2925 in / 262 out            |
| "Look up the entity named 'adapter'…"        | `gpt-5.6-sol` / `openai_standard`                       | −3, 2928 / 121                          |
| "What is a pull-up resistor?" + think harder | `gpt-5.6-sol` (trivial → standard)                      | −2, 2922 in, **2815 cached** / 250      |
| "Call get_entity with id …" (Do)             | tool call `get_entity` over the Responses API, 2 rounds | −1 / −1, cached 2815 / 2949             |
| spend pinned at the cap (1000)               | —                                                       | SSE `error` `trial_cap`; value restored |

`make seed-secrets` on the fresh worktree stored all four refs (names + lengths only); `--check` exit 0.

Review findings fixed before commit (security C1/H3/H4/M5/M6, python H1): billing on `response.incomplete`,
no zero-usage success, auth-error cause stripped, malformed function_call not replayed, per-turn model pin,
red-team suites register the fake for every routed provider, `test_provider_tools` no longer reaches the network.

Tests: 365 backend tests across the touched files green; desktop `features/sol` 214 green; `pnpm typecheck`
clean; `openapi.json` + `schema.ts` regenerated (`make gen-openapi`).

Delegated-judgment decisions: `claude-sonnet-5` price corrected to $2/$10 (the cancelled increase); role names
`openai_trivial`/`openai_standard`/`anthropic_hard`; cached tokens above the long-context breakpoint bill at
long rates (over-bills, never under — `# ponytail`); `reasoning_effort` is a config-load allow-list.

Human-owed: `.env` typo `SOLUS_OAUTH_REDIRECT_APP=…:5172` (should be `:5273`; harmless here); OAuth redirect
URIs registered with providers do not include `:8100`/`:5273` — connect flows are not exercisable from this
worktree.

## Phase 2 — S2 (streaming)

Built: per-frame token batching in the chat store (`tokenBatcher.ts`: one `setState` per animation frame,
`flushNow` before every non-token event so tool calls, messages and errors never overtake buffered prose,
`setTimeout` fallback without rAF, disposed on cancel), index-based patch of the streaming row, stable
`useSolChat` callbacks, memoised `MessageRow`, two-parse markdown (`markdownSplit.ts`: settled blocks memoised,
only the tail block re-parsed; unclosed fences and half-typed tables held back so a `<pre>` stays one node and
a table never toggles paragraph↔table), citations space reserved while streaming, `content-visibility: auto`
on settled rows (CSS virtualisation, no library). No new dependency.

Measured with `streamBench.test.tsx` (unchanged between runs; jsdom render work, not paint; 2,000 token
events building a 7,335-char markdown reply, median of 3 runs × 3 invocations):

| mode                                    | tokens ms | React commits | MessageRow renders | store notifications | markdown re-parses |
| --------------------------------------- | --------- | ------------- | ------------------ | ------------------- | ------------------ |
| before, sync                            | 38        | 7             | 10                 | 2004                | 1                  |
| before, paced (one token per macrotask) | 10149     | 2006          | 4008               | 2004                | 2000               |
| after, sync                             | 36        | 7             | 3                  | 5                   | 1                  |
| after, paced                            | 31        | 7             | 3                  | 5                   | 1                  |

Isolated render-lane micro-bench (SolMarkdown over the same 2,000 growing prefixes): one-parse 8034 ms →
two-parse 1753 ms. At 60 fps a 6 s stream now costs ≤ ~365 commits regardless of token rate (was one per token).

Reviews: code APPROVE (one LOW: the batcher's in-flight cap drops rather than truncates past 200 000 chars in a
single frame — documented ceiling); TypeScript review: one MEDIUM — `content-visibility: auto` also hides
off-screen settled rows from the accessibility tree; acknowledged in the CSS comment with the upgrade path.
Desktop `features/sol` suite: 29 files / 253 tests green.

Owed to the run-it pass: real-window scroll pinning with skipped rows (jsdom has no layout).

## Phase 3 — S3 (SOL window, hotkeys, on-screen intelligence, gesture, no orb)

Design: `docs/architecture/sol-window.md` + `docs/wireflows/sol-window.md` (tier-1, new). Built in two waves.

**Core (main/preload/API):** `main/platform/capabilities.ts` (the one platform-inspection point; static
degrade table); `main/hotkeys/` (pure Ctrl state machine — double-tap / hold+move / chord passthrough / Ctrl+Space
non-interference — optional `uiohook-napi` loader with a load-time self-test, `globalShortcut` chords with
fallbacks); `main/gesture/` (60 Hz cursor sampler armed only while Ctrl is held, pure circle detector with
sweep/closure/bbox thresholds, 12 % margin region clamped to the display); `main/capture/` (one interface over
`desktopCapturer`, per-OS permission probes, X11 `xprop` active-window via argument lists on a pinned path,
darwin/win32 return null — documented gap); `main/solSettings.ts` (`~/.solus/config.json` `sol` key, atomic
writes, corrupt-file recovery, newer-schema read-only); `main/sol-window/` (window manager: open/focus, persisted
geometry with display-gone reset, always-on-top, queued region delivery until the renderer mounts, sender-gated
IPC on constants only); `main/tray.ts` (mode radio, sees-screen checkbox, hotkeys checkbox, shortcuts line);
`preload/solBridge.ts` (`window.solus.sol`, inbound shape validation). API: `MessageCreate.screenshot` (base64
crop + optional context PNG; caps and magic-byte sniffing in `agent/screen.py`; a VISUAL_LOG extractor pass whose
read is a nonce-fenced `screen` data section; the crop rides the live `Turn.images`; the transcript keeps
`{width, height, app}` only; a hostile screen read is red-teamed).

**Platform facts verified live on this box (Linux aarch64, X11, GNOME + AppIndicator):** the published
`uiohook-napi@1.5.5` `linux-arm64` prebuild is an x86-64 ELF (sha256 identical to `linux-x64`), so
`require()` fails with `ERR_DLOPEN_FAILED` and the loader degrades to the fallback without touching `require`;
`electron-builder install-app-deps` could not detect the N-API prebuild and fell back to a source build that
fails here (`X11/extensions/record.h` missing), so the desktop `postinstall` was removed (`npmRebuild: false`
was already set; the project has no other native dependency) — a clean `pnpm install` exits 0. The app boots
with no exception; the tray registers on DBus (tooltip `SOL · Build`); `Ctrl+Shift+Space` (fallback) opened the
SOL window via XTest; `Ctrl+Space` flipped `guide → do` in `config.json`; geometry was saved on close. Not
exercisable here: the hook path (double-tap Ctrl, Ctrl-hold circle) — needs Linux x64, Windows or macOS with
Accessibility; macOS Screen Recording / Windows branches are unit-tested with fakes only.

Review fixes applied after the core wave: capture-off enforced inside `createScreenCapture` (not only in the
wiring), `sol:state` no longer pushed to extension windows, own-accelerator unregister, complexity splits, 422
`input` redaction across all endpoints, a Content-Length guard on the SOL message route, the context image made an
explicit API field consumed only by the extractor, a hotkeys on/off setting (consent surface for the global key
hook), credit estimate bumped for screenshot turns.

**Renderer wave:** `features/sol/SolWindow.tsx` at `#/sol-window` (header: wordmark + streaming dot, Guide|Build
`ModeBadge`, "sees your screen", pin, close; status line from the hotkey summary and the capture posture; the
`lastRegionRefused` one-liner; the same `SolChat` as the page). `SolChat` (renamed from `OrbChat`) hosts the
region card (crop, `app — title`, "What do you think this is?" which sends a turn with the screenshot attached,
composer placeholder "What would you like to know about it?", attach-once chip with ×). `solWindowStore`
mirrors the bridge state and holds the region in memory only; `solSessionStore` replaces `orbStore`
(one-time read of the legacy key). Deleted: `MiniOrb`, `OrbWindow`, `orbStore`, `solWindowBridge`, `SolOrb`,
`orbPerf.test.tsx` (ratchet carried to `solWindowPerf.test.tsx`), route `#/orb`. Settings → Preferences gains
Action mode (Guide|Build), "SOL sees your screen" (wireflow §D copy verbatim, platform note) and "Hold-Ctrl
gestures"; outside Electron the rows collapse to one note. `ContextPanel` shows the tentative screen read.
`AppRoutes` registers `#/sol-window`. Pixels never reach the `~/.solus` chat cache (asserted); the transcript
row carries `hasScreenshot` only.

**Live gate on this box (Linux aarch64 X11; hook cell unavailable → fallback chords), driven by XTest + CDP with
Chromium as the foreign application:** double-tap Ctrl is unavailable here (documented), `Ctrl+Shift+Space` opened the
SOL window over Chromium at `#/sol-window` (header `SOL · Guide · sees your screen · Pin · ×`, status line naming
circle mode); `Ctrl+Space` flipped `guide → do → guide` (read back from `window.solus.sol.getState()`); in Chromium,
Ctrl+A / Ctrl+C / Ctrl+V kept working (`copy event fired`, `paste event fired`, text duplicated); `Ctrl+Shift+C` then a
circle over Chromium pushed a 142×299 region → the card showed the crop, `@solus/desktop — Electron`, "What do you
think this is?"; clicking it ran the extractor on `gemini-3.5-flash` (VISUAL_LOG, 1 credit) and the reasoning turn
on `gpt-5.6-luna` (1 credit) and streamed a hedged read ("It appears to be a cropped view of the Solus desktop web
app… The screenshot is cropped, so I can't identify … with certainty"); the persisted user turn carries
`{"screenshot": {"app": "@solus/desktop", "width": 142, "height": 299}}` and the API log contains no base64. No orb
anywhere; `#/orb` redirects. With the setting off the loop opened the window with the one-line refusal.

The gate found a real defect: a ≥ 300 ms hesitation mid-loop triggered an evaluation that failed on the half-drawn
stroke and then RESET the stroke, so the two halves never combined. Fixed: a failed pause evaluation keeps the stroke
(bounded by the 10 s window), and closure is measured from the head point nearest the end so an approach segment is
excluded from the loop, its bbox and its sweep; tests added (hesitation, approach segment). A `SOLUS_DEBUG_GESTURE=1`
diagnostic (coordinates only) prints samples and evaluations for QA on other machines.

Decision recorded: **hold-Ctrl gestures default ON** — double-tap Ctrl is the headline summon; the hook observes
only Ctrl/non-Ctrl keycodes and retains nothing; the tray and Settings carry the off switch (the security review
suggested opt-in; kept opt-out with this note). The context image (`screenshot.context`) is consumed by the
VISUAL_LOG extractor only and never reaches the reasoning turn or the transcript.

## Phase 4 — S5a (artifacts, diagrams, error logging)

**`make_diagram`** turns the graph plus the robot's hardware config into a labelled SVG wiring diagram.
`agent/diagram/{model,build,svg}.py` are pure: nodes come from graph entities, wires from wiring-typed
relations and from `bus_map` entries. **A pin is drawn only when the graph or the config names it** —
anything else becomes a dashed "unknown pin" stub, is listed in `unknown_pins`, and is called out in the
legend. Nothing is invented. Every label is XML-escaped; the SVG carries no script or foreign object. The
result is stored through the existing artifact service, so the reference it returns is fetchable by the
artifacts route.

**Filing.** A new `artifact` SSE event carries `{artifact_id, uri, media_type, title, source_tool, summary}`
after a tool result — keyed on both an allowlist and the result shape, and now on the value actually being a
mapping, so a look-alike from another tool can never make the UI fetch something. The renderer's
`ArtifactCard` fetches the bytes through the authenticated client, renders an SVG as an `<img>` from a blob
URL (the SVG text never enters the DOM) and revokes the URL on unmount, then offers "File this to…?" over the
five `.solus` sections. Filing goes through the existing entries route, is idempotent, and shows API errors
inline.

**Error logging.** A tool descriptor gained `files_errors`; when such a tool fails, the runner files one
`.solus` Errors entry with the command, output, entity and timestamp, author `sol`, user-editable.

Review found this **inverted**, and both the security and code reviewers found it independently: filing keyed
on `ok=False`, but a confirmation-gated call that is merely _parked_ also returns `ok=False`. So the only
entries the feature ever wrote were for actions that never ran — filed the moment SOL _proposed_ them, before
any human saw the card, writing model-chosen argv verbatim into a durable team-visible row. The filed text
itself read "This is not a failure". Meanwhile a genuinely failed action after approval filed nothing.
Fixed at the root: `file_tool_error`/`should_file` take an explicit required `executed` flag rather than
inferring execution from a status, the runner derives it from the same `requires_confirmation` the gate parks
on, and the post-approval path in `decide_confirmation` files the real outcome against the stored arguments.
A tool that genuinely returns `UNAUTHORIZED` _after running_ still files — proving the fix is not an
error-code sniff.

## Phase 5 — S5b (SOL acts: `.solus`, the local machine, environments)

**Gated `.solus` writers**: `edit_solus_entry`, `delete_solus_entry`, `set_hardware_config_field` — each
`requires_confirmation` with a Solus-authored consent sentence and a live before/after preview; the hardware
field writes through R5's store with provenance `sol`.

**The `machine` server** is a Solus-owned built-in inside the companion (no third-party code, so ADR-031's
fork gate does not apply; the README says why). Seven tools — run a command, install a package, read and
write files, list and create environments, list packages. Every path is realpath-resolved and confined to the
project workspace, every call is argv-only with no shell, the child environment is scrubbed per OS, output is
capped with a kept tail, and timeouts kill the process **tree**.

Review found the consent card did not show what would run: the allowlist and README promised the exact argv,
but no preview existed, so the approver of an install saw `{manager: "pip", package: "x"}` and never learned
which interpreter it targeted — and a conda command's injected `conda run -n <env>` prefix was invisible.
Fixed: bridge tools opt in through a Solus-owned `supports_dry_run` set (never from the fork's own yaml), and
the preview re-issues the same call with `dry_run: true`, rendering argv, cwd, the resolved interpreter and
each step of a multi-step plan. The companion returns the plan before executing anything; a failing dry run
degrades to argument rows rather than breaking the confirmation.

A second review finding: the child process tree was killed on timeout but **not on cancellation**, so
restarting the companion mid-install orphaned a detached process group that kept writing into the workspace.
Fixed and covered by a real-process regression test.

**Environments** are first-class `.solus` `code` entries: conda, venv, pyenv, system Python and Docker
detected per OS behind one interface with honest degrade, importable, creatable (venv, conda, Dockerfile from
a template) and usable — "install X in the sim env" resolves the environment from `.solus` and runs there.
This is explicitly the minimal layer I3 extends behind the same tool names.

## Phase 6 — S5c (knowledge: Brave, datasheets, layering)

**Brave** is Brave's own MIT server, vendored under `integrations/mcp/brave/` as an ADR-031 Pattern 1 fork but
launched **cloud-side** by the API, because the companion ships no Node. `bin/launch` resolves Node from a
fixed list with zero network at launch; the API key is delivered as a child environment variable at spawn from
the SecretStore, declared by name, and a validator refuses any secret whose ref is not also in
`required_secrets` so key delivery can never outrun the keyless gate. `agent/research.py` is a hard-budgeted
multi-query loop (queries, pages, bytes, seconds) that prefers official and vendor sources, follows the top
hits for full page content, dedupes, and cites what it used.

**`read_document`** fetches a PDF (https only, every resolved address checked against loopback, private and
link-local ranges before connecting, redirects re-checked, size capped while streaming, `%PDF` magic
verified), renders pages with `pypdfium2`, and extracts pinouts, ratings and timing **with page citations**
through the VISUAL_LOG route. Vision proposes: extracted specs are candidates, and turning one into a part
definition is a separate gated tool.

**Context layers** assemble corpus → root `.solus` preferences → project `.solus` → screen capture/region →
conversation, later overriding earlier, each with its own token budget. An absent layer is reported with an
`empty_reason` rather than hidden — honest empty layers, never a stub that pretends.

Review found the research tool had no call site at all and the layers were partly unwired. Both are now wired:
Brave discovery runs request-scoped where the async work belongs, registering nothing when the key is absent
or the server is unreachable, and the runner passes the session and preference/conversation token counts so
every layer the turn actually carries appears in the `context_used` manifest.

## The Phase 5 live gate — what running it for real found

Every gated machine action below was driven end to end through a real SOL turn against the running
API and a connected companion: the model proposed, the card showed the resolved plan, a person
approved, the companion executed. Six defects surfaced that the test suites did not, all fixed and
covered by regression tests.

| # | Found | Fix |
| - | ----- | --- |
| 1 | **The bridge refused every real companion.** `hello` carries the full tool inventory — every advertised tool's JSON schema for every running fork — so with two vendored forks plus the built-in `machine` server it measured 22,531 bytes against a 16,384-byte *control-frame* cap. The socket closed 4400 "update required", blaming a protocol mismatch that did not exist. | `bridge_hello_frame_max_bytes` (256 KB) sizes `hello` apart from the other control frames, and an oversize hello now closes 4413 `oversize_hello` — the honest code. |
| 2 | **The companion tried to launch a cloud-side fork.** It discovered the Brave fork (which the API spawns, and which needs Node ≥ 22 the companion does not ship), failed, and took the bridge down before `hello`. | `launched_by: companion \| cloud \| builtin` on the allowlist; the companion starts only what is its to start. |
| 3 | **The consent card hid the working directory.** `cwd` rendered as `[REDACTED]`: a long absolute path clears every bar of the secret-entropy heuristic, because the path separator is inside its charset. A card that will not say where a command runs is not consent. | Path-shaped values are judged per segment, so a key sitting in a path component is still redacted and the path itself is not. |
| 4 | **A file preview fused its own lines.** The consent-card renderer deleted every non-printable character, so a Dockerfile read `FROM python:3.12-slimWORKDIR /app` — words nobody wrote. | Line breaks collapse to one space instead of vanishing. A row still cannot become two rows, so the forgery it was written to stop is still closed. |
| 5 | **A command that failed filed nothing.** Error logging keyed on the bridge call failing, but a command that runs and exits 1 is a perfectly ok call carrying `exit_code: 1` — which is the only failure Error logging exists to catch. | `run_failure` widens "failure" to a non-zero exit or a timeout; the filed row carries the exit code and the stderr tail. |
| 6a | **A datasheet page came back nearly empty.** `read_document` fetched, rendered and cited correctly, but a dense ratings page yielded ONE proposal ("manufacturer") and no error. The per-page output ceiling was 900 tokens; a reasoning-capable vision model spends most of that before it writes, so the single line it emitted was cut mid-string and dropped — correctly — by the parser. | The ceiling is 6,000, pinned by a test to the 40-proposal roster. The same page now returns five complete proposals, and pages 5-6 of a TI regulator datasheet return fifteen with a candidate part definition. |
| 6 | **SOL could create an environment but not link one** (the S5 sentence says "creates and links"). Nothing but a raw REST call could put an environment into `.solus`. | `link_environment`, gated: the model names which one, every recorded fact is read back from the machine. |

A seventh finding is not a defect but a **handoff blocker**: this OpenAI account is limited to **3 requests
and 10,000 tokens per minute**, and one SOL turn with tools and project context wants ~9,000 tokens per
request. Multi-round turns fail mid-way with `provider_unavailable` no matter how long you wait. Every gate
above was completed by keeping the turn to one round, or by routing to a second model. **A payment method on
the OpenAI account is required before SOL is usable for real work.** Related fix: a provider that will not
answer used to report `internal` ("The SOL turn failed."), which reads as a Solus outage; it now reports
`provider_unavailable` with a caller-safe sentence, and logs the real reason at warning for the operator.

**What ran, live, on this box:**

| Gate | Result |
| ---- | ------ |
| `machine.run_command` (`python3 --version`) | card shows argv + real cwd → approve → exit 0, `Python 3.12.3` |
| A failing command (`import solus_nonexistent_module`) | exit 1 → one `.solus` **errors** entry, `author: sol`, carrying the command, the exit code and the traceback |
| `machine.create_environment` (venv) | real venv at `<workspace>/solus-gate` with `six 1.17.0` |
| `link_environment` | `.solus` **code** CONFIG entry, `author: sol`, observed interpreter / path / python 3.12.3 / packages |
| `machine.install_package` (pip, into the linked env) | resolved that env's own interpreter → `attrs 26.1.0`, exit 0 |
| Re-link after the install | **same entry id**, package count 2 → 3 |
| `machine.create_environment` (dockerfile) | 97-byte Dockerfile written into the workspace, contents shown on the card |
| `read_document` on a public TI datasheet | 15 proposals across two pages, each with a page number and a verbatim quote — output voltage, dropout voltage and peak output current for two part variants — plus a candidate part definition marked "human review required". A first attempt against a dead URL reported the 404 honestly rather than inventing. |

### Security review of the live-gate fixes

A fresh-context security pass over exactly these changes returned one blocking finding, which is fixed:

- **HIGH — a failing command's output reached `.solus` unredacted.** `run_failure` reads the RESULT value,
  and the bridge redacts values only by key name plus single high-entropy tokens; the ERROR channel is what
  gets `redact_text`. A build script that echoes its environment before dying would have written
  `AWS_SECRET_ACCESS_KEY=…` verbatim into a durable, team-visible Errors row that `GET /solus` serves and the
  project context layer replays to the model. Fixed: the filed text goes through `redact_text`, and
  `redact_text` itself was hardened — it now splits on ANY whitespace (a command's output is lines, not one
  space-separated line) and trims a token's surrounding punctuation before judging it, so a secret does not
  survive by sitting inside quotes.
- **MEDIUM — the path relaxation could have hidden a base64 blob** that merely starts with `/`. Fixed: a
  value containing `+` or `=` is judged whole, never per segment.
- **LOW — the companion asserted its own provenance.** `link_environment` now SETS `provenance = sol` rather
  than accepting what the machine claimed.

A second fresh-context pass, on correctness rather than security, found nine more. Fixed:

- **HIGH — the hardened `redact_text` was quadratic.** Trimming a token's punctuation with
  `re.sub(r"^[^C]+|[^C]+$", …)` backtracks from every start position: measured 0.7 s on a 16 KB
  unbroken non-charset run, and this runs over a failing command's whole output, so a CJK build log
  or a progress bar would block the event loop for minutes. Replaced with a two-pointer scan — the
  same 16 KB now takes 0.7 ms, and 1 MB takes 49 ms.
- **A failed step of a multi-step build filed nothing.** `create_environment` runs an ordered build
  and reports each step under `results` with no top-level exit code, so a `python -m venv` that
  failed was invisible — the same silent-miss class the `ok`-only keying was fixed for. `run_failure`
  now walks the steps and names which one failed.
- **A duplicate environment name was first-wins and silent.** A conda env and a workspace venv can
  share a name; linking the wrong one stores it under a different identity, so the next link makes a
  second row instead of updating. `link_environment` now refuses the ambiguity, as
  `resolve_environment` already did.
- **The link preview showed a package COUNT.** The gate compares rendered rows at decision time, so
  an install that left the count unchanged could rewrite every recorded version with no staleness
  refusal. The row now lists package identities and versions.
- **The environments read was pinned by name alone.** It is the one tool handle invoked outside the
  gated dispatcher; it now also requires the descriptor to be ungated, and two new tests cover the
  wiring that nothing exercised before (one of them fails if the guard is removed).
- **A float or boolean `exit_code`** is now handled explicitly rather than silently meaning success.
- **Two tests that could not fail** were repaired: the base64 guard now uses a blob whose every
  segment is under the length bar, so only the guard can catch it, and a stale module docstring that
  still described the old newline-deleting renderer was corrected.

Recorded as ceilings, with reasons:

- **A long RELATIVE path can still redact on a card.** The path exemption is anchored to an
  absolute, `~`, `./` or drive prefix. Widening it to "contains a separator" would exempt any
  slash-bearing blob, which is the bigger hole; the upgrade path is a real secret detector, not a
  looser shape rule. Named in a `ponytail:` comment at the rule.
- **A slow machine makes a link unapprovable.** `link_environment`'s preview is a full detection
  scan behind the 10 s preview budget; a scan that straddles it only at decision time degrades to
  argument rows, which never match the stored rows, so the approval fails as stale every time. This
  is the generic bridge-preview timeout, not specific to linking, and the fix is a cheaper scan.
- **Whitespace-only changes do not trip the staleness gate**, because rendered rows are compared
  after flattening. This is not new — deleting newlines collided strictly more.
- **`link_environment` is registered inside the artifact-store branch**, so an unset store removes it
  with no log line, indistinguishable from "no companion".
- **`edit_solus_entry`'s preview does not check the entry kind**, so an artifact or config entry can
  be approved and then refused at execution.

Three LOW findings are recorded rather than changed, with reasons:

- **`link_environment` is time-of-check/time-of-use.** It reads the machine when the card is built and again
  when it is approved. That is the gate's design, not a bug: the decision path re-runs `preview` and refuses
  as STALE when the rows moved. The visible consequence is that installing a package between proposing a link
  and approving it invalidates the card, which is the correct answer to "you approved something else".
- **"Bridge offline" files an Errors row.** A gated machine call approved while the companion is disconnected
  fails `UNAVAILABLE` and files. Suppressing it by sniffing that code is exactly the lie `should_file`'s
  docstring rejects — a tool that refuses AFTER running must still file, and both cases share the code. The
  honest fix needs the companion to distinguish them, which is a protocol change, not a patch.
- **The `.invoke(` seam is timeout-bounded** on both paths (the registry wraps the handler, `_build_preview`
  wraps the preview), so the "unbounded call" concern does not hold; recorded because the seam is worth
  re-checking whenever either wrapper changes.

Out of scope but re-raised by the reviewer and still true: `research` has no per-team budget and every tenant
shares one `brave_api_key` (ADR-019 is the named upgrade path; it is in the Phase 6 notes above).

**Doc amendment needing sign-off**: `docs/contracts/bridge-protocol.md` §6 said every control frame is
capped at 16 KiB. `hello` now has its own 256 KiB bound, because it is the only frame whose size follows the
deployment (every allowlisted tool of every running server, schemas included) rather than a message. The
amendment is marked in place. Nothing else in the contract changed; the socket is authenticated and
team-scoped before that frame is read.

**Environment the operator must set**: `SOLUS_NODE_BIN` (absolute path to a Node ≥ 22) in the API process
wherever `node` is not at `/usr/bin/node` — an nvm install is the common case. Without it the Brave fork
refuses to launch and research degrades to no web tools.

## Portability report

| Capability                            | Win x64 / arm64                  | macOS x64 / arm64                     | Linux X11 x64     | Linux X11 arm64                                  | Linux Wayland                        |
| ------------------------------------- | -------------------------------- | ------------------------------------- | ----------------- | ------------------------------------------------ | ------------------------------------ |
| Chord hotkeys (Ctrl+Space, fallbacks) | CI-built, unrun                  | CI-built, unrun                       | unrun             | **live**                                         | unavailable by design, message shown |
| Double-tap Ctrl / Ctrl-hold circle    | prebuild ships                   | prebuild ships, needs Accessibility   | prebuild ships    | **prebuild is broken upstream → fallback, live** | unavailable, fallback                |
| Screen capture                        | table-tested                     | table-tested (needs Screen Recording) | table-tested      | **live**                                         | disabled with a message              |
| Tray                                  | table-tested                     | table-tested                          | table-tested      | **live**                                         | same                                 |
| Active window title                   | not implemented (documented gap) | not implemented (documented gap)      | `xprop`, **live** | **live**                                         | unavailable                          |
| Environment detection                 | table-tested (`py -0p`, `where`) | table-tested (Homebrew, framework)    | table-tested      | **live, 39 environments**                        | n/a                                  |
| Command / install execution           | table-tested (`taskkill /F /T`)  | table-tested                          | table-tested      | **live**                                         | n/a                                  |
| PDF rendering (`pypdfium2`)           | wheel exists                     | wheel exists (13.0)                   | wheel exists      | **live**                                         | n/a                                  |
| Brave fork (Node ≥ 22)                | image-built                      | image-built                           | image-built       | **live**                                         | n/a                                  |

**Verified live on this box only** (Linux aarch64, X11): every cell marked live above. Everything else is
covered by per-OS code behind one interface with fake filesystem and subprocess tables, and degrades with a
plain-language message rather than failing. **No native dependency lacks a prebuild for a target we ship**:
the only native module, `uiohook-napi`, is an `optionalDependency` whose absence costs the hold-Ctrl gesture
and nothing else — and its published `linux-arm64` prebuild is a mislabelled x86-64 binary, which is exactly
why the fallback path exists and is the one exercised here. `pypdfium2` has wheels for all six targets. The
desktop `postinstall` was removed because `electron-builder install-app-deps` cannot detect an N-API prebuild
and fell back to a source build that fails on this box; `npmRebuild` was already false and no other native
dependency exists.

**Unverified anywhere**: the native key hook's actual event delivery (no machine here can load it), the
Windows `taskkill` timeout path, macOS Accessibility and Screen Recording prompts, and Wayland's portal
behaviour. These are the Cowork QA matrix's job.
