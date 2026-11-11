# simulation.md — Simulation as a capability with rungs (SOLUSDEV-321 P4)

**Last updated:** 2026-10-29. Tier-1 plan (ADR-032). **Authority:** ADR-001 (graph-centric),
ADR-014 (the built-in sim; external sims are integration targets), ADR-018 (pure logic is
unmetered), CLAUDE.md §7 (connector and model text is untrusted).

A simulation is a capability: SOL and the matrix ask a question of a quantity, and a provider at
some rung answers it, or says what it lacks. There are four parts:

- **The capability** (`simulation/sim_capability.py`) is the shape every rung implements.
- **The ladder** (`simulation/sim_ladder.py`, the spec's `router.py`) decides when a simulation would
  settle something, which rung and target to use, and whether it can run. It only PROPOSES.
- **The facts** (`simulation/sim_facts.py`) are what a run leaves in the graph.
- **The rung-1 providers** (`simulation/providers/`, §6) are the closed-form code the ladder starts
  with: mechanics, electrics and robot kinematics.

None of it is an HTTP route. P4-T4 adds SOL's three simulation tools, `simulate`,
`get_sim_result` and the gated `apply_sim_change` (§8), and the bounded CAD twin (§9). P4-T5 wires
the ladder to the matrix, the gated real-world tools, the rung-3 jobs and the run comparison (§10).

The package is shared code. It names a quantity, a rung or a provider, and never a vendor, a
simulator or a routing target. The yaml names the targets (§4). Both hygiene ratchets sweep it
with no exclusion: `tests/test_capability_hygiene.py` (`simulation`) and
`tests/test_vendor_hygiene_api.py` (`simulation/*.py`, `simulation/providers/*.py`).

## 1. The capability

| Rung | What runs                                                      | Gate            | Task  |
| ---- | -------------------------------------------------------------- | --------------- | ----- |
| 1    | closed-form code: mechanics, electrics, kinematics             | none (pure)     | P4-T2 |
| 2    | an external routing target                                     | confirmation    | P4-T4 |
| 3    | local headless jobs: mesh interference, a circuit, the physics | none (ARQ jobs) | P4-T3 |
| 4    | an external full simulation (`simulation.targets`)             | confirmation    | P4-T4 |

```text
SimProvider (Protocol; read-only members, so a frozen dataclass implements it)
  name: str                    # what a style entry and the caller's `available` set call it
  domain: str                  # the world it models
  rung: int                    # 1–4
  quantities: frozenset[str]   # what it computes
  can_answer(question: SimQuestion) -> MissingInputs   # what the question lacks; never a guess
  run(inputs: {name: SimInput}) -> SimResult           # sync; rung 3 calls it inside its ARQ job

SimQuestion   {subject_id, quantity: <lowercase name>, facts: the subject's attrs}
MissingInputs {missing: [FactNeed{name, set_in}], derivable: [name], covered: [quantity]}
              # nothing missing → it can answer; `names` lists the missing names
SimResult     {values: {quantity: {value: finite float, unit}}, provenance}   # ≤ 64 KiB as JSON
  provenance  {solver: non-blank str,
               inputs: {name: {value: JSON, source: known | derived | assumed}},
               leaves_out: [non-blank str, ≥ 1]}   # every model leaves something out
```

**Input sources.** An input is `known` when the graph or a config states it, `derived` when the
provider computed it from known inputs, and `assumed` when it is a default the provider states.

**Validation.** A `SimResult` does not validate without its full provenance. It also does not
validate when the provenance is blank: an empty or whitespace-only `solver`, or such an entry in
`leaves_out`.

Each of the four models re-validates any instance it is handed (`revalidate_instances="always"`
on `SimResult`, `SimProvenance`, `SimInput` and `SimValue`). A `model_construct` shell at any
depth is therefore refused.

The facts writer goes further. It validates the JSON it is about to persist, and writes exactly
that JSON. Nothing reaches the graph without the solver, the inputs with their sources, and what
the model leaves out.

## 2. The ladder

### Entry points

```text
should_simulate(results: list[RuleResult], *, trigger, context) -> list[SimProposal]
propose_for(question: SimQuestion, *, trigger, context, above_rung=0, reason="") -> SimProposal | None
missing_input_finding(proposal, subject: EntityRead) -> FindingSpec
```

All three are pure. A provider is asked `can_answer`, never `run`. Nothing is written and no model
is called.

### Context

`LadderContext` is the caller's to build. It holds:

- `config` (`simulation:` in models.yaml);
- `graph`, the `GraphContext` the results are about: the subjects' attrs and names;
- `providers`;
- `available`: the provider names the caller found connected and configured. That means a
  connection exists for the project, a pinned binary is present, or an optional module imports.
  The ladder checks no connection itself;
- `style`, the project's `constraints/style` entries, oldest first (`FactStore.style`);
- `asked`: the `(subject, input)` pairs a person was already asked for.

### When

`SimTrigger` has four members, and only four.

| trigger             | reads                                                                   |
| ------------------- | ----------------------------------------------------------------------- |
| `rule`              | an `inconclusive` result inside its band (below)                        |
| `real_world_action` | the same; the gated real-world tools call this pre-check (P4-T5)        |
| `expected_value`    | an `unknown_input` whose missing fact is a quantity a provider computes |
| `user`              | both                                                                    |

A sync or a save is never a trigger: any other value raises `ValueError`. The matrix run a sync
causes passes `rule`, and its proposals stay proposals.

**The band.** An `inconclusive` result takes part only when its evidence states these keys:

- `quantity` (str);
- `value` and `limit`: finite, `limit != 0`;
- optionally `comparator`:
  - `"<="`, the default: the value must stay under the limit, ratio = value / limit;
  - `">="`, for a floor such as a clearance: ratio = limit / value;
- optionally `rung`: the rung whose value the rule judged, `0` before any simulation;
- optionally `unit`.

The result proposes when the ratio is at least the quantity's band: `simulation.bands[quantity]`,
else `simulation.escalate_at` (0.8, the spec's "within 20 % of a limit").

These propose nothing:

- a result without those keys, e.g. a unit mismatch, which no simulation settles;
- a quantity that is not a lowercase name;
- a `rung` that is not an integer;
- a `comparator` other than the two above;
- a result without a subject;
- a result whose subject is not in `graph`.

The subject is `subjects[0]`, in blame order. Each (subject, quantity) gets at most one proposal:
the first result that asks for it.

### Cheap first

The candidates are the providers that compute the quantity at a rung above the result's `rung`.
They are ranked in where-order (below). When no style entry prefers one and availability does not
separate them, the cheapest goes first, which by default is the lowest rung.

A value with margin proposes nothing, so the ladder stops where it is.

For a bracket:

- 15 % of yield after rung 1 stops at rung 1.
- 85 % climbs. The cheapest available candidate above rung 1, the mesh check at rung 3, is
  proposed, and an unconnected rung-2 target ranks after it.

### Whether

The chosen provider's `can_answer` decides. The first matching row wins.

| what it lacks                                                      | decision        | `missing`                | `leaves_out`          |
| ------------------------------------------------------------------ | --------------- | ------------------------ | --------------------- |
| nothing                                                            | `run`           | —                        | —                     |
| only what it can derive                                            | `derive`        | the inputs it derives    | —                     |
| an input nobody was asked for (`asked`)                            | `ask` (once)    | those inputs             | —                     |
| inputs already asked for, while it still covers the asked quantity | `run`           | the inputs still missing | their names (the gap) |
| inputs already asked for, the asked quantity not covered           | `missing_input` | the inputs still missing | —                     |

`covered` counts only when it holds the asked quantity. Take a provider that could still compute
a bracket's mass without its material: it never runs a stress question on that basis. The
no-material bracket is asked once for its material. After that it reaches `missing_input`.

A `missing_input` runs nothing. `missing_input_finding` words it as the standing `info` finding
the caller raises through `raise_finding` (P4-T4/T5):

- `rule_id = "simulation_missing_input"`;
- `severity = info` and `source = "simulation"`;
- `bucket = <quantity>`, so there is one finding per subject and quantity;
- the headline "could not simulate <q> for <subject>: <input> unknown; set it in <set_in>";
- evidence `{missing, quantity, rung, target}`.

### Where

The candidates are ordered by these keys, in turn:

1. **A `constraints/style` preference.** An entry whose text is
   `simulate <quantity> with <target>` states one. `<quantity>` may be `*` for any quantity, the
   match ignores case, and the newest matching entry wins.
2. **Connected and configured** (`available`).
3. **Cost**, ascending.
4. **Fidelity**, descending.
5. **Name.**

Cost and fidelity are a target's ordinals in `simulation.targets`. For a provider the yaml does
not list, both equal its rung.

A preferred target that is not connected still comes first. The proposal says `available: false`,
and the run step reports "not connected" rather than hiding the person's choice.

### SimProposal

```text
SimProposal
  trigger, subject_id, quantity, rung, target, available: bool
  decision: run | derive | ask | missing_input   # derive, ask and missing_input name ≥ 1 input
  missing: [FactNeed{name, set_in}]
  leaves_out: [str]
  alternatives: [target]                         # the other candidates, in where-order
  reason: str                                    # e.g. "stress_mpa is at 85% of its limit at rung 1: inside its 0.8 band"
  remember_as: "simulate <quantity> with <target>"
```

A person may override the target for one run. On confirm, P4-T4 remembers the override as a
`constraints/style` entry (`add_text_entry(..., subsection="style", author="sol")`). The text is
`STYLE_LINE.format(quantity=..., target=...)`, which is `remember_as` for the chosen target.

## 3. The facts a run leaves

`record_sim_result(sessions, hub, *, project_id, subject_id, rung, result, created_by) -> UUID` is
the one writer of `sim_result` entities, of their `verified_by` edges and of `attrs.expected`.

### The `sim_result` entity

```text
graph_entity  kind = "sim_result" (graph/kinds.py:SIM_RESULT), domain = "simulation", origin = "system"
              name = "<quantities> — <subject name>"
  attrs:
    subject_id: uuid
    rung: int
    values: {quantity: {value, unit}}
    provenance: {solver, inputs: {name: {value, source}}, leaves_out: [str]}
    created_by: uuid | null
```

The writer constructs this row itself, the way `raise_finding` constructs a finding. `graph/` has
no entity writer to call. Each run is its own entity, so history is kept.

`sim_result` is a descriptor kind (`graph/kinds.py:DESCRIPTOR_KINDS`): it describes its subject
and carries the subject's name. The scope planner and the first tier therefore never tie it with
its subject.

### The `verified_by` edge

The edge runs from the subject to the `sim_result` ("goal or claim → run or sim result"). It goes
through `graph/edges.py:write_edge` with:

- `origin = "system"` and `confidence = 1.0`;
- `EdgeEvidence(kind="sim", ref=<sim_result id>, detail=<solver>)`;
- no `matrix_cell`: `simulation` is not one of the three worlds.

### The expected value

Each computed quantity becomes `subject.attrs.expected[quantity] = {value, unit,
sim_result_id}`. It always names the newest run. Quantities this run did not compute keep their
entries. `attrs` is reassigned, never mutated, and the subject's `version` is bumped.

Two readers use it:

- P2's envelopes: the `nominal` slot, `bounds_source = "sim"`, confidence 0.8.
- P3's `FactStore.expected(part, quantity)`, for the matrix.

### Transaction

The writer owns its transaction:

1. It validates two things first: the JSON it will persist, and the rung, which must be one the
   config names (1–4). A result without its full provenance, or a rung outside 1–4, raises
   pydantic's `ValidationError` and writes nothing.
2. It takes `lock_project`.
3. It reads the subject fresh under a row lock, and never waits for that lock. A row another
   transaction holds is a retryable `409 conflict`, and nothing is written. A sync takes graph
   rows before the project lock, the opposite order, so a writer holding `lock_project` that
   waited could deadlock with it (R68). A foreign, deleted or unknown subject is
   `404 not_found`.
4. It writes the entity, the edge and the attrs.
5. It commits and logs `sim result recorded project=… subject=… rung=… sim_result=…`.
6. After the commit, in its own guard (the way a sync does), it publishes `graph.changed` for the
   project with counts of 1 entity created, 1 updated and 1 relation created.

The publish matters because the envelope cache is keyed by config version and would not notice the
new `attrs.expected` without it (M69). It also wakes the debounced matrix run, which re-judges
with the new value. A failed publish is logged, and the recorded run stands.

### Ceiling (M126)

A connector-owned subject's next sync rewrites its `attrs` from what the connector emits, but it
carries over the attrs Solus writes there (`connectors/runtime.py:SOLUS_OWNED_ATTR_KEYS`:
`expected`, `motifs`, `motif_labels`, `sim_asked`) when the connector does not emit that key, so
`attrs.expected` survives a re-sync (final fix wave, M126). A key the connector itself emits still
wins. The `sim_result` and its `verified_by` edge survive either way.

Hardware parts and seeded parts keep the expected value.

P4-T5 does not re-derive the value from the surviving `sim_result`, and leaves the ceiling to the
final wave. The same rewrite drops the inputs the run read (`material`, `section`, `load`, a
`mesh`), so a value read back from the old result would describe inputs the part no longer states,
and a graph read (`EntityRead`) carries no time to tell the newest of several results. The fix
belongs where the attrs are rewritten: a sync that keeps the keys no connector owns (M118 is the
same ceiling for the motifs).

## 4. Config: `simulation:` in models.yaml

```yaml
simulation:
  escalate_at: 0.8 # the spec's "within 20 % of a limit"
  bands: {} # quantity → fraction in (0, 1), overriding escalate_at
  targets: # the external routing targets — named here, never in simulation/
    - name: <lowercase name>
      rung: 1–4
      domain: <world>
      quantities: [<quantity>, …] # at least one
      cost: <ordinal ≥ 0> # optional; defaults to the rung
      fidelity: <ordinal ≥ 0> # optional; defaults to the rung
```

`SimulationConfig` and `SimTargetConfig` (`orchestration/config.py`) are frozen, with
`extra="forbid"`. A load refuses each of these:

- an `escalate_at` or a band outside (0, 1);
- a rung outside 1–4;
- a target without quantities;
- a duplicate target name;
- a name that is not a lowercase identifier.

What ships:

- two rung-4 targets, both `domain: mechanical` with `quantities: [joint_trajectory]`, each the
  full-simulation integration that P4-T4 routes through its `run_routine` tool. `isaac` has `cost`
  and `fidelity` of 4; `gazebo` (SOLUSDEV-322 P1-T3) has 3 and 3, so when both are connected the
  where-order ranks `gazebo` first on cost and a person's style entry or an explicit `provider`
  still picks `isaac`. The names are yaml strings, never names in code;
- no rung-2 target. The ladder skips a rung that has no candidate.

## 5. Consumers

- **P4-T2** (rung 1, §6) and **P4-T3** (rung 3) implement `SimProvider`.
- **P4-T4** (§8, §9):
  - wraps the yaml targets as providers (`ExternalProviders`, "not connected" when absent);
  - runs rung 1 in process, enqueues rung 3 and routes rungs 2 and 4 to their gated tools;
  - records results through `record_sim_result`;
  - keeps `asked` on the subject (`attrs.sim_asked[quantity]`);
  - raises `missing_input_finding` through `raise_finding`;
  - remembers an override as a style entry;
  - closes the backward loop behind `apply_sim_change`'s card;
  - writes the bounded CAD twin beside a CAD import's static model.
- **P4-T5** (§10):
  - passes the matrix's `inconclusive` results to `should_simulate` as `rule`, and keeps the
    proposals on `MatrixReport.proposals`;
  - runs the same pre-check, as `real_world_action`, on the CAD import's, the flash's and the
    companion deployment's cards (the last two since fix 1, R116);
  - makes `bracket_strength_at_joint` and `interference_through_range` judge the expected values,
    with the band's evidence keys on every verdict;
  - flags a rung-3 job whose simulator the worker lacks, reads a failing result's owning domain
    off its rule's cell, and reads a real run against its routine's twin in `compare`.

## 6. Rung 1: the closed-form providers

`simulation/providers/` holds three rung-1 providers: `deterministic_mech`, `deterministic_elec`
and `deterministic_robot`. They are pure code: no I/O, no session and no model, and numpy at most.
Each is a `ClosedForm` (`providers/__init__.py`), a table of formulas over a subject's attrs that
the base turns into a `SimProvider`. `domain` is `mechanical`, `electrical` and `mechanical`;
`rung` is 1.

### How a provider behaves

- **A need is a fact in the attrs.** A formula reads its needs by name. A need that is absent or
  unusable is a missing input, named with where a person states it (`FactNeed.set_in`). It is never
  guessed.
- **`can_answer(question)`** returns the needs of the asked quantity's formula that the facts do not
  state usably, and `covered`: every quantity whose formula has all it needs. `covered` is spelled
  exactly as `quantities`, which the ladder compares as strings. `derivable` is empty: nothing at
  rung 1 stands in for a fact a person states. A quantity the provider does not compute raises
  `ValueError`; the ladder only asks a provider for a quantity it lists.
- **`run(inputs)`** computes every formula whose needs `inputs` states usably. `inputs` are the
  subject's attrs, each a `SimInput` with its source. `provider.inputs_for(facts)` wraps the attrs
  the provider reads as `known`, and a caller may pass any superset. A formula that cannot run is
  named in `leaves_out` as `<quantities> not computed: <needs> unknown`. When none can run, `run`
  raises `ValueError`.
- **Provenance.** `solver` is `<provider>:<formulas that ran>`, joined by `+`. `inputs` holds:

  - each need read, with the source its attr was given. A mesh and a joint tree are summarised,
    never copied into a result;
  - what the formula derived, as `derived`: computed here from known inputs, and the formula is
    the one `solver` names;
  - a default the formula assumed, as `assumed`.

  `leaves_out` names what each closed form ignores. A formula may add lines of its own when what
  it ignores depends on the facts: the robot names the branches of a tree it did not evaluate.

- **Untrusted attrs.** A reader never raises, returns a copy, and drops every key it does not
  read. A number is taken only when it is finite and within ±1e9 in whatever unit it is in, so no
  product of two overflows. A quantity that must be positive has a floor of its own, in its own
  unit, named beside the formula that reads it (below): a zero or a denormal never reaches a
  division, and a real part is never refused for being small. A bool or a string is no number.

### Quantities and their spellings

| Provider              | Quantity                          | Unit |
| --------------------- | --------------------------------- | ---- |
| `deterministic_mech`  | `stress_mpa`                      | MPa  |
|                       | `yield_fraction` (stress / yield) | none |
|                       | `mass_kg`                         | kg   |
|                       | `com_x_m`, `com_y_m`, `com_z_m`   | m    |
| `deterministic_elec`  | `power_w`                         | W    |
|                       | `divider_out_v`                   | V    |
|                       | `rc_settling_s`                   | s    |
|                       | `cable_drop_v`                    | V    |
| `deterministic_robot` | `reach_m`, `sweep_span_m`         | m    |
|                       | `tip_x_m`, `tip_y_m`, `tip_z_m`   | m    |

A vector is its scalar components, because a `SimValue` is one number.

### Mechanics

| Formula              | Gives                           | Reads                                                                       |
| -------------------- | ------------------------------- | --------------------------------------------------------------------------- |
| `cantilever_bending` | `stress_mpa`, `yield_fraction`  | `load` {force_n, arm_m}, `section` {shape, dims_mm}, `material` {yield_mpa} |
| `mesh_mass`          | `mass_kg`                       | `mesh`, `material` {density_kg_m3}                                          |
| `mesh_com`           | `com_x_m`, `com_y_m`, `com_z_m` | `mesh`                                                                      |

- **Bending.** The part is a prismatic cantilever of the stated section with the load at its arm:
  M = |F| · arm (N m), stress = M · c / I (MPa, with M in N mm and the section in mm), and the yield
  fraction is the stress over `yield_mpa`.
  - `section.shape` is `rect` (`dims_mm` [width, depth], the depth along the load: swap a 30 x 5
    plate's dims and the stress reads six times too low), `round` ([diameter]) or `tube` ([outer,
    inner] diameters, inner smaller). A dim is at least `MIN_MM` = 1e-6 mm.
  - `load.force_n` may be negative, for only its magnitude is used. `arm_m` is not negative.
  - Derived: `moment_nm`, `second_moment_mm4` and `extreme_fibre_mm`.
  - A stress is reported only with the yield it is judged against, so a part without a `material`
    is a named `missing_input` for the stress question and the ladder runs nothing. Its `covered`
    is the centre of mass.
- **Mass and centre of mass.** The part is a uniform solid whose triangles are `mesh`, stored the
  way `MeshCatalog` stores one: `{"vertices": [x, y, z, ...]}` in metres, nine numbers per
  triangle, at most 50,000 triangles. The volume is the sum of the signed volumes of the
  tetrahedra the triangles make with the mesh's centre (the divergence theorem); the centre of
  mass is their weighted centroids; the mass is `density_kg_m3` times the volume. Derived:
  `volume_m3`.
  - **A mesh must be a closed surface facing outward**, or it is the named missing input `mesh`.
    Its edges must cancel in pairs: every directed edge has its reverse, as many times, with
    corners matched by their coordinates (a tessellation shares its corners exactly; a mesh whose
    shared corners differ by rounding is refused as open). An open mesh (a box without its top, a
    planar patch) is no solid, however small its rounding noise leaves its volume, and a triangle
    listed twice breaks the pairing. The volume must also be positive: a surface facing inward is
    no solid. Tessellated curved parts pass (a cylinder, a sphere, a torus, a drilled plate, a
    filleted box).
- **Material.** `material` is {name, yield_mpa, density_kg_m3}. A yield is at least `MIN_MPA` =
  1e-6 MPa and a density at least `MIN_KG_M3` = 1e-3 kg/m³. A name is shown redacted on one line of
  at most 80 characters.
- **Leaves out.**
  - Bending: shear and axial stress, stress concentrations, dynamic loads and fatigue, buckling,
    temperature, and changes of section along the member.
  - Mass and centre: voids, fasteners and coatings the mesh omits, non-uniform density, solids in
    the mesh that overlap or cross (only that its surface is closed is checked), and curved faces
    approximated by flat triangles (the mesh's volume is a little off).

### Electrics

| Formula       | Gives           | Reads                                      | Closed form                         |
| ------------- | --------------- | ------------------------------------------ | ----------------------------------- |
| `power_sum`   | `power_w`       | `loads_w`, a list of watts                 | the sum                             |
| `divider`     | `divider_out_v` | `divider` {vin_v, r_top_ohm, r_bottom_ohm} | vin · r_bottom / (r_top + r_bottom) |
| `rc_settling` | `rc_settling_s` | `rc` {r_ohm, c_f}                          | 5 · r · c                           |
| `cable_drop`  | `cable_drop_v`  | `cable` {current_a, length_m, ohm_per_m}   | current · length · ohm_per_m        |

- `loads_w` holds 1 to 256 loads, none negative. A divider's supply may be negative. A current, a
  length and a resistance per metre are not negative.
- **Floors**, each in its own unit and far below any part: a resistance is at least `MIN_OHMS` =
  1e-9 ohm and a capacitance at least `MIN_FARADS` = 1e-15 F, so 10 kohm with 100 pF or 10 pF is a
  filter and not a missing fact. A zero is still no resistance and no capacitance.
- `length_m` is the conductor length the current flows through, so a two-wire run counts twice.
  The resistance per metre is a fact about the cable; there is no table of cables.
- Derived: `tau_s` (r · c) and `resistance_ohm` (length · resistance per metre).
- **Assumed: `settling_taus` = 5.** Settling is a convention (e^-5, 99.3 % of the way), the one the
  matrix rule `sample_rate_vs_adc_settling` also uses.
- Leaves out: converter efficiency and inrush, load duty cycle; the load on a divider's output and
  resistor tolerance; component tolerance and any other load on the node; conductor heating,
  connector resistance and AC skin effect.

### Robot kinematics

| Formula              | Gives                           | Reads                       |
| -------------------- | ------------------------------- | --------------------------- |
| `joint_sweep`        | `reach_m`, `sweep_span_m`       | `joints`                    |
| `forward_kinematics` | `tip_x_m`, `tip_y_m`, `tip_z_m` | `joints`, `joint_positions` |

- **`joints`** is `attrs.model.joints` of a scene model, as `livebench/scene/parser.py` emits them:
  `{name, type, parent, child, xyz, rpy, axis, lower, upper}` in metres and radians, with `type`
  `fixed`, `revolute`, `continuous` or `prismatic`. The joints make one tree: a single root link,
  every other link with one parent, at most 128 joints and names of at most 128 characters. A
  model with no joints (a CAD import has none) or joints that do not make one tree is the named
  missing input `joints`.
- **Kinematics.** A joint's `xyz` and `rpy` place its child in its parent's frame at zero (`rpy`
  are the URDF fixed axes, R = Rz(yaw) Ry(pitch) Rx(roll)); it then turns about its `axis` or
  slides along it. The root link's frame is the base.
- **The base and the tip.** The base is the tree's root link. The tip is the leaf link behind the
  most movable joints (a fixed mast does not outrank an arm), then the deepest, then the first in
  joint order. Both are derived inputs, `root_link` and `tip_link`, in every provenance. Names are
  shown on one printable line of at most 80 characters.
- **A tree that branches is evaluated along one branch.** Only the root-to-tip branch is swept and
  reported. When the tree has more than one leaf, `leaves_out` says so and names the leaves of the
  branches ignored (the first eight, then a count); when several leaves tie for the tip, it says
  that too and names them (an arm's two fingers, two arms). Nothing is evaluated for a branch it
  names.
- **`joint_positions`** is {joint name: rad, or m for a prismatic joint} for every movable joint
  from the root to the tip. A joint of the model off that path may be stated, and a name the model
  lacks makes the whole attr unusable.
- **The sweep** takes each movable joint from its lower limit to its upper in 9 steps with the
  others at neutral (zero, or the nearest limit if zero is out of range); a continuous joint
  sweeps over one turn. It visits 1 + 9 · (movable joints on the path) poses, recorded as the
  derived `configs_evaluated`. `reach_m` is the farthest the tip is from the base anywhere in the
  sweep, and `sweep_span_m` the widest distance between two points the tip reaches while a single
  joint is swept.
- **Assumed: `sweep_steps` = 9** (`SWEEP_STEPS`).
- Leaves out: link geometry beyond the frames' origins, joints swept one at a time (so the reach
  is a lower bound), self-collision and obstacles, joint velocity and torque limits, backlash and
  link flex, the tip's orientation, and joint limits on the stated `joint_positions` (forward
  kinematics enforces none). A branching tree adds the lines above.

### The assumed defaults

Two inputs are `assumed`, and no other: `settling_taus` (5) and `sweep_steps` (9). Each is a
default the provider states; a run records it in its provenance.

### The bracket fixture

`tests/fixtures/sim_bracket.py` seeds the P4 acceptance's three variants of one bracket. The
geometry is real: `bracket.step` (a base plate with two pegs) is tessellated once per test session
through `connectors/step_tessellation.py`, each leaf is placed by its occurrence transform, and the
36 triangles are stored as `attrs.mesh` the way `MeshCatalog` does. The section (30 x 5 mm, a
section modulus of 125 mm³), the load (25 mm arm) and the material (`fake-6061`: yield 276 MPa,
2700 kg/m³) are fake, and each says `"fake": true`.

| Variant | Load   | Material | Stress at the root   | At rung 1                                                 |
| ------- | ------ | -------- | -------------------- | --------------------------------------------------------- |
| a       | 207 N  | fake     | 41.4 MPa, 15 % yield | stops: under the 0.8 band                                 |
| b       | 1173 N | fake     | 234.6 MPa, 85 %      | climbs: the next rung's `stress_mpa` provider is proposed |
| c       | 207 N  | none     | cannot be judged     | `missing_input` naming `material`                         |

The whole bracket weighs 9.1368 g (3384 mm³, the volume the STEP states) and its centre of mass is
(14.943, 10, 3.465) mm. `seed_brackets(db, project_id)` writes the three as mechanical parts.

The rule that asks the ladder after a rung-1 run (P4-T5, `bracket_strength_at_joint`, §10) states
the band's evidence as `quantity: "yield_fraction"`, `value` the run's fraction of yield, `limit`
1.0 and `rung: 1`, with the stress beside them as `stress_mpa`. The mesh check computes both
quantities, so the 85 % bracket climbs to it.

## 7. Rung 3: the mesh check, the SPICE transient and the trajectory job

Rung 3 is local, headless work. Three providers live in `simulation/providers/`, each a
`SimProvider` with `rung` 3 that behaves as §6 describes: needs are facts, `can_answer` names what
is missing, and a run's provenance marks every input `known`, `derived` or `assumed`.

| Provider (`name`)                               | Domain     | Quantities                                                           | Where it runs                      |
| ----------------------------------------------- | ---------- | -------------------------------------------------------------------- | ---------------------------------- |
| `MeshInterference` (`mesh_interference`)        | mechanical | `interference_mm`, `stress_mpa`, `yield_fraction`                    | only the ARQ job `run_mesh_sim`    |
| `NgspiceProvider` (`spice_transient`)           | electrical | `peak_current_a`, `final_current_a`, `min_node_voltage_v`            | only the ARQ job `run_ngspice_sim` |
| `RigidBodyTrajectory` (`rigid_body_trajectory`) | mechanical | `peak_joint_torque_nm`, `peak_joint_force_n`, `peak_joint_current_a` | only the ARQ job `run_mujoco_sim`  |

No model is called anywhere at rung 3, and all three run only inside their ARQ jobs, never in the
request path. The mesh check is bounded numpy with no I/O, but its worst case is about two
million edge-face tests, so it has a job of its own too (P4-T4, R110).

### The jobs

`run_ngspice_sim(ctx, request)`, `run_mujoco_sim(ctx, request)` and `run_mesh_sim(ctx, request)`
(`simulation/mesh_job.py`) are registered on the worker (`connectors/worker.py`) with
`max_tries=1` and `keep_result=0`. Their timeouts, 120 s, 300 s and 120 s, sit above each
provider's own deadline (60 s, and the trajectory child's 75 s). The mesh job runs
`QueuedMeshCheck`, the mesh check marked available wherever the job runs (it needs only numpy);
a subject it has nothing to check in is `refused`, and a result that does not validate is
`failed`, its values never logged.

