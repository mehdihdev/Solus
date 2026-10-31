"""SOLUSDEV-321 P4 — simulation as a capability with rungs (docs/api/simulation.md).

- `sim_capability` is the shape every rung implements (`SimProvider`) and the result a run
  leaves (`SimResult`, with its whole provenance).
- `sim_ladder` decides when a simulation would settle something, which rung and target to use,
  and whether it can run. `should_simulate` only proposes.
- `sim_facts` writes what a run found into the graph.

This is shared code. It names a quantity, a rung or a provider, and never a vendor, a simulator or
a routing target: `models.yaml` names the targets. Both hygiene ratchets sweep this package with
no exclusion.
"""
