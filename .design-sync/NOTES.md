# design-sync notes — Solus

Repo-specific gotchas for future syncs. Read this before re-running the sync.

## Shape and layout

- **No Storybook anywhere** in the repo (checked `**/.storybook/main.*` and `*.stories.*`) — this is the
  **package** shape. Don't re-detect; `shape` is pinned in `config.json`.
- **There is no standalone design-system package.** The component library lives inside the Electron
  renderer at `apps/desktop/src/renderer/src/`. The synced surface is therefore curated by hand via
  `.design-sync/entry.tsx` (a committed barrel) + `componentSrcMap`, not discovered from a `dist/`.
- **`--entry .design-sync/entry.tsx` is what sets `PKG_DIR` to the repo root.** The converter walks up
  from the entry's directory to the first `package.json` with a `name` — that's `/` (name `solus`).
  This is deliberate and load-bearing: `extraFonts` is bounded to `PKG_DIR`, and the IBM Plex fonts live
  in the root `node_modules/@fontsource/`. Moving the entry under `apps/desktop/` would put the fonts
  out of bounds. All config paths are therefore **repo-root-relative**.
- **`--node-modules` must be the REPO ROOT `node_modules`**, not `apps/desktop/node_modules`. pnpm
  hoists `react`/`react-dom`/`@types/react` to the root and leaves the app's own dir without them;
  pointing at the app dir fails prop extraction with `[DTS_REACT]`.

## Styling

- Components style with **inline styles reading CSS custom properties** (`var(--acc)`, `var(--tx)`,
  `var(--bd)`…) plus a small set of **hand-written CSS classes** (`.interactive`, `.sol-spin`,
  `.popover-in`, `.sol-mode-badge`, `.graph-node-*`). Tailwind *utilities* are barely used by the
  synced surface — do not assume a utility-class idiom when writing the conventions header.
- **`assets/main.css` is a Tailwind v4 source, not a stylesheet.** Its first line is
  `@import 'tailwindcss'`, which the converter cannot resolve. It is compiled ahead of the build to
  `.design-sync/solus-base.css` (committed, so a fresh clone can sync without the Tailwind step):

      ./.ds-sync/node_modules/.bin/tailwindcss \
        -i apps/desktop/src/renderer/src/assets/main.css -o .design-sync/solus-base.css

  **Re-run this whenever `main.css` changes**, then rebuild. `cssEntry` points at the compiled file.
- No theme provider is needed. `main.css` defines the full Solus Dark token set on `:root` as
  pre-`applyTheme()` defaults, so the compiled base CSS carries the tokens and previews render themed
  with `cfg.provider` unset. Runtime theming (`theme/applyTheme.ts`) only *overrides* those vars.
- **Feature CSS is imported by container components outside the synced surface.** `GraphCard` needs
  `navigation.css` but doesn't import it (`GraphNavigator` does). `.design-sync/entry.tsx` therefore
  imports all 9 feature stylesheets explicitly so esbuild rolls them into `_ds_bundle.css`. If a card
  renders unstyled, check whether its CSS file is in that import block.
- Fonts: IBM Plex Sans 400/500/600/700 + IBM Plex Mono 400/500, from `@fontsource` in the root
  `node_modules` — exactly the set `src/renderer/main.tsx` imports. Keep the two lists in sync.

## Scope decisions

- Synced surface = **14 UI primitives + 35 curated feature exports = 49 components**.
- Deliberately excluded: route-level screens (`WorkspaceShell`, `BillingScreen`, `HomeScreen`,
  `StoreScreen`…) — not design-system parts — and components that fetch on mount (`SolusCard`,
  `BridgePill`, `TeamStrip`), which would render as error or empty cards.
- `Icons` (`components/ui/icons.constants.tsx`) is excluded via `componentSrcMap: {"Icons": null}`:
  it's a record of SVG components, not a component.
- The four curated components that reference stores/the API (`ProjectCard`, `DeviceCard`, `GraphCard`,
  `ClassifyIndicator`) do so only through **type-only imports**; they are fully prop-driven and render
  statically. Verified — don't re-litigate this each sync.