- **The request** is a `SimJobRequest` (`simulation/sim_facts.py`): `{project_id, subject_id,
requested_by?, facts}`, unknown keys refused, and the facts at most 1 MiB as JSON. The enqueuer
  derives the ids from the turn's own scope, never from the facts.
- **The run** (`run_and_record`), in order: validate the request, which raises on a malformed one;
  check again that the provider is available on the worker's own machine; run it off the event
  loop; record the result through `record_sim_result` (§3).
- **The status it returns**, since the queue keeps nothing: `recorded` with the `sim_result_id`, or
  `not_available`, `refused` or `failed` with a bounded reason. Every status but `recorded` is also
  a log line naming the provider, the project and the subject.

### Mechanics: the mesh check

| Formula              | Gives                          | Reads                                                  |
| -------------------- | ------------------------------ | ------------------------------------------------------ |
| `mesh_interference`  | `interference_mm`              | `mesh`, and beside it `meshes` and `poses`             |
| `cantilever_bending` | `stress_mpa`, `yield_fraction` | rung 1's own formula, reused (§6), so a climb keeps it |

- **The bodies** are the pieces of the subject's `mesh` (triangles that share an edge are one
  piece: the bracket's plate and its two pegs), plus any `meshes` {name: {vertices}} the caller
  adds. Each is a closed surface in metres facing outward, read by rung 1's readers.
