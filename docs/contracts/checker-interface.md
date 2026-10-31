# Checker Interface — Design Contract (SOLUS-CHK-01)

**Status:** Design contract + the three core rules + attribute vocabulary + a graph-traversal
helper + a seeded-bug eval. Ships `Checker`/`Warning`/`Severity`/`run_checkers`, the electrical &
temporal attribute keys the rules read, `GraphView`, the `op_amp_mismatch` /
`sensor_frequency_conflict` / `power_compatibility` rules, and the catch-rate / false-positive
eval. The warning **UI** (CHK-03/04) and connector population of the attribute keys are separate
tickets.

**Authority:** CLAUDE.md §1 (the reasoning layer reads the graph, never tool-specific raw data)

- §9 (the checker interface is a shared contract) + §7 (connector-ingested `attrs` are untrusted
  input), ADR-001 (graph-centric), ADR-003 (**checkers are pure, stateless functions — graph in,
  warnings out; heavy runs are background jobs, never the request path**), ADR-013 (robotics
  autocomplete / system-level proving / part compatibility are all this one checker library),
  ADR-028 (Week-0 shared contracts are **human-owned**). Code:
  `packages/api/src/solus_api/checkers/`.

Consumers: **CHK-03/04** renders `Warning` and **must lock its shape with this ticket** (ticket
note). **System-level proving** (SOLUSDEV area 3) runs every checker concurrently as a background
job over the full graph. **Robotics autocomplete** (area 11) runs the same rules on change.
The **SOL Agent** invokes checkers as a validated tool and re-explains each `Warning` per the
user's SOL mode.

> ⚠ **Staging note (flag for the founders):** CLAUDE.md §9 lists the checker interface as a shared
> contract and ADR-028 makes `packages/contracts/` **human-owned**. This contract is therefore
> **staged inside `solus-api`** (mirroring how the connector contract was staged), not written to
> `packages/contracts/`. Promotion — locked together with the CHK-03/04 warning UI — is a human
> follow-up.

---

## 1. The shapes (`checkers/interface.py`)

```python
class Severity(StrEnum):          # ordered by REAL-WORLD impact, not style
    INFO      = "info"            # advisory
    WARNING   = "warning"         # degraded / unreliable (aliasing, a marginal op-amp)
    CRITICAL  = "critical"        # won't work or may be damaged (wrong voltage, under-rated supply)

severity_rank(s) -> int           # higher = more severe; use to sort/compare

class Warning(BaseModel):         # frozen + extra="forbid" — an immutable, closed value object
    checker_id:     str           # which rule produced it, e.g. "op_amp_mismatch"
    severity:       Severity
    domains:        tuple[str, ...]   # spanned domains, DERIVED from the entities implicated
    message:        str               # human summary (SOL may re-explain per mode)
    evidence:       dict[str, Any]    # structured WHAT/WHY for the UI + debugging
    entity_ids:     tuple[UUID, ...]  # graph entities implicated (UI highlight / focus)
    suggested_area: str | None        # where to look / what to change

class Checker(abc.ABC):
    checker_id: ClassVar[str]
    domains:    ClassVar[tuple[str, ...]]   # the rule's INTENDED span
    def check(self, graph: GraphContext, parts: FingerprintOutput,
              facts: FactStore | None = None) -> list[Warning]: ...   # a rule that reads no facts ignores them

run_checkers(graph, parts, checkers) -> list[Warning]   # fan rules over one graph, most-severe first
```

The interaction-matrix rules (SOLUSDEV-321 P3) build on that contract:

```python
class MatrixRule(Checker):                  # checkers/matrix_rule.py
    rule_id:     ClassVar[str]              # also its checker_id
    matrix_cell: ClassVar[MatrixCell]       # one of the nine src->dst cells; its domains derive from it
    needs:       ClassVar[Needs] = Needs()  # rule_base.Needs; needs.facts are FactNeed{name, set_in}
    def evaluate(self, graph, facts: FactStore) -> list[RuleResult]: ...   # the pure rule
    @final results(graph, facts) -> list[RuleResult]   # what a runner calls: an unmet needs.facts → ONE unknown_input, else evaluate()
    @final check(graph, parts, facts=None) -> list[Warning]   # ONLY status == "fail" → Warning

@dataclass(frozen=True, kw_only=True)   # keyword-only: RuleResult(status=..., message=..., ...)
class RuleResult:
    status:   Literal["pass", "fail", "inconclusive", "unknown_input"]
    message:  str
    severity: Severity = INFO
    subjects: tuple[UUID, ...] = ()        # blame order; the Warning's entity_ids
    edge_ref: EdgeRef | None = None        # (src_id, dst_id, relation_type): an EdgeRead has no id
    evidence: Mapping[str, Any] = {}
    missing:  FactNeed | None = None       # required on unknown_input

FactStore    # checkers/fact_store.py; build_fact_store(session, project_id, graph) once per run:
             # definitions · runtime_configs · budgets · scene_joints · pcb_positions ·
             # software_environments · divergences · style · expected_values ·
             # motifs · rc_settling_s · proximity_clearance_mm · module_interfaces;
             # has(name) · part_config(part_id) · expected(part_id, quantity)
CheckerResult  # checkers/checker_results.py: one item of an edge's attrs.checker_results,
               # {rule_id, status, severity, message, evidence, at}, at ISO-8601 UTC
```

**Invariants every checker upholds (verified by the shared tests):**

1. **Pure & stateless** (ADR-003) — no I/O, no input mutation, deterministic. Event emission and
   persistence belong to the job/route that _calls_ `run_checkers`, never inside a rule.
2. **Graceful degradation → no false positives** — when an attribute a comparison needs is absent
   or malformed, the rule **skips** that comparison rather than guessing. An incomplete graph
   raises nothing (proven by the `incomplete_graph` eval control).
3. **`Warning.domains` is derived** from the entities a finding actually implicates (via
   `domains_of`), so a bus-saturation finding is `("electrical",)` while an under-sampling finding
   spanning code + circuit is `("code", "electrical")`.
4. **Only a `fail` is a `Warning`.** A matrix rule that lacks a fact says `unknown_input` (naming
   the fact and where a person states it), one whose facts do not settle it `inconclusive`; neither
   — nor `pass` — ever becomes a `Warning`, so `run_checkers`, impact and the eval's clean
   controls stay silent whatever facts are missing. The matrix runner (P3-T3) keeps every result:
   on the edge through `annotate_edge` (`docs/api/relations.md` §2) and as `info` findings.
5. **Facts come from the graph and configs only.** `build_fact_store` reads the run's
   `GraphContext` (built through `to_graph_context`, so no candidate edge) and the project's config
   entries — never a model call, never a vendor or connector name (`test_vendor_hygiene_api.py` and
   `test_capability_hygiene.py` sweep `checkers/`).

## 2. Graph access (`GraphContext`, reused from `agent/interfaces.py`)

Checkers consume the **same serializable `GraphContext`** the reasoning layer uses — `EntityRead`
(`id`, `kind`, `domain`, `name`, `attrs`, `canonical_part_id`, …) and `EdgeRead`
(`src_id`, `dst_id`, `relation_type`, `domain_pair`, …). `checkers/traversal.py::GraphView`
indexes it once per `check`: `entity(id)` and `edges_of_type(relation)` → resolved `(src, dst)`
pairs, **dropping dangling edges** so a half-ingested graph never crashes a rule.

`parts: FingerprintOutput` is in the signature so a rule MAY resolve a canonical part's datasheet
attributes; v1 reads attributes straight off the graph entities the connectors populate.

## 3. Attribute vocabulary (`checkers/attributes.py`)

`attrs` is untrusted, connector-ingested data (§7). Extractors are **total & defensive**:
`attr_float` / `attr_str` / `part_class` **coerce** to a clean value or `None`, never raise, and
reject `bool` as a number (`True` must not read as `1.0 V`). No connector populates these keys yet
— **this module is the spec the EDA connectors (KiCad / SPICE / Altium) must honour.**