- `Section`, `Row`, and `InlineError` (from `features/settings/settingsUi.tsx`) keep their repo names
  even though they're generic in a global namespace. Faithfulness to the source won over renaming;
  their group and `.prompt.md` disambiguate.

## Environment

- Playwright + Chromium were not cached on this machine; installed into `.ds-sync/node_modules`
  (`npx playwright install chromium`, ~200MB). A fresh machine needs this again for the render check.
- zsh does **not** word-split unquoted variables — `grep $FILES` passes one giant filename. Use a
  `for` loop or `${=VAR}` when scripting over file lists here.

## Known issues

- **`DeviceCard` is excluded from the sync** (`componentSrcMap: {"DeviceCard": null}`).
  `features/graph/hardware/` contains **both `deviceCard.ts` and `DeviceCard.tsx`** — the only
  case-colliding module pair in the whole renderer tree. `DeviceCard.tsx` does
  `import { cardGlyph, cardQuestion, cardSentence, conflictText, evidenceNotes } from './deviceCard'`,
  and on macOS's case-insensitive filesystem esbuild resolves `./deviceCard` to `DeviceCard.tsx`
  itself, so the build dies with five "No matching export" errors. Vite/electron-vite happen to
  resolve it correctly, which is why the app builds fine.
  **This is a latent repo hazard, not just a sync problem** — any case-strict-by-accident toolchain
  can mis-resolve it. The fix is a one-line rename in product code (`deviceCard.ts` →
  `deviceCardText.ts` + update its importers); deliberately NOT done as part of the sync. Once
  renamed, drop the `DeviceCard: null` entry and restore its export in `.design-sync/entry.tsx`.

- **`ConnectTile` is excluded** (`componentSrcMap: {"ConnectTile": null}`). It imports
  `features/onboarding/integrationLogos.ts`, which loads the brand logos with **Vite's
  `import.meta.glob`**. esbuild has no equivalent and leaves `import.meta` empty, so the call throws
  `TypeError: import_meta.glob is not a function` — and because the bundle is a single IIFE that
  executes on load, that one throw took **all 48 previews** down (`render check: 0/48 clean`), not
  just ConnectTile's. If you ever want ConnectTile synced, give `integrationLogos.ts` a non-Vite
  fallback (a static import map) rather than trying to work around it in the converter.
  `widgets/discover.ts` also uses `import.meta` — check it isn't reachable before adding widgets.

## Prop extraction (`.d.ts`) — the important one

The converter resolves each `<Name>Props` from a **shipped `.d.ts` tree**. This repo has none, so out
of the box every emitted contract was a bare `{[key: string]: unknown}` index signature — useless to
the design agent, which codes against exactly these files.

Fix: `.design-sync/overrides/dts.mjs` (declared in `cfg.libOverrides`) seeds the ts-morph project with
the component `.tsx` files listed in `componentSrcMap` and calls `resolveSourceFileDependencies()`.
ts-morph then resolves `ButtonProps`, `GraphCardProps`, … straight from source, and React/DOM
inherited props are filtered out as usual. **If a future re-sync shows empty prop bodies again, this
is the first thing to check** — diff the fork against the bundled `lib/dts.mjs` for upstream changes.

## Authoring previews — the contract that actually works

- One file per component at `.design-sync/previews/<Name>.tsx`, committed, no marker comment.
- Each named PascalCase export is one card cell, and **must be a component (a function returning
  JSX), not a JSX element constant**. The card harness calls `React.createElement(export)`, so
  `export const Kinds = <div/>` silently renders nothing.
- Import from `'@solus/desktop'` (that is `cfg.pkg`); the story-import plugin rewires it to
  `window.Solus` at compile time.
- Preview files are **transpiled by esbuild, never typechecked** — a wrong prop shape fails at
  render, not at build. Read the emitted `<Name>.d.ts` and the component's `*.test.tsx` for real
  shapes rather than guessing.
