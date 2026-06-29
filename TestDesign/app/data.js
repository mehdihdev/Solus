// Solus — placeholder data: graph, alerts, telemetry, team, activity, SOL scripts

/* ================= GRAPH ================= */
window.GRAPH = {
  vb: [1100, 820],
  hulls: [
    { d: "sw", x: 38, y: 58, w: 318, h: 320 },
    { d: "ee", x: 306, y: 398, w: 426, h: 332 },
    { d: "me", x: 716, y: 60, w: 336, h: 300 },
    { d: "rt", x: 714, y: 448, w: 338, h: 312 },
  ],
  nodes: [
    { id: "legik", d: "sw", x: 118, y: 128, l: "leg_ik.c", type: "Firmware source", sub: "Inverse kinematics, per-leg", props: [["Path", "firmware/src/leg_ik.c"], ["Lines", "412"], ["Last commit", "3d ago · Marcus H."]] },
    { id: "gait", d: "sw", x: 262, y: 104, l: "gait_params.h", type: "Firmware header", sub: "Gait + torque constants", props: [["Path", "firmware/include/gait_params.h"], ["Constants", "28"], ["Last commit", "3d ago · Marcus H."]] },
    { id: "md", d: "sw", x: 168, y: 205, l: "motor_driver.c", hot: true, type: "Firmware source", sub: "PWM + gate driver control", props: [["Path", "firmware/src/motor_driver.c"], ["Lines", "638"], ["Last commit", "6d ago · Maya K."]], alert: "a1" },
    { id: "can", d: "sw", x: 272, y: 272, l: "can_bus.c", type: "Firmware source", sub: "CAN FD transport layer", props: [["Path", "firmware/src/can_bus.c"], ["Bitrate", "1 Mbit/s"], ["Last commit", "2w ago · Maya K."]] },
    { id: "foc", d: "sw", x: 120, y: 338, l: "foc_loop.c", type: "Firmware source", sub: "Field-oriented control, 20 kHz", props: [["Path", "firmware/src/foc_loop.c"], ["Loop rate", "20 kHz"], ["Last commit", "6d ago · Maya K."]] },
    { id: "pin", d: "sw", x: 184, y: 300, l: "TIM1_CH1 · STM32H7", hot: true, type: "MCU peripheral pin", sub: "PWM output, AF1", props: [["MCU", "STM32H743ZI"], ["Mode", "PWM, 18.7 kHz"], ["Mapped in", "motor_driver.c:91"]] },

    { id: "m3pwm", d: "ee", x: 388, y: 458, l: "M3_PWM", hot: true, type: "Schematic net", sub: "PWM signal net", props: [["Sheet", "strider_main.sch / p.3"], ["Endpoints", "2"], ["Freq", "18.7 kHz"]] },
    { id: "drv", d: "ee", x: 524, y: 516, l: "DRV8316C · U4", hot: true, type: "IC · gate driver", sub: "3-phase BLDC gate driver", props: [["Package", "QFN-32 (RSM)"], ["Rail", "VBAT_12V"], ["Peak current", "8 A"], ["Control mode", "6×-PWM"], ["Source", "kicad: strider_main.sch"]], alert: "a1" },
    { id: "vbat", d: "ee", x: 400, y: 602, l: "VBAT_12V", type: "Power net", sub: "Main battery rail", props: [["Nominal", "12.0 V"], ["Loads", "14"], ["Fused", "10 A"]] },
    { id: "ina", d: "ee", x: 536, y: 658, l: "INA226 · U7", type: "IC · current monitor", sub: "Bus voltage + current sense", props: [["Bus", "I²C1 @ 0x40"], ["Shunt", "2 mΩ"], ["Alert pin", "PB12"]] },
    { id: "mpu", d: "ee", x: 648, y: 435, l: "MPU9250 · U3", type: "IC · 9-axis IMU", sub: "Accel + gyro + mag", props: [["Bus", "SPI1 @ 1 MHz"], ["INT pin", "PC4"], ["Rail", "3V3_A"]], alert: "a2" },
    { id: "tja", d: "ee", x: 654, y: 615, l: "TJA1051 · U9", type: "IC · CAN transceiver", sub: "CAN FD PHY", props: [["Bus", "can0"], ["Standby", "PB14"], ["Rail", "5V0"]] },
    { id: "tps", d: "ee", x: 432, y: 700, l: "TPS563200 · U11", type: "IC · buck converter", sub: "12 V → 3.3 V, 3 A", props: [["Vout", "3.30 V"], ["Switching", "580 kHz"], ["Rail", "3V3_A"]] },

    { id: "fleg", d: "me", x: 802, y: 122, l: "FL leg assembly", type: "CAD assembly", sub: "Front-left leg, 3 DOF", props: [["Source", "onshape: Strider / Legs"], ["Parts", "23"], ["Mass", "412 g"]] },
    { id: "kgear", d: "me", x: 810, y: 224, l: "knee gearbox 9:1", hot: true, type: "CAD part · gearbox", sub: "Planetary, 9:1", props: [["Ratio", "9:1"], ["Backlash", "0.4°"], ["Rated torque", "6 N·m"], ["Changed", "3d ago · Jonas W."]], alert: "a3" },
    { id: "belt", d: "me", x: 948, y: 165, l: "belt drive 2:1", type: "CAD part", sub: "GT2 belt reduction", props: [["Ratio", "2:1"], ["Belt", "GT2-6mm"], ["Tension", "spec 35 N"]] },
    { id: "chass", d: "me", x: 962, y: 272, l: "chassis frame", type: "CAD assembly", sub: "Carbon main frame", props: [["Parts", "8"], ["Mass", "1.84 kg"], ["Material", "CF + 7075"]] },
    { id: "hgear", d: "me", x: 824, y: 322, l: "hip gearbox 6:1", type: "CAD part · gearbox", sub: "Planetary, 6:1", props: [["Ratio", "6:1"], ["Backlash", "0.3°"], ["Rated torque", "9 N·m"]] },

    { id: "gaitcmd", d: "rt", x: 938, y: 478, l: "/gait/cmd_vel", type: "ROS 2 topic", sub: "geometry_msgs/Twist", props: [["Publisher", "/gait_controller"], ["Rate", "50 Hz"], ["QoS", "reliable"]] },
    { id: "jstate", d: "rt", x: 800, y: 508, l: "/joint_states", type: "ROS 2 topic", sub: "sensor_msgs/JointState", props: [["Publisher", "/state_estimator"], ["Rate", "500 Hz"], ["Joints", "12"]] },
    { id: "tau", d: "rt", x: 930, y: 560, l: "τ3 torque", hot: true, type: "Live signal", sub: "FL knee torque estimate", props: [["Source", "/joint_states · effort[2]"], ["Now", "2.41 N·m"], ["1h range", "0.4 – 3.1 N·m"]] },
    { id: "imu", d: "rt", x: 802, y: 640, l: "/imu/data", type: "ROS 2 topic", sub: "sensor_msgs/Imu", props: [["Publisher", "/imu_filter"], ["Rate", "200 Hz"], ["Frame", "base_link"]] },
    { id: "foot", d: "rt", x: 940, y: 694, l: "foot_contact[FL]", type: "Live signal", sub: "Contact estimate, boolean", props: [["Source", "/contact_estimator"], ["Now", "true"], ["Confidence", "0.94"]] },
  ],
  edges: [
    ["legik", "md"], ["gait", "md"], ["can", "md"], ["foc", "md"],
    ["md", "pin", "writes PWM duty", true], ["pin", "m3pwm", "pin ↔ net", true],
    ["m3pwm", "drv", "gate input", true], ["drv", "vbat"], ["vbat", "ina"], ["vbat", "tps"],
    ["ina", "can", "telemetry via CAN"], ["mpu", "imu", "raw samples"],
    ["drv", "kgear", "drives FL knee", true], ["kgear", "fleg"], ["fleg", "belt"],
    ["fleg", "chass"], ["hgear", "fleg"], ["kgear", "tau", "torque estimate", true],
    ["jstate", "tau"], ["fleg", "foot"], ["can", "tja"], ["jstate", "legik", "feedback"],
    ["gait", "gaitcmd", "params consumed"],
  ],
};

