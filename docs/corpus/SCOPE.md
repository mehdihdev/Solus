# Engineering Corpus — Scope (CORPUS C1)

**Ticket:** SOLUSDEV-241 (CORPUS C1) · **Status:** scope document, tier-1 (ADR-032), reviewed at
the MR. **No code ships with this document.** The chunk store, ingestion job, and retrieval path
are CORPUS C2+ and get their own ADR when the store is designed.
**Companion documents:** `docs/corpus/LICENSING.md` (what is allowed to ship),
`docs/schemas/corpus-chunk.md` (the shape of one chunk).
**Authority consulted:** ADR-033 (global, tenant-free tool knowledge — the containment precedent
this corpus inherits), ADR-034 and `docs/architecture/solus-folder.md` (the `.solus` layers the
preferences sit in; custom instructions remain deferred to their own ADR), ADR-016 (SOL modes are
universal), ADR-013 (autocomplete is the checker library, not a model),
`docs/contracts/tool-knowledge.md` (what the tool-knowledge store is, so this corpus does not
duplicate it), `packages/api/src/solus_api/agent/prompt.py` (every non-Solus string is fenced
data).

---

## 1. What the corpus is

The engineering corpus is **what SOL ships knowing**: the baseline engineering knowledge every
Solus user gets, identical for every tenant, versioned and shipped as an asset of the product.

- It is **content, not code.** Checkers decide whether a design is wrong (ADR-013). The corpus is
  what SOL and the checkers reach for to _explain_ why, to teach the concept in Guide mode, and to
  cite a source in Expert mode. A warning without a corpus chunk behind it is still a warning; a
  chunk without a checker is still useful to SOL.
- It is **global and tenant-free**, exactly like the tool-knowledge store (ADR-033). Nothing in it
  is derived from, describes, or points at any customer's project. The chunk schema makes that
  structurally unrepresentable (see `docs/schemas/corpus-chunk.md` §3).
- It is **layered under the team's preferences.** A project's committed `.solus/` (ADR-034,
  Layer 2) declares facts about the robot — voltage classes, target boards, ROS distro, which
  fabrication class the team designs to. Those facts **select and rank** corpus chunks through
  applicability tags. They never add text to the corpus and never become instructions to SOL
  (custom instructions are a separate, deferred ADR — `solus-folder.md` §6).
- It is **fenced as data in every prompt.** Curated by Solus or not, a chunk's body is third-party
  or Solus prose, and it enters a prompt only inside a `<<<SOLUS-DATA kind=corpus>>>` fence. Only
  the system message is instructions.

## 2. What the corpus is not

| Not this                                     | Where that lives instead                                                                   |
| -------------------------------------------- | ------------------------------------------------------------------------------------------ |
| Tool UI and API knowledge ("extrude is at…") | Tool-knowledge store, `docs/contracts/tool-knowledge.md`, ADR-033                          |
| Anything derived from a customer project     | Nowhere. Tenancy boundary — never a source, never an example                               |
| The text of a standard                       | Never shipped. Standards are summarised only (`LICENSING.md` §4.7)                         |
| Checker logic                                | `packages/api/src/solus_api/checkers/` — code, not prose                                   |
| A training set                               | Data collection has its own schema and consent model; the corpus is retrieval content only |
| Certification or sign-off                    | Out of scope entirely (§5)                                                                 |
| Team or personal instructions to SOL         | Deferred to the custom-instructions ADR (`solus-folder.md` §6)                             |

## 3. Depth levels

Every chunk carries an `audience` value. SOL mode (ADR-016) selects between them; both are
always shipped.

| Audience       | Written for                                           | SOL mode that pulls it first |
| -------------- | ----------------------------------------------------- | ---------------------------- |
| `fundamentals` | Someone expert in another domain meeting this one     | Guide                        |
| `reference`    | Someone who knows the domain and wants the value/rule | Expert                       |

And a `kind` that says what the chunk does:

`principle` (why it matters) · `procedure` (how to do it) · `rule_of_thumb` (a defensible default
with its limits stated) · `reference_value` (a fact with a citation) · `pitfall` (the way it
usually goes wrong) · `glossary` (a term defined).

The minimum for a topic to count as covered at v1: one `fundamentals` principle, one `reference`
rule or value, and one pitfall. Priorities below mean: **P0** — must exist before the corpus is
called v1.0; **P1** — v1.x; **P2** — when a consumer asks for it.

## 4. Domains and topics

