# Cowork QA — Compatibility Checkers Core (SOLUSDEV-115 / SOLUS-CHK-01)

This ticket delivers the **cross-domain compatibility checker library** — pure-function rules that
run over the linked graph and emit structured `Warning`s. It is a **backend reasoning library**:
there is **no API route and no UI in this ticket** (the warning UI is CHK-03/04; system-proving
that runs these as a background job is a separate area). So this QA exercises the library directly
through Python, plus the automated test/eval suite. A tester needs only the repo and its Python
environment.

## Setup

1. Repo at `/Users/mehdihdev/Solus`, on branch `SOLUSDEV-115-compatibility-checkers-core`.
2. Python env is the workspace venv at `/Users/mehdihdev/Solus/.venv` (Python 3.12). All commands
   below use it explicitly. No database, Redis, secrets, or network are required — the checkers are
   pure functions over in-memory graph objects.
3. No accounts, connected sources, or seeded DB data needed.

Run everything from the repo root.

---

## Flow 1 — Automated suite is green

**Steps**

1. Run the checker unit + contract tests:
   `.venv/bin/pytest packages/api/tests/test_core.py packages/api/tests/test_traversal.py packages/api/tests/test_interface.py packages/api/tests/test_attributes.py -q`
2. Run the full API suite (regression):
   `.venv/bin/pytest packages/api/tests -q`

**Expected**

- Step 1: all tests pass (41: 17 core + 7 traversal + 17 interface/attributes).
- Step 2: **385 passed** (1 pre-existing unrelated JWT key-length warning in `test_security.py`).

- [ ] Flow 1 passes

## Flow 2 — The seeded-bug eval reports catch rate + false-positive rate

**Steps**

1. `.venv/bin/pytest packages/api/tests/test_checker_graphs.py -q -s`

**Expected** — the printed report shows:

- Each seeded bug `CAUGHT` by its rule: `wrong_op_amp`→`op_amp_mismatch`,
  `sensor_frequency_clash`→`sensor_frequency_conflict`, `under_rated_supply` &
  `wrong_supply_voltage`→`power_compatibility`.
- Each clean control (`clean_op_amp`, `clean_sensor`, `clean_supply`, `incomplete_graph`,
  `unrelated_graph`) reports `warnings=0 -> ok`.
- Final line: `catch_rate=100% (4/4)  false_positive_rate=0% (0/5, 0 spurious)`.

- [ ] Flow 2 shows 100% catch, 0% false positives

## Flow 3 — Op-amp mismatch rule (happy path + bug)

Run a Python snippet with `.venv/bin/python -`:

```python
from uuid import uuid4
from solus_api.agent.interfaces import EdgeRead, EntityRead, GraphContext
from solus_api.checkers import attributes as av
from solus_api.checkers.core import run_all
from solus_api.fingerprint.contract import FingerprintOutput

def e(name, attrs): return EntityRead(id=uuid4(), kind="component", domain="electrical", name=name, attrs=attrs)
def edge(s, d, r): return EdgeRead(src_id=s.id, dst_id=d.id, relation_type=r, domain_pair="electrical<->electrical", confidence=1.0)
parts = FingerprintOutput(canonical_parts=[], unmatched=[], ambiguous=[])

# BUG: slow, weak op-amp driving a fast/high-current stage
op = e("LM358", {av.PART_CLASS: av.OP_AMP, av.GBW_HZ: 1_000_000, av.OUTPUT_CURRENT_MAX_A: 0.04})
load = e("driver", {av.PART_CLASS: av.LOAD, av.REQUIRED_GBW_HZ: 10_000_000, av.REQUIRED_OUTPUT_CURRENT_A: 0.25})
g = GraphContext(entities=[op, load], edges=[edge(op, load, av.DRIVES)])
for w in run_all(g, parts):
    print(w.severity.value, w.checker_id, "|", w.message, "|", w.domains)
```

**Expected**

- Exactly one warning, `checker_id="op_amp_mismatch"`, severity `critical` (output-current failure
  dominates the bandwidth WARNING), message names the op-amp and the load, `domains=("electrical",)`.
- Change `GBW_HZ` to `40_000_000` and `OUTPUT_CURRENT_MAX_A` to `0.5` → **no warnings** (compatible).

- [ ] Bug flagged; fixed part produces nothing

## Flow 4 — Sensor-frequency conflict (cross-domain)

