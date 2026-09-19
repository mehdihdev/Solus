## Building with Solus

Solus is the cross-domain workspace for robotics teams — a graph across code, electronics, CAD and
the running robot. The UI is a **dark-first desktop application**: dense, monospace-accented,
engineering-tool feel. Design for that, not for a marketing page.

### Setup: no provider, no wrapper

Components are plain exports — there is **no ThemeProvider or root wrapper to mount**. Everything
visual comes from CSS custom properties defined on `:root` by the stylesheet, so a component is
correctly themed the moment `styles.css` is loaded. At runtime the app re-skins itself by rewriting
those same variables on `:root` (5 themes x 4 accents), which is why nothing below hardcodes a colour.

### The styling idiom: CSS variables, not utility classes

This is the part most likely to be got wrong. Solus components style themselves with **inline styles
that read CSS custom properties**. There is no utility-class vocabulary to compose with (Tailwind is
present in the app but the component surface barely uses it). When you write your own layout and
surfaces around these components, use the same variables:

| Token | Role |
|---|---|
| `--bg` | app background, the page itself |
| `--sur` / `--sur2` | raised surface (cards) / recessed or active surface |
| `--bd` | every border and divider |
| `--tx` / `--mut` | primary text / secondary and label text |
| `--acc` / `--acc-ink` | accent (amber by default) / text ON accent |
| `--ok` / `--warn` / `--err` | success, warning, error |
| `--sw` / `--ee` / `--me` / `--rt` | the four engineering domains: software, electrical, mechanical, runtime |
| `--font-ui` / `--font-mono` | IBM Plex Sans / IBM Plex Mono |

So: `style={{ background: 'var(--sur)', border: '1px solid var(--bd)', color: 'var(--tx)' }}` — never
`#1a1a1a`, never `bg-gray-900`. The domain colours are meaningful, not decorative: use `--sw`/`--ee`/
`--me`/`--rt` (or the `DomainChip` component) whenever something belongs to one of the four worlds.

A few real classes are worth knowing: **`interactive`** on any element makes it read as clickable
(pointer, hover tint, focus ring) without fighting inline styles; `sol-spin` is the spinner
animation; `app-drag` / `app-no-drag` mark window drag regions.

### Composition conventions

- `Mono` is the workhorse label: small, letter-spaced, uppercase-looking section headers and metadata.
  Reach for it before styling a `<span>` yourself.
- `Card` is the surface primitive (`pad` defaults to 16); give it an `onClick` and it becomes
  interactive automatically.
- `KV` for spec/attribute rows, `Field` for labeled inputs, `Segmented` for mode switches,
  `Switch` for booleans, `Button` with `kind` of `primary | ghost | soft | danger | bare`.
- `Icons` is a record of icon components (`Icons.warn`, `Icons.bench`, …), not a component — pass its
  members into icon-shaped props such as `ScreenEmptyState.icon`.
- Density is deliberate: 11–13px body text, 3–4px radii, 1px borders. Don't inflate spacing.

### Where the truth lives

Read `_ds/<folder>/styles.css` and its imports for the real token values and class definitions, and
each component's `<Name>.prompt.md` / `<Name>.d.ts` for its exact API before using it.

### Idiomatic example

```jsx
<Card style={{ width: 360 }}>
  <Mono>PRE-FLIGHT CHECKS</Mono>
  <div style={{ marginTop: 12 }}>
    <KV k="Power budget" v="within limits" vColor="var(--ok)" />
    <KV k="I²C collisions" v="1 conflict" vColor="var(--warn)" />
  </div>
  <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
    <Button kind="primary" size="sm">Re-run checks</Button>
    <Button kind="bare" size="sm">Dismiss</Button>
  </div>
</Card>
```