Consumers named per topic: **SOL** (conversational diagnosis, both modes), **CHK** (an existing or
planned checker cites the chunk in its explanation), **AC** (robotics autocomplete warning
explanation), **LB** (Live Bench anomaly explanation).

### 4.1 Mechanical

| Topic (`topic` enum)    | Must be able to answer                                                                                                                                                                                                                    | P   | Consumers    |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --- | ------------ |
| `gdt`                   | What a datum is; what each geometric control means; when to use position vs profile; reading a feature control frame; material condition modifiers and bonus tolerance                                                                    | P1  | SOL, AC      |
| `fits_tolerances`       | Clearance vs transition vs interference; the ISO hole/shaft basis system and how to read `H7/g6`; picking a fit for a bearing seat, a dowel, a press fit; stack-up (worst case vs RSS); what tolerance a given process can hold           | P0  | SOL, CHK, AC |
| `fasteners`             | Thread designations (metric and unified); grade/class and proof load; torque-to-preload and why torque is a poor proxy; thread engagement length in aluminium vs steel; locking methods; heat-set inserts in printed parts                | P0  | SOL, AC      |
| `material_selection`    | Common robot materials (6061/7075, 304/316, 4140, POM, PETG/PLA/ABS/nylon, CF composites) and when each is wrong; stiffness vs strength; galling and galvanic pairs; anodise vs plate; temperature limits of printed plastics             | P0  | SOL, AC      |
| `machining_constraints` | Internal corner radii and end-mill reach; minimum wall; drill vs ream; sheet-metal bend radius and K-factor; FDM overhangs, bridging, and print orientation vs strength; DFM for the processes a student or startup team can actually buy | P0  | SOL, AC      |
| `bearings_shafts`       | Radial vs thrust; bearing preload; shaft shoulders and retaining rings; keyways vs set screws vs clamping hubs; misalignment tolerance                                                                                                    | P1  | SOL          |
| `mechanisms`            | Gear ratio, backlash, efficiency by type (spur, planetary, harmonic, belt, lead/ball screw); backdrivability; when a linkage beats a motor                                                                                                | P1  | SOL          |

### 4.2 Electrical

| Topic (`topic` enum)     | Must be able to answer                                                                                                                                                                        | P   | Consumers        |
| ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --- | ---------------- |
| `trace_width_current`    | Why width, copper weight, and temperature rise set current capacity; internal vs external layers; via current; the principle behind the IPC-2221/2152 approach (summarised, never the tables) | P0  | SOL, CHK, AC     |
| `clearance_creepage`     | The difference; what pollution degree and voltage class do to the numbers; slots and coatings; why 48 V still matters                                                                         | P0  | SOL, CHK, AC     |
| `decoupling`             | What a decoupling capacitor actually does; placement and loop area; value spread; bulk vs local; ceramic DC bias derating                                                                     | P0  | SOL, CHK, AC     |
| `grounding`              | Star vs plane; ground loops; chassis vs signal ground; mixed-signal partitioning; where the return current flows                                                                              | P0  | SOL, AC          |
| `emi_basics`             | Sources and coupling paths; slew rate vs edge rate; cable shielding termination; ferrites; motor drive noise in the same box as a sensor                                                      | P1  | SOL, LB          |
| `power_design`           | LDO vs buck vs boost; dropout, efficiency, ripple; inrush and brown-out; reverse polarity and hot-plug; battery chemistries, C-rating, BMS, low-voltage cutoff                                | P0  | SOL, CHK, AC, LB |
| `wire_gauge`             | AWG vs mm²; ampacity vs voltage drop as the real limit in a robot; stranded vs solid; crimp vs solder                                                                                         | P0  | SOL, CHK, AC     |
| `connector_selection`    | Current rating and derating; mating cycles; locking; keying and polarity; JST/Molex/XT families and where each belongs; strain relief                                                         | P0  | SOL, AC          |
| `signal_integrity`       | I2C pull-ups and bus capacitance; SPI clock vs trace length; UART levels; differential pairs (CAN, RS-485, USB) and termination; level shifting                                               | P0  | SOL, CHK, AC     |
| `bus_addressing`         | I2C address conflicts and how devices set them; CAN ID allocation; SPI chip-select                                                                                                            | P0  | CHK, AC          |
| `analog_frontend`        | Op-amp supply and rail-to-rail limits; input bias and offset; sensor excitation; ADC reference and resolution; anti-alias filtering                                                           | P0  | SOL, CHK         |
| `motor_drive_electrical` | H-bridge and FET selection; gate drive; flyback; regenerative braking into a supply that cannot sink; current sensing                                                                         | P1  | SOL, LB          |
| `pcb_layout_basics`      | Stackup; return paths; thermal relief; via stitching; test points; DFM for common fabs                                                                                                        | P1  | SOL, AC          |