- **`poses`** is one pose set {body: 4x4 row-major rigid transform} or a list of at most 16, a
  joint range sampled pose by pose. A body a pose set does not name stays where it is.
- **Two bodies interfere** when some point of one is firmly inside the other: the point and the
  six points around it are inside by the other's winding number. The candidates are an edge of one
  crossing a face of the other strictly, then face centres, then each body's volume centre, then
  points just past a crossing that meets only a face's boundary. Bodies that only touch do not
  interfere, so touching pegs report 0.
- **`interference_mm`** is the deepest pair's depth: the shortest distance either body's bounding
  box must move along an axis to clear the other's. It is an upper bound on how far they
  interpenetrate. Derived: `edge_face_tests`, `probes` and `interfering_pairs` (the first 8, each
  {bodies, pose, depth_mm}, then a count).
- **Bounds (R105).** The work is planned before anything is tested, and no list grows past its
  bound before it is cut: at most 16 bodies (a mesh's pieces are counted before any is built),
  50,000 triangles, 16 pose sets, 2,000,000 edge-face tests (only over pairs whose bounding boxes
  overlap with depth), and 256 probes (cut inside the vectorised batch that yields them). A scene
  past a bound is the named missing input `mesh`, never a partial answer; probes past theirs are
  named in `leaves_out`.
- **numpy only.** trimesh's collision check needs python-fcl, rtree and scipy, none of which the
  project carries, so the check is numpy over bounding-box-pruned pairs. A `ponytail:` note in the
  module names trimesh with python-fcl as the upgrade, for when dense meshes must be checked.
- Leaves out: clearance between bodies that do not touch, poses between the stated pose sets, a
  body that intersects itself, and deformation under load.

### Electrics: the SPICE transient

The netlist is the companion's schematic SPICE export: untrusted device output that never becomes
a directive the simulator executes. `SpiceDeck` (`simulation/providers/spice_deck.py`) reads it
through a closed grammar, line by line (R85, R101):

- **Kept:** element cards whose first letter is R, C, L, V, I, D, Q, M or X, each in a fixed shape
  for its letter, every token from a bounded class: a name, a node, a number with a SPICE suffix,
  a model, or `DC`/`AC`. A card is re-emitted from its tokens, never as its raw line.
- **Dropped**, each listed with its line number and never followed: `.title` and `.end` (Solus
  writes its own), the schematic's analysis lines (`.tran`, `.ac`, `.dc`, `.op`, `.noise`, `.tf`;
  Solus writes the one analysis line), and `.include` and `.lib`.
