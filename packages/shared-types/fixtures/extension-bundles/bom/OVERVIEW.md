# BOM

Every part in the robot, the raw materials it is made from, and anything you purchase — in one
list, one row per physical part.

- A part that appears in CAD, in the schematic and in your purchase list is **one row**: the BOM
  is a view over the parts Solus has fingerprinted (or you have confirmed) as the same component.
  Nothing is merged by name alone.
- Identical part numbers within one design aggregate into a **quantity**.
- Rows for **raw materials and purchases** the design does not know about yet — a motor still
  being sourced, stock plate, fasteners — start as *planned*.
- Every row carries a **lifecycle state**: planned → ordered → received → installed → retired.
- **Supplier preferences and a cost target** are configuration: this bundle's settings here, or
  the team's `[ext.bom]` table in the repo's `.solus/project.toml`.
- **Export CSV** at any time.

Ask SOL to "add a planned NEMA 17 stepper to the BOM" — it calls `bom.add_item`. Uninstalling
removes the rows this widget added (planned items and per-row notes); the parts from your tools stay.