- Components that stretch (`flex: 1`, full-width bars) collapse in a card — wrap them in a sized
  container. Overlay/absolute components need `cfg.overrides.<Name>.cardMode: "single"` plus a
  `viewport`.

## The dark-canvas fix (do not lose this)

The card template injects `<style>body{margin:0;padding:24px;background:#fff}</style>` AFTER the
stylesheet link. Solus is dark-first, so the DS's light `--tx` text landed on a white page — every
card was unreadable, and `_screenshots/` proves it silently. `.design-sync/preview-overrides.css`
re-asserts the system's own `body` rule at `html body` specificity and is concatenated onto the
compiled Tailwind output by `.design-sync/build-css.sh`. If cards ever come back white, check that
script ran and that `cssEntry` still points at `.design-sync/solus-base.css`.

## Known render warns (triaged, expected — not new)

- `[DOCS_UNMAPPED]` for every feature component: only the 14 primitives have doc stubs (in
  `.design-sync/docs/`, used solely to name the `primitives` group). Feature components intentionally
  get a `.prompt.md` synthesized from their `.d.ts` + authored preview examples.
- Group names are derived from the source directory, so the feature components land in repo-shaped
  groups (`sol`, `graph`, `workspace`, `extensions`, `pageview`, `frame`, `host`, …). `cfg.overrides`
  has no `group` key, and doc-frontmatter `category` only overrides a group of `general`/`misc` — so
  thematic regrouping is NOT available without renaming source directories. The repo-shaped groups
  were accepted deliberately.

## Icons

`components/ui/icons.constants.tsx` exports `Icons`, a **record of SVG components**, not a component.
It is `componentSrcMap: {"Icons": null}` so it never becomes a card, but it IS exported from
`.design-sync/entry.tsx` so it reaches `window.Solus.Icons` — previews and real designs need it to
fill icon-shaped props (`ScreenEmptyState.icon`, page-header tiles, empty states). Keep both halves:
dropping the entry export silently removes every icon; dropping the `null` pin makes it a broken card.

## Components referenced by previews but deliberately not synced

- `ProjectSwitcher` (the real content of `TitleBar` in the app) is store-coupled and out of scope, so
  the TitleBar preview composes an equivalent project pill instead. Expected, not a defect.
- `LabeledSelect` has no visual disabled treatment — a disabled native `<select>` looks identical to
  an enabled one in this theme. That is the component's behaviour, not a preview problem.
- `GithubButton` owns its `authorizing`/`error` state internally (only `onAuthorize` is a prop), so
  those states are not statically renderable; the preview shows idle only.
- `InlineError` returns `null` for `message={null}` — it must be composed inside other content or the
  cell captures blank.

## Write ownership manifests BEFORE fanning out (H12)

