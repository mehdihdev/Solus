// Solus v4 — model: whole-account connections, projects, .solus, robots + parts with lifecycle, derivation
(function () {
  const P = window.V2P;
  const T = (l, d, kids, hot) => ({ l, d, kids, hot });
  const TREES = {
    "gh-act": [T("policies/", "sw", [T("act_policy.py", "sw", null, 1), T("chunking.py", "sw")]), T("eval/", "sw", [T("eval.py", "sw"), T("metrics.py", "sw")]), T("robot/", "me", [T("so101.urdf", "me", null, 1), T("calib.json", "sw")]), T("train.py", "sw")],
    "gh-vcu": [T("src/", "sw", [T("fault_handler.c", "sw", null, 1), T("can_ids.h", "sw"), T("main.c", "sw")]), T("docs/", "sw", [T("CAN map.md", "sw")])],
    "gh-tel": [T("ingest/", "sw", [T("pcan_reader.py", "sw")]), T("dash/", "sw", [T("laps.py", "sw")])],
    "on-desk": [T("arm (asm)", "me", [T("servo bracket", "me", null, 1), T("arm link", "me"), T("base plate", "me")]), T("gripper (asm)", "me", [T("finger L", "me"), T("finger R", "me")])],
    "on-so101": [T("follower (asm)", "me", [T("shoulder", "me"), T("upper arm", "me"), T("wrist", "me"), T("gripper", "me")]), T("leader (asm)", "me", [T("handle", "me")])],
    "fu-mount": [T("camera-mount", "me", [T("clamp", "me"), T("arm", "me")])],
    "ki-shield": [T("servo-shield.sch", "ee", [T("PWM-9 header", "ee", null, 1), T("5 V regulator", "ee"), T("servo conn ×3", "ee")]), T("board.kicad_pcb", "ee", [T("F.Cu", "ee"), T("B.Cu", "ee")])],
    "ad-pdu": [T("PDU rev C", "ee", [T("sheet 4 · power out", "ee"), T("F3 · 30 A", "ee", null, 1), T("sheet 2 · LV", "ee")]), T("BOM · 47 lines", "ee")],
    "sw-ev27": [T("chassis (asm)", "me", [T("front bulkhead", "me"), T("floor panel", "me")]), T("harness loom (asm)", "me", [T("W-12 · 16 AWG", "me", null, 1), T("W-07 · 12 AWG", "me")]), T("+ 3,178 parts", "me")],
    "an-ev27": [T("chassis torsion", "me"), T("upright FEA", "me")],
    "mj-so101": [T("so101_cube.xml", "rt", [T("so101 model", "rt"), T("cube body", "rt"), T("sim joint2 (clips)", "rt", null, 1)]), T("physics · 500 Hz", "rt")],
    "log-sat": [T("inverter · 0x0A2", "rt", [T("fault 14:42:07", "rt", null, 1), T("40 A peak", "rt")], 1), T("BMS · 0x1B0", "rt"), T("VCU · 0x050", "rt")],
  };
  const ACCOUNTS = [
    { id: "github", name: "GitHub", mark: "GH", kind: "cloud", domain: "sw", quota: { used: 3120, limit: 5000, unit: "req/h", reset: "41 min" }, docs: [{ id: "gh-act", name: "maya-builds/lerobot-act-cube", sub: "repo · 214 files" }, { id: "gh-vcu", name: "fsae-ev/vcu-fw", sub: "repo · 88 files" }, { id: "gh-tel", name: "fsae-ev/telemetry", sub: "repo · 41 files" }] },
    { id: "onshape", name: "Onshape", mark: "On", kind: "cloud", domain: "me", quota: { used: 8600, limit: 10000, unit: "calls/day", reset: "midnight" }, docs: [{ id: "on-desk", name: "desk-arm", sub: "document · 2 assemblies" }, { id: "on-so101", name: "SO-101 (community copy)", sub: "document · 2 assemblies" }] },
    { id: "fusion", name: "Fusion", mark: "Fu", kind: "cloud", domain: "me", quota: { used: 120, limit: 2000, unit: "calls/day", reset: "midnight" }, docs: [{ id: "fu-mount", name: "camera-mount", sub: "design · 1 component" }] },
    { id: "solidworks", name: "SolidWorks 2025", mark: "SW", kind: "local", domain: "me", running: true, docs: [{ id: "sw-ev27", name: "EV27 master assembly", sub: "3,182 parts" }] },
    { id: "altium", name: "Altium Designer", mark: "AD", kind: "local", domain: "ee", running: false, docs: [{ id: "ad-pdu", name: "PDU rev C", sub: "project · 4 sheets" }] },
    { id: "kicad", name: "KiCad 8", mark: "Ki", kind: "local", domain: "ee", running: false, docs: [{ id: "ki-shield", name: "servo-shield", sub: "project · 2 sheets" }] },
    { id: "ansys", name: "ANSYS Mechanical", mark: "AN", kind: "local", domain: "me", running: false, docs: [{ id: "an-ev27", name: "EV27 studies", sub: "12 studies" }] },
    { id: "mujoco", name: "MuJoCo", mark: "MJ", kind: "local", domain: "rt", running: true, docs: [{ id: "mj-so101", name: "so101_cube.xml", sub: "scene" }] },
  ];
  const DOC = (id) => { for (const a of ACCOUNTS) { const d = a.docs.find((x) => x.id === id); if (d) return { ...d, service: a.id, serviceName: a.name, domain: a.domain, mark: a.mark, tree: TREES[id] || [] }; } if (id === "log-sat") return { id, name: "Testing log · Sat", sub: "42 min · 1.2 M CAN frames", service: "log", serviceName: "Log file", domain: "rt", mark: "LOG", tree: TREES["log-sat"] }; return null; };

  const CATS = ["sensors", "actuators", "controllers", "end effectors", "power", "structure", "wiring"];
  const CAT_D = { sensors: "rt", actuators: "ee", controllers: "ee", "end effectors": "me", power: "ee", structure: "me", wiring: "ee" };
  const STATES = ["planned", "ordered", "received", "installed", "live"];
  const guessCat = (l) => /cam|lidar|imu|sensor|encoder|speed/i.test(l) ? "sensors" : /servo|motor|actuator|inverter/i.test(l) ? "actuators" : /mcu|controller|vcu|bms|board|arduino|pdu/i.test(l) ? "controllers" : /grip|finger|effector|tool/i.test(l) ? "end effectors" : /supply|batter|fuse|regulator|power|pack|F3/i.test(l) ? "power" : /harness|wire|conn|header|cable|W-\d/i.test(l) ? "wiring" : "structure";

  const LIBRARY = [
    { id: "so101", name: "SO-101", by: "TheRobotStudio", sub: "5-DOF arm + gripper", actuators: "6× Feetech STS3215, serial bus", kinematics: "5R + parallel gripper · reach 40 cm · 0.5 kg payload", protocol: "Feetech TTL @ 1 Mbaud", parts: [["base_pan", "actuators"], ["shoulder_lift", "actuators"], ["elbow_flex", "actuators"], ["wrist_flex", "actuators"], ["wrist_roll", "actuators"], ["gripper", "end effectors"], ["bus servo adapter", "controllers"], ["5 V / 4 A supply", "power"], ["3D-printed links", "structure"]] },
    { id: "koch", name: "Koch v1.1", by: "Alexander Koch", sub: "6-DOF low-cost arm", actuators: "6× Dynamixel XL430/XL330", kinematics: "6R · reach 35 cm", protocol: "Dynamixel 2.0 @ 1 Mbaud", parts: [["6× Dynamixel", "actuators"], ["U2D2", "controllers"], ["gripper", "end effectors"]] },
    { id: "g1", name: "Unitree G1", by: "Unitree", sub: "Humanoid, 23 DOF", actuators: "23× Unitree joint motors", kinematics: "23 DOF · 1.32 m · 35 kg", protocol: "EtherCAT + DDS", parts: [["23× joint motors", "actuators"], ["Jetson Orin NX", "controllers"], ["LiDAR + depth cam", "sensors"], ["13 Ah pack", "power"]] },
    { id: "ur5", name: "UR5e", by: "Universal Robots", sub: "Industrial 6-axis", actuators: "6 joint modules", kinematics: "6R · reach 850 mm · 5 kg", protocol: "RTDE / TCP", parts: [["6 joint modules", "actuators"], ["control box", "controllers"], ["teach pendant", "controllers"]] },
    { id: "px4", name: "PX4 quad stack", by: "PX4 / Holybro", sub: "X500 v2 + Pixhawk 6C", actuators: "4× 2216 920 kV + ESCs", kinematics: "500 mm class · 1.4 kg AUW", protocol: "MAVLink / DShot", parts: [["4× motors + ESC", "actuators"], ["Pixhawk 6C", "controllers"], ["GPS + baro + IMU", "sensors"], ["4S 5000 mAh", "power"]] },
  ];
  const DETECTED = [
    { id: "acm0", name: "USB serial · /dev/ttyACM0", serial: "A3F2", identity: "Waveshare bus-servo adapter — 6× STS3215 answered the handshake.", honest: false, platform: "so101", mapping: [[1, "base_pan", 0.94, "first to move in sweep · 270° range"], [2, "shoulder_lift", 0.91, "highest current under gravity"], [3, "elbow_flex", 0.88, "180° range · mid-chain"], [4, "wrist_flex", 0.82, "180° range · low load"], [5, "wrist_roll", 0.71, "continuous rotation seen"], [6, "gripper", 0.62, "short travel — could be wrist_roll"]] },
    { id: "acm1", name: "USB serial · /dev/ttyACM1", serial: "9C11", identity: "Identical hardware to ACM0 — told apart only by USB serial 9C11. Leader or follower is your call.", honest: false, platform: "so101", mapping: [[1, "base_pan", 0.9, "same sweep signature as ACM0"], [2, "shoulder_lift", 0.88, "same"], [3, "elbow_flex", 0.85, "same"], [4, "wrist_flex", 0.8, "same"], [5, "wrist_roll", 0.7, "same"], [6, "gripper", 0.6, "same"]] },
    { id: "usb0", name: "USB serial · /dev/ttyUSB0", serial: "—", identity: "CH340 USB-serial bridge. The microcontroller behind it is unknown — I won't guess.", honest: true, platform: "uno", mapping: [["PWM-9", null, null, "50 Hz stream · no board ID"], ["PWM-10", null, null, "50 Hz stream · no board ID"], ["PWM-11", null, null, "50 Hz stream · no board ID"]] },
    { id: "pcan", name: "PCAN-USB FD", serial: "1C4", identity: "PEAK PCAN-USB FD. No bus voltage — nothing to enumerate until the car is on. Saturday's log can stand in.", honest: true, platform: "fsae", mapping: [] },
    { id: "cam0", name: "UVC camera", serial: "—", identity: "Generic UVC 640×480. Vendor string is empty — labelled by port, not by model.", honest: true, platform: null, mapping: [] },
  ];
  const SOURCED = [
    { name: "Dynamixel XM540-W270", torque: "10.6 N·m", cost: "$309", weight: "165 g", proto: "RS-485", note: "2× headroom; heaviest" },
    { name: "MyActuator RMD-X4", torque: "8.0 N·m", cost: "$189", weight: "300 g", proto: "CAN", note: "integrated driver; needs 24 V" },
    { name: "Feetech STS3250", torque: "4.9 N·m", cost: "$45", weight: "78 g", proto: "TTL bus", note: "under requirement — would stall", weak: true },
    { name: "Robotis XL430-W250", torque: "1.4 N·m", cost: "$50", weight: "57 g", proto: "TTL", note: "far under requirement", weak: true },
  ];

  const NEWSOLUS = () => ({ hardware: [], details: [], errors: [], docs: [], code: [] });
  const part = (id, name, cat, state, src, robotId, extra) => ({ id, name, cat, state, src, robotId, ...extra });

  const PRESETS = {
    maya: { label: "ML researcher", name: "lerobot-act-cube", persona: "maya", accounts: ["github", "mujoco"], docs: ["gh-act", "mj-so101"],
      robots: [{ id: "r1", name: "so101-follower", platform: "so101", device: "acm0", mapped: true }, { id: "r2", name: "so101-leader", platform: "so101", device: "acm1", mapped: true, idle: true }],
      parts: [...DETECTED[0].mapping.map((m, i) => part("p" + i, m[1], i === 5 ? "end effectors" : "actuators", "live", "detected", "r1", { ev: m[3], conf: m[2] })), part("pc", "bus servo adapter", "controllers", "live", "detected", "r1"), part("pp", "5 V / 2 A supply", "power", "installed", "authored", "r1", { hot: 1 }), part("pl", "6× STS3215 (leader)", "actuators", "live", "detected", "r2")],
      installed: [], suggestions: [{ id: "s1", what: "UVC camera (detected)", to: "r1", conf: 0.74, ev: "same USB hub as ACM0 · appeared 2 min after it", cat: "sensors" }],
      solus: { ...NEWSOLUS(), details: [{ t: "text", title: "ACT policy · cube pick-and-place · 20-episode evals" }], code: [{ t: "text", title: "Python 3.11 · torch 2.4 · lerobot main" }], hardware: [{ t: "sol", title: "so101-follower.yaml", sub: "written from detection · 6 channels mapped" }, { t: "sol", title: "so101-leader.yaml", sub: "written from detection" }] },
      activity: ["run 41 failed · 14/20", "SOL: joint 2 stall finding", "so101-leader added"] },
    sam: { label: "Hobbyist", name: "desk-arm-v1", persona: "sam", accounts: ["onshape", "kicad"], docs: ["on-desk", "ki-shield"],
      robots: [{ id: "r1", name: "desk-arm-v1", platform: "uno", device: "usb0", mapped: false }],
      parts: [part("p0", "Motor-1", "actuators", "live", "detected", "r1", { ch: "PWM-9", honest: 1 }), part("p1", "Motor-2", "actuators", "live", "detected", "r1", { ch: "PWM-10", honest: 1 }), part("p2", "Motor-3", "actuators", "live", "detected", "r1", { ch: "PWM-11", honest: 1 }), part("pm", "MCU: unknown (CH340 bridge)", "controllers", "live", "detected", "r1", { honest: 1 }), part("pb", "servo bracket", "structure", "installed", "file", "r1", { doc: "on-desk" })],
      installed: [], suggestions: [{ id: "s1", what: "gripper (asm) · desk-arm", to: "r1", conf: 0.81, ev: "mates to arm link in CAD", cat: "end effectors" }],
      solus: { ...NEWSOLUS(), details: [{ t: "text", title: "Arduino desk arm · 3 hobby servos · learning KiCad" }], errors: [{ t: "sol", title: "upload failed: avrdude stk500_recv() timeout", sub: "auto-filed by SOL · 2 d ago" }] },
      activity: ["servos 9 & 10 jitter finding", "servo bracket added from CAD"] },
    priya: { label: "FSAE electronics lead", name: "fsae-ev-2027", persona: "priya", accounts: ["github", "solidworks", "altium", "ansys"], docs: ["gh-vcu", "sw-ev27", "ad-pdu", "an-ev27", "log-sat"],
      robots: [{ id: "r1", name: "EV27", platform: "fsae", device: "pcan", mapped: true }],
      parts: [part("p0", "inverter · Cascadia PM100", "actuators", "installed", "file", "r1", { hot: 1 }), part("p1", "F3 · 30 A fuse", "power", "installed", "file", "r1", { hot: 1, doc: "ad-pdu" }), part("p2", "harness W-12 · 16 AWG", "wiring", "installed", "file", "r1", { hot: 1, doc: "sw-ev27" }), part("p3", "BMS · Orion 2", "controllers", "installed", "file", "r1"), part("p4", "VCU · STM32H7", "controllers", "live", "detected", "r1"), part("p5", "wheel speed ×4", "sensors", "installed", "file", "r1"), part("p6", "F3 · 35 A fuse", "power", "planned", "sourced", "r1", { replaces: "p1" }), part("p7", "accumulator 400 V", "power", "installed", "file", "r1")],
      installed: ["bom"], suggestions: [{ id: "s1", what: "fsae-ev/telemetry (repo)", to: "r1", conf: 0.66, ev: "reads 0x0A2 frames from this bus", cat: null }],
      solus: { ...NEWSOLUS(), details: [{ t: "file", title: "FSAE Rules 2027.pdf", sub: "imported · 142 pages · 38 EV rules indexed", rules: 38 }], docs: [{ t: "file", title: "Harness spec v3.docx" }], errors: [{ t: "sol", title: "CAN 0x0A2 overcurrent trip · lap 7 · 14:42:07", sub: "auto-filed from Saturday log" }], hardware: [{ t: "sol", title: "EV27.yaml", sub: "CAN IDs · 9 nodes" }], code: [{ t: "text", title: "STM32 · C · make" }] },
      activity: ["power cut finding · lap 7", "F3 35 A planned (sourced)", "BOM installed"] },
  };
  const LINKS = [
    { a: "gh-act", b: "robot:so101", n: 12, label: "policy → servos · limits", hot: 1, a2: "act_policy.py", b2: "shoulder_lift", label2: "action head → M2 commands" },
    { a: "gh-act", b: "mj-so101", n: 8, label: "URDF · scenes", a2: "so101.urdf", b2: "so101_cube.xml", label2: "same URDF, both worlds" },
    { a: "robot:so101", b: "mj-so101", n: 6, label: "sim ↔ real joints", a2: "shoulder_lift", b2: "sim joint2 (clips)", label2: "joint 2 mirrored" },
    { a: "on-desk", b: "robot:uno", n: 3, label: "CAD ↔ parts", a2: "servo bracket", b2: "Motor-1", label2: "bracket holds Motor-1" },
    { a: "ki-shield", b: "robot:uno", n: 4, label: "pins ↔ sheet", hot: 1, a2: "PWM-9 header", b2: "Motor-1", label2: "PWM-9 drives Motor-1" },
    { a: "ad-pdu", b: "sw-ev27", n: 3, label: "F3 ↔ harness W-12", hot: 1, a2: "F3 · 30 A", b2: "W-12 · 16 AWG", label2: "F3 rating → W-12 gauge" },
    { a: "log-sat", b: "ad-pdu", n: 5, label: "CAN frames ↔ sheets", hot: 1, a2: "inverter · 0x0A2", b2: "F3 · 30 A", label2: "fault frame ↔ F3" },
    { a: "gh-vcu", b: "log-sat", n: 4, label: "fault handling", a2: "fault_handler.c", b2: "inverter · 0x0A2", label2: "decodes 0x0A2" },
    { a: "robot:fsae", b: "ad-pdu", n: 7, label: "parts ↔ schematic", a2: "F3 · 30 A fuse", b2: "F3 · 30 A", label2: "same fuse" },
    { a: "sw-ev27", b: "an-ev27", n: 6, label: "studies", a2: "chassis (asm)", b2: "chassis torsion", label2: "chassis → torsion" },
    { a: "widget:bench", b: "robot:*", n: 1, label: "streams" },
    { a: "solus:root", b: "robot:*", n: 2, label: "hardware configs" },
  ];
  const WIDGETS = [
    { id: "bom", name: "BOM", fp: true, by: "Solus", req: "a robot with parts", does: "Every part in the robot, raw materials, anything purchased — one row per canonical part. Lifecycle per row. Find compatible parts honouring your compliance rules.", adds: ["BOM tab (after the separator)", "BOM node in the graph", "SOL: find compatible parts, check stock"], icon: "file" },
    { id: "compliance", name: "Compliance", fp: true, by: "Solus", req: "rules in .solus › Project details", does: "Checks parts and wiring against imported rules; violations become findings.", adds: ["Compliance tab", "Rule checks on every part change", "SOL: “is this legal under T.9?”"], icon: "check" },
    { id: "canview", name: "CAN Inspector", fp: false, by: "community · fsae-tools", req: "a CAN device or log", does: "Decode frames by DBC, bus load, node health.", adds: ["CAN tab", "Frame decoding in findings"], icon: "bench" },
    { id: "datasheets", name: "Datasheet Finder", fp: false, by: "community · r0b0tk1d", req: "an EDA document", does: "Pins datasheets to schematic components.", adds: ["Datasheet links on parts"], icon: "file" },
    { id: "notes", name: "Session Notes", fp: false, by: "community · benchnotes", req: "nothing", does: "Timestamped notes pinned to telemetry moments.", adds: ["Notes strip on Live Bench"], icon: "file" },
  ];

  function newProject(name, preset) {
    const base = preset ? PRESETS[preset] : null;
    return {
      id: "prj-" + Math.random().toString(36).slice(2, 7), name: name || (base ? base.name : "untitled"), persona: base ? base.persona : null, created: "today", archived: false,
      docs: base ? [...base.docs] : [], robots: base ? base.robots.map((r) => ({ ...r })) : [], parts: base ? base.parts.map((p) => ({ ...p })) : [],
      installed: base ? [...base.installed] : [], suggestions: base ? base.suggestions.map((s) => ({ ...s })) : [], solus: base ? JSON.parse(JSON.stringify(base.solus)) : NEWSOLUS(), activity: base ? [...base.activity] : ["project created"],
      mapped: {},
    };
  }

  function derive(project, connectedAccounts, pinned, rootSolus) {
    const docs = project.docs.map(DOC).filter(Boolean).filter((d) => d.service === "log" || connectedAccounts.includes(d.service));
    const robots = project.robots.map((r) => {
      const parts = project.parts.filter((p) => p.robotId === r.id);
      const tree = CATS.filter((c) => parts.some((p) => p.cat === c)).map((c) => T(c, CAT_D[c], parts.filter((p) => p.cat === c).map((p) => ({ l: p.name + (p.state !== "live" ? " · " + p.state : ""), d: CAT_D[c], hot: p.hot, honest: p.honest, part: p.id })), parts.some((p) => p.cat === c && p.hot)));
      return { ...r, parts, tree, sub: parts.length + " parts · " + (parts.filter((p) => p.state === "live").length) + " live" + (r.idle ? " · idle" : "") };
    });
    const affinity = project.persona || (robots.some((r) => r.platform === "fsae") ? "priya" : robots.some((r) => r.platform === "uno") ? "sam" : robots.some((r) => r.platform === "so101") ? "maya" : null);
    const base = affinity ? P[affinity] : null;
    const liveRobots = robots.filter((r) => !r.idle && r.parts.some((p) => p.state === "live"));
    const signals = [].concat(...liveRobots.map((r) => {
      const src = r.platform === "so101" ? P.maya.signals : r.platform === "uno" ? P.sam.signals : r.platform === "fsae" ? P.priya.signals : [];
      return src.map((s, i) => ({ ...s, id: r.id + "-" + s.id, robot: r.name, name: r.mapped ? s.name : `${r.name}-Motor-${i + 1}`, unit: r.mapped ? s.unit : null, unitNote: r.mapped ? null : "no unit reported — raw values" }));
    }));
    const simKind = liveRobots.some((r) => r.platform === "so101") ? "arm" : liveRobots.some((r) => r.platform === "uno") ? "servo" : liveRobots.some((r) => r.platform === "fsae") ? "can" : "none";
    const graphNodes = [
      ...docs.map((d) => ({ id: d.id, kind: d.service === "log" ? "log" : /gh-/.test(d.id) ? "repo" : d.service === "mujoco" ? "sim" : "doc", name: d.name.length > 26 ? d.name.split("/").pop() : d.name, detail: d.serviceName + " · " + d.sub, domain: d.domain, tree: d.tree, mark: d.mark })),
      ...robots.map((r) => ({ id: "robot:" + r.id, kind: "robot", name: r.name, detail: "Physical Robot · " + r.sub, domain: "ee", tree: r.tree, platform: r.platform, robot: r })),
      ...(robots.length ? [{ id: "widget:bench", kind: "widget", name: "Live Bench", detail: "widget · " + signals.length + " signals", domain: "rt", tree: [] }] : []),
      { id: "solus:root", kind: "solus", name: ".solus", detail: "root + project · " + Object.values(project.solus).reduce((a, s) => a + s.length, 0) + " project entries", domain: "sw", tree: [
        { l: "~/.solus (root)", d: "sw", kids: (rootSolus ? Object.keys(rootSolus).filter((k) => rootSolus[k].length).map((k) => ({ l: k + " · " + rootSolus[k].length, d: "sw" })) : []) },
        ...[["hardware", "Hardware configs"], ["details", "Project details"], ["errors", "Error logging"], ["docs", "Documentation"], ["code", "Code environment"]].filter(([k]) => project.solus[k].length).map(([k, l]) => ({ l, d: k === "errors" ? "rt" : k === "hardware" ? "ee" : "sw", kids: project.solus[k].slice(0, 4).map((e) => ({ l: e.title.length > 26 ? e.title.slice(0, 26) + "…" : e.title, d: k === "errors" ? "rt" : "sw", hot: k === "errors" ? 1 : 0 })) })),
      ] },
      ...project.installed.map((w) => ({ id: "widget:" + w, kind: "widget", name: WIDGETS.find((x) => x.id === w).name, detail: "widget · installed", domain: "sw", tree: [] })),
    ];
    const nid = (ref) => ref.startsWith("robot:") ? robots.filter((r) => ref === "robot:*" || r.platform === ref.slice(6)).map((r) => "robot:" + r.id) : [ref];
    const links = [];
    LINKS.forEach((l) => nid(l.a).forEach((A) => nid(l.b).forEach((B) => { if (graphNodes.some((n) => n.id === A) && graphNodes.some((n) => n.id === B) && A !== B) links.push({ ...l, a: A, b: B }); })));
    const findingsAll = [{ p: "maya", req: () => docs.some((d) => d.id === "gh-act") && robots.some((r) => r.platform === "so101"), key: "diagnose" }, { p: "sam", req: () => robots.some((r) => r.platform === "uno"), key: "jitter" }, { p: "priya", req: () => docs.some((d) => d.id === "ad-pdu") && robots.some((r) => r.platform === "fsae"), key: "cutout" }];
    const findings = findingsAll.filter((f) => f.req()).map((f) => ({ ...f, finding: P[f.p].finding, node: "robot:" + (robots.find((r) => r.platform === ({ maya: "so101", sam: "uno", priya: "fsae" })[f.p]) || {}).id }));
    const rules = (project.solus.details.find((e) => e.rules) || {}).rules || 0;
    const bom = project.parts.map((p) => ({ ...p, sources: ["robot", ...docs.filter((d) => JSON.stringify(d.tree).toLowerCase().includes(p.name.split(" ")[0].toLowerCase().replace("·", "").trim())).map((d) => d.serviceName)] }));
    return { project, docs, robots, signals, simKind, camera: project.parts.some((p) => /cam/i.test(p.name)) || docs.some((d) => d.id === "log-sat"), lidar: project.parts.some((p) => /lidar/i.test(p.name)), graphNodes, links, findings, finding: findings[0] ? findings[0].finding : null, base, affinity, rules, bom,
      anomaly: base ? base.anomaly : {}, approvals: base ? base.approvals : {}, sol: base ? base.sol : { hello: { text: "Nothing is connected in this project yet. Add a document or hardware in Workspace and ask me again — I only speak from what's here." } }, guide: base && base.guide && docs.some((d) => d.id === "ki-shield") ? base.guide : null, compare: base ? base.compare : {}, runs: base ? base.runs : [],
      id: affinity || "custom", tabs: [...new Set([...(pinned || []), ...project.installed])].filter((w) => WIDGETS.some((x) => x.id === w)) };
  }

  window.V4 = { ACCOUNTS, DOC, TREES, CATS, CAT_D, STATES, guessCat, LIBRARY, DETECTED, SOURCED, PRESETS, WIDGETS, newProject, derive };
})();
