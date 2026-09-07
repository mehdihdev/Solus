# COWORK QA — STORE ST5: Sourcing, one engine for two doors (SOLUSDEV-246)

Written for Claude Cowork. You have the running application and this file, nothing else.
Mark each path PASS / FAIL and note what you saw.

## 0. Required setup state

- Solus desktop running against an API that has: PostgreSQL migrated to head (`sourcing_requests`
  table, `jobs.kind` accepts `sourcing`), Redis (or `SOLUS_SYNC_INLINE=true`), an Anthropic key
  seeded in the SecretStore (live model calls happen), and an ARQ worker when Redis is used.
- A signed-in user who is a **member** (not viewer) of a team with one project, call it **Project A**.
  A second user in a different team with **Project B** (for the isolation check).
- Project A has:
  - the **BOM** widget installed (Store › BOM › Install) so the BOM tab is in the rail;
  - a **Physical Robot** (Workspace › Add › Hardware › Add Physical Robot) so the seven categories exist;
  - a CAD **assembly** with at least two child parts that carry masses and placements, and one child
    part with **no mass**. If no CAD source is connected, ask an engineer to seed one: an entity of type
    `part` with `is_assembly: true`, children linked by `contains` edges whose attrs hold
    `placement: [x, y, z]` (mm), and child attrs `mass_kg`. Example used in development: "Arm assembly"
    with "Arm link" (0.6 kg at [300,0,0]), "Gripper" (0.4 kg at [450,0,50]), "Camera" (no mass, at
    [420,0,80]) → required torque **5.30 N·m** without the camera, **5.91 N·m** with the camera at 0.1 kg.
- The user has some credits (a sourcing request is one metered model call).

## 1. Workspace door — derive torque from a real assembly and select a motor

1. Open Project A › **Workspace**. Click **Add** (top-left) › **Hardware** tab.
   - Expected: below "Add Physical Robot" there is a short explanation and a **Find a sourced part**
     button. It is enabled (project online).
2. Click **Find a sourced part**.
   - Expected: a wide panel titled **ADD A SOURCED PART** with a Describe | From CAD switch; **From CAD**
     is preselected; the **Assembly** dropdown lists the project's assemblies (only assemblies, not
     every part); a "Project rules: …" line at the bottom with **Edit rules**.
3. Pick the assembly. Click **Derive torque from geometry**.
   - Expected: a **DERIVED TORQUE** card: "Required X N·m (static Y N·m × 1.5 safety) from <assembly>
     · not included: <part with no mass>", the assumptions list, and a kg field for each part without
     a mass. Nothing is guessed for the massless part.
4. Type a mass (e.g. `0.1`) for the massless part. Click **Derive torque from geometry** again.
   - Expected: the required torque rises and "not included" disappears.
5. Optionally fill Protocol `CAN` and Voltage `24`. Click **Find candidates**.
   - Expected: "Solus is finding candidates for required X N·m …" with a spinner (units keep their
     case). Within about a minute the comparison appears.
6. Inspect the comparison table.
   - Expected: one column per candidate with name, manufacturer, a **CITED** badge with `source ↗` OR an
     **UNVERIFIED** badge; a line "Optimises for … · gives up …" on EVERY candidate; rows Torque, Price,
     Weight, Protocol, Voltage, Availability, Supplier, Certifications, Vendor CAD. For an UNVERIFIED
     candidate Price and Availability are **—** (never a number). A cited candidate's `source ↗` and
     `model ↗` links are https and open in the system browser.
   - Expected: the panel scrolls inside itself when taller than the window.
7. In one column choose a **Category** (defaults to "Actuators / motors"), set Quantity `1`, click
   **Select <name>**.
   - Expected: "<name> is planned" with the sentence about the Workspace and BOM; a **Get vendor CAD
     model ↗** link when the candidate cited one, else "No vendor CAD model was cited for this part."
8. Click **Done**.
   - Expected: the panel closes. Enter the robot › the chosen category: the new part is there.
9. Open the **BOM** tab.
   - Expected: a row named after the part number (or name) with state **Planned**, supplier and quantity
     from the selection, and a price only if the candidate was cited.

## 2. Compliance rule excludes a supplier, with the reason visible

1. Workspace › Add › Hardware › Find a sourced part › **Edit rules**.
2. In **Excluded suppliers** type `<a supplier that appeared in §1>: Vendor failed the lab compliance
audit` (name, colon, reason). Optionally set Max voltage `24` and Allowed protocols `CAN`. Click
   **Save rules**.
   - Expected: the editor closes; the line reads "Project rules: 1 excluded supplier · max 24 V ·
     protocols CAN".