### 4.3 Software

| Topic (`topic` enum)    | Must be able to answer                                                                                                                                                                                    | P   | Consumers    |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --- | ------------ |
| `embedded_patterns`     | Superloop vs RTOS; ISR discipline (short, no allocation, volatile and atomics); state machines; watchdogs; non-blocking drivers; fixed-point where floats are absent                                      | P0  | SOL          |
| `real_time_constraints` | Hard vs soft real time; jitter and latency budgets; priority inversion; DMA; why `delay()` in a control loop is a bug                                                                                     | P0  | SOL, LB      |
| `embedded_testing`      | Hardware-in-the-loop; mocking peripherals; unit-testing firmware off-target; logging without breaking timing                                                                                              | P1  | SOL          |
| `ros_conventions`       | REP 103 (units, frames, coordinate conventions) and REP 105 (frame hierarchy); topics vs services vs actions; QoS profiles and why sensor data drops; launch and parameter conventions; `tf` tree hygiene | P0  | SOL, CHK, LB |
| `build_and_toolchain`   | Cross-compilation; CUDA/JetPack version coupling on Jetson; Python vs system package conflicts; pinning                                                                                                   | P0  | SOL, CHK, AC |
| `serial_protocols`      | Framing, checksums, and escaping; timeouts; versioned message schemas; why unframed ASCII over serial breaks at speed                                                                                     | P1  | SOL, LB      |
| `firmware_deployment`   | Bootloaders; flashing over serial vs debug probe; verifying a flash; rollback; fuse and option-byte hazards                                                                                               | P1  | SOL          |

### 4.4 Systems

| Topic (`topic` enum) | Must be able to answer                                                                                                                                                                       | P   | Consumers        |
| -------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --- | ---------------- |
| `power_budget`       | Building a budget from datasheet worst cases, not typicals; peak vs average; motor stall current; margin; how a 5 V rail browns out from a servo                                             | P0  | SOL, CHK, AC, LB |
| `thermal_budget`     | Junction vs ambient; θJA and why it lies; heatsinks and airflow in an enclosure; derating; where the heat goes in a sealed robot                                                             | P0  | SOL, CHK, LB     |
| `safety_interlocks`  | E-stop as a hardware chain, never software-only; category and performance-level vocabulary at the level of principle; safe-torque-off; interlock vs enable; fail-safe defaults on power loss | P0  | SOL, AC          |
| `enclosure_ingress`  | IP ratings; sealing vs venting and pressure equalisation; cable glands; condensation                                                                                                         | P1  | SOL              |
| `cabling_harness`    | Routing away from motion; service loops; labelling; separation of power and signal; connector counts as a reliability metric                                                                 | P1  | SOL, AC          |
| `system_integration` | Interface control between domains; who owns a pin; the cross-domain change that breaks the other team; commissioning order                                                                   | P0  | SOL              |

### 4.5 Robotics

| Topic (`topic` enum)   | Must be able to answer                                                                                                                                                                   | P   | Consumers    |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --- | ------------ |
| `actuator_selection`   | Torque, speed, and duty cycle from the load, not the catalogue; servo vs stepper vs BLDC vs DC-gearmotor; stall torque vs rated; gearbox efficiency; thermal limits of continuous torque | P0  | SOL, CHK, AC |
| `kinematics_basics`    | Frames and transforms; DH-style vs URDF conventions; forward vs inverse; Jacobian and singularities at the level of intuition; workspace                                                 | P0  | SOL, LB      |
| `dynamics_basics`      | Inertia and reflected inertia; gravity compensation; why the arm sags; payload rating                                                                                                    | P1  | SOL, LB      |
| `sensor_fusion_basics` | IMU drift and complementary vs Kalman filtering at the level of intuition; encoder vs IMU vs vision; timestamps and synchronisation; covariance as a statement of trust                  | P0  | SOL, LB      |
| `control_tuning`       | PID by hand; what each term does to the response; anti-windup; sample rate vs bandwidth; derivative on measurement; cascade loops for position over velocity over current                | P0  | SOL, LB      |
| `perception_basics`    | Camera intrinsics and calibration; rolling vs global shutter for motion; lidar vs depth camera limits; lighting                                                                          | P1  | SOL          |
| `simulation_fidelity`  | What MuJoCo models well and badly; contact parameters; sim-to-real gaps; why the URDF mass matters                                                                                       | P1  | SOL, LB      |
| `locomotion_basics`    | Wheel and drive configurations; traction and centre of mass; legged vs wheeled trade-offs                                                                                                | P2  | SOL          |

