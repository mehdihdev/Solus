# Wireflow — BOM (SOLUSDEV-246, STORE ST4)

The BOM tab: every part in the robot, raw materials and anything purchased, as ONE view over
canonical parts. A first-party page rendered in-repo (`features/bom/`, mounted by the shell for
an installed `bom` — `extensions-runtime.md` §2), over the bundle's own routes
(`docs/api/widget-bundles.md` §11). Requires an EDA or CAD source; installed from the Store like
any extension (`store.md`), suggested in context when the first EDA/CAD tool connects.

```
| rail  | ← BOM  by Solus ✓                         [ Export CSV ] [ + Add row ] |
|       | 3 rows · 1 priced · total $29.00 · within target $250.00              |
|       | Preferred suppliers: Mouser, Digi-Key · USD · cost target $250.00     |
|       | ------------------------------------------------------------------- |
|       | Part                    Kind      Qty  State       Supplier  Unit   Line |
|       | MG996R                  DESIGN      1  Installed ▾  —        —      —   |
|       |   TowerPro                                                          |
|       |   electrical: U3 · mechanical: Servo body                           |
|       | RC0402FR-0710KL         DESIGN      2  Installed ▾  —        —      —   |
|       | NEMA 17 stepper         PURCHASE    2  Planned ▾    Stepper… $14.50 $29 |
|       |   Remove                                                            |
|       | 6061-T6 plate 3 mm      RAW MATERIAL 4 Planned ▾    —        —      —   |
```

## Header

- The shared page header (`PageHeader`): `← Back` · name `BOM` · verified mark · `by Solus`.
- Right: `Export CSV` (ghost) and `+ Add row` (primary). Both only while the view is `ready`.
- `Export CSV` reads `GET …/widgets/bom/export.csv` with the session and hands the bytes to the
  platform as `bom-<project name slug>.csv` (a blob download; Electron shows the OS save dialog).
  A failure shows inline next to the buttons; nothing is invented.

## Totals and configuration line

- `N rows · M priced · total <sum>` and, when a cost target is configured, `within target <t>` /
  `over target <t>`.
- Muted: `Preferred suppliers: …` (or "No preferred suppliers set") · currency · `cost target <t>`
  / "no cost target". These are CONFIGURATION, not data: the bundle's settings (Store › BOM ›
  Settings: `preferred_suppliers`, `cost_target`, `currency`) or the team's `[ext.bom]` table in
  the repo's `.solus/project.toml`, layered manifest ← repo ← install settings.

## The table

One `<tr>` per physical part (`aria-label` = the row name):

- **Part**: name (the part number when one is known, else the value, else the tool's name) ·
  manufacturer (muted) · `sources` line `"<domain>: <name> · …"` for design rows — where it was
  observed (a fingerprinted servo lists `electrical: U3 · mechanical: Servo body` on ONE row) ·
  notes.
- **Kind**: `DESIGN` · `PURCHASE` · `RAW MATERIAL` (mono).
- **Qty**: placements for a design row; the item's quantity otherwise.
- **State**: a `<select>` (`Lifecycle state of <name>`) over the R5 states `Planned · Ordered ·
  Received · Installed · Retired`, coloured warn/accent/ok/muted; changing it PATCHes the row and
  re-reads the view. A design row's state (and supplier, cost, notes) is an overlay the design
  never sees.
- **Supplier · Unit · Line**: `—` when unknown, money in the configured currency.
- **Remove** on item rows only (design rows come from the tools and are never removed here);
  confirms in a small modal ("Remove <name> from the BOM? Parts from your tools are never removed
  here; this row was added by hand.") → soft-delete.

Order: design rows, then purchases, then raw materials, each by name.

## Add row (`+ Add row`)

Modal `Add a BOM row` (420px): "Something the design does not know about yet — a purchase being
sourced, or a raw material. Parts already in CAD or the schematic list themselves." Fields:
`Name` (required) · `Category` (Purchase | Raw material) · `Quantity` (whole, ≥ 1; default 1) ·
`Unit cost` (≥ 0) · `Part number` · `Supplier`. `Add to BOM` POSTs; a refusal (viewer role, a
server validation) shows inline and keeps the dialog open; success closes it and the new row is
in the table in the `planned` state. Asking SOL ("add a planned NEMA 17 to the BOM") does the same
through `bom.add_item`.

## States

- `loading` — "Loading the BOM…".
- `ready`, empty — "No parts yet. Connect a CAD or EDA source and sync it, or add a purchase or raw
  material with Add row." (an empty project is an empty BOM, never a sample one).
- `ready`, truncated — a note: "This project has more parts than the BOM can list at once; the rows
  below are a bounded subset."
- `not_installed` (the routes answer 404: not installed, disabled or team-blocked here) — "BOM
  isn't installed in this project." + `Open in Store`.
- `offline` — "Solus can't reach Solus right now." The view re-reads every 10 s while ready; a
  failed refresh keeps the rows already on screen.

## What is honest about identity

The BOM merges rows ONLY on the fingerprint's `canonical_part_id` and confirmed `same_as` links
(ADR-012 zero-false-merge). Two parts that merely share a part-number string across CAD and the
schematic stay two rows; identical part numbers within one domain aggregate into a quantity.