3. Run the same requirement again (steps §1.3–§1.5).
   - Expected: below the table, **EXCLUDED BY THIS PROJECT'S RULES** lists the excluded candidate with
     the reason text you typed, e.g. "Supplier 'X' is excluded: Vendor failed the lab compliance audit".
     Note: the model is NOT told which suppliers are excluded, so the exclusion is only visible when the
     model proposes that supplier; if it did not propose it this time, run once more.
   - Expected: candidates from a supplier listed under **Preferred suppliers** carry a "Preferred
     supplier" flag and rank first. A candidate with unknown voltage is flagged "Voltage unknown
     (project maximum 24 V)" but NOT excluded (unknown facts never exclude).
4. Repo rules: if Project A has a Git source with a `.solus` file, add
   `[ext.sourcing]` with `excluded_suppliers = "X: reason"` and sync. Reopen the panel.
   - Expected: the effective rules include the repo entry; the project-level rules saved in step 2
     layer on top.

## 3. BOM door — typed requirement

1. BOM tab › **Find compatible parts** (between Export CSV and + Add row).
   - Expected: the same panel titled **FIND COMPATIBLE PARTS**, **Describe** preselected.
2. Click **Find candidates** with everything empty.
   - Expected: inline "Describe the requirement, give a load and arm, or pick an assembly." Nothing is sent.
3. Type Load `2` and leave Arm empty › Find candidates.
   - Expected: "Give the arm length in metres too."
4. Requirement `holds 2 kg at 30 cm, quiet, must speak CAN`, Load `2`, Arm `0.3`, Protocol `CAN` › Find.
   - Expected: searching line shows "required 8.83 N·m (static 5.88 N·m × 1.5 safety)"; candidates
     appear; there is **no Category selector** on this door (the part lands in the project).
5. Select one › Done.
   - Expected: the BOM refreshes and shows the new row as **Planned**.

## 4. Failure paths

- **No credits / rate limit**: with an account out of credits (or after more than 10 requests in one
  minute), Find candidates.
  - Expected: a typed message ("Not enough credits…" / "Too many sourcing requests…") in the panel with
    **Try again**; never a raw provider error, never a spinner forever.
- **Model returns nothing usable**: cannot be forced from the UI; if it happens the panel shows "No
  candidate passed this project's rules…" rather than invented parts.
- **Offline project** (sign out or disconnect): Workspace › Add › Hardware.
  - Expected: **Find a sourced part** is disabled and "Connect this project to add hardware." shows.
- **Viewer role**: as a viewer of Project A, Find candidates / Save rules / Select.
  - Expected: refused with a permission message; nothing is created.
- **Bad numbers**: Load `abc` → "Load must be a number of kilograms."; rules Max voltage `x` → "Max
  voltage must be a number of volts."

## 5. Isolation

1. As the Project B user, open the panel in Project B.
   - Expected: Project A's assemblies, rules, requests and planned parts are not visible; Project B's
     rules are empty.
2. (API-level, for an engineer) `GET /api/v1/projects/<A>/sourcing/requests/<id>` with the B user's
   token → **404**; `POST …/select` with B's token → **404**.

## 6. Cross-feature checks

- The selected part is a normal manual graph entity: it can be renamed/deleted from the Workspace like
  any manual node; deleting it removes its BOM row.
- SOL: ask "what torque does the <assembly> need at its pivot?" — SOL uses the `sourcing.derive_torque`
  tool and answers with the same numbers as the panel; no model call is metered for the tool itself.
- Data events (for users with data-collection consent): `sourcing.requested`, `sourcing.rules_updated`,
  `sourcing.selected` appear with request/candidate/entity ids and never with the candidate text.

## Checklist

| #   | Path                                                                                        | Result | Notes |
| --- | ------------------------------------------------------------------------------------------- | ------ | ----- |
| 1   | Workspace door: derive, mass, find, compare, select, Workspace + BOM show planned           |        |       |
| 2   | Rule excludes a supplier with the reason visible; preferred flagged; unknown never excludes |        |       |
| 3   | BOM door: validation messages, typed requirement, no category, BOM refresh                  |        |       |
| 4   | Failure paths: credits/rate limit, offline, viewer, bad numbers                             |        |       |
| 5   | Isolation between projects/teams                                                            |        |       |
| 6   | Cross-feature: manual entity behaviour, SOL torque tool, events                             |        |       |
