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
    def check(self, graph: GraphContext, parts: FingerprintOutput) -> list[Warning]: ...

run_checkers(graph, parts, checkers) -> list[Warning]   # fan rules over one graph, most-severe first
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
| relations traversed     | `drives`, `reads_from`, `powers`, `connected_to`                           |

## 4. The three rules (`checkers/core.py`)

| `checker_id`                | Walks                         | Flags                                                   | Severity   |
| --------------------------- | ----------------------------- | ------------------------------------------------------- | ---------- |
| `op_amp_mismatch`           | `op_amp --drives--> load`     | GBW below required                                      | `WARNING`  |
|                             |                               | output current below required                           | `CRITICAL` |
|                             |                               | required supply V outside the op-amp's `[v_min, v_max]` | `CRITICAL` |
| `sensor_frequency_conflict` | `code --reads_from--> sensor` | loop rate below the sensor's Nyquist floor (aliasing)   | `WARNING`  |
|                             |                               | loop rate above the sensor's sample rate (stale reads)  | `WARNING`  |
|                             |                               | sample rate above the bus max (dropped samples)         | `CRITICAL` |
| `power_compatibility`       | `supply --powers--> load(s)`  | load voltage outside the supply's tolerance band        | `CRITICAL` |
|                             |                               | summed load current above the supply's rating           | `CRITICAL` |

`op_amp_mismatch` emits **one warning per bad pairing**, aggregating every failed dimension at the
worst severity. The frequency and power rules emit **one warning per distinct conflict**
(`evidence["conflict"]` names it). `DEFAULT_CHECKERS` / `run_all(graph, parts)` run all three,
most-severe first.

**Roles are inferred from the edge `relation_type`** (`drives`→driver, `reads_from`→reader/sensor,
`powers`→supply/load), _not_ gated on `part_class` — so a rule still fires on a graph a connector
labelled with edges but not `part_class`. `part_class` is **advisory** classification metadata for
the UI/agent; a comparison only runs when the specific attributes it needs are present and valid.

**Untrusted-input hardening (§7).** `attrs` is attacker-influenceable. The extractors reject
non-finite (`nan`/`inf`) and negative physical values, and the op-amp rule skips inverted
`[v_min, v_max]` bounds — a single malformed attribute can neither fabricate a spurious CRITICAL
nor silently disarm a real one. The `malicious_attrs` eval control locks this in.

## 5. The eval (`tests/test_checker_graphs.py` + `tests/fixtures/checker_graphs.py`)

Seeded-bug fixtures (wrong op-amp, sensor-frequency clash, under-rated supply, wrong supply
voltage) + clean controls (matched parts, an **incomplete** graph, an **unrelated** graph) drive a
**catch rate** and a **false-positive rate**. Current result: **100% catch (4/4), 0% false
positives (0/5)**. Add a fixture here whenever a rule gains a dimension.

## 6. Extending the library

Declare a `Checker` subclass with a `checker_id` + `domains`, add its keys to
`attributes.py` (never inline magic strings), add it to `DEFAULT_CHECKERS`, and add a seeded-bug +
clean fixture. The library scales **by addition, not modification** — that is the whole point of
the pure-function shape (ADR-013).