/* ================= ALERTS ================= */
window.ALERTS = [
  {
    id: "a1", sev: "critical", state: "open", time: "2h ago", actor: "Priya Nair",
    fromD: "ee", toD: "sw",
    title: "Motor driver swap breaks firmware pin map",
    summary: "U4 changed DRV8833 → DRV8316C. 3 firmware files still assume the old part's control interface and current limits.",
    change: {
      title: "Component swapped on strider_main board",
      source: "KiCad · strider_main.sch · rev 41 → 42",
      commit: "“swap U4 for higher current headroom” — Priya N., 2h ago",
      before: [["Part", "DRV8833"], ["Control", "2-pin PWM (IN1/IN2)"], ["Peak current", "1.5 A"], ["Package", "HTSSOP-16"]],
      after: [["Part", "DRV8316C"], ["Control", "6×-PWM + nSLEEP"], ["Peak current", "8 A"], ["Package", "QFN-32 (RSM)"]],
    },
    files: [
      {
        path: "firmware/src/motor_driver.c", range: "L 84–112",
        note: "Pin map still targets DRV8833 IN1/IN2 interface",
        code: [
          "// --- M3 (FL knee) driver pin map ---",
          "#define M3_IN1_PIN      GPIO_PIN_8   // TIM1_CH1",
          "#define M3_IN2_PIN      GPIO_PIN_9   // TIM1_CH2",
          "#define M3_SLEEP_PIN    GPIO_PIN_10",
          "",
          "void m3_set_duty(float duty) {",
          "    // DRV8833: sign-magnitude on IN1/IN2",
          "    tim1_write(M3_IN1_PIN, duty > 0 ? fabsf(duty) : 0);",
          "    tim1_write(M3_IN2_PIN, duty < 0 ? fabsf(duty) : 0);",
          "}",
        ],
        hot: [1, 2, 6, 7, 8],
      },
      {
        path: "firmware/src/foc_loop.c", range: "L 203",
        note: "Current limit hardcoded to old part's 1.5 A ceiling",
        code: [
          "// clamp commanded current to driver rating",
          "#define I_PHASE_MAX_A   1.5f   // DRV8833 limit",
          "i_cmd = clampf(i_cmd, -I_PHASE_MAX_A, I_PHASE_MAX_A);",
        ],
        hot: [1],
      },
      {
        path: "firmware/include/gait_params.h", range: "L 44",
        note: "Torque ceiling derived from old current limit",
        code: [
          "#define TAU_KNEE_MAX_NM   2.0f  // from I_PHASE_MAX × Kt × 9.0",
        ],
        hot: [0],
      },
    ],
    why: {
      guide: "The DRV8833 takes two PWM inputs per motor (IN1/IN2) and the firmware drives it in sign-magnitude mode. The DRV8316C is a different class of part — a 3-phase gate driver expecting 6×-PWM with explicit high/low-side inputs and an SPI-configured control register. With the current firmware, the new chip will interpret IN1/IN2 duty cycles as half-bridge commands: at best the motor won't spin, at worst you get shoot-through current spikes on the FL knee phase. The torque and current ceilings in two other files are also derived from the old part's 1.5 A limit, so even after a remap the robot would leave 5× headroom on the table.",
      expert: "DRV8833 = 2-pin sign-magnitude. DRV8316C = 6×-PWM gate driver + SPI config. Current pin map drives half-bridges with stale duty semantics → torque ripple or shoot-through on M3. I_PHASE_MAX (1.5 A) and TAU_KNEE_MAX (2.0 N·m) also stale.",
    },
    fix: {
      summary: "Remap M3 to 6×-PWM, configure DRV8316C over SPI, raise current/torque limits to new ratings.",
      file: "firmware/src/motor_driver.c",
      confidence: 0.92,
      diff: [
        { t: "ctx", s: "// --- M3 (FL knee) driver pin map ---" },
        { t: "del", s: "#define M3_IN1_PIN      GPIO_PIN_8   // TIM1_CH1" },
        { t: "del", s: "#define M3_IN2_PIN      GPIO_PIN_9   // TIM1_CH2" },
        { t: "add", s: "#define M3_INHA_PIN     GPIO_PIN_8   // TIM1_CH1" },
        { t: "add", s: "#define M3_INLA_PIN     GPIO_PIN_9   // TIM1_CH1N" },
        { t: "add", s: "#define M3_DRV_CS_PIN   GPIO_PIN_4   // SPI1_NSS" },
        { t: "ctx", s: "" },
        { t: "add", s: "void m3_driver_init(void) {" },
        { t: "add", s: "    drv8316_write(DRV_CTRL_2, PWM_MODE_6X);" },
        { t: "add", s: "    drv8316_write(DRV_CSA_CTRL, CSA_GAIN_0V3);" },
        { t: "add", s: "}" },
        { t: "ctx", s: "void m3_set_duty(float duty) {" },
        { t: "del", s: "    tim1_write(M3_IN1_PIN, duty > 0 ? fabsf(duty) : 0);" },
        { t: "del", s: "    tim1_write(M3_IN2_PIN, duty < 0 ? fabsf(duty) : 0);" },
        { t: "add", s: "    tim1_complementary_write(M3_INHA_PIN, 0.5f + duty * 0.5f);" },
        { t: "ctx", s: "}" },
      ],
    },
    issue: { repo: "strider-fw", num: 142 },
  },
  {
    id: "a2", sev: "warning", state: "open", time: "1d ago", actor: "Priya Nair",
    fromD: "ee", toD: "sw",
    title: "3V3 rail change under-drives MPU9250 interrupt",
    summary: "U3's INT line moved from the 5 V rail to 3V3_A. Firmware still configures PC4 with a 5 V-era debounce threshold.",
    change: {
      title: "IMU interrupt rail rerouted",
      source: "KiCad · strider_main.sch · rev 40 → 41",
      commit: "“clean up 5 V usage on sensor block” — Priya N., 1d ago",
      before: [["INT rail", "5V0"], ["Logic high", "≥ 3.5 V"], ["Pull-up", "10 kΩ → 5V0"]],
      after: [["INT rail", "3V3_A"], ["Logic high", "≥ 2.3 V"], ["Pull-up", "10 kΩ → 3V3_A"]],
    },
    files: [
      {
        path: "firmware/src/imu_filter.c", range: "L 57",
        note: "EXTI threshold + schmitt config assumes 5 V swing",
        code: [
          "// PC4: IMU data-ready interrupt",
          "gpio_config(GPIOC, PIN_4, GPIO_IT_RISING, GPIO_SPEED_HIGH);",
          "#define IMU_INT_DEBOUNCE_US   40   // tuned for 5 V edge",
        ],
        hot: [2],
      },
    ],
    why: {
      guide: "The interrupt line now swings to 3.3 V instead of 5 V. The edge is slower into the same RC, and the 40 µs debounce window tuned for a 5 V edge can now swallow real data-ready pulses at 200 Hz. You'd see intermittent dropped IMU samples — the kind of bug that looks like sensor noise.",
      expert: "INT swing 5 V → 3.3 V, slower edge into same RC. 40 µs debounce can mask DRDY pulses at 200 Hz → intermittent sample drops.",
    },
    fix: {
      summary: "Reduce debounce to 12 µs and enable the input schmitt trigger on PC4.",
      file: "firmware/src/imu_filter.c",
      confidence: 0.81,
      diff: [
        { t: "ctx", s: "// PC4: IMU data-ready interrupt" },
        { t: "del", s: "#define IMU_INT_DEBOUNCE_US   40   // tuned for 5 V edge" },
        { t: "add", s: "#define IMU_INT_DEBOUNCE_US   12   // 3V3 edge, schmitt on" },
      ],
    },
    issue: { repo: "strider-fw", num: 143 },
  },
  {
    id: "a3", sev: "warning", state: "resolved", time: "3d ago", actor: "Jonas Weber",
    fromD: "me", toD: "sw", resolvedBy: "Marcus Hale",
    title: "Gearbox ratio change invalidates odometry constants",
    summary: "Knee gearbox changed 12:1 → 9:1 in CAD. Odometry and torque constants in gait_params.h were derived from the old ratio.",
    change: {
      title: "Knee gearbox redesigned",
      source: "Onshape · Strider / Legs · v18 → v19",
      commit: "“lighter knee stage, 9:1” — Jonas W., 3d ago",
      before: [["Ratio", "12:1"], ["Backlash", "0.6°"], ["Mass", "118 g"]],
      after: [["Ratio", "9:1"], ["Backlash", "0.4°"], ["Mass", "86 g"]],
    },
    files: [
      {
        path: "firmware/include/gait_params.h", range: "L 38–44",
        note: "KNEE_GEAR_RATIO and derived constants",
        code: [
          "#define KNEE_GEAR_RATIO   12.0f",
          "#define RAD_PER_TICK      (TWO_PI / (4096 * KNEE_GEAR_RATIO))",
        ],
        hot: [0],
      },
    ],
    why: {
      guide: "Joint angle is computed from encoder ticks through the gear ratio. With the ratio constant still at 12:1, every knee angle estimate is off by 33% — the gait planner thinks legs are somewhere they aren't.",
      expert: "KNEE_GEAR_RATIO stale (12 vs 9) → knee angle estimates off 33%, odometry drift.",
    },
    fix: {
      summary: "Update KNEE_GEAR_RATIO to 9.0 — derived constants recompute automatically.",
      file: "firmware/include/gait_params.h",
      confidence: 0.97,
      diff: [
        { t: "del", s: "#define KNEE_GEAR_RATIO   12.0f" },
        { t: "add", s: "#define KNEE_GEAR_RATIO   9.0f" },
      ],
    },
    issue: { repo: "strider-fw", num: 138 },
  },
];