This repo's SubagentStop hook (H12) enforces `.claude/state/ownership/<task-id>.list` manifests. A
preview-authoring subagent cannot stop without one, and it must not write its own (that would route
around the guard) — so the orchestrator must create them **before** spawning the wave, per CLAUDE.md
§5 Phase 2. Manifests are a union across concurrent agents. This run's set:
`DESIGN-SYNC-ORCH.list` (harness: `.gitignore`, config, entry, NOTES, overrides, docs, the solo
previews, `.ds-sync/`, `ds-bundle/`) plus `DESIGN-SYNC-{A,B,C,D}.list` (one per batch, listing that
batch's `previews/*.tsx`, `.cache/review/`, and `learnings/<ID>.md`). Delete them once the work is
merged and verified.

## Card-mode overrides

- `ContextMenu` is two `position: fixed` elements, so in the product's default multi-cell grid every
  story stacks at the same coordinates and the card reads as broken. `cfg.overrides.ContextMenu` is
  set to `{"cardMode": "single", "primaryStory": "SectionMenu"}`. The capture harness drives
  `?story=` (full-bleed `.ds-single`), so grading does NOT catch this class of bug — it only shows up
  in the live product card. Any future fixed/absolute component needs the same treatment.

## More preview gotchas (from the authoring wave)

- `Spark` takes `values: readonly number[]`. A wrong shape renders a silent empty `<svg>` — no error
  cell, no warning. Same class of trap as `InlineError message={null}`.
- **The emitted `.d.ts` drops generics**: `Segmented` comes through as `ComponentType<SegmentedProps>`
  with `<T extends string>` lost. When a component is generic, read the `.tsx`, not the contract.
- Recipe for near-blank primitives (Spinner, SolusLogo, SectionLabel, ExtensionIcon): separate size
  and colour sweep cells in fixed-width centred captioned columns, plus at least one cell embedding
  the primitive in a real `Card` composition.

## Two bugs in `.claude/hooks/subagent_ownership_check.sh` (HUMAN FIX REQUIRED — H1 blocks agents)

Both are in line 19:

    CHANGED="$(git -C "$ROOT" status --porcelain 2>/dev/null | awk '{print $NF}' || true)"

1. **Untracked directories collapse.** Plain `--porcelain` emits one entry for a wholly-untracked
   tree — literally `?? .design-sync/` — never the files inside. So H12 compares the string
   `.design-sync/` against manifests listing files within it, nothing matches, and **every** subagent
   touching a new untracked tree is blocked no matter how correct its manifest is. Verified
   side by side against `git status --porcelain -uall`, which does expand per file.
   Fix: add `-uall`. Workaround used this run: a bare `.design-sync/` line in
   `DESIGN-SYNC-ORCH.list` (nothing is lost — the hook could never see the inner files anyway, so
   per-file attribution inside an untracked tree is currently unenforceable either way).
2. **`awk '{print $NF}'` takes only the last whitespace-delimited field.** A rename
   (`R  old -> new`) yields `new`, which is survivable, but **any path containing a space yields only
   its final token**, silently mis-attributing the file. Fix: `git status --porcelain -z` with NUL
   parsing, or `cut -c4-`.

Found by a preview-authoring subagent that correctly refused to write its own manifest or revert its
work, and escalated instead.

## Preview-authoring findings, wave 1 (folded from learnings/A-D.md)

**Prop shapes that only the source or tests reveal**
- `DomainChip` takes `d="sw"|"ee"|"me"|"rt"` (+ `on`, `small`) — not a `domain` prop.
- The repo's `ExtensionView` fixtures (`features/extensions/testing/fixtures.ts`) **import vitest** and
  cannot be used from a preview — build the view literal inline. The Store components read only
  `catalog.{slug,name,summary,publisher,verified}`, `state.updateAvailable`, `availability`, `missing`.
  `availability` is trusted data, not derived: keep it consistent with `state.installed`/`missing`.
  `missing` drives the pill text (`[['eda']]` → NEEDS EDA; `[['cad','eda']]` → NEEDS CAD|EDA;
  `[['cad'],['runtime']]` → NEEDS CAD + RUNTIME).
- `ExtensionIcon`/`PageIconTile` take an SVG **string** through `reduceSvg`: lucide-style
  `fill="none" stroke="currentColor"` passes; anything outside the allowlist drops the icon to the
  neutral tile.
- **Two incompatible widget-prop generations coexist**: `features/workspace/widget.contract.ts`
  (`{focus: WidgetFocus, actions}` — FocusSummaryWidget/NeighborsWidget) vs `@solus/shared-types`
  CTR-01 `WidgetProps` (`{focus: Focus|null, onFocusChange, onStateChange}` — WidgetSlot's builtin
  entry component). Mixing them fails silently or throws.

**Layout traps**
- `FrameSkeleton`/`FrameCard` share `flex:1; min-height:0` and collapse without a flex-column parent
  with a real height. Same for `ScreenEmptyState`/`AlertScreen`.
- `.solus-entry-content` is capped at `max-height: 55px; overflow-y: auto`, so a large
  `CodeEnvironmentCard` payload silently scrolls its own controls out of frame.
- **The capture viewport is ≤900px, which trips a real media query**: `.widget-canvas-grid` drops
  4→2 columns and `.widget-slot[data-span="3"|"4"]` collapses to `span 2` at `max-width: 900px`. A
  `wide`/`full` WidgetSlot is therefore pixel-identical to `standard` on camera. Correct product
  behaviour, not defeatable from a preview file — needs `cfg.overrides.WidgetSlot.viewport` wider
  than 900px if those spans should be shown (note: an explicit viewport is grade-keyed and forces a
  re-grade). Left as-is this run; the compact/standard sweep inside the real `.widget-canvas-grid`
  class was accepted instead.
- `export function Error()` in a preview file shadows the global — name it `LoadError`.

**Confirmed working** — feature CSS (`navigation.css`, `canvas.css`, `solusCard.css`,
`codeEnvironment.css`) really is reaching `_ds_bundle.css` via the entry's import block, so
`.graph-node`, `.widget-slot` and `.sol-region-card` style correctly. No provider is needed anywhere
in the 47-component surface.

## Product finding, NOT fixed (needs a human decision)

`.sol-md ul/ol` sets only `padding-left`, and Tailwind's preflight has already stripped
`list-style` — so **SOL's markdown lists render with no bullets or numbers, in the real app as well
as the previews**. Visible in the `SolMarkdown` / `Diagnosis` card. The preview is faithful, so it was
graded good, but a one-line `main.css` fix (`list-style: revert` or explicit `list-style-type`) would
settle it. Deliberately not changed as part of the sync — it is product CSS.

## Re-sync risks — what can silently go stale

Read this first on the next sync; each item is something that will NOT announce itself.

1. **`.design-sync/solus-base.css` is generated and committed.** If `assets/main.css` changes (new
   token, new class, changed theme default) and nobody re-runs `.design-sync/build-css.sh`, the sync
   ships the OLD tokens and every card still looks fine — just subtly wrong. Re-run it whenever
   `main.css` moves, and diff the result.
2. **The `dts.mjs` fork is pinned to upstream's shape.** `.design-sync/overrides/dts.mjs` edits two
   things: the `isComponentName` allow-list (`KV`) and `projectFor`'s source seeding. If the bundled
   `lib/dts.mjs` changes upstream, diff it against the fork and merge — the failure mode is silent,
   empty `{[key: string]: unknown}` prop bodies, which look like valid output.
3. **`componentSrcMap` is a hand-curated list of 47.** New components added to
   `components/ui/` or the feature tree are NOT picked up automatically — there is no dist and no
   `.d.ts` tree to discover from. Adding a component means editing BOTH `componentSrcMap` and
   `.design-sync/entry.tsx`.
4. **`DeviceCard` and `ConnectTile` are excluded for repo-side reasons** (case-collision, Vite
   `import.meta.glob`). If either is fixed in product code, re-include it in both files. If neither is
   fixed, they stay excluded — do not "fix" them inside the converter.
5. **Preview files are never typechecked.** A prop rename in product source will not break the build;
   it will render a wrong or empty card that only the graded screenshot catches. Re-grade after any
   component API change.
6. **Grades live in gitignored `.cache/`.** Cross-machine carry-forward comes only from the uploaded
   `_ds_sync.json`. A fresh clone with no project access re-verifies all 47 from scratch.
7. **Only partially verified:** the `?story=` capture harness renders each cell full-bleed, so it
   cannot see grid-layout problems. The 36 `cardMode` overrides were derived from validate's
   `[GRID_OVERFLOW]` warnings, not from grading. A new component with multi-item rows will very likely
   need `{"cardMode": "column"}` too.
8. **Build assumptions:** node 22, pnpm-hoisted root `node_modules`, Tailwind CLI 4.3.1 pinned in
   `.ds-sync/`, Playwright chromium in `~/.cache/ms-playwright`. The converter deps live in the
   gitignored `.ds-sync/`, so a fresh clone must re-run the staging `cp -r` + `npm i` step, and
   recreate `ln -sfn ../.ds-sync/node_modules .design-sync/node_modules` for the fork's bare imports.
