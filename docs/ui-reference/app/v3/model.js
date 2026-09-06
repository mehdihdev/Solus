// Solus v3 — the derivation engine: connection catalog + widget registry + deriveWorld.
// Nothing downstream is persona-hardcoded: screens render whatever this derives.
(function () {
  const P = window.V2P; // reuse persona content as DATA (signals, findings, sol scripts)

  /* ---------- connection catalog: generic instances with capability tags ---------- */
  const C = (id, sect, name, mark, domain, tags, detail, extra) => ({ id, sect, name, mark, domain, tags, detail, state: "connectable", ...extra });
  const CATALOG = [
    C("ghRepo", "cloud", "GitHub", "GH", "sw", ["repo", "history"], "maya-builds/lerobot-act-cube · 214 files"),
    C("ghOrg", "cloud", "GitHub org", "GH", "sw", ["repo", "history"], "fsae-ev · 6 repos (vcu-fw, dash, telemetry…)"),
    C("onshapeFree", "cloud", "Onshape (free)", "On", "me", ["cad"], "desk-arm · 1 part studio"),
    C("hf", "cloud", "Hugging Face", "HF", "sw", ["datasets"], "Checkpoints & datasets"),
    C("kicadApp", "local", "KiCad 8", "Ki", "ee", ["localapp", "eda"], "servo-shield.kicad_pro · last opened 2 d ago", { running: false }),
    C("swApp", "local", "SolidWorks 2025", "SW", "me", ["localapp", "cad"], "EV27 master assembly · 3,182 parts", { running: true }),
    C("altiumApp", "local", "Altium Designer", "AD", "ee", ["localapp", "eda"], "PDU rev C · last opened yesterday", { running: false }),
    C("ansysApp", "local", "ANSYS Mechanical", "AN", "me", ["localapp", "analysis"], "12 studies indexed", { running: false }),
    C("so101f", "devices", "SO-101 · Follower", "F", "ee", ["robot", "stream"], "USB /dev/ttyACM0 · 6 servos @ 50 Hz", { role: "FOLLOWER", identity: "Feetech STS3215 ×6 — confirmed by bus handshake", signals: "maya", sim: { kind: "arm", spawn: [{ id: "so101f", label: "SO-101 Follower (live mirror)" }, { id: "cube", label: "Cube prop (sim only)" }] } }),
    C("so101l", "devices", "SO-101 · Leader", "L", "ee", ["robot"], "USB /dev/ttyACM1 · teleop input, not streaming", { role: "LEADER", identity: "Same model as follower — labels from pairing wizard", swap: true, simSpawn: { id: "so101l", label: "SO-101 Leader (idle)" } }),
    C("mujoco", "devices", "MuJoCo", "SIM", "rt", ["sim"], "scene so101_cube.xml · RT ×1.0"),
    C("wristcam", "devices", "Wrist camera", "CAM", "rt", ["camera"], "640×480 @ 30 fps · time-synced"),
    C("uno", "devices", "USB serial device", "?", "rt", ["device", "stream"], "/dev/ttyUSB0 · 115200 baud", { honest: true, identity: "Recognized: CH340 USB-serial bridge. The board behind it is unknown — likely Arduino-compatible, but I won't guess.", signals: "sam", sim: { kind: "servo", spawn: [{ id: "horn", label: "Servo horn (from PWM-9)" }] } }),
    C("pcan", "devices", "PCAN-USB", "CAN", "rt", ["canbus"], "500 kbit/s · no bus voltage — car not connected", { honestIdle: "Nothing on the bus right now. Connect the car, or load a log." }),
    C("satlog", "devices", "Testing day log · Sat", "LOG", "rt", ["log", "stream", "canbus"], "42 min · 1.2 M CAN frames · 4 video angles", { signals: "priya", camera: true, sim: { kind: "can", spawn: [{ id: "pdu", label: "PDU node map" }] } }),
  ];

  /* graph children per instance — nested: assemblies / files → components */
  const CHILDREN = {
    ghRepo: [
      { l: "policies/", d: "sw" },
      { l: "act_policy.py", d: "sw", hot: 1, kids: [{ l: "action head · L214", d: "sw", hot: 1 }, { l: "select_action()", d: "sw" }] },
      { l: "eval.py", d: "sw" },
      { l: "so101.urdf", d: "me", kids: [{ l: "joint2 limit ±90°", d: "me", hot: 1 }, { l: "joint3 limit ±110°", d: "me" }, { l: "link masses", d: "me" }] },
    ],
    ghOrg: [{ l: "vcu-fw", d: "sw", hot: 1, kids: [{ l: "fault_handler.c", d: "sw", hot: 1 }, { l: "can_ids.h", d: "sw" }] }, { l: "dash", d: "sw" }, { l: "telemetry", d: "sw" }],
    so101f: [
      { l: "M1 base_pan", d: "ee" },
      { l: "M2 shoulder_lift", d: "ee", hot: 1, kids: [{ l: "stall 3.0 A", d: "ee", hot: 1 }, { l: "position feedback", d: "rt" }, { l: "temp 41 °C", d: "rt" }] },
      { l: "M3 elbow_flex", d: "ee" },
      { l: "M4–M6", d: "ee" },
      { l: "servo bus 5 V", d: "ee", kids: [{ l: "supply 5 V / 2 A", d: "ee", hot: 1 }, { l: "wiring · JST", d: "ee" }] },
    ],
    so101l: [{ l: "6 servos · idle", d: "ee" }],
    mujoco: [{ l: "so101_cube.xml", d: "rt", kids: [{ l: "so101 model", d: "rt" }, { l: "cube body", d: "rt" }, { l: "sim joint2 (clips)", d: "rt", hot: 1 }] }, { l: "physics · 500 Hz", d: "rt" }],
    kicadApp: [{ l: "servo-shield.sch", d: "ee", kids: [{ l: "PWM-9 header", d: "ee", hot: 1 }, { l: "5 V regulator", d: "ee" }, { l: "servo conn ×3", d: "ee" }] }, { l: "board · 2 layer", d: "ee" }],
    swApp: [
      { l: "chassis (asm)", d: "me", kids: [{ l: "front bulkhead", d: "me" }, { l: "floor panel", d: "me" }] },
      { l: "harness loom (asm)", d: "me", kids: [{ l: "W-12 · 16 AWG", d: "me", hot: 1 }, { l: "W-07 · 12 AWG", d: "me" }] },
      { l: "+ 3,178 parts", d: "me" },
    ],
    altiumApp: [{ l: "PDU rev C", d: "ee", kids: [{ l: "sheet 4 · power out", d: "ee" }, { l: "F3 · 30 A", d: "ee", hot: 1 }] }, { l: "BOM · 47 lines", d: "ee" }],
    ansysApp: [{ l: "chassis torsion", d: "me" }, { l: "upright FEA", d: "me" }],
    pcan: [{ l: "bus idle", d: "rt" }],
    satlog: [{ l: "inverter · 0x0A2", d: "rt", hot: 1, kids: [{ l: "fault frame 14:42:07", d: "rt", hot: 1 }, { l: "current 40 A peak", d: "rt" }] }, { l: "BMS · 0x1B0", d: "rt" }, { l: "VCU · 0x050", d: "rt" }],
    uno: [{ l: "PWM-9 stream", d: "rt", hot: 1 }, { l: "PWM-10 stream", d: "rt", hot: 1 }, { l: "MCU: unknown", d: "rt", honest: 1 }],
    onshapeFree: [{ l: "servo bracket", d: "me", hot: 1, kids: [{ l: "slot ×2", d: "me" }, { l: "base plate", d: "me" }] }, { l: "arm link", d: "me" }],
    wristcam: [{ l: "frames · 30 fps", d: "rt" }],
    hf: [{ l: "act-cube-v2 ckpt", d: "sw" }],
  };

  /* cross-integration links; a2/b2 = specific child endpoints revealed on zoom */
  const LINKS = [
    { a: "ghRepo", b: "so101f", n: 12, label: "policy → servos · pin maps · limits", hot: true, a2: "act_policy.py", b2: "M2 shoulder_lift", label2: "action head → servo commands" },
    { a: "ghRepo", b: "mujoco", n: 8, label: "URDF · scenes", a2: "so101.urdf", b2: "so101_cube.xml", label2: "same URDF, both worlds" },
    { a: "so101f", b: "mujoco", n: 6, label: "sim ↔ real joints", a2: "M2 shoulder_lift", b2: "so101_cube.xml", label2: "joint states mirrored" },
    { a: "wristcam", b: "mujoco", n: 2, label: "frame sync" },
    { a: "so101l", b: "so101f", n: 3, label: "teleop pairing" },
    { a: "uno", b: "kicadApp", n: 4, label: "pins ↔ sheet", hot: true, a2: "PWM-9 stream", b2: "servo-shield.sch", label2: "pin 9 ↔ PWM-9 header" },
    { a: "uno", b: "onshapeFree", n: 2, label: "horn ↔ bracket", a2: "PWM-9 stream", b2: "servo bracket", label2: "drives horn on bracket" },
    { a: "satlog", b: "altiumApp", n: 5, label: "CAN frames ↔ sheets", hot: true, a2: "inverter · 0x0A2", b2: "PDU rev C", label2: "fault frame ↔ F3 fuse" },
    { a: "altiumApp", b: "swApp", n: 3, label: "F3 ↔ harness W-12", hot: true, a2: "PDU rev C", b2: "harness loom (asm)", label2: "F3 rating → W-12 gauge" },
    { a: "ghOrg", b: "satlog", n: 4, label: "fault handling", a2: "vcu-fw", b2: "inverter · 0x0A2", label2: "fault_handler.c decodes 0x0A2" },
    { a: "swApp", b: "ansysApp", n: 6, label: "studies", a2: "chassis (asm)", b2: "chassis torsion", label2: "chassis → torsion study" },
    { a: "hf", b: "ghRepo", n: 2, label: "checkpoints" },
  ];

  /* ---------- widget registry (the store) ---------- */
  const W = (id, name, fp, by, req, does, adds, icon) => ({ id, name, fp, by, req, does, adds, icon });
  const WIDGETS = [
    W("signals", "Live Signals", true, "Solus", ["stream"], "One widget per signal — value, rolling chart, anomaly markers, inline rename, unit conversion.", ["Bench telemetry grid", "Home signal strip", "SOL can reference any signal"], "bench"),
    W("scene", "Scene", true, "Solus", ["robot|sim"], "Spawn connected robots and assemblies; mirrors real motion.", ["Bench scene panel", "Anomaly highlighting on the robot"], "box"),
    W("experiments", "Experiments", true, "Solus", ["repo", "robot|sim"], "Define, run, record, play back and compare runs — sim and hardware.", ["Experiments surface", "SOL can propose and re-run experiments", "Run history"], "play"),
    W("findings", "Cross-domain Findings", true, "Solus", ["xdomain"], "Explanations that span mechanical, electrical and software — what happened, why, what to do.", ["Finding cards + notifications", "Trace evidence in the graph"], "warn"),
    W("guide", "Guide", true, "Solus", ["localapp"], "SOL teaches the tool you don't know, step by step, with per-step confidence and honest gaps.", ["Guide panel in SOL", "Pointing at controls in the external app"], "sol"),
    W("bom", "BOM", true, "Solus", ["eda"], "Bill of materials from your EDA project — sourcing status, findings flag affected lines.", ["BOM card on Home", "SOL can check part availability"], "file"),
    W("can", "CAN Telemetry", true, "Solus", ["canbus"], "Bus load, node health, fault frames — live or from logs.", ["CAN health card", "Fault frame decoding in findings"], "bench"),
    W("provenance", "Provenance", true, "Solus", ["history"], "Who designed what, when, and why — from PDM, git, and team drives. Knowledge survives graduation.", ["Ask-the-history search", "Provenance cards in SOL answers"], "team"),
    W("datasheet", "Datasheet Finder", false, "community · r0b0tk1d", ["eda"], "Looks up datasheets for parts in your schematic and pins them to graph nodes.", ["Datasheet links on EE nodes"], "file"),
    W("rules", "FSAE Rules Checker", false, "community · fsae-tools", ["cad|eda"], "Checks EV rules against your CAD and schematic — wire gauges, fusing, insulation.", ["Rules card", "Violations become findings"], "check"),
    W("notes", "Session Notes", false, "community · benchnotes", [], "Timestamped notes pinned to telemetry moments.", ["Notes strip on Bench"], "file"),
  ];

  /* persona quick-fill presets = pure connection sets + starter installs */
  const PRESETS = {
    maya: { label: "Maya — ML researcher", ids: ["ghRepo", "so101f", "so101l", "mujoco", "wristcam"], installs: ["signals", "scene", "experiments", "findings"] },
    sam: { label: "Sam — hobbyist", ids: ["uno", "kicadApp", "onshapeFree"], installs: ["signals", "scene", "guide"] },
    priya: { label: "Priya — FSAE lead", ids: ["ghOrg", "swApp", "altiumApp", "ansysApp", "pcan", "satlog"], installs: ["signals", "findings", "can", "provenance", "bom"] },
  };

  /* findings become active when their required instances are all connected */
  const FINDINGS = [
    { id: "f-stall", req: ["ghRepo", "so101f"], persona: "maya", solKey: "diagnose", node: "so101f" },
    { id: "f-jitter", req: ["uno"], persona: "sam", solKey: "jitter", node: "uno" },
    { id: "f-cut", req: ["satlog", "altiumApp", "swApp"], persona: "priya", solKey: "cutout", node: "satlog" },
  ];

  const hasTag = (insts, tok) => tok.split("|").some((t) => t === "xdomain" ? new Set(insts.map((i) => i.domain)).size >= 2 : insts.some((i) => i.tags.includes(t)));
  const reqMet = (insts, w) => w.req.every((tok) => hasTag(insts, tok));
  const reqMissing = (insts, w) => w.req.filter((tok) => !hasTag(insts, tok));

  function deriveWorld(connectedIds, installed) {
    const insts = CATALOG.filter((c) => connectedIds.includes(c.id));
    const affinity = connectedIds.includes("satlog") || connectedIds.includes("pcan") ? "priya" : connectedIds.includes("uno") ? "sam" : (connectedIds.includes("ghRepo") || connectedIds.includes("so101f")) ? "maya" : null;
    const base = affinity ? P[affinity] : null;
    const sigOwners = insts.filter((i) => i.signals);
    const signals = installed.includes("signals") ? [].concat(...sigOwners.map((i) => P[i.signals].signals)) : [];
    const simOwner = insts.find((i) => i.sim);
    const activeFindings = FINDINGS.filter((f) => f.req.every((id) => connectedIds.includes(id)) && installed.includes(f.persona === "sam" ? "signals" : "findings")).map((f) => ({ ...f, finding: P[f.persona].finding }));
    const canRun = installed.includes("experiments") && hasTag(insts, "repo") && hasTag(insts, "robot|sim");
    return {
      id: affinity || "custom",
      wsName: base ? base.wsName : "new-workspace", wsSub: base ? base.wsSub : "Solo", tagline: insts.length ? insts.map((i) => i.name).slice(0, 3).join(" · ") + (insts.length > 3 ? " · …" : "") : "nothing connected yet",
      insts, connectedIds, installed, affinity,
      signals, anomaly: base ? base.anomaly : {}, camera: insts.some((i) => i.camera || i.id === "wristcam"),
      sim: simOwner ? { kind: simOwner.sim.kind, spawnable: [...simOwner.sim.spawn, ...insts.filter((x) => x.simSpawn).map((x) => x.simSpawn)], defaultScene: [simOwner.sim.spawn[0].id] } : { kind: "none", spawnable: [], defaultScene: [] },
      runs: canRun && base ? base.runs : [],
      runsEmpty: !installed.includes("experiments") ? "The Experiments capability isn't installed. Get it from the Store — it needs a repo plus a robot or simulator." : !hasTag(insts, "repo") ? "No repo connected — nothing runnable yet. Connect one and Experiments wakes up." : "Connect a robot or simulator to run against.",
      compare: base ? base.compare : { simReal: null, runRun: null },
      findings: activeFindings,
      finding: activeFindings.length ? activeFindings[0].finding : null,
      approvals: base ? base.approvals : {},
      sol: base ? base.sol : { hello: { text: "Nothing is connected yet, so I can't see much. Connect a tool or a device in Connections and ask me again — I only speak from what's actually here." } },
      guide: base && base.guide && connectedIds.includes("kicadApp") ? base.guide : null,
      notifications: activeFindings.map((f) => ({ id: f.id, sev: f.finding.sev === "critical" ? "critical" : "warning", title: f.finding.title, sub: f.finding.when, action: f.solKey })),
      graph: { insts, children: CHILDREN, links: LINKS.filter((l) => connectedIds.includes(l.a) && connectedIds.includes(l.b)) },
      widgets: { installed: WIDGETS.filter((w) => installed.includes(w.id)), suggested: WIDGETS.filter((w) => !installed.includes(w.id) && reqMet(insts, w)), locked: WIDGETS.filter((w) => !installed.includes(w.id) && !reqMet(insts, w)).map((w) => ({ ...w, missing: reqMissing(insts, w) })) },
    };
  }

  window.V3 = { CATALOG, WIDGETS, PRESETS, LINKS, CHILDREN, deriveWorld, reqMet, reqMissing };
})();