/* ================= TELEMETRY ================= */
window.TELEM = {
  joints: [],
  system: [
    { id: "vbat", l: "VBAT", unit: "V", base: 22.4, amp: 0.15, period: 9 },
    { id: "itot", l: "I_total", unit: "A", base: 3.8, amp: 0.9, period: 3.2 },
    { id: "canl", l: "can0 load", unit: "%", base: 42, amp: 6, period: 5 },
    { id: "loop", l: "ctrl loop", unit: "Hz", base: 1000, amp: 2, period: 7 },
    { id: "pitch", l: "IMU pitch", unit: "°", base: 0.4, amp: 1.1, period: 2.4 },
    { id: "roll", l: "IMU roll", unit: "°", base: -0.2, amp: 0.8, period: 3.1 },
  ],
};
["FL", "FR", "RL", "RR"].forEach((leg, li) => {
  ["hip", "thigh", "knee"].forEach((j, ji) => {
    window.TELEM.joints.push({
      id: `${leg}_${j}`, leg, joint: j,
      l: `τ_${leg}_${j}`, unit: "N·m",
      base: [0.8, 2.2, 1.6][ji], amp: [0.3, 0.7, 0.5][ji],
      period: 1.9 + li * 0.13 + ji * 0.21, phase: li * 1.57 + ji * 0.6,
    });
  });
});