## 5. Explicit exclusions

These are out of scope for the corpus at every version, not just v1:

- **Standards text, tables, and figures.** Summaries of principle and clause pointers only
  (`LICENSING.md` §4.7).
- **Certification, compliance sign-off, or regulatory advice** presented as such: CE, UL listing,
  FCC, medical, aviation, functional-safety certification. The corpus may explain what a
  vocabulary term means; it never says "this design complies".
- **Customer-derived content** in any form, including anonymised examples.
- **Vendor tool UI knowledge** — that is the tool-knowledge store.
- **Anything the reviewer could not source** to a shippable or summarisable class under
  `LICENSING.md`. Empty beats invented: a topic with no allowed source stays empty and says so.

## 6. Applicability

Chunks carry closed-key `applicability` tags; the project's Layer-2 `.solus/project.toml` (when
that contract lands) will declare the same keys. The v1 key set:

| Key                 | Example values                                                           | Selects chunks about                             |
| ------------------- | ------------------------------------------------------------------------ | ------------------------------------------------ |
| `voltage_class`     | `elv_lt_50v`, `lv_50_1000v`                                              | clearance, wire gauge, interlocks                |
| `fabrication_class` | `hobby`, `prototype`, `production`                                       | PCB DFM, machining constraints                   |
| `process`           | `fdm`, `sla`, `cnc_mill`, `cnc_lathe`, `sheet_metal`, `pcb_2l`, `pcb_4l` | DFM, tolerances                                  |
| `mcu_family`        | `avr`, `stm32`, `esp32`, `rp2040`, `nrf52`, `jetson`, `raspberry_pi`     | embedded patterns, toolchain                     |
| `ros_distro`        | `humble`, `jazzy`, `rolling`                                             | ROS conventions, QoS                             |
| `bus`               | `i2c`, `spi`, `uart`, `can`, `rs485`, `usb`, `ethernet`                  | signal integrity, addressing                     |
| `environment`       | `indoor`, `outdoor`, `wet`, `dusty`, `vibration`                         | enclosures, connectors, materials                |
| `unit_system`       | `si`, `imperial`                                                         | presentation only, never a filter on correctness |

Values are closed enums per key. A chunk with no tag for a key applies regardless of that key.
Preferences filter and rank; they never exclude a `pitfall` or `safety_interlocks` chunk that
matches on any other axis.

## 7. Versioning and size

- The corpus has one semantic version. **v1.0.0** means every P0 topic in §4 meets the §3
  minimum with sources that pass `LICENSING.md`. Chunks record the version they were introduced
  in and the version they were last revised in.
- Removing or withdrawing a chunk is a version bump, never a silent edit; withdrawn chunks keep
  their id with `status: withdrawn` so citations in past SOL answers still resolve.
- Size is bounded by the §3 minimum, not by a target count. There is no number of chunks to hit;
  there is a set of questions to be able to answer.

## 8. Open items carried to C2 — resolution (CORPUS C2, ADR-036)

- **Storage:** a global `corpus_chunk` table under ADR-036 (ADR-033's four rules, with prose
  columns admitted under closed enums, caps, and a single curated write path). Not a static
  bundle. The content tree in `packages/api/src/solus_api/corpus/content/` is the source of
  truth; `python -m solus_api.corpus ingest` is the only writer (`docs/corpus/AUTHORING.md`).
- **Checker warnings citing chunk ids:** still open — needs the checker-interface owner. SOL
  cites chunk ids today; checkers do not yet.
- **`.solus/project.toml` applicability keys:** the Layer-2 contract has not landed. The §6 key
  set is implemented as the retrieval filter's `applicability` parameter (closed keys and
  values); nothing supplies it at request time yet, so every chunk "applies regardless" at v1.
  Whichever lands second still reconciles.
- **Root preferences (ADR-034 amendment, SOLUSDEV-244)** are free text, not applicability keys.
  They sit above the corpus in the system prompt; the corpus enters below them as fenced
  `context_corpus` data. That is the whole layering at v1.
