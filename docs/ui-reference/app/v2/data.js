// Solus v2 — persona worlds: Maya (ML researcher), Sam (hobbyist), Priya (FSAE lead)
(function () {
  const sig = (id, name, unit, base, amp, period, extra) => ({ id, name, unit, base, amp, period, phase: (id.charCodeAt(0) + id.length) % 6, ...extra });
  const ALT_UNITS = { deg: ["deg", "rad"], A: ["A", "mA"], V: ["V", "mV"], kph: ["kph", "mph"], "%": ["%"], null: [] };

  /* ============ MAYA ============ */
  const maya = {
    id: "maya", label: "Maya — ML researcher", wsName: "lerobot-act-cube", wsSub: "Solo · SO-101 + MuJoCo",
    tagline: "ACT policy · SO-101 arms · MuJoCo",
    connections: {
      cloud: [
        { id: "github", name: "GitHub", mark: "GH", state: "connected", detail: "maya-builds/lerobot-act-cube · 214 files, indexed" },
        { id: "hf", name: "Hugging Face", mark: "HF", state: "connectable", detail: "Checkpoints & datasets" },
        { id: "onshape", name: "Onshape", mark: "On", state: "connectable", detail: "Mechanical CAD" },
      ],
      local: [],
      localNote: "No local CAD or EDA applications found on this machine. SolidWorks, KiCad, Altium and ANSYS appear here automatically when installed.",
      devices: [
        { id: "so101f", name: "SO-101 · Follower", mark: "F", state: "live", role: "FOLLOWER", detail: "USB /dev/ttyACM0 · 6 servos @ 50 Hz", identity: "Feetech STS3215 ×6 — confirmed by bus handshake", canStop: true },
        { id: "so101l", name: "SO-101 · Leader", mark: "L", state: "idle", role: "LEADER", detail: "USB /dev/ttyACM1 · teleop input, not streaming", identity: "Same model as follower — labels from pairing wizard", swap: true },
        { id: "mujoco", name: "MuJoCo", mark: "SIM", state: "live", detail: "scene so101_cube.xml · RT ×1.0", canStop: true },
        { id: "wristcam", name: "Wrist camera", mark: "CAM", state: "live", detail: "640×480 @ 30 fps · time-synced", canStop: true },
      ],
    },
    derive: [
      ["Robot + simulator connected", "Live Bench"],
      ["Repo has train / eval scripts", "Experiments"],
      ["Camera present", "Video, time-aligned with telemetry"],
      ["No CAD connected", "CAD widgets stay hidden until you connect one"],
    ],
    taskTabs: ["Debug", "Train"],
    widgets: {
      Debug: [
        { id: "exp", type: "exp", title: "Experiments", because: "repo has eval scripts" },
        { id: "finding", type: "finding", title: "Latest finding", because: "run 41 anomalies" },
        { id: "bench", type: "bench", title: "Live Bench", because: "SO-101 streaming" },
        { id: "repo", type: "repo", title: "lerobot-act-cube", because: "GitHub connected" },
      ],
      Train: [
        { id: "exp", type: "exp", title: "Experiments", because: "repo has eval scripts" },
        { id: "repo", type: "repo", title: "lerobot-act-cube", because: "GitHub connected" },
        { id: "sim", type: "sim", title: "MuJoCo", because: "simulator connected" },
      ],
    },
    unlocks: [{ n: "Connect Onshape or KiCad", u: "part views + cross-domain CAD checks" }, { n: "Connect Hugging Face", u: "checkpoint compare across runs" }],
    signals: [
      sig("j1", "base_pan", "deg", 5, 38, 4.2),
      sig("j2", "shoulder_lift", "deg", 40, 45, 3.4, { hot: true }),
      sig("j3", "elbow_flex", "deg", -20, 50, 2.9),
      sig("j4", "wrist_flex", "deg", 10, 35, 2.2),
      sig("j5", "wrist_roll", "deg", 0, 80, 5.0),
      sig("j6", "gripper", "%", 55, 40, 1.8),
      sig("i2", "M2 current", "A", 0.6, 0.45, 1.7, { hot: true }),
      sig("vbus", "supply", "V", 5.02, 0.04, 6.0, { hot: true }),
    ],
    anomaly: { j2: { pin: 90, cmd: 112 }, i2: { pin: 3.0 }, vbus: { dip: 4.35 } },
    sim: { kind: "arm", spawnable: [{ id: "so101f", label: "SO-101 Follower (live mirror)" }, { id: "so101l", label: "SO-101 Leader (idle)" }, { id: "cube", label: "Cube prop (sim only)" }], defaultScene: ["so101f"] },
    camera: true,
    runs: [
      { id: "41", name: "ACT eval · cube pick", status: "failed", eps: 20, bad: [2, 3, 5, 6, 8, 9, 10, 12, 13, 15, 16, 17, 18, 19], when: "today 09:12", dur: "6m 40s", target: "hardware", expect: "≥ 18/20 successful grasps" },
      { id: "40", name: "ACT eval · cube pick (sim)", status: "passed", eps: 20, bad: [], when: "yesterday", dur: "3m 05s", target: "sim", expect: "≥ 18/20 successful grasps" },
    ],
    compare: {
      simReal: "Sim and real agree until the arm nears the joint limit (ep 2, t≈4.1 s). In sim the joint clips silently at ±90°; on hardware the servo hits the stop, stalls at 3.0 A, and the supply browns out — resetting the bus. The divergence is the URDF limit meeting real electronics.",
      runRun: "After the clamp + current-limit flash, joint 2 stays inside ±90°, M2 current peaks at 1.4 A, and the supply holds 5.0 V. 0 of 20 episodes anomalous (was 14).",
    },
    finding: {
      id: "f-stall", sev: "critical", title: "Joint 2 stalls — your policy, the servo, and the supply are fighting",
      when: "Run 41 · 14 of 20 episodes",
      chain: [
        { d: "sw", l: "policy commands 112°", n: "act_policy.py L214 — no output clamp on the action head" },
        { d: "me", l: "URDF limits joint 2 to ±90°", n: "so101.urdf — the physical hard stop" },
        { d: "ee", l: "servo stalls at 3.0 A", n: "STS3215 stall current — it can't push past the stop" },
        { d: "ee", l: "supply browns out at 2.1 A", n: "5 V / 2 A wall adapter — the whole servo bus resets" },
      ],
      what: "In 14 episodes the policy asked joint 2 to go past its mechanical limit. The servo pinned against the stop drawing stall current until the supply sagged and every servo on the bus reset mid-episode.",
      why: "This isn't a bad policy or a broken arm — it's the boundary between them. Nothing in training penalized commands past ±90°, and nothing in firmware limits current yet.",
      next: "Clamp the policy output to the URDF limits, and flash a 2.4 A current limit so a future stall can't brown out the bus.",
      fixes: ["ap-clamp", "ap-flash"],
    },
    approvals: {
      "ap-clamp": {
        id: "ap-clamp", type: "code", risk: "low", title: "Clamp policy output to URDF joint limits", target: "act_policy.py · L212–216",
        diff: [
          { t: "ctx", s: "def select_action(self, obs):" }, { t: "ctx", s: "    a = self.head(obs_embed)" },
          { t: "del", s: "    return a" },
          { t: "add", s: "    lim = self.urdf_limits  # ±90° for joints 1–4" },
          { t: "add", s: "    return torch.clamp(a, -lim, lim)" },
        ], note: "Limits are read from so101.urdf at load — stays correct if the CAD changes.",
      },
      "ap-flash": {
        id: "ap-flash", type: "flash", risk: "medium", title: "Flash M2 servo with a 2.4 A current limit",
        manifest: [["Controller", "Feetech STS3215 · bus id 2"], ["Port", "/dev/ttyACM0"], ["Change", "I_limit 3.0 A → 2.4 A"], ["During flash", "all 6 servos disabled ~4 s"], ["Rollback", "previous table saved to .solus/backup"]],
        note: "2.4 A keeps full working torque but stays under the 2.1 A × 1.15 brownout margin of your supply — replace the 2 A adapter to raise this.",
      },
      "ap-rerun": {
        id: "ap-rerun", type: "motion", risk: "medium", title: "Re-run experiment on hardware — the arm will move",
        manifest: [["Robot", "SO-101 Follower"], ["Motion", "20 episodes · pick-and-place, cube"], ["Envelope", "keep 30 cm around the arm clear"], ["Abort", "Space bar, or the E-stop tab on the bench"]],
        note: "Starts from home pose. SOL aborts automatically if any joint exceeds limits.",
      },
    },
    sol: {
      diagnose: { finding: true, text: "I traced the 14 failed episodes across your stack — this is one fault, seen from three domains. Full chain below; both fixes are one click each." },
      why42: { q: "Why does it stall on some episodes and not others?", text: "Only episodes where the cube spawns in the far-left third of the workspace drive joint 2 past 90° — the policy learned an over-reach for that region. The 6 clean episodes never approached the limit. That's also why it looked random: the spawn position is the hidden variable." },
      whatflash: { q: "What exactly does the flash change?", text: "One register in the servo's control table: the phase-current ceiling (3.0 A factory → 2.4 A). It's not firmware replacement — the control loop is untouched, and I keep a backup of the table. Worst case you re-flash the factory value from Connections → SO-101 → registers." },
      hello: { text: "I'm grounded in what's connected: your repo, both arms, the sim and the wrist camera. Ask why a run failed, what a signal means, or what a change would affect. Try: “diagnose run 41.”" },
    },
    graph: {
      roots: [
        { id: "github", label: "GitHub · lerobot-act-cube", d: "sw", kids: [
          { id: "train", label: "train.py", d: "sw" }, { id: "eval", label: "eval.py", d: "sw" },
          { id: "policy", label: "act_policy.py", d: "sw", hot: true, kids: [{ id: "head", label: "action head · L214", d: "sw", hot: true }] },
          { id: "urdf", label: "so101.urdf", d: "me", kids: [{ id: "j2lim", label: "joint2 limit ±90°", d: "me", hot: true }, { id: "j3lim", label: "joint3 limit ±110°", d: "me" }] },
        ], more: 208 },
        { id: "so101f", label: "SO-101 Follower", d: "ee", kids: [
          { id: "m1", label: "M1 · base_pan", d: "ee" }, { id: "m2", label: "M2 · shoulder_lift", d: "ee", hot: true, kids: [{ id: "m2i", label: "stall 3.0 A", d: "ee", hot: true }] },
          { id: "m3", label: "M3 · elbow_flex", d: "ee" }, { id: "bus", label: "servo bus 5 V", d: "ee", kids: [{ id: "psu", label: "supply 5 V / 2 A", d: "ee", hot: true }] },
        ], more: 3 },
        { id: "mujoco", label: "MuJoCo", d: "rt", kids: [{ id: "scene", label: "so101_cube.xml", d: "rt" }, { id: "simj2", label: "sim joint2 (clips)", d: "rt" }] },
      ],
      links: [["head", "j2lim", "should respect"], ["j2lim", "m2", "same physical joint"], ["m2i", "psu", "stall exceeds supply"], ["simj2", "m2", "sim ↔ real"]],
      proposals: [{ a: "M2 · shoulder_lift", b: "urdf joint “shoulder_lift”", conf: 0.87, ev: "matched by motion range + bus order" }],
    },
    notifications: [
      { id: "n1", sev: "critical", title: "Run 41: joint 2 stalled in 14/20 episodes", sub: "Cross-domain finding ready — policy · URDF · servo · supply", action: "diagnose" },
      { id: "n2", sev: "info", title: "Leader arm idle 3 days", sub: "Unplug it or start teleop to use it", action: null },
    ],
  };

  /* ============ SAM ============ */
  const sam = {
    id: "sam", label: "Sam — hobbyist", wsName: "desk-arm-v1", wsSub: "Solo · Arduino + KiCad",
    tagline: "Arduino Uno · 3 servos · KiCad + Onshape free",
    connections: {
      cloud: [{ id: "onshape", name: "Onshape (free)", mark: "On", state: "connected", detail: "desk-arm · 1 part studio" }, { id: "github", name: "GitHub", mark: "GH", state: "connectable", detail: "No repo yet — sketches live on this PC" }],
      local: [
        { id: "kicad", name: "KiCad 8", mark: "Ki", state: "installed", running: false, detail: "servo-shield.kicad_pro · last opened 2 d ago" },
      ],
      localNote: null,
      devices: [
        { id: "uno", name: "USB serial device", mark: "?", state: "live", detail: "/dev/ttyUSB0 · 115200 baud", identity: "Recognized: CH340 USB-serial bridge. The board behind it is unknown — likely Arduino-compatible, but I won't guess.", honest: true, probe: "ap-probe", canStop: true },
      ],
    },
    derive: [
      ["Serial device streaming 3 PWM values", "Live Bench (3 signals, unnamed)"],
      ["KiCad installed", "Guide mode for KiCad"],
      ["No repo connected", "Experiments stay hidden — nothing runnable yet"],
      ["Onshape free tier", "Part views, read-only"],
    ],
    taskTabs: ["Build"],
    widgets: {
      Build: [
        { id: "guide", type: "guide", title: "Guide · ground pour", because: "KiCad installed, task in progress" },
        { id: "bench", type: "bench", title: "Live Bench", because: "serial device streaming" },
        { id: "board", type: "board", title: "servo-shield.kicad_pcb", because: "KiCad project found" },
        { id: "identify", type: "identify", title: "Unknown board", because: "device identity unconfirmed" },
      ],
    },
    unlocks: [{ n: "Connect a GitHub repo", u: "Experiments — define and compare runs" }, { n: "Confirm the board identity", u: "pin names instead of PWM-9/10/11" }],
    signals: [
      sig("p9", "UNO-PWM-9", null, 1500, 380, 2.6, { unitNote: "no unit reported — raw timer counts" }),
      sig("p10", "UNO-PWM-10", null, 1420, 300, 3.1, { unitNote: "no unit reported — raw timer counts" }),
      sig("p11", "UNO-PWM-11", null, 1550, 340, 2.2, { unitNote: "no unit reported — raw timer counts" }),
    ],
    anomaly: { p9: { jitter: 260 }, p10: { jitter: 260 } },
    sim: { kind: "servo", spawnable: [{ id: "horn", label: "Servo horn (from PWM-9)" }], defaultScene: ["horn"] },
    camera: false,
    runs: [],
    runsEmpty: "No runs yet. Experiments appear once something can be run — connect a repo with a script, or ask SOL to scaffold one from your sketch.",
    finding: {
      id: "f-jitter", sev: "warning", title: "Servos 9 and 10 jitter together — they share Timer1",
      when: "Live · started when both servos active",
      chain: [
        { d: "sw", l: "Servo library uses Timer1", n: "pins 9 & 10 are both driven by the same 16-bit timer" },
        { d: "ee", l: "PWM pulses collide", n: "when both update in the same cycle the pulse width wobbles ±260 µs" },
        { d: "me", l: "horn oscillates ±4°", n: "visible as the shake you noticed on the bracket" },
      ],
      what: "Both servos are timed by one hardware timer; updating them in the same loop iteration makes their pulses wobble.",
      why: "It looks like a mechanical problem but it's a timing one — no amount of bracket stiffening will fix it.",
      next: "Move one servo to pin 11 (Timer2) or stagger the writes by 10 ms. I can show you where in the sketch.",
      fixes: [],
    },
    approvals: {
      "ap-probe": { id: "ap-probe", type: "cmd", risk: "low", title: "Probe the unknown board (uploads a 2 KB identify sketch)", cmd: "arduino-cli upload -p /dev/ttyUSB0 --fqbn arduino:avr:uno identify/", manifest: [["Writes", "flash sector 0x7000 (bootloader untouched)"], ["Reverts", "your sketch is re-flashed after"], ["Tells us", "MCU, clock, fuse bits"]], note: "If it's not an AVR board this fails safely with a timeout." },
      "ap-pour": { id: "ap-pour", type: "cad", risk: "low", title: "Draw GND pour on In2.Cu (KiCad)", params: [["Layer", "In2.Cu", "GND pour, 0.25 mm clearance"], ["Islands", "keep", "remove"], ["Thermal relief", "—", "4 spokes, 0.5 mm"]], note: "Runs through KiCad's API — undo works normally (⌘Z in KiCad)." },
    },
    sol: {
      pour: { guide: true, text: "Ground pour in KiCad 8 — I'll walk you through it. My confidence per step is marked; where the 8.0 menus moved and I'm not sure, I say so instead of pointing at the wrong thing." },
      jitter: { finding: true, text: "That shake isn't mechanical. Here's the chain — it starts in the Servo library and ends at your bracket." },
      hello: { text: "I can see your serial device, your KiCad project and your Onshape part. I'm best at explaining the next step in a tool you haven't used — try “how do I add a ground pour?”" },
    },
    guide: {
      task: "Add a ground pour", tool: "KiCad 8 · pcbnew", progress: 0,
      steps: [
        { t: "Open the PCB editor (pcbnew) from the KiCad project window", conf: 0.98 },
        { t: "In the right-hand Layers panel, select In2.Cu", conf: 0.93 },
        { t: "Place ▸ Zone (in 8.0 this moved from the Add menu)", conf: 0.72, note: "menu changed between 7.x and 8.0" },
        { t: "Set net to GND, clearance 0.25 mm, click OK, then trace the board outline", conf: 0.9 },
        { t: "Remove islands", conf: null, gap: "I'm not sure where “Remove islands” lives in 8.0 — in 7.x it was in Zone Properties. Open Zone Properties (E on the zone) and look under Electrical Properties. If you find it, tell me and I'll remember." },
        { t: "Press B to refill zones, then run DRC", conf: 0.97 },
      ],
    },
    graph: {
      roots: [
        { id: "kicad", label: "KiCad · servo-shield", d: "ee", kids: [{ id: "sheet", label: "main sheet", d: "ee", kids: [{ id: "j9", label: "PWM-9 header", d: "ee" }, { id: "reg", label: "5 V regulator", d: "ee" }] }, { id: "pcb", label: "board · 2 layer", d: "ee" }], more: 14 },
        { id: "uno", label: "USB serial (CH340)", d: "rt", kids: [{ id: "p9n", label: "PWM-9 stream", d: "rt", hot: true }, { id: "p10n", label: "PWM-10 stream", d: "rt", hot: true }, { id: "mcu", label: "MCU: unknown", d: "rt", honest: true }] },
        { id: "onshape", label: "Onshape · desk-arm", d: "me", kids: [{ id: "bracket", label: "servo bracket", d: "me", hot: true }, { id: "arm", label: "arm link", d: "me" }] },
      ],
      links: [["p9n", "j9", "same pin"], ["p9n", "bracket", "drives horn on"], ["mcu", "p9n", "source unknown"]],
      proposals: [{ a: "USB serial device", b: "Arduino Uno (ATmega328P)", conf: 0.62, ev: "CH340 bridge + 115200 baud is the common Uno clone setup — unconfirmed" }],
    },
    notifications: [{ id: "n1", sev: "warning", title: "Servos 9 & 10 jitter when both active", sub: "Shared-timer conflict — explanation ready", action: "jitter" }],
  };

  /* ============ PRIYA ============ */
  const priya = {
    id: "priya", label: "Priya — FSAE electronics lead", wsName: "fsae-ev-2027", wsSub: "Team · 40 members",
    tagline: "SolidWorks · Altium · CAN bus · testing days",
    connections: {
      cloud: [{ id: "github", name: "GitHub org", mark: "GH", state: "connected", detail: "fsae-ev · 6 repos (vcu-fw, dash, telemetry…)" }, { id: "luminary", name: "Luminary Cloud", mark: "LC", state: "connectable", detail: "Aero CFD runs" }],
      local: [
        { id: "sw", name: "SolidWorks 2025", mark: "SW", state: "installed", running: true, detail: "EV27 master assembly open · 3,182 parts" },
        { id: "altium", name: "Altium Designer", mark: "AD", state: "installed", running: false, detail: "PDU rev C · last opened yesterday" },
        { id: "ansys", name: "ANSYS Mechanical", mark: "AN", state: "installed", running: false, detail: "12 studies indexed" },
      ],
      localNote: null,
      devices: [
        { id: "pcan", name: "PCAN-USB", mark: "CAN", state: "stopped", detail: "500 kbit/s · no bus voltage — car not connected", honestIdle: "Nothing on the bus right now. Saturday's log is loaded instead.", canStart: true },
        { id: "log", name: "Testing day log · Sat", mark: "LOG", state: "loaded", detail: "42 min · 1.2 M CAN frames · 4 video angles" },
      ],
    },
    derive: [
      ["PCAN idle + Saturday log present", "Bench plays back the log, not fabricated live data"],
      ["SolidWorks + Altium installed", "Part & schematic views, provenance"],
      ["Org repos connected", "Who-changed-what across domains"],
      ["40 members", "Knowledge survives graduation — provenance search"],
    ],
    taskTabs: ["Testing day", "Design review"],
    widgets: {
      "Testing day": [
        { id: "log", type: "log", title: "Saturday log", because: "PCAN idle — log loaded" },
        { id: "finding", type: "finding", title: "Power cut at turn 3", because: "fault frames in log" },
        { id: "can", type: "can", title: "CAN health", because: "PCAN interface configured" },
        { id: "knowledge", type: "knowledge", title: "Ask the car's history", because: "3 years of team data indexed" },
      ],
      "Design review": [
        { id: "knowledge", type: "knowledge", title: "Ask the car's history", because: "3 years of team data indexed" },
        { id: "board", type: "board", title: "PDU rev C", because: "Altium project indexed" },
        { id: "team", type: "team", title: "Recent changes", because: "org repos + PDM activity" },
      ],
    },
    unlocks: [{ n: "Start the PCAN stream", u: "live bench when the car is on" }, { n: "Connect Luminary", u: "aero runs beside track data" }],
    signals: [
      sig("ws", "wheelspeed FL", "kph", 62, 28, 7.0),
      sig("inv", "inverter current", "A", 18, 9, 4.4, { hot: true }),
      sig("pack", "pack voltage", "V", 398, 6, 9.0, { hot: true }),
      sig("busload", "CAN load", "%", 46, 8, 5.2),
    ],
    anomaly: { inv: { pin: 40 }, pack: { dip: 371 } },
    sim: { kind: "can", spawnable: [{ id: "pdu", label: "PDU node map" }], defaultScene: ["pdu"] },
    camera: true,
    runs: [
      { id: "sat", name: "Endurance sim · Saturday", status: "failed", eps: 12, bad: [7], when: "Sat 14:20", dur: "42 min", target: "log", expect: "12 laps, no faults" },
      { id: "thu", name: "Shakedown · Thursday", status: "passed", eps: 6, bad: [], when: "Thu", dur: "18 min", target: "log", expect: "systems check" },
    ],
    compare: { simReal: null, runRun: "Thursday's shakedown never exceeded 24 A — Saturday's endurance pace pulls 40 A on corner exit. The fuse was never the limit until the driving got faster." },
    finding: {
      id: "f-cut", sev: "critical", title: "Power cut at turn 3 — controller fault, fuse and harness disagree",
      when: "Saturday log · lap 7 · 14:42:07",
      chain: [
        { d: "rt", l: "inverter faults at 40 A", n: "CAN frame 0x0A2: overcurrent trip, lap 7 corner exit" },
        { d: "ee", l: "fuse F3 rated 30 A", n: "PDU rev C schematic, sheet 4 — blows before the inverter limit" },
        { d: "me", l: "harness W-12 is 16 AWG", n: "rated 22 A continuous in the loom spec — undersized for either" },
      ],
      what: "On corner exit the inverter pulled 40 A. F3 (30 A) opened, the VCU browned out, and the car coasted. The harness feeding it is rated below both numbers.",
      why: "Three teams sized three parts against three different assumptions. Each is fine alone; together the weakest one decides when the car stops.",
      next: "Align the chain: 40 A inverter limit → 35 A fuse → 12 AWG harness. I can draft the CAD change and the BOM updates for review.",
      fixes: ["ap-harness"],
    },
    approvals: {
      "ap-harness": { id: "ap-harness", type: "cad", risk: "medium", title: "Resize harness W-12 in SolidWorks routing", params: [["Wire gauge", "16 AWG", "12 AWG"], ["Bend radius", "18 mm", "24 mm (min for 12 AWG)"], ["Connector", "MR30", "XT60 — 16 AWG pins won't crimp on 12 AWG"]], note: "Touches the routing assembly only. F3 fuse change goes on the BOM as a separate line for electrical review." },
      "ap-fuse": { id: "ap-fuse", type: "cad", risk: "low", title: "Update F3 30 A → 35 A on PDU rev C (Altium)", params: [["F3 rating", "30 A", "35 A"], ["Footprint", "unchanged", "unchanged"]], note: "Schematic + BOM only; no layout change." },
    },
    sol: {
      cutout: { finding: true, text: "Found it in the Saturday log. This is a three-domain disagreement — each part is fine alone. Chain below." },
      harness: { prov: true, text: "Harness W-12 history, assembled from PDM + git + the old team drive:", provRows: [["Designed by", "A. Okafor '24 (graduated)"], ["Sized for", "the 2024 20 kW motor — note in drawing: “30 A worst case”"], ["Last touched", "loom re-route, J. Park, Mar 2026 — gauge unchanged"], ["Related", "F3 fuse chosen in the same week, same assumption"]] },
      hello: { text: "I'm indexed on the car: CAD, boards, firmware, CAN logs, and three years of team history. Ask “why did the car cut power” or “who designed the accumulator harness.”" },
    },
    graph: {
      roots: [
        { id: "sw", label: "SolidWorks · EV27", d: "me", kids: [{ id: "chassis", label: "chassis", d: "me" }, { id: "loom", label: "harness loom", d: "me", kids: [{ id: "w12", label: "W-12 · 16 AWG", d: "me", hot: true }] }], more: 3170 },
        { id: "altium", label: "Altium · PDU rev C", d: "ee", kids: [{ id: "s4", label: "sheet 4 · power out", d: "ee", kids: [{ id: "f3", label: "F3 · 30 A", d: "ee", hot: true }] }], more: 11 },
        { id: "pcan", label: "CAN bus (log)", d: "rt", kids: [{ id: "inv", label: "inverter · 0x0A2", d: "rt", hot: true }, { id: "bms", label: "BMS · 0x1B0", d: "rt" }, { id: "vcu", label: "VCU · 0x050", d: "rt" }] },
        { id: "gh", label: "GitHub · fsae-ev", d: "sw", kids: [{ id: "vcufw", label: "vcu-fw", d: "sw" }] },
      ],
      links: [["f3", "inv", "feeds"], ["w12", "f3", "carries"], ["vcufw", "inv", "fault handling"]],
      proposals: [{ a: "W-12 in loom", b: "“INV supply” in PDU sheet 4", conf: 0.91, ev: "endpoint connectors match in both models" }],
    },
    notifications: [
      { id: "n1", sev: "critical", title: "Car cut power at turn 3 (Sat, lap 7)", sub: "Inverter · fuse · harness disagree — explanation ready", action: "cutout" },
      { id: "n2", sev: "info", title: "3 members graduate in May", sub: "Their design notes are indexed — nothing leaves", action: null },
    ],
  };

  window.V2P = { maya, sam, priya };
  window.V2_ALT_UNITS = ALT_UNITS;
  window.v2conv = (v, from, to) => {
    if (from === to || v == null) return v;
    if (from === "deg" && to === "rad") return v * Math.PI / 180;
    if (from === "A" && to === "mA") return v * 1000;
    if (from === "V" && to === "mV") return v * 1000;
    if (from === "kph" && to === "mph") return v * 0.6214;
    return v;
  };
  window.v2fmt = (v, unit) => {
    if (v == null) return "—";
    const a = Math.abs(v);
    const d = a >= 1000 ? 0 : a >= 100 ? 1 : a >= 10 ? 1 : 2;
    return v.toFixed(d);
  };
  window.v2sample = (s, t, anomaly) => {
    let v = s.base + s.amp * Math.sin((2 * Math.PI * t) / s.period + (s.phase || 0)) + (Math.random() - 0.5) * s.amp * 0.12;
    if (anomaly && window.__v2world) {
      const an = window.__v2world.anomaly[s.id];
      if (an) {
        if (an.pin != null) v = an.pin + (Math.random() - 0.5) * an.pin * 0.008;
        if (an.dip != null && Math.sin(t * 2.6) > 0.4) v = an.dip + Math.random() * 0.04;
        if (an.jitter != null) v = s.base + (Math.random() - 0.5) * an.jitter * 2;
      }
    }
    return v;
  };
})();