/* ================= TEAM + ACTIVITY ================= */
window.TEAM = [
  { name: "Maya Krishnan", you: true, role: "Firmware", d: "sw", last: "now", email: "maya@strider.dev" },
  { name: "Priya Nair", role: "Electrical", d: "ee", last: "12 min ago", email: "priya@strider.dev" },
  { name: "Jonas Weber", role: "Mechanical", d: "me", last: "1h ago", email: "jonas@strider.dev" },
  { name: "Marcus Hale", role: "Controls", d: "rt", last: "3h ago", email: "marcus@strider.dev" },
];
window.ACTIVITY = [
  { who: "Priya Nair", d: "ee", what: "swapped U4: DRV8833 → DRV8316C", where: "strider_main.sch · rev 42", time: "2h ago", affects: true, alert: "a1" },
  { who: "Marcus Hale", d: "rt", what: "tuned standing-gait stride to 2.1 Hz", where: "/gait_controller params", time: "5h ago" },
  { who: "Maya Krishnan", d: "sw", what: "merged PR #41 — CAN FD frame batching", where: "strider-fw", time: "6h ago", you: true },
  { who: "Priya Nair", d: "ee", what: "moved IMU INT to 3V3_A rail", where: "strider_main.sch · rev 41", time: "1d ago", affects: true, alert: "a2" },
  { who: "Jonas Weber", d: "me", what: "released Legs v19 — knee gearbox 9:1", where: "Onshape · Strider / Legs", time: "3d ago", affects: true, alert: "a3" },
  { who: "Marcus Hale", d: "sw", what: "updated KNEE_GEAR_RATIO to 9.0", where: "strider-fw · #138", time: "3d ago" },
  { who: "Jonas Weber", d: "me", what: "re-tensioned belt spec 30 N → 35 N", where: "Onshape · Strider / Legs", time: "4d ago" },
];

