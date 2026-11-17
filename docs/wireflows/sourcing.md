# Sourcing — one panel (SOLUSDEV-246, STORE ST5)

The panel (`features/sourcing/SourcingModal.tsx`, 860px `ModalShell`, dialog "Find a part")
opens from **BOM › Find compatible parts** (`door: bom`). Routes: `docs/api/sourcing.md`.

The renderer's second door, **Workspace › Add › Hardware › Find a sourced part**
(`door: workspace`), is gone with the Add › Hardware panel (SOLUSDEV-326). The backend still
accepts `door: workspace` and the panel still has that mode (the From CAD tab and the robot
select below describe it); nothing in the renderer opens it.

```
┌ ADD A SOURCED PART                                                    ✕ ┐
│ [Describe | From CAD]                                                    │
│ Assembly  [Arm assembly ▾]   (Derive torque from geometry)               │
│ ┌ DERIVED TORQUE ──────────────────────────────────────────────────────┐ │
│ │ Required 8.24 N·m (static 5.49 N·m × 1.5 safety) from Arm assembly   │ │
│ │ · not included: Camera                                               │ │
│ │ • lever arm = horizontal distance from the pivot …                   │ │
│ │ No mass in the graph for these parts — give one (kg): Camera [0.1 ]  │ │
│ └──────────────────────────────────────────────────────────────────────┘ │
│ Anything else [quiet, must speak CAN]   Protocol [CAN]  Voltage (V) [24] │
│ Project rules: 1 excluded supplier · requires RoHS · max 24 V  Edit rules│
│                                                       (Find candidates)  │
└──────────────────────────────────────────────────────────────────────────┘
```

## Requirement step

- **Describe** (default for the BOM door): `Requirement` text, `Load (kg)`, `Arm (m)`, `Protocol`,
  `Voltage (V)`. Load and arm come together or not at all; a bad number is refused inline. Empty
  everything → "Describe the requirement, give a load and arm, or pick an assembly." Nothing is
  submitted.
- **From CAD** (default for the Workspace door): `Assembly` lists the project's parts flagged
  `is_assembly` (honest empty option when there are none). **Derive torque from geometry** →
  `POST …/sourcing/torque`; the card shows the sentence, the assumptions, and names the parts with
  no mass, each with a kg field (typed as text; blanks are left out). Re-deriving with masses
  includes them. Nothing is guessed.
- **Project rules** line: the effective set (`GET …/rules`), `Edit rules` opens the typed editor
  (excluded suppliers as `name: reason; …`, certifications, max voltage, allowed protocols,
  preferred suppliers) → `PUT …/rules`; the line updates from the response.
- **Find candidates** → `POST …/requests` (202) with the form, the assembly/masses when From CAD,
  and the user's `~/.solus/preferences.json` string sections attached as ranking context.

## Searching

"Solus is finding candidates for required 8.24 N·m …" with a spinner; the panel polls
`GET …/requests/{id}` every 1.5 s until the request settles. A failed request shows its typed
message (credits, rate limit, model unavailable) with **Try again**.

## Candidates

A comparison table, one column per included candidate:

- header: name, manufacturer, **CITED** (green, with `source ↗`) or **UNVERIFIED** (amber, no
  price / no stock ever), the trade-off line `Optimises for <x> · gives up <y>`, the rules pass's
  flags in amber (e.g. "Voltage unknown (project maximum 24.0 V)");
- rows: Torque · Price · Weight · Protocol · Voltage · Availability · Supplier · Certifications ·
  Vendor CAD (`<host> ↗`, https only — every model-chosen link shows its destination host) —
  unknown is a dash;
- last row: `Quantity` · **Select <name>** (the Workspace door's robot contains the part; no
  category, SOLUSDEV-326).

Below: **EXCLUDED BY THIS PROJECT'S RULES** — each excluded candidate with the rule text as the
reason. No candidates at all → "No candidate passed this project's rules. Loosen a rule below or
describe the requirement differently." `← Change the requirement` returns to the form.

## Selected

"<name> is planned" — it entered the graph as a planned part (contained by the chosen robot for the
Workspace door); the BOM lists it as PLANNED. **Get vendor CAD model from <host> ↗** opens the cited https URL
in the system browser (no download, no execution); without one: "No vendor CAD model was cited
for this part." **Source another** resets; **Done** closes and the door refreshes (the robot
session reloads; the BOM re-reads its rows).

## Links to other wireflows

- `workspace.md` › Add: the Add modal no longer carries a sourced-part door (SOLUSDEV-326).
- `bom.md` › Header: `Find compatible parts` (ghost) sits between `Export CSV` and `+ Add row`.