- **Refused**, each with its line number: every other dot line (`.control`, `.param`,
  `.options`, `.model` or `.subckt` inside the export, …), the words `codemodel`, `shell` and
  `source` and any word starting `wr`, a token outside its class, a name starting `solus_` (kept
  for Solus's own cards), and anything past the bounds (256 KiB, 4,000 lines, 2,000 cards).
- **Models come only from `hardware/definitions/spice/`**: `generic.lib` holds `d_generic`,
  `npn_generic`, `pnp_generic`, `nmos_generic` and `pmos_generic`, textbook parameters for generic
  parts, read through a closed grammar of their own. An element naming any other model fails as
  "model not found".

The deck Solus renders is all its own text: a fixed title, the definitions the cards name, the
kept cards, the motor's cards, the one `.tran <step> <stop> uic` line, and `.end`.

**The facts.** `spice_netlist` (the export's `content`); `spice_probe` {node, source}, the node
whose voltage is read and the V element the current flows through; `motor` (optional) {nodes:
[plus, minus], resistance_ohm, inductance_h, back_emf_v_per_rad_s, speed_rad_s}, written as R and
L in series with a DC back-EMF source whose value is `derived` (the constant times the speed); and
`spice_analysis` {step_s, stop_s}, `assumed` 10 µs steps to 20 ms when unstated. It gives
`peak_current_a` and `final_current_a` (the largest and last magnitude of the current) and
`min_node_voltage_v`.

**The pinned binary (R86).** `settings.ngspice_bin` (`SOLUS_NGSPICE_BIN`) names it. It must
resolve to an absolute path to a regular, executable file; unset or anything else is "not
available on this machine", and nothing is ever looked up on PATH.

- Solus writes the deck into a private 0700 directory, the child's cwd, removed afterwards.
- The argv is fixed, never a shell: `<bin> -b -n -r out.raw -o out.log deck.cir`. `-n` skips
  every `.spiceinit`, which would otherwise run as a control script.
- The environment holds three names (`HOME` the private directory, `SPICE_ASCIIRAWFILE=1`,
  `LC_ALL=C`), and stdin is closed.
- The child runs under the tessellation child's CPU and memory limits, a cap on every file it
  writes (8 MiB, stdout and stderr included), a zero core-file size (a child killed at a cap
  dumps no core), and a 60 s wall timeout.
- The ASCII rawfile is read through bounds (512 vectors, 100,001 points). At most 2 KiB of the
  log, made printable, reaches a log line or a reason.

**Where the netlist comes from.** The KiCad fork's `kicad.export_spice_netlist`
(`integrations/mcp/kicad/solus/spice_export.py`) runs
`kicad-cli sch export netlist --format spice` with a fixed argv over the workspace-confined
snapshot `kicad.export_netlist` reads, and
returns the text inline as data, at most 256 KiB. Each `.include` and `.lib` line keeps its
directive and loses its path, which names a file on the customer's machine and which the deck
would drop unread. There is no KiCad-free fallback: without a
native kicad-cli, or under the Flatpak adapter (whose fixed operations hold no SPICE export), the
result is degraded with no content. The tool widens the fork's allowlist, so its entry is drafted
in-branch and flagged for the humans to ratify.

### Mechanics in motion: the trajectory job

`RigidBodyTrajectory` reads three facts:

- `mjcf`: the scene model in the physics engine's own XML, at most 512 KiB of UTF-8: half the job's
  1 MiB facts bound, so a model at its bound still fits once JSON escapes its quotes. Text UTF-8
  cannot encode (a lone surrogate) is no usable model;
- `trajectory`: a generic `JointTrajectory` {joints, points: [{t, positions}]}, at most 16 joints
  (names of letters, digits, `_`, `.` and `-`) and 64 points, from 0 s, strictly in time, within
  30 s;
- `torque_constants` {joint: N m/A, or N/A for a slide joint}, one positive constant for each
  joint the routine drives.

**Before the engine sees the text** (R87, R107):

- a DTD, a comment or a NUL is refused, and so is text that is not well-formed;
- a root element other than the engine's own is refused, a URDF among them;
- livebench's guard (`_reject_file_referencing_mjcf`) runs on every text compiled, as a first,
  cheap reject;
- then a walk over every parsed element refuses what the parser itself sees: an `include`,
  `model`, `extension` or `plugin` element; any XML namespace; any attribute named `file*` or
  `*dir` (the engine's own schema names no other attribute it reads a file through, and a test
  checks it); and any value holding a path (`/`, `\`, `..`, `:`). A real bypass of the substring
  guard is refused here: a cube texture's six face attributes (`fileup=` and its siblings), which
  `file=` does not match. A namespace is refused because the parser would rename `x:file` to a
  name the attribute rule cannot see;
- the same walk refuses `replicate`, `composite`, `flexcomp` and `size` (R106): each multiplies the
  model, or sizes its memory, far past what its text states.

**The engine runs only in a child of its own (R106).** On the engine (3.11.0), under a 1 GiB child,
`<replicate count="100000">` burned the whole 20 s CPU limit in the compile, a 20000 x 20000 height
field or builtin texture asked for 1.2 to 1.6 GB, and `<size memory="10G">` allocated its arena at
compile time. So the compile can run away, and a crash in the engine must not take the worker with
it:

- the child is the worker's own interpreter running the module (`sys.executable -I -m`), the
  `step_tessellation` pattern: no PATH lookup and no shell, a private directory, and a three-name
  environment (`HOME`, `LC_ALL=C`, `OPENBLAS_NUM_THREADS=1`);
- it sets its limits before it reads its request: the tessellation child's CPU (20 s) and address
  space (2 GiB) caps, a cap on every file it writes and a zero core-file size. The parent kills
  it hard at 75 s;
- it compiles through the engine's virtual file system, the text the one file it holds, under a
  directory that does not exist. A relative reference, which a compile from a string resolves
  against the working directory, is never opened, and a reference to an asset the VFS lacks fails
  closed. An absolute path the engine still opens from the disk, which is why the walk keeps every
  one out;
- after the compile and before any `MjData`, each count is checked against its cap
  (`MODEL_CAPS`): 256 bodies, 256 joints, 128 actuators, 1,024 geoms, 256 degrees of freedom and a
  64 MiB arena. A chain of 255 hinges fits, and its default arena is 28 MiB;
- a run takes at most 50,000 steps and 60 s of wall time, the clock read at every step;
- what the child leaves is read back as untrusted: at most 1 MiB, parsed and validated whole. On
  anything but a run, the end of what the child printed is logged; the engine's own message, which
  can echo the text, never reaches a reason.

**The run** is forward dynamics. Each routine joint needs a position actuator. At each step its
target is the routine's, interpolated linearly. The run records the expected trajectory, the
actuator force on each joint (`qfrc_actuator` at the joint's degree of freedom), and the expected
current, that force over the joint's torque constant, `derived`. It gives `peak_joint_torque_nm`
(hinges), `peak_joint_force_n` (slides) and `peak_joint_current_a`, each the largest over every
step. A result records at most 200 samples, and the model by its counts, never by its text. A
1 kg mass 0.5 m out on a hinge, held level by a position servo, needs m g L = 4.905 N m; the test
checks it against the engine.

Leaves out: the motor's electrical dynamics (the current follows the force at once), friction,
backlash and compliance the model does not state, control beyond the model's own position
actuators, the steps between recorded samples, and sensor noise and delay.

## 8. SOL's simulation tools (P4-T4)

Three tools, in `agent/tools/simulate.py` and `agent/tools/apply_sim_change.py`. None of them makes
a model call: rungs 1 and 3 are code, and rungs 2 and 4 are other systems reached through their
own gated tools.

| Tool               | Gate                                        | What it does                                                                |
| ------------------ | ------------------------------------------- | --------------------------------------------------------------------------- |
| `simulate`         | none                                        | runs rung 1, enqueues rung 3, routes rungs 2 and 4, dry-runs a fix          |
| `get_sim_result`   | none (read-only)                            | reads one `sim_result` of the project                                       |
| `apply_sim_change` | a card in Build mode; Guide mode refuses it | applies one dry-run fix after the person approves, then re-runs             |
| `sim.available`    | none (read-only, SOLUSDEV-322)              | one row per provider: installed, connected, runnable here, sessions         |
| `sim.map_to_parts` | a card in Build mode; Guide mode refuses it | records simulated joints as `attrs.sim_aliases` of the parts they stand for |

### Registration and wiring

`register_simulation_tools` runs inside `agent/runtime.py:_register_user_tools`, so every tool acts
as the requesting person and a bare registry still lists only `get_entity`.

- `get_sim_result` registers whenever a person is bound.
- `simulate` and `apply_sim_change` also need the app's `graph_hub`, which
  `deps.get_sol_registry` passes. Every recorded run publishes `graph.changed` through it, and only
  the publishing hub fires the fan-out (M69), so a hub of the tool's own would skip it.
- `enqueue_sim` (`deps.create_sim_enqueue`) exists when the server has Redis and is not inline. It
  queues `(job, request)` on the app's ARQ pool under `<job>:<project>:<sha1 of the request>[:12]`.
  arq refuses an id that is still live, so the same request never queues twice while it waits; the
  jobs keep no result (`keep_result=0`), so a finished request may run again.
- Which external targets are connected is read once, at registration, off the tools already
  registered: the bridge's. Connection is registration (SOLUSDEV-322 P1-T3): the routine tool's
  static gate does not count, since its gate is decided per call (P2-T2).
- `sim.available` (`agent/tools/sim_available.py`, SOLUSDEV-322 P1-T2) registers whenever a person
  is bound, after the bridge tools. It answers `{providers: [{provider, installed, connected,
runnable_here, reason, version, running_sessions: {owned, attached}, capabilities}]}` for
  `calculators`, `mujoco`, `ngspice`, `gazebo` and `isaac`. `installed` is a fact: `mujoco` and
  `ngspice` from this deployment (`find_spec`, the pinned `SOLUS_NGSPICE_BIN`), `gazebo` from the
  asker's machine (`attrs.simulators`, derived by `services/machine_simulators.py` from the
  companion's `tool_versions` lines: `{gazebo: {family: classic|ignition|gz, version} | null,
nvidia_smi: bool, ngspice: version | null}`), `isaac` only from its probe's `available: true`
  (otherwise `null`, never "absent"). `connected` is registration: a bridge row is connected when
  its `<provider>.probe` tool is in the registry; the tool calls at most those two probe objects
  and forwards their answers as `capabilities`. Every `reason` is one sentence SOL repeats as it
  is (P7-T2): without a companion `The companion is offline (bridge offline).`; Isaac's platform
  reasons (non-Linux, non-x86_64, no `nvidia-smi`) come first. The same rule holds across the
  `gazebo.*` / `isaac.*` wrappers: a companion refusal `{ok: false, code, reason}` reaches SOL
  with its `reason` flattened to one path-free sentence (a bare code names the code), and a dead
  bridge answers `The companion is offline (bridge offline); reconnect it and try again.` with
  the contract's `unavailable` code and retryability. `running_sessions` counts the project's live rows in the ownership ledger
  (`simulation/sessions_ledger.py`) by provider: `owned` = started by Solus, `attached` = the
  person's own.
- `sim.map_to_parts` (`agent/tools/sim_mapping.py`, SOLUSDEV-322 P5-T1) registers whenever a person
  is bound. Arguments: `{provider, session_id?, model_entity_id?, channels: [{device_id,
joint_name}] ≤ 64, robot_id?}` (strict, closed; ids are uuid text; a `session_id` must be a live
  ledger row of that provider in this project). Matching per channel, first rung with candidates:
  the bound `simulation_model`'s joint binding `name` → a live part whose normalized name is the
  joint or whose hardware config carries a telemetry channel `<joint>.<signal>` → (P6, not yet) the
  generated model's URDF joint names. Exactly one candidate maps; none or several stay unmapped.
  Static card (`requires_confirmation`, complete preview): one row per mapped part (`before` = the
  provider's existing alias, `after` = `<provider>/<device_id>`) and one
  `unmapped: <joint> (ambiguous: a, b | no part matches)` row; a mapping with nothing to write
  refuses the park. The approved write is `part.attrs.sim_aliases = existing + [{provider,
device_id}]`, deduped and reassigned under `lock_project`, `version` bumped, `external_ref` never
  touched; it emits the data event `sim.aliases_mapped` `{provider, mapped, unmapped, part_ids}`.
  `model_entity_id`/`robot_id` from another project, or a model binding that points outside the
  project, are refused (`not_found`), never followed.

### `simulate(question, scope?, provider?, change?)`

| Argument   | Shape                                                                           |
| ---------- | ------------------------------------------------------------------------------- |
| `question` | `{subject_id: uuid, quantity}`, the quantity one that some provider computes    |
| `scope`    | at most 16 entity ids whose facts bear on the question                          |
| `provider` | a provider or target that computes the quantity, only when the person names one |
| `change`   | a proposed fix (the backward loop, below): dry-run and returned, never applied  |

It reads the subject's neighbourhood (two hops, under the bound read scope) and the matrix's
`FactStore` over it; a subject the project does not hold is `not_found`. The ladder is asked with
`trigger="user"`. `available` holds the rung-1 providers, the rung-3 providers when a queue
exists, and the connected targets (`available_targets`, the reading the matrix's ladder and the
gated actions' pre-check share, §10); `asked` comes from the subject's `attrs.sim_asked[quantity]`
(`asked_names`, shared the same way); a `provider` choice is the newest style entry for this one
call.

| The ladder says      | `simulate` does                                                        | `decision`                    |
| -------------------- | ---------------------------------------------------------------------- | ----------------------------- |
| no candidate         | nothing                                                                | `none`                        |
| `ask`                | records `attrs.sim_asked[quantity]`, reassigned under the project lock | `ask`                         |
| `missing_input`      | raises `missing_input_finding` through `raise_finding`                 | `missing_input`, `finding_id` |
| `run` at rung 1      | runs the provider in process and records it (`record_sim_result`)      | `ran`, `sim_result_id`        |
| `run` at rung 3      | enqueues the provider's job; never runs it inline                      | `queued`, `job_id`            |
| rung 3, no queue     | nothing                                                                | `not_available`               |
| `run` at rung 2 or 4 | names the target's gated routine tool; invokes nothing                 | `route`, `route`              |

Every result carries the proposal's `rung`, `provider`, `reason` and `alternatives`, and its
`missing` and `leaves_out` when it has them. A subject another writer holds is not waited for when
an ask is recorded: the next question then asks again. A queue that does not take the job is
`not_available` too, with its `reason` and a warning in the log; when that job was a rung-1 climb,
the rung-1 run stays recorded and the call does not fail (M4).

**A rung-1 run is judged** by the limit the result states itself: the yield fraction against 1, or
the stress against the yield it is that fraction of. No other quantity states one yet.

- `no_limit`: the result states no limit for the quantity.
- `stops`: the value is below its band; with margin, the ladder stops at rung 1.
- `climbs`: the ladder's own band check (`should_simulate`) proposes a higher rung, and `climb`
  says what happened to it: queued, routed, or only proposed.
- `fails`: `yield_fraction >= 1` (R112). `backward_loop` names the owning domain (step 1 of the
  backward loop below), or says to set `attrs.owning_domain`.

**A person's provider** is remembered as the `constraints/style` entry
`simulate <quantity> with <provider>` (author `sol`, `remembered_as`) when the run happened and the
ladder's own first choice was another. It is best effort: the run already happened.

### `get_sim_result(sim_result_id)`

A bounded read (20 rows, 8,000 characters) of one `sim_result` under the bound read scope:

- one row `{id, name, subject_id, rung, solver, created_at}`;
- one row per value, `{quantity, value, unit}`;
- one row per `leaves_out` line;
- one row per input, `{input, source, value}`: last, since a trajectory's are the long ones.

Another project's result, a deleted one, an entity of another kind or an unknown id is `not_found`.

### The routing targets (rungs 2 and 4)

`simulation/providers/external_providers.py` wraps each `simulation.targets` row as an
`ExternalTarget` provider the ladder ranks; the module names no target.

- Its tool is `<target>.run_routine`, and it is connected when the turn's registry holds that tool
  (`ExternalProviders.of(config, registered=…)`), whatever the tool's static gate: connection is
  registration (SOLUSDEV-322 P1-T3). A sibling tool of the same server never connects it.
- It lacks nothing Solus can tell (`can_answer`): the routed tool previews its own inputs. It never
  runs here: `run` raises `SimulationRefusedError`.
- A route reads `{rung, target, tool, gate: "per call", connected, status}`, where `status` is
  "call `<tool>`: it previews the run and its gate decides per call" or "not connected". The model
  calls the tool itself, through the gated dispatcher, so the call keeps that tool's own gate: its
  preview, and a card where the per-call gate (P2-T2: the ownership ledger) asks for one. The route
  never promises `requires_confirmation`; the gate does.
- **A routed call always shows its card (M1, R115).** `simulate` notes the routed tool for the turn
  (`note_routed`), and in that turn the Build policy treats that tool's call as forced confirmation
  (`BuildExecutionPolicy.prepare` asks `routed_by_simulation`): it is never owned, so the call goes
  to its card. Even an owned routine such as `isaac.run_routine`, which Build mode would otherwise
  run on its own after two identical previews, waits behind its card: the person asked to simulate,
  not to run a routine. The next turn the tool is owned again. SOLUSDEV-322 decision 2 supersedes
  this for the simulator tools, which P2-T3 made static-ungated and gated per call by the
  ownership ledger (`isaac.*` and, since P3-T4, `gazebo.*`): a routed call on a Solus-owned
  session runs without a card, on an attached one it cards; `routed_by_simulation` still guards
  the Onshape owned routines (`docs/api/isaac-development.md` §"Ownership decides the card",
  `docs/api/gazebo-integration.md`).

### The backward loop (R91, R111, R112)

1. **A failing result** names the domain that owns its fix: the subject's `attrs.owning_domain`,
   any `Domain` but `workspace`; a value that names none is logged and read as absent (fix 1,
   Minor 6). Nothing writes that attr, so a subject that states none takes the
   destination side of the cell whose rule judges the failing value (M141, P4-T5,
   `checkers/cells:fix_owner`): the yield fraction is `bracket_strength_at_joint`'s, mechanical →
   mechanical, so its fix is mechanical's, which no Solus writer makes (propose only). `simulate`
   notes each failing rung-1 result for the turn, by subject and quantity (`note_failing`), and a
   change answers only a failing result the same turn holds (R112). Without one,
   `simulate(change=…)` answers `no_failing_result` ("no failing result to fix") and judges
   nothing, and `apply_sim_change` refuses in the same words. Nor is there a loop when neither the
   attr nor a rule names an owner: `simulate(change=…)` answers `no_loop` and dry-runs nothing, and
   `apply_sim_change` refuses.
2. **SOL proposes the change** in that domain as `change`, one of:

   | `kind`       | Shape                                                                 |
   | ------------ | --------------------------------------------------------------------- |
   | `config`     | `{entity_id, path: component.<…>, value}`, a scalar, at most 6 levels |
   | `constraint` | `{subsection: rules \| compliance \| style, text}`, at most 480 chars |
   | `attr`       | `{entity_id, attr, value}`, the value at most 4 KiB as JSON           |

   **The owner selects the one writer (R111).** The dry run, the preview and the handler all read
   the same table (`OWNER_WRITERS`, through `writer_for`):

   | `owning_domain`         | The change it writes | Its writer                                                    |
   | ----------------------- | -------------------- | ------------------------------------------------------------- |
   | `runtime`, `electrical` | `config`             | `put_entity_config`: a field of the entity's own v2 config    |
   | `project`               | `constraint`         | `add_text_entry`, author `sol`: a `.solus` constraints line   |
   | any other owner         | none                 | none: `code`, `mechanical` definitions and `simulation` alike |

   Every other change (an attr; a kind its owner does not write, such as a config change of a
   `project` owner; any change of a `code`, `mechanical` or `simulation` owner) is **propose only**.
   Its text comes back for the person in the same words at every step ("Propose only: …"): the
   dry run selects no writer, the preview parks nothing, and the handler refuses.

   A config path's containing group must already exist (the `set_hardware_config_field` rule), and
   the field is recorded as set by `sol`, source `simulation backward loop`. `budgets` is a config
   document with its own route, so it is no constraint subsection here.

3. **The dry run** lays the change over a copy of the facts and has the matrix judge both stores,
   each with `run_matrix(facts=…, dry_run=True)`, which writes nothing:

   - an attr of the subject: rung 1 runs in memory on the changed attrs, and its values become the
     subject's `expected_values` (`predicted`);
   - a config field: each robot's resolved config with the part's slot (`parts.<id>.<…>`) set;
   - a style line: one more style entry; a rules or compliance line states no fact the matrix
     reads, so the facts stay as they are.

   It returns `{decision: dry_run, owning_domain, failing_result_id, change, change_text, writer,
appliable, predicted, matrix: {changed, changed_count, truncated}, apply, next}`: the verdicts that
   differ, at most 20, and the writer the owner selects, or none. A change with a writer is noted
   for the turn and `apply` holds the call to make; without one, `apply` is empty and `next` is the
   propose-only text. Since P4-T5 the two P4 rules read the expected values, so a dry run of an
   attr the bracket's rung-1 provider reads can move `bracket_strength_at_joint`'s verdict.

4. **`apply_sim_change(subject_id, quantity, change)`** is always gated: `requires_confirmation` and
   never passed to `register_owned_routine`, so no Build policy runs it without its card. In Build
   mode each call parks its card. In Guide mode the mode layer refuses the call before any card is
   built (`build_mode_dispatch`: Guide mode can explain the change, and the person switches to
   Build mode to carry it out). It also requires a complete preview, so a preview that fails
   refuses the park.
   - **The preview** shows the simulation, the owning domain, the change (a config field's before
     and after with the config version, or the constraints line) and what happens after approval.
     A propose-only change is refused with its text, and nothing is parked.
   - **One apply per turn.** In a turn the preview admits only a change that answers a failing
     result the turn holds and was dry-run in the same turn, and only one: a second is refused.
     The turn's one apply is claimed only once the card is complete (`_complete_preview`, the
     check the gate itself applies, M3), so a card that cannot show the change whole (a control
     character in the line, say) is refused and spends nothing. The ledger is keyed by the turn's
     id (`agent/turn_context.py`) and keeps 1,024 turns. The approval re-builds the preview outside
     any turn and claims nothing.
   - **The handler** runs only after the person approves. It refuses a propose-only change in the
     same words, and otherwise writes through the owner's writer (a config field on the version the
     card showed). Then it re-runs rung 1 on the subject's facts as they now are and records it:
     `{applied, rerun: {decision, sim_result_id, values, verdict}}`. A re-run that cannot happen
     says why. One that fails after the write is `rerun: {decision: failed, reason}` beside
     `applied`, and logged (M4): the change stands and is reported, never hidden behind an error.

## 9. The bounded CAD twin (P4-T4, R92, R113)

A CAD import's scene model is static: `joints` stays `[]`, since the graph holds no mate frame, and
`STATIC_REASON` is its first warning. `materialize` (`livebench/scene/cad_import.py`) adds what the
graph can say about how its leaves move and what they carry (`twin_of`):

- **`candidate_joints`**: each `mates_with` between two leaves of the import whose `mate_type` is
  `REVOLUTE` (a `revolute` candidate) or `SLIDER` (a `prismatic` one), in any case, ordered by
  feature id, at most 128. Each is `{name, type, parent, child, axis: "unknown", origin: "unknown",
mate_feature_id, actuated, actuator, limits}`. They are never in `joints`: the desktop types an
  axis as numbers, and the mapping route must never bind a signal to an axis-less joint.
- **`actuated`**: the robot's bus map, `{part_entity_id, protocol, address}`. A candidate is
  actuated when either mated leaf is a bus-mapped part, and its `limits` are then that part's
  definition `position_min`/`position_max`, `{lower, upper, unit: null, source: definition}`. A
  definition states no unit, so they never become a joint's radians or metres.
- **`sensor_sites`**: each `mounts` edge from a leaf, `{device_entity_id, link, xyz}`. `xyz` is the
  edge's `attrs.position_m` (metres, in the structure's frame) placed by the leaf's transform, or
  `unknown`. At most 128.
- **`masses`**: none. A cached mass property is never read through a live call (M138).
- **`missing`**: `mate_frame` when there are candidates, and `mass`, as `{name, set_in}`; the
  warnings say the same, and say when the bus map or the part library did not load.

An inferred edge below the candidate threshold is a proposal and is skipped. The twin only reads:
it rides the scene model `materialize` persists, and it names no CAD vendor. The rung-1 robot
provider reads a model with no joint tree but candidate joints as lacking `mate_frame`, not
`joints`, so the ladder asks for it once and then names it in its `missing_input`.

`mounts` positions stay a connector fact (M141): no Solus writer states `attrs.position_m`, so on
real data the sensor sites stay `unknown` until a connector states them.

### The twin → the generated model (SOLUSDEV-322 P6-T2)

A candidate's `axis` and `origin` are numbers when the `mates_with` edge carries the connector's
`mate_frame` (`{origin_m, x_axis, y_axis, z_axis}`, the src part's frame; P6-T1): the frame's z axis
and origin placed by the src part's assembly transform (`cad_import.placed_frame`). `missing` lists
`mate_frame` only while some candidate is still `unknown`.

`sim.generate_model{robot_id, name, source_entity_id?}` (`agent/tools/sim_generate.py`) turns the
twin into a model. It is a static card whose preview IS the gap report; approval enqueues
`run_generate_sim_model` (`simulation/model_job.py`; ARQ `timeout=300`, `max_tries=1`,
`keep_result=0`), which reads the robot's static CAD import, its placed leaves and the twin, and:

- **gap report** `{"properties": [{name, value, unit, source}], "gaps": [{name, set_in}]}`, in
  source order: `<link>.mass` from the part's cached `attrs.mass_properties.mass_kg` (`cad_mass`),
  else `attrs.material.density_kg_m3` over the closed placed mesh (`mesh_mass`), else a gap;
  `<joint>.frame` from the placed mate frame (`mate_frame`) or a gap; `<joint>.limits` in radians
  or metres from the MOVING part's (the mate's child) hardware config
  `position_min_<unit>`/`position_max_<unit>` (`user_config`), then its definition's position
  limits in the unit its position telemetry states (`definition`), else a gap (no measured range
  is read: nothing stores one); `<joint>.actuated` when the child is on the bus map (`bus_map`);
  `<link>.sensor_site` from `mounts`. Every gap names where to set the fact.
- **joints**: a mate is a moving joint only when its frame AND its limits are known. Any other
  mate, and any part no mate moves, is a `fixed` attachment keeping the CAD placement. One parent
  per child and no loop; a later mate that breaks either is a `<joint>.tree` gap. No mate able to
  move → `status: "refused"` with the gaps.
- **files**: `model.urdf` (`urdf_writer`: world-aligned link frames at the moving joint's origin,
  `<limit>` always, visual + collision mesh per link, `<inertial>` only for a known mass over a
  closed mesh), `meshes/<link>.stl` (binary), and when the physics engine builds it the compiled
  scene XML (`mjcf_compile`: child process under `limit_child`, post-processed to the compiler
  attrs and `pos`+`euler` the scene parser pins; a build failure is the gap `mjcf`). All are
  retained artifacts; `attrs.artifacts = {urdf, mjcf | null, meshes: {path: artifact_id}}` and the
  v2 `asset` manifest holds every file's sha256.
- **graph**: one `joint` entity per moving joint (kind `joint`, origin `system`, domain
  simulation, `external_ref = solus:sim-joint:<robot>:<parent>:<child>:<feature>`, attrs
  `{robot_id, type, unit, mate_feature_id, parent_part_id, child_part_id, actuator_part_id, axis,
  origin_m, lower, upper, limits_source}`, reassigned on a rerun), then the `simulation_model` v2
  through `SimulationModelService.create(origin="system", extra_attrs={robot_id, scene_model_id,
  source_entity_id, cad_microversion, requested_by, gaps, artifacts})`; its `contains` edges bind
  every part and joint. `_validate` compares only `attrs["simulation_model"]`, so the same
  definition is `status: "reused"` (its `cad_microversion` and `gaps` refreshed) and a changed one
  is a new model beside the old. The job emits `sim.model_generated`.

`sim.map_to_parts` reads the joint entities as its rung 3: a channel named after a generated
joint maps the part it moves (`actuator_part_id`, else `child_part_id`). A successful CAD refresh
re-queues the job for each system model whose `cad_microversion` is no longer the scene's
`source_revision` (`docs/api/bench-scene.md`).

## 10. The wiring (P4-T5, R97–R99)

### The matrix run asks the ladder (R97)

After the rules, `run_matrix` (`checkers/matrix_runner.py`) hands its `inconclusive` results that
state a band's `quantity`, the only ones the ladder reads, to
`should_simulate(results, trigger="rule", context=ladder_context(graph, facts, queued=…))`: at most
`MAX_LADDER_RESULTS` (64), in registry order, each costing at most one provider's `can_answer`, so
a result that states no band never crowds one out. A cap that binds is logged. `ladder_context`
(`simulation/sim_ladder.py`) holds:

- the config: `FactStore.simulation`, the shipped `simulation:` section, read once a process
  (`shipped_simulation`, which `simulate` reads too: one cache of the bands, fix 1);
- the providers: `ladder_providers(config)`, `LOCAL_PROVIDERS` (rung 1 in process, rung 3 as its
  job; the roster `simulate` and `apply_sim_change`'s `RUNG_ONE` use too) and the yaml's targets;
- `available`: `available_targets(queued=…)`, the one reading `simulate` shares (fix 1, Minor 8):
  every rung-1 provider, the rung-3 ones only when the deployment queues jobs, and no target,
  since no turn's registry holds its gated routine tool here. `jobs_queued(settings)` says whether
  it queues: a Redis URL and not inline, read off the settings the session runs under, as the
  registry's `enqueue_sim` is given (`deps.py` spells the same test inline);
- the store's `constraints/style` entries. What a person was asked is read per quantity off each
  subject (`asked_names(attrs, quantity)`, `attrs.sim_asked[quantity]`) by `should_simulate`, as
  `simulate` reads it, so a card never proposes asking again what `simulate` would not, or a run
  `simulate` would call `not_available`.

The proposals are data: `MatrixReport.proposals`, and `proposals=<n>` in the run's log line. A dry
run has them too, except one given its caller's facts (a change's dry run, `dry_run_change`): that
run is judged and no more, so no `can_answer` runs on it (fix 1, Minor 7). Nothing runs from a
run: SOL's `simulate`, inside a turn, is the only executor. `judge_matrix` (SOL's `run_checkers`)
is unchanged.

### The two rules (R94)

`bracket_strength_at_joint` and `interference_through_range` (`checkers/cells/mechanical_mechanical.py`)
judge what a simulation expects of a part (`SimulatedQuantityRule`), one verdict per entity the
store holds the quantity for:

| Rule                         | Reads                                     | `fail` (WARNING) | `inconclusive`                              | `pass`         |
| ---------------------------- | ----------------------------------------- | ---------------- | ------------------------------------------- | -------------- |
| `bracket_strength_at_joint`  | `yield_fraction`, the stress over yield   | at or past 1     | at or past the band (`yield_fraction`: 0.8) | under the band |
| `interference_through_range` | `interference_mm`, the mesh check's depth | any depth        | never                                       | no depth       |

- **The band** is the ladder's own (`facts.simulation.band(quantity)`), so a verdict is
  `inconclusive` exactly where the ladder would climb, and a bracket with margin passes. The
  bracket's `inconclusive` says "which a higher rung settles" only where a provider the ladder
  ranks computes `yield_fraction` above the value's rung (`climbs(quantity, rung, config)`), and
  "unresolved: no higher rung computes it" otherwise: the mesh check's own rung-3 value, in the
  shipped yaml (fix 1, Minor 5).
- **The evidence**, on every verdict: `{quantity, value, limit, comparator: "<=", unit,
sim_result_id, rung}`, and the bracket's `stress_mpa`. The rung is the `rung` of the `sim_result`
  the value names, read off the graph; when the graph does not hold it, `rung` is left out and the
  ladder starts from the cheapest rung.
- **With nothing simulated**, each answers ONE `unknown_input` naming the quantity to simulate,
  never one per part.
- **`fix_owner(quantity)`** (`checkers/cells/__init__.py`) names the domain a failing quantity's
  fix belongs to: the destination side of the cell whose rule judges it, as the graph names it
  (M141, §8).

### The gated actions' pre-check (R99)

- **`precheck_real_world_action(results, touched, *, context)`** (`sim_ladder.py`, pure): the same
  ladder over the `inconclusive` results whose first subject the action touches, as
  `real_world_action`.
- **`precheck_rows(session, project_id, user_id, touched, *, room)`** (`agent/tools/simulate.py`,
  amended in fix 1): the matrix judged over the touched entities' one-hop neighbourhood, under the
  person's own read scope (resolved and bound here), and one card row per proposal, at most
  `min(MAX_PRECHECK_ROWS (8), room)`, where `room` is what the card's row bound (50) leaves after
  its own rows, each line within the card's value cap (500):

  ```text
  {label: "Simulate first", before: null,
   after: "<subject>: <the ladder's reason>. Simulate <quantity> at rung <n> with <target> first
           [; it needs <inputs>] [; no job queue runs it here | ; that target is not connected]"}
  ```

  `touched` is the action's entities, or a read of them on the pre-check's session. It writes and
  runs nothing, and reads on its own connection to the caller's database under its own
  `PRECHECK_TIMEOUT_SECONDS` (3, inside the preview's 10): a query cut short invalidates its
  connection, and the caller's session may be an approval's, holding the card's row lock. A
  pre-check that fails or outlasts its timeout is logged and adds no row, and the card keeps its
  other rows; the preview's own cancellation still propagates.

- **The gate (R118).** `agent/confirmations.py:_diverged` leaves the rows labelled
  `PRECHECK_LABEL` ("Simulate first") out of its staleness check: they are advice rebuilt from
  state the action does not change, so a line that moved or vanished at approval never refuses
  the card, while a moved effect row still does. `_complete_preview` still bounds them.
- **Wired** (each card's own rows lead unchanged; its gate, descriptor, consent summary and the
  Build policy are unchanged):
  - `bench.import_cad_scene` (`agent/tools/bench_scene.py`): the robot, the CAD source and its
    occurrences;
  - `hardware.flash_presence` (`agent/tools/firmware_presence.py`, R116): the robot it flashes, its
    focus entities (`livebench/focus_scope.py:focus_entity_ids`). A full card (4 rows and 46
    source chunks) leaves no room, and parks without the line;
  - `hardware.deploy_companion` (`agent/tools/companion_deployment.py`, R116): the target it
    deploys to. No one read gives the robot whose host topology holds a target, so a line shows
    only for a band about the target itself.
- **Not wired:** `machine.write_file` and `link_environment`, since a workspace file or an
  environment is no entity a simulation expects anything of, and the `.solus` write tools.

### A rung-3 job whose simulator is missing (M140)

`run_or_flag(ctx, provider, request)` (`simulation/providers/ngspice_provider.py`) is
`run_and_record`, used by `run_ngspice_sim` and `run_mujoco_sim`. On `not_available` it also raises
the standing info finding:

```text
{rule_id: simulation_not_available, severity: info, source: simulation,
 headline: "could not simulate on the worker: <provider> is not available on this machine",
 subjects: [<subject>], evidence: {provider, rung, reason}, domain: <provider's>, bucket: <provider>}
```

One node per subject and provider, counted again on a repeat, and no `sim_result`. A subject gone
since the job was queued gets none, which is logged. A later recorded run leaves it open for a
person to dismiss. The mesh job always has its code and is unchanged.

### The envelope and the fact store

- `attrs.expected[quantity]` is the envelope's `nominal` for that quantity, `bounds_source:
{nominal: sim}`, confidence 0.8 (P2-T1). `tests/test_envelopes.py::test_expected_from_sim_result`
  pins it through `record_sim_result` and the loader.
- Ceiling: `part_envelopes` builds only the six envelope quantities (`current`, `temperature`,
  `voltage`, `position`, `velocity`, `torque`), and no provider computes one by that name. Theirs
  carry a unit (`peak_joint_current_a`), and some describe a whole scene model. A simulation's value
  is therefore in an envelope built for its own quantity only. No mapping is made: a peak over a
  model's joints is not one part's nominal.
- `FactStore.expected` serves the P4-T1 shape `{value, unit, sim_result_id}`. M126 is left to the
  final wave (§3).

### The run comparison

`compare` reads a real run against its routine's twin (docs/api/bench-runs.md, "The simulation as
the control"). It reads only what the two manifests hold, and calls no provider (R98).
