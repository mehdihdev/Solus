// GraphMock — Context Model screen for one direction (1440×900)
const GM_NODES = [
  { id: 1,  d: "sw", x: 115, y: 130, l: "leg_ik.c" },
  { id: 2,  d: "sw", x: 258, y: 105, l: "gait_params.h" },
  { id: 3,  d: "sw", x: 165, y: 205, l: "motor_driver.c", hot: true },
  { id: 4,  d: "sw", x: 268, y: 272, l: "can_bus.c" },
  { id: 5,  d: "sw", x: 168, y: 300, l: "TIM1_CH1 · STM32H7", hot: true },
  { id: 6,  d: "ee", x: 385, y: 448, l: "M3_PWM", hot: true },
  { id: 7,  d: "ee", x: 520, y: 505, l: "DRV8316C · U4", hot: true, sel: true },
  { id: 8,  d: "ee", x: 398, y: 592, l: "VBAT_12V" },
  { id: 9,  d: "ee", x: 532, y: 648, l: "INA226 · U7" },
  { id: 10, d: "ee", x: 645, y: 425, l: "MPU9250 · U3" },
  { id: 11, d: "ee", x: 652, y: 605, l: "TJA1051 · U9" },
  { id: 12, d: "me", x: 800, y: 122, l: "FL leg assembly" },
  { id: 13, d: "me", x: 808, y: 222, l: "knee gearbox 9:1", hot: true },
  { id: 14, d: "me", x: 945, y: 165, l: "belt drive 2:1" },
  { id: 15, d: "me", x: 952, y: 282, l: "chassis frame" },
  { id: 16, d: "rt", x: 798, y: 495, l: "/joint_states" },
  { id: 17, d: "rt", x: 928, y: 548, l: "τ3 torque", hot: true },
  { id: 18, d: "rt", x: 800, y: 628, l: "/imu/data" },
  { id: 19, d: "rt", x: 938, y: 682, l: "foot_contact[FL]" },
];
const GM_EDGES = [
  [1, 3], [2, 3], [4, 3], [3, 5, true], [5, 6, true], [6, 7, true],
  [7, 8], [8, 9], [9, 4], [10, 18], [7, 13, true], [13, 12], [12, 14],
  [12, 15], [13, 17, true], [16, 17], [12, 19], [4, 11], [16, 1],
];
const GM_HULLS = [
  { d: "sw", x: 38,  y: 58,  w: 312, h: 300 },
  { d: "ee", x: 308, y: 388, w: 412, h: 318 },
  { d: "me", x: 718, y: 60,  w: 316, h: 282 },
  { d: "rt", x: 716, y: 438, w: 318, h: 302 },
];

function GMNode({ n, t }) {
  const D = window.SOLUS_DOMAINS;
  const c = D[n.d].color;
  const w = n.l.length * 6.7 + 30;
  const r = Math.min(t.radius, 7);
  return (
    <g transform={`translate(${n.x - w / 2}, ${n.y - 13})`}>
      {n.sel && <rect x="-4" y="-4" width={w + 8} height="34" rx={r + 3} fill="none" stroke={t.accent} strokeWidth="1.5" opacity="0.9"></rect>}
      <rect width={w} height="26" rx={r} fill={t.surface2} stroke={n.hot ? `${c}AA` : `${c}50`} strokeWidth="1"></rect>
      <circle cx="14" cy="13" r="3.2" fill={c}></circle>
      <text x="24" y="17" fontFamily={t.fontMono} fontSize="10.5" fill={t.text}>{n.l}</text>
    </g>
  );
}