/* ================= INTEGRATIONS ================= */
window.INTEGRATIONS = [
  { id: "github", name: "GitHub", kind: "Code", mark: "GH", steps: ["Authorizing with GitHub…", "Cloning strider-fw, strider-tools…", "Indexing 214 files…"], result: "Connected — 2 repos, 214 files, 31k LOC indexed" },
  { id: "kicad", name: "KiCad", kind: "PCB / Schematic", mark: "Ki", steps: ["Watching project folder…", "Parsing strider_main.kicad_sch…", "Extracting netlist…"], result: "Connected — 47 components, 16 nets, 3 ICs" },
  { id: "onshape", name: "Onshape", kind: "Mechanical CAD", mark: "On", steps: ["Authorizing with Onshape…", "Loading Strider workspace…", "Reading 12 assemblies…"], result: "Connected — 12 assemblies, 84 parts, 6 mates" },
  { id: "ros", name: "ROS 2", kind: "Runtime", mark: "R2", steps: ["Discovering domain 42…", "Listening to /rosout…", "Mapping node graph…"], result: "Connected — 9 nodes, 23 topics live" },
];

/* ================= SOL SCRIPTS ================= */
window.SOL_SCRIPTS = {
  anomaly: {
    q: "τ_FL_knee is oscillating at ~4.2 Hz on the bench. What's going on?",
    likely: "FL knee torque ripple driven by a firmware ↔ gate-driver interface mismatch",
    root: "U4 was swapped to a DRV8316C (rev 42), but motor_driver.c still drives it with DRV8833-style sign-magnitude PWM. The driver intermittently re-latches its half-bridges, producing torque ripple locked to the 2.1 Hz stride — visible at the 2nd harmonic, 4.2 Hz.",
    evidence: [
      { d: "ee", l: "DRV8316C · U4", n: "changed 2h ago, rev 42" },
      { d: "sw", l: "motor_driver.c L84–112", n: "stale IN1/IN2 pin map" },
      { d: "rt", l: "τ3 ripple @ 4.2 Hz", n: "= 2 × stride freq (2.1 Hz)" },
      { d: "me", l: "knee gearbox 9:1", n: "ripple amplified at joint" },
    ],
    fixDesc: "Remap M3 to 6×-PWM and configure the DRV8316C control register — same fix as open alert #a1.",
    guide: "Here's the chain I followed. Your bench shows τ_FL_knee oscillating at 4.2 Hz — exactly twice the stride frequency Marcus set yesterday (2.1 Hz), which usually points at a per-revolution disturbance rather than a control instability. Tracing the FL knee through the graph: the joint is driven by U4, which Priya swapped to a DRV8316C two hours ago. The firmware still talks to it like the old DRV8833 — wrong PWM scheme entirely. The driver re-latches mid-stride, and the 9:1 gearbox turns that into visible torque ripple. The fix is the one attached to the open alert: remap the pins and configure the new driver over SPI.",
    expert: "4.2 Hz = 2× stride (2.1 Hz) → per-rev disturbance, not loop instability. FL knee ← U4, swapped 2h ago. FW still sign-magnitude (DRV8833 semantics) → DRV8316C re-latches mid-stride → ripple through 9:1 stage. Fix = alert a1 patch: 6×-PWM remap + SPI config.",
    followups: [
      {
        q: "Why exactly 4.2 Hz and not the stride frequency itself?",
        guide: "Each stride loads the knee twice — once at touchdown, once at push-off. A disturbance that fires on both load peaks shows up at twice the stride rate. That's why I treated 4.2 Hz as a signature of a load-synchronous fault rather than a tuning problem: a control-loop instability would drift with gain, not lock to a gait harmonic.",
        expert: "Knee loads 2×/stride (touchdown + push-off). Load-synchronous fault → 2nd harmonic. Lock to gait harmonic ⇒ not a gain/tuning issue.",
      },
      {
        q: "Could it be the belt tension Jonas changed last week?",
        guide: "I checked that. The belt change (30 → 35 N) was on the hip stage, not the knee — and it landed 4 days ago while the oscillation started within the last 2 hours, right after rev 42. Timing and topology both point at U4.",
        expert: "Belt change = hip stage, 4d ago. Oscillation onset <2h, post-rev-42. Topology + timing exclude it.",
      },
    ],
  },
  alertq: {
    q: "Explain the U4 alert to me.",
    likely: "Open critical alert a1 — PCB component swap with un-migrated firmware",
    root: "DRV8833 → DRV8316C changes the control interface (2-pin sign-magnitude → 6×-PWM + SPI) and the electrical ratings (1.5 A → 8 A). Three firmware locations encode the old part's assumptions.",
    evidence: [
      { d: "ee", l: "strider_main.sch rev 42", n: "U4 footprint + nets changed" },
      { d: "sw", l: "motor_driver.c, foc_loop.c, gait_params.h", n: "3 stale references" },
    ],
    fixDesc: "Apply the prepared patch to motor_driver.c, then raise I_PHASE_MAX and TAU_KNEE_MAX in a follow-up.",
    guide: "When Priya swapped U4, she changed two contracts at once: the control interface (the new chip wants 6×-PWM and SPI configuration, not two PWM pins) and the ratings (8 A headroom instead of 1.5 A). Firmware encodes the old contract in three places, which I've listed in the alert. If you flash and run as-is, the FL knee motor will either stall or draw shoot-through spikes. I'd apply the pin-map patch first — the rating constants are safe to raise afterwards.",
    expert: "U4 swap breaks 2 contracts: control IF (6×-PWM+SPI vs 2-pin) + ratings (8 A vs 1.5 A). 3 stale FW refs. Run as-is → stall or shoot-through on M3. Patch pin map first; raise limits after.",
    followups: [
      {
        q: "Is the FR knee affected too?",
        guide: "No — only U4 (the FL knee driver) was swapped in rev 42. The other three knee drivers are still DRV8833s, so their pin maps remain correct. Worth noting for consistency: mixed driver models means motor_driver.c now needs per-channel configuration.",
        expert: "No. Only U4 swapped; FR/RL/RR still DRV8833. Side effect: per-channel driver config now required.",
      },
    ],
  },
  hello: {
    q: "What can you help me with?",
    likely: null,
    guide: "I sit on top of your project's context model — the graph linking firmware, schematics, CAD, and live telemetry. Ask me why something broke, what a change affects, or what a signal means, and I'll answer with the cross-domain chain of evidence. I can also draft fixes and flash them to the bench. Try asking about the open U4 alert, or the τ_FL_knee oscillation if the bench is running.",
    expert: "I reason over the project graph (FW + EE + CAD + runtime). Ask: root-cause, change impact, signal meaning. I draft + flash fixes. Try: U4 alert, τ_FL_knee oscillation.",
    followups: [],
  },
};