| Group                   | Keys                                                                       |
| ----------------------- | -------------------------------------------------------------------------- |
| classification          | `part_class` ∈ {`op_amp`,`sensor`,`supply`,`load`,`bus`}                   |
| op-amp capability       | `gbw_hz`, `output_current_max_a`, `supply_v_min`, `supply_v_max`           |
| driven-load requirement | `required_gbw_hz`, `required_output_current_a`, `required_supply_v`        |
| supply                  | `voltage_nominal_v`, `voltage_tolerance_pct` (default 5%), `current_max_a` |
| power load              | `voltage_required_v`, `current_draw_a`                                     |
| sensor / timing         | `sample_rate_hz`, `min_sample_rate_hz`, `bus_max_hz`                       |
| code / control loop     | `loop_rate_hz`                                                             |
| relations traversed     | `wires`, `reads`, `powers`, `connected_to` (the contracts' `RelationType`) |

## 4. The three rules (`checkers/core.py`)

| `checker_id`                | Walks                                       | Flags                                                   | Severity   |
| --------------------------- | ------------------------------------------- | ------------------------------------------------------- | ---------- |
| `op_amp_mismatch`           | `op_amp --wires-- load` (the `op_amp` end)  | GBW below required                                      | `WARNING`  |
|                             |                                             | output current below required                           | `CRITICAL` |
|                             |                                             | required supply V outside the op-amp's `[v_min, v_max]` | `CRITICAL` |
| `sensor_frequency_conflict` | `code --reads--> sensor` (confirmed, ≥ 0.8) | loop rate below the sensor's Nyquist floor (aliasing)   | `WARNING`  |
|                             |                                             | loop rate above the sensor's sample rate (stale reads)  | `WARNING`  |
|                             |                                             | sample rate above the bus max (dropped samples)         | `CRITICAL` |
| `power_compatibility`       | `supply --powers--> load(s)`                | load voltage outside the supply's tolerance band        | `CRITICAL` |
|                             |                                             | summed load current above the supply's rating           | `CRITICAL` |

`op_amp_mismatch` emits **one warning per bad pairing**, aggregating every failed dimension at the
worst severity. The frequency and power rules emit **one warning per distinct conflict**
(`evidence["conflict"]` names it). `DEFAULT_CHECKERS` / `run_all(graph, parts)` run all three,
most-severe first.

**Roles (SOLUSDEV-321 P3-T2: the rules read the real relation vocabulary).** Where an edge has a
direction it gives the roles: `reads` reader → sensor, `powers` supply → load. A `wires` edge has
none (the netlist inference writes one edge per unordered pair), so the op-amp is the end whose
`part_class` is `op_amp` and the load is the other; a wire with no op-amp end, or two, is skipped,
and so is a wire whose nets are all supply rails or ground (a power connection, not a signal path).
An inferred `reads` edge is written at 0.55, a candidate `to_graph_context` hides: the sensor rule
reads only `reads` edges at the candidate threshold (0.8) or above and declares
`needs = Needs(relations=("reads",))`, so until a person confirms one it raises nothing. Beyond
the op-amp role, `part_class` is **advisory** classification metadata for the UI/agent; a
comparison only runs when the specific attributes it needs are present and valid. The pre-vocabulary
`drives` (op-amp → load) and `reads_from` are retired from `attributes.py`.

**The pin conflict moved into the matrix.** `package_version_conflict`
(`checkers/cells/software_software.py`) raises a package the dependency files pin differently,
read through `checkers/environment.py:pin_conflicts`. `PinConflictChecker` (`python_pin_conflict`)
is therefore not in `DEFAULT_CHECKERS`, so one conflict is raised once. The checker stays for the
code-environment proposal (`propose_environments`, `docs/api/code-environment.md`), whose
`conflicts` are still `python_pin_conflict` warnings with their `suggested_area`.

**Untrusted-input hardening (§7).** `attrs` is attacker-influenceable. The extractors reject
non-finite (`nan`/`inf`) and negative physical values, and the op-amp rule skips inverted
`[v_min, v_max]` bounds — a single malformed attribute can neither fabricate a spurious CRITICAL
nor silently disarm a real one. The `malicious_attrs` eval control locks this in.

## 5. The eval (`tests/test_checker_graphs.py` + `tests/fixtures/checker_graphs.py`)

Seeded-bug fixtures (wrong op-amp, sensor-frequency clash, under-rated supply, wrong supply
voltage) + clean controls (matched parts, an **incomplete** graph, an **unrelated** graph, the
**malicious attrs** of §4) drive a **catch rate** and a **false-positive rate**. Current result:
**100% catch (4/4), 0% false positives (0/6)**. Add a fixture here whenever a rule gains a
dimension.

## 6. Extending the library

Declare a `Checker` subclass with a `checker_id` + `domains`, add its keys to
`attributes.py` (never inline magic strings), add it to `DEFAULT_CHECKERS`, and add a seeded-bug +
clean fixture. The library scales **by addition, not modification** — that is the whole point of
the pure-function shape (ADR-013).

**A matrix rule** subclasses `MatrixRule` in its cell's module (`checkers/cells/<src>_<dst>.py`):
set `rule_id`, `matrix_cell` and the `needs.facts` it reads — each a `FactNeed` whose `name` is a
`FactStore` field (`FACT_NAMES`) and whose `set_in` says, in words, where a person states it — and
implement `evaluate`. It returns a `RuleResult` per judgement, names an edge it judged by
`EdgeRef.of(edge)`, and answers `unknown_input` with `missing` rather than guessing when a fact
for one entity is absent. The base answers the store-wide unmet fact and the `Warning` mapping;
`results` and `check` are final. A runner calls `results`, never `evaluate` directly — that would
skip the unmet-fact guard. The base guards only `needs.facts`: an unmet `needs.relations` or
`needs.channels` (a `reads` edge not yet confirmed) is the rule's own `unknown_input`, with a
`FactNeed` naming it. A fact no source states yet is still declared (its `FactNeed`
names no store field, so the rule reports `unknown_input` with its hint until one does); a new
fact is a new `FactStore` field read in `build_fact_store` from the graph or a config entry.

**The matrix (SOLUSDEV-321 P3-T2).** The 36 rules live in `checkers/cells/<src>_<dst>.py`, one
module per cell, each holding its rules in `RULES`. `checkers/cells/__init__.py` registers them
as `MATRIX_RULES` (each cell's rules, in `MatrixCell` order) and `RULES_BY_ID`.

- **Judging today (twelve):** `package_version_conflict`, `pin_in_code_vs_wiring`,
  `commanded_range_vs_joint_limit`, `pin_capability_vs_firmware_use`, `power_budget`,
  `joint_limit_vs_code_constant`, since P3-T4 `sample_rate_vs_adc_settling`, `proximity_pair` and
  `wall_too_thin`, since P4-T5 `interference_through_range` and `bracket_strength_at_joint`, and
  since SOLUSDEV-321 P6 `module_contract_mismatch`.
- **Waiting (25):** the rest subclass `UnstatedFactRule`. One of its facts names no `FactStore`
  field, so the rule answers `unknown_input` naming that fact until a source exists.
- **Beyond the 36 (R76).** A cell may register a rule the spec's table does not list. Since
  P3-T4, mechanical → mechanical also holds the manufacturing rule `wall_too_thin`, so 37 are
  registered. The registry test asserts the 36 by id and lists the extras.
- **Shared helpers:**
  - `confirmed_edges`: an edge at the candidate threshold or above;
  - `relation_gap`: the rule's own `unknown_input` for an unmet `needs.relations`, naming where
    the relation comes from;
  - `unknown_input`;
  - the wiring readers: `wired_pins`, and `wires_by_endpoint`, which indexes the `wires` edges by
    endpoint once an evaluation, so that each read looks up only its own part's (R79).
- **On an empty graph and empty facts,** every rule answers exactly one `unknown_input`
  (`tests/test_matrix_registry.py`, whose ids are the rule table: `cell|rule_id|field`).
  Every rule's `unknown_input` is worded by the one helper, the base's included.

**Netlist motifs (SOLUSDEV-321 P3-T4).** `checkers/netlist_motifs.py:detect_motifs(graph) ->
tuple[NetMotif, ...]` is pure (R57): graph in, motifs out, with no model and no I/O.

- **Inputs.** It reads:
  - the schematic connector's `component` and `net` entities;
  - the `connected_to` edges between them: a component's pins on a net, and the export's pin
    functions;
  - the confirmed `reads` edges, which say the code samples a net.
- **Roles.** A part's role comes from its reference designator's letter (R, C, Q, U) and its
  `value`, read with SI prefixes (`si_value`: `10k`, `4k7`, `100nF`). A net is a rail or a ground
  by the power inference's names. A net name or pin function says "analog input" only through a
  whole token, split on anything not a letter or a digit: `ADC0`, `AIN3`, `ANALOG`, or `SENSE`
  or `MEAS` with an optional V or I before it (`VSENSE`). So `VBAT_AIN0` says it, and
  `HEADCAM_EN` and `MEASURE_EN` do not. `PRESENCE_SENSE` does: a name alone cannot tell a
  presence line from a voltage sense.
- **The five shapes.**
  - `divider_adc`: R_top from a source and R_bottom to ground meet at a net an IC pin is on. Its
    RC is R_top‖R_bottom with the capacitance to ground there.
  - `rc_on_input`: one series R into an IC pin's net and C from it to ground. Its RC is R · C.
  - `decoupling_at_pin`: C from a rail to ground at the rail an IC is powered from.
  - `h_bridge`: two half bridges on one rail and ground.
  - `level_shifter`: a transistor between two signals, each pulled up to its own rail.
- **Confidence.**
  - `CONFIDENT` (0.9) when the role is evidenced: a read samples the input, or a pin function or
    net name says ADC; exactly one IC is on a decoupled rail; a load sits across a bridge.
  - `DISTINCT` (0.8) for a bridge whose shape alone settles it.
  - `CANDIDATE` (0.6) when nothing evidences the role. A level shifter is always one: nothing
    beyond its shape says it shifts levels.
  - A motif at `LABEL_THRESHOLD` (0.7) or below is a candidate for a person's SOL turn to label
    (`label_motifs`). No rule reads one.
- **Bounds (R79).** There is no all-pairs scan.
  - A net's ICs are looked up once, and so is its pull-up.
  - At most `MAX_SUPPLY_HALVES` (32) half bridges of one supply are paired.
  - A signal net holding more than `MAX_SHIFTER_NET_PARTS` (64) parts is no level shifter's: the
    search skips it.
  - Each cap is logged when it binds.

**The facts the two P3-T4 rules read (R73).** `FactStore.motifs` holds the run's one detection.

- `rc_settling_s` maps each member of a settled ADC input to an `RcSettling(net_id, r_ohm, c_f)`,
  whose `tau_s` is R · C. A member two inputs share maps to neither.
- `proximity_clearance_mm` is the largest lower bound (`>=` or `>`) in millimetres that a live
  `constraints/rules` entry states for `quantity: proximity_clearance_mm`.

**The two rules made runnable by P3-T4.**

- **`sample_rate_vs_adc_settling`** judges each confirmed `reads` edge.
  - It reads the RC of the input its target sits on (`rc_settling_s`), and the code entity's
    `loop_rate_hz`.
  - It fails (WARNING) when 5 · RC exceeds the sample period 1 / `loop_rate_hz`, and passes
    otherwise.
  - A missing RC or rate is that edge's `unknown_input`.
- **`proximity_pair`** judges an aggressor and a victim by the distance between their footprint
  positions (`pcb_positions`), against the clearance.
  - The pairs are a switcher with precision analog, and a heat source with a capacitor.
  - Roles come from the behaviour class (attrs, else the definition's) or from a settled motif:
    an H-bridge's parts switch, and a divider's or RC input's parts are precision analog.
  - It fails (WARNING) inside the clearance and passes outside it.
  - Bounds (R79): each role keeps its first `MAX_ROLE_PARTS` (256) parts, logged when it binds.
    The pairs are generated lazily, and `heapq.nsmallest` keeps only the nearest `MAX_PAIRS` (64).
  - Positions on two boards of one project are compared as one board, a ceiling.

**The two rules made runnable by P4-T5** judge what a simulation expects of a part, through
`FactStore.expected` (`attrs.expected`, which `record_sim_result` writes). They subclass
`SimulatedQuantityRule` (`checkers/cells/__init__.py`): one verdict per entity the store holds the
quantity for, and with none ONE `unknown_input` naming the quantity to simulate.

- **`bracket_strength_at_joint`** reads `yield_fraction`, the simulated stress over the yield it is
  judged against. It fails (WARNING) at or past 1, is `inconclusive` at or past the ladder's own
  band for the quantity (`FactStore.simulation.band`, 0.8 by default), and passes under it.
- **`interference_through_range`** reads `interference_mm`, the depth the mesh check found over the
  poses it sampled. Any depth fails (WARNING), and none passes.
- **The band keys (R94).** Every verdict's evidence is `{quantity, value, limit, comparator: "<=",
unit, sim_result_id, rung}`, the bracket's with its `stress_mpa`. `rung` is the rung of the
  `sim_result` the value names, read off the graph, and it is left out when the graph does not hold
  that result. The simulation ladder reads these keys off an `inconclusive` result
  (docs/api/simulation.md §2, §10).
- **`FactStore.simulation`** holds the shipped `simulation:` section of models.yaml. It is
  configuration, not a fact: `FACT_NAMES` leaves it out, so no rule waits for it.
- **`fix_owner(quantity)`** names the domain that owns a failing simulated quantity's fix: the
  destination side of the cell whose rule judges it, `software` read as `code` (M141).

**The module contract (SOLUSDEV-321 P6).** `module_contract_mismatch` (software → software)
compares what a policy acts with against what the controller it feeds takes.

- **The facts.** `software/policy_reader.py:read_policy(path, text)` is pure and framework-neutral:
  it reads Python with `ast.parse` only (a `Box(..., shape=(n,))` assigned to a name ending
  `action_space` or `observation_space`) and YAML or JSON through the capped, alias-refusing
  safe loader, which keeps each key's line (`action_dim`/`obs_dim`, an
  `action_space`/`observation_space` with a `shape`, `output_features`/`input_features` with one
  1-D feature, and each mapping beneath a key that names a controller with its `joints`,
  `input_dim` or `command_dim`). A ref is the line of the key that states the interface, in the
  mapping that states it. A checkpoint path is recorded and never opened. A dimension that is not
  a literal integer is None and named in `ambiguous`.
- **Where they land.** A code-host sync reads the candidate files (`connectors/code_content.py`:
  `.py`, `.yaml`, `.yml` or `.json` whose name or directory names a policy, a controller, an
  environment or a config, at most `MAX_POLICY_READS` (16) within the sync's 64 reads, no model
  call) and writes each file's interfaces on its entity as `attrs.module_interfaces`. A local
  folder's files are not shipped by the companion, so it states none yet.
- **The store.** `FactStore.module_interfaces` maps each holder to a `ModuleFacts`: its
  `source_id`, from one project-scoped lookup, and its `interfaces`, the items that validate as
  `ModuleInterface`, at most 16 an entity. A run loads holders with the fact kinds, under the same
  entity cap.
- **The rule.** Which controller a policy feeds is stated nowhere, so a source is judged only
  when its controllers all take one width. Controllers of more than one width (an arm and a
  gripper, say) answer ONE `unknown_input` for the "policy and controller pairing", naming the
  policy and controller files, and never a fail (I1). Otherwise each policy with stated outputs is
  compared with each controller: unequal fails (WARNING), for example "`config/policy.yaml`'s
  action space is 6 wide but `config/controller.yaml` takes 7 inputs", and equal passes. The
  subjects are the policy file then the controller file. The evidence keys are `policy_ref`,
  `action_dim`, `controller_ref` and `input_dim`. An unsettled dimension answers `unknown_input`
  naming its field at its `path:line`, and an unsettled controller leaves the source unjudged. A
  source that states only one side answers `unknown_input` for the other.

**Manufacturing rules (R76).** `checkers/manufacturing_rules.py` judges whether a part can be made
as drawn by the process the project intends for it. Its rules are MatrixRule-shaped and sit in
the mechanical → mechanical cell.

- **Process intent** (`process_intent(part, style)`).
  - The process is the part's own `attrs.process` when its CAD states one. Otherwise it is the
    process that an applying `constraints/style` entry's words name, from a closed list
    (`PROCESSES`: `fdm`, `sla`, `sls`, `cnc`, `sheet_metal`, `injection_molding`, `laser_cut`).
  - The minimum wall is that entry's bound: `quantity: min_wall_thickness_mm`, `>=` or `>`, unit
    mm.
  - An entry scoped to the part wins over a project-wide one. A project-wide entry that names
    another process does not apply, and one naming the part's process wins over a neutral one.
  - A part that states no process takes a project-wide minimum only when every applying entry
    states the same one. When they differ (FDM 1.2 mm, CNC 0.5 mm), the part's minimum depends on
    its process, so the rule answers that part's `unknown_input` naming `process`.
- **`wall_too_thin`** reads the part's `wall_thickness_mm`.
  - With no part stating one, it answers ONE `unknown_input` naming it, never one per part. No
    connector writes it yet.
  - A part with a thickness but no applying minimum is that part's `unknown_input`, naming
    `min_wall_thickness_mm`.
  - Otherwise it fails (WARNING) under the minimum and passes at or above it.

**The run (SOLUSDEV-321 P3-T3).** `checkers/matrix_runner.py:run_matrix(session, project_id, *,
cells=None, facts=None, dry_run=False) -> MatrixReport` reads the project ONCE, through
`to_graph_context`. It holds at most `MAX_MATRIX_ENTITIES` (5,000) entities, and at most
`MAX_EDGE_SCAN` edges of the relations the rules declare (`RUN_RELATIONS`). Under the entity cap it
keeps, in order:

1. the fact kinds (robots, scene models, components, requirements);
2. the entities a judged relation touches;
3. the nets, which feed only the motifs, so the motifs degrade first;
4. the rest.

It builds one
`FactStore` from that read and calls `judge_matrix`, the pure part. `judge_matrix` runs each
requested cell's rules through `results()` and maps each `fail` through `MatrixRule.warning`.

- **What it keeps.** The run writes the edges' `checker_results` (`docs/api/relations.md` §2) and
  the findings (`docs/api/findings.md` §5). A rule whose `raises_findings` is False keeps its
  `fail` on the edge and in the report only: its problem is another producer's finding (R60).
- **The netlist (R74).** A second read takes the schematic's `connected_to` edges, which the motifs
  and an input's RC come from. It is bounded by `MAX_EDGE_SCAN` too, and either read past its cap
  marks the run truncated, which is logged. These edges feed the fact store only: no rule judges
  them, and no `checker_results` is written on them.
- **The motifs (R78).** After the results, the run keeps each motif on its members' `attrs.motifs`
  as `{kind, members, confidence}`, most confident first, at most 16 a member.
  - It writes through `netlist_motifs.write_motifs`: a fresh read with `SKIP LOCKED`, under the
    project lock, `attrs` reassigned. It writes only the entities whose list moved, and an entity
    that left every motif loses the key.
  - A row another writer holds is skipped and logged, counted in `MatrixReport.motifs_skipped`;
    the next run keeps it. Motifs publish nothing.
  - A run whose read was truncated detects no motifs and keeps none, because a net cut short
    could settle a wrong RC. It logs that, and the members keep what the last whole run wrote.
- **The labels.** A model's label lives under its own key, `attrs.motif_labels`:
  `{kind, members, confidence, labelled_by: "model", turn_id}`. Only `label_motifs` writes it.
  The run never rewrites it, and no rule reads it.
- **Ceiling (M118).** A connector re-sync rewrites a synced entity's `attrs`, so it drops both keys.
  The next run puts the motifs back; nothing puts the labels back. A label also outlives a motif
  that is gone, until that re-sync.
- **What writes nothing.** A dry run, or a run given its own `facts`, returns the report and
  writes nothing.
- **The simulation ladder (P4-T5, R97).** After the rules, the run's `inconclusive` results that
  state a band's `quantity`, at most `MAX_LADDER_RESULTS` (64), go to `should_simulate` as
  `rule`, over `sim_ladder.ladder_context`. Its proposals are data on `MatrixReport.proposals` and a count in
  the run's log line, a dry run's too, but not a run given its own `facts` (a change's dry run,
  P4-T5 fix 1), which is judged and no more. Nothing runs from a run: SOL's `simulate` acts on a
  proposal inside a turn.
- **Who calls it.** `checkers/checker_trigger.py` runs it after every graph change, debounced 10 s
  per project, as the ARQ job `run_matrix_checkers` or inline. SOL's `run_checkers` calls
  `judge_matrix` on its own slice (a dry run).