function GraphMock({ t }) {
  const D = window.SOLUS_DOMAINS;
  const byId = {};
  GM_NODES.forEach((n) => (byId[n.id] = n));
  const mono = (e) => ({ fontFamily: t.fontMono, ...e });
  const railIcon = (active, key, svg) => (
    <div key={key} style={{
      width: 36, height: 36, borderRadius: Math.min(t.radius, 8),
      display: "flex", alignItems: "center", justifyContent: "center",
      background: active ? `${t.accent}1A` : "transparent",
      color: active ? t.accent : t.muted,
    }}>{svg}</div>
  );
  const I = {
    graph: <svg width="17" height="17" viewBox="0 0 17 17"><circle cx="4" cy="4" r="2.4" fill="none" stroke="currentColor" strokeWidth="1.4"/><circle cx="13" cy="6" r="2.4" fill="none" stroke="currentColor" strokeWidth="1.4"/><circle cx="7" cy="13" r="2.4" fill="none" stroke="currentColor" strokeWidth="1.4"/><path d="M6 5l4.8.8M5.8 11.2L11.8 8" stroke="currentColor" strokeWidth="1.2"/></svg>,
    bench: <svg width="17" height="17" viewBox="0 0 17 17"><path d="M1 9h3l2-5 3 9 2-4h5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round"/></svg>,
    sol:   <svg width="17" height="17" viewBox="0 0 17 17"><circle cx="8.5" cy="8.5" r="4" fill="currentColor" opacity="0.85"/><circle cx="8.5" cy="8.5" r="7" fill="none" stroke="currentColor" strokeWidth="1" opacity="0.4"/></svg>,
    team:  <svg width="17" height="17" viewBox="0 0 17 17"><circle cx="6" cy="6" r="2.6" fill="none" stroke="currentColor" strokeWidth="1.4"/><circle cx="11.5" cy="7.5" r="2" fill="none" stroke="currentColor" strokeWidth="1.3"/><path d="M2 14c.5-2.5 2-3.8 4-3.8s3.5 1.3 4 3.8" fill="none" stroke="currentColor" strokeWidth="1.3"/></svg>,
    gear:  <svg width="17" height="17" viewBox="0 0 17 17"><circle cx="8.5" cy="8.5" r="2.5" fill="none" stroke="currentColor" strokeWidth="1.4"/><circle cx="8.5" cy="8.5" r="5.8" fill="none" stroke="currentColor" strokeWidth="1.4" strokeDasharray="2.8 2.4"/></svg>,
  };
  const chip = (k, on) => (
    <span key={k} style={mono({
      fontSize: 10, letterSpacing: "0.04em", padding: "5px 10px", borderRadius: 99,
      color: on ? D[k].color : t.muted, background: on ? `${D[k].color}14` : "transparent",
      border: `1px solid ${on ? D[k].color + "44" : t.border}`,
      display: "inline-flex", alignItems: "center", gap: 6,
    })}>
      <span style={{ width: 5, height: 5, borderRadius: 99, background: on ? D[k].color : t.muted, display: "inline-block" }}></span>
      {D[k].label}
    </span>
  );
  const conn = (d, label, sub) => (
    <div key={label} style={{ display: "flex", alignItems: "center", gap: 9, padding: "8px 0", borderBottom: `1px solid ${t.border}` }}>
      <span style={{ width: 6, height: 6, borderRadius: 99, background: D[d].color, flexShrink: 0 }}></span>
      <div style={{ minWidth: 0 }}>
        <div style={mono({ fontSize: 11, color: t.text, whiteSpace: "nowrap" })}>{label}</div>
        <div style={{ fontSize: 10, color: t.muted, fontFamily: t.fontUI }}>{sub}</div>
      </div>
    </div>
  );

  return (
    <div style={{ width: "100%", height: "100%", background: t.bg, color: t.text, fontFamily: t.fontUI, display: "flex", boxSizing: "border-box", overflow: "hidden" }}>
      {/* icon rail */}
      <div style={{ width: 56, borderRight: `1px solid ${t.border}`, display: "flex", flexDirection: "column", alignItems: "center", padding: "14px 0", gap: 8, flexShrink: 0 }}>
        <div style={{ width: 22, height: 22, borderRadius: "50%", background: `radial-gradient(circle at 35% 32%, ${t.accent}, ${t.accent}22 72%)`, boxShadow: `0 0 12px ${t.accent}55`, marginBottom: 14 }}></div>
        {railIcon(true, "g", I.graph)}
        {railIcon(false, "b", I.bench)}
        {railIcon(false, "s", I.sol)}
        {railIcon(false, "t", I.team)}
        <div style={{ flex: 1 }}></div>
        {railIcon(false, "se", I.gear)}
        <div style={{ width: 26, height: 26, borderRadius: 99, background: t.surface2, border: `1px solid ${t.border}`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 10, fontWeight: 600, color: t.muted }}>MK</div>
      </div>

      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        {/* top bar */}
        <div style={{ height: 48, borderBottom: `1px solid ${t.border}`, display: "flex", alignItems: "center", gap: 14, padding: "0 16px", flexShrink: 0 }}>
          <span style={{ fontSize: 13, fontWeight: 600 }}>strider-qd12</span>
          <span style={{ color: t.muted, fontSize: 12 }}>/</span>
          <span style={{ fontSize: 13, color: t.muted }}>Context Model</span>
          <div style={{ flex: 1, maxWidth: 340, marginLeft: 18, background: t.surface, border: `1px solid ${t.border}`, borderRadius: Math.min(t.radius, 8), padding: "6px 11px", display: "flex", justifyContent: "space-between" }}>
            <span style={{ fontSize: 12, color: t.muted }}>Search nodes, nets, files…</span>
            <span style={mono({ fontSize: 10, color: t.muted })}>⌘K</span>
          </div>
          <div style={{ flex: 1 }}></div>
          <div style={{ display: "flex", gap: 6 }}>{["sw", "ee", "me", "rt"].map((k) => chip(k, true))}</div>
          <div style={{ position: "relative", marginLeft: 6 }}>
            <svg width="17" height="17" viewBox="0 0 17 17"><path d="M8.5 2a4.2 4.2 0 014.2 4.2c0 3 .9 4.3 1.8 5H2.5c.9-.7 1.8-2 1.8-5A4.2 4.2 0 018.5 2zM7 13.5a1.6 1.6 0 003 0" fill="none" stroke={t.muted} strokeWidth="1.3" strokeLinejoin="round"/></svg>
            <span style={{ position: "absolute", top: -4, right: -6, minWidth: 14, height: 14, borderRadius: 99, background: t.accent, color: t.accentInk, fontSize: 9, fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center" }}>2</span>
          </div>
        </div>

        {/* graph canvas */}
        <div style={{ flex: 1, position: "relative", backgroundImage: `radial-gradient(${t.border} 1px, transparent 1px)`, backgroundSize: "26px 26px", minWidth: 0 }}>
          <svg width="100%" height="100%" viewBox="0 0 1064 804" preserveAspectRatio="xMidYMid meet" style={{ position: "absolute", inset: 0 }}>
            {GM_HULLS.map((h) => (
              <g key={h.d}>
                <rect x={h.x} y={h.y} width={h.w} height={h.h} rx="14" fill={D[h.d].color} opacity="0.045"></rect>
                <rect x={h.x} y={h.y} width={h.w} height={h.h} rx="14" fill="none" stroke={D[h.d].color} opacity="0.18" strokeDasharray="3 4"></rect>
                <text x={h.x + 14} y={h.y + 20} fontFamily={t.fontMono} fontSize="9.5" letterSpacing="2" fill={D[h.d].color} opacity="0.8">{D[h.d].label}</text>
              </g>
            ))}
            {GM_EDGES.map(([a, b, hot], i) => {
              const A = byId[a], B = byId[b];
              return hot ? (
                <line key={i} x1={A.x} y1={A.y} x2={B.x} y2={B.y} stroke={t.accent} strokeWidth="1.6" strokeDasharray="6 5" opacity="0.9" className="gm-flow"></line>
              ) : (
                <line key={i} x1={A.x} y1={A.y} x2={B.x} y2={B.y} stroke={t.text} strokeWidth="1" opacity="0.13"></line>
              );
            })}
            {GM_NODES.map((n) => <GMNode key={n.id} n={n} t={t} />)}
          </svg>

          {/* legend + zoom */}
          <div style={{ position: "absolute", left: 16, bottom: 14, display: "flex", flexDirection: "column", gap: 8 }}>
            <div style={{ display: "flex", gap: 2, background: t.surface, border: `1px solid ${t.border}`, borderRadius: Math.min(t.radius, 8), overflow: "hidden" }}>
              {["−", "100%", "+", "⛶"].map((z) => (
                <span key={z} style={mono({ fontSize: 11, color: t.muted, padding: "6px 10px", borderRight: z !== "⛶" ? `1px solid ${t.border}` : "none" })}>{z}</span>
              ))}
            </div>
          </div>
          <div style={{ position: "absolute", left: 16, top: 12 }}>
            <span style={mono({ fontSize: 10, color: t.muted, letterSpacing: "0.08em" })}>247 NODES · 31 CROSS-DOMAIN LINKS · SYNCED 2 MIN AGO</span>
          </div>

          {/* SOL orb */}
          <div style={{ position: "absolute", right: 18, bottom: 16, width: 46, height: 46, borderRadius: "50%", background: `radial-gradient(circle at 34% 30%, ${t.accent}EE, ${t.accent}33 60%, transparent 75%)`, boxShadow: `0 0 22px ${t.accent}77, inset 0 0 10px ${t.accent}55`, display: "flex", alignItems: "center", justifyContent: "center" }} className="gm-orb">
            <div style={{ width: 14, height: 14, borderRadius: "50%", background: t.accent, filter: "blur(2px)" }}></div>
          </div>
        </div>
      </div>

      {/* detail panel */}
      <div style={{ width: 318, borderLeft: `1px solid ${t.border}`, background: t.surface, padding: "18px 18px 14px", display: "flex", flexDirection: "column", boxSizing: "border-box", flexShrink: 0 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <div>
            <span style={mono({ fontSize: 9.5, letterSpacing: "0.1em", color: D.ee.color })}>● ELECTRICAL · IC</span>
            <div style={{ fontSize: 19, fontWeight: 650, marginTop: 6, letterSpacing: "-0.01em" }}>DRV8316C</div>
            <div style={{ fontSize: 12, color: t.muted, marginTop: 2 }}>U4 · 3-phase BLDC gate driver</div>
          </div>
          <span style={{ color: t.muted, fontSize: 14 }}>✕</span>
        </div>

        <div style={{ marginTop: 14, background: `${t.accent}10`, border: `1px solid ${t.accent}44`, borderRadius: Math.min(t.radius, 8), padding: "9px 11px", display: "flex", gap: 9, alignItems: "center" }}>
          <span style={{ width: 7, height: 7, borderRadius: 99, background: t.accent, boxShadow: `0 0 8px ${t.accent}`, flexShrink: 0 }}></span>
          <div>
            <div style={{ fontSize: 11.5, fontWeight: 600 }}>Changed 2h ago by Priya N.</div>
            <div style={{ fontSize: 10.5, color: t.muted }}>1 open alert — breaks pin map in firmware</div>
          </div>
        </div>

        <div style={{ marginTop: 16 }}>
          {[["Package", "QFN-32 (RSM)"], ["Rail", "VBAT_12V"], ["Peak current", "8 A"], ["Control mode", "6×-PWM"], ["Source", "kicad: strider_main.sch"]].map(([k, v]) => (
            <div key={k} style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", borderBottom: `1px solid ${t.border}` }}>
              <span style={{ fontSize: 11.5, color: t.muted }}>{k}</span>
              <span style={mono({ fontSize: 11, color: t.text })}>{v}</span>
            </div>
          ))}
        </div>

        <div style={mono({ fontSize: 9.5, letterSpacing: "0.1em", color: t.muted, marginTop: 18, marginBottom: 2 })}>CONNECTED ACROSS DOMAINS</div>
        {conn("sw", "motor_driver.c · TIM1_CH1", "drives PWM via this pin")}
        {conn("ee", "M3_PWM → AGND", "net · 18.7 kHz switching")}
        {conn("me", "FL knee actuator", "through 9:1 gearbox")}
        {conn("rt", "/joint_states · τ3", "live torque estimate")}

        <div style={{ flex: 1 }}></div>
        <div style={{ display: "flex", gap: 8 }}>
          <button style={{ flex: 1, fontFamily: t.fontUI, fontSize: 12.5, fontWeight: 500, background: "transparent", color: t.text, border: `1px solid ${t.border}`, borderRadius: t.radius, padding: "9px 0" }}>Open in KiCad</button>
          <button style={{ flex: 1, fontFamily: t.fontUI, fontSize: 12.5, fontWeight: 600, background: t.accent, color: t.accentInk, border: "none", borderRadius: t.radius, padding: "9px 0" }}>Ask SOL</button>
        </div>
      </div>
    </div>
  );
}
window.GraphMock = GraphMock;