```python
from uuid import uuid4
from solus_api.agent.interfaces import EdgeRead, EntityRead, GraphContext
from solus_api.checkers import attributes as av
from solus_api.checkers.core import run_all
from solus_api.fingerprint.contract import FingerprintOutput
parts = FingerprintOutput(canonical_parts=[], unmatched=[], ambiguous=[])

imu  = EntityRead(id=uuid4(), kind="component", domain="electrical", name="imu",
                  attrs={av.PART_CLASS: av.SENSOR, av.SAMPLE_RATE_HZ: 1000, av.MIN_SAMPLE_RATE_HZ: 100, av.BUS_MAX_HZ: 400})
loop = EntityRead(id=uuid4(), kind="module", domain="code", name="control_loop.cpp",
                  attrs={av.LOOP_RATE_HZ: 50})
g = GraphContext(entities=[imu, loop],
                 edges=[EdgeRead(src_id=loop.id, dst_id=imu.id, relation_type=av.READS_FROM, domain_pair="code<->electrical", confidence=1.0)])
for w in run_all(g, parts):
    print(w.severity.value, w.evidence.get("conflict"), "|", w.domains)
```

**Expected** — two warnings:

- `warning  undersampling  | ('code', 'electrical')` (50 Hz poll below the 100 Hz Nyquist floor — spans **both** domains).
- `critical bus_saturation | ('electrical',)` (1000 Hz sample rate exceeds the 400 Hz bus).

- [ ] Undersampling spans code+electrical; bus saturation is electrical + critical

## Flow 5 — Power compatibility (voltage + current budget)

```python
from uuid import uuid4
from solus_api.agent.interfaces import EdgeRead, EntityRead, GraphContext
from solus_api.checkers import attributes as av
from solus_api.checkers.core import run_all
from solus_api.fingerprint.contract import FingerprintOutput
def e(n, a): return EntityRead(id=uuid4(), kind="component", domain="electrical", name=n, attrs=a)
def edge(s, d): return EdgeRead(src_id=s.id, dst_id=d.id, relation_type=av.POWERS, domain_pair="electrical<->electrical", confidence=1.0)
parts = FingerprintOutput(canonical_parts=[], unmatched=[], ambiguous=[])

sup = e("buck_5v_2A", {av.PART_CLASS: av.SUPPLY, av.VOLTAGE_NOMINAL_V: 5.0, av.CURRENT_MAX_A: 2.0})
a   = e("jetson",     {av.VOLTAGE_REQUIRED_V: 5.0,  av.CURRENT_DRAW_A: 3.0})
b   = e("radio",      {av.VOLTAGE_REQUIRED_V: 12.0, av.CURRENT_DRAW_A: 1.5})   # also wrong voltage
g = GraphContext(entities=[sup, a, b], edges=[edge(sup, a), edge(sup, b)])
for w in run_all(g, parts):
    print(w.severity.value, w.evidence.get("conflict"), "|", w.message)
```

**Expected** — a `critical voltage` warning (radio needs 12 V from a 5 V rail) **and** a
`critical current_budget` warning (3.0 + 1.5 = 4.5 A drawn from a 2 A supply).

- [ ] Both a voltage mismatch and a current-budget overrun are flagged

## Edge / failure cases (the no-false-positive guarantee)

6. **Incomplete graph → silence.** Build the same `drives`/`reads_from`/`powers` edges but give the
   entities **no** capability/requirement attrs. Expect `run_all` → `[]` (rules SKIP, never guess).
   - [ ] No warnings on an attribute-less graph
7. **Malformed attrs don't crash.** Set `av.GBW_HZ` to `"wide"` (non-numeric) and
   `av.VOLTAGE_NOMINAL_V` to `True` (a bool). Expect no exception and no warning from those values
   (`attr_float` coerces to `None`; `True` must NOT read as `1.0 V`).
   - [ ] Non-numeric string and bool are ignored, no crash
8. **Unrelated edge → silence.** Two fully-specified parts joined only by a `connected_to` edge
   (no `drives`/`reads_from`/`powers`). Expect `[]`.
   - [ ] Generic connection produces no warnings
9. **Dangling edge → no crash.** An edge whose `dst_id` is not in `entities` is dropped, not raised
   on. Expect `[]`.
   - [ ] Half-ingested graph is handled gracefully

## Cross-feature notes for the tester

- `Warning` is **frozen** and rejects unknown fields — attempting to mutate `w.message` or pass a
  typo field raises `ValidationError` (this is the shape CHK-03/04 will render; treat it as locked).
- Results from `run_all` are **most-severe first** (`critical` before `warning` before `info`).
- `Warning.evidence` is plain JSON-serializable data (numbers/strings/lists); `entity_ids` are the
  graph UUIDs the UI should highlight.
