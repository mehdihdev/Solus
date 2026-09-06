// TokenCard — type + color + component tokens for one direction
function TokenCard({ t }) {
  const D = window.SOLUS_DOMAINS;
  const sw = (c) => ({
    width: 44, height: 44, borderRadius: Math.min(t.radius, 8),
    background: c, border: "1px solid rgba(255,255,255,0.08)",
  });
  const lbl = {
    fontFamily: t.fontMono, fontSize: 9, letterSpacing: "0.08em",
    color: t.muted, textTransform: "uppercase",
  };
  const row = { display: "flex", gap: 10, alignItems: "flex-end" };
  return (
    <div style={{
      width: "100%", height: "100%", background: t.bg, color: t.text,
      fontFamily: t.fontUI, padding: 28, boxSizing: "border-box",
      display: "flex", flexDirection: "column", gap: 22,
    }}>
      <div>
        <div style={{ ...lbl, color: t.accent }}>{t.name}</div>
        <div style={{ fontSize: 13, color: t.muted, marginTop: 8, lineHeight: 1.5 }}>{t.desc}</div>
      </div>

      <div style={{ borderTop: `1px solid ${t.border}`, paddingTop: 18 }}>
        <div style={lbl}>Type</div>
        <div style={{ fontSize: 44, fontWeight: 600, letterSpacing: "-0.02em", marginTop: 10, lineHeight: 1.05 }}>
          One robot,<br/>one graph.
        </div>
        <div style={{ fontSize: 14, color: t.muted, marginTop: 10, lineHeight: 1.55 }}>
          Body copy — {t.fontUI.split('"')[1]}. Calm, legible, information-dense without shouting.
        </div>
        <div style={{ fontFamily: t.fontMono, fontSize: 12, color: t.text, marginTop: 10, background: t.surface, border: `1px solid ${t.border}`, borderRadius: Math.min(t.radius, 6), padding: "8px 10px" }}>
          τ3 = 2.41 N·m &nbsp;·&nbsp; M3_PWM → DRV8316C (U4) &nbsp;·&nbsp; 18.7 kHz
        </div>
      </div>

      <div style={{ borderTop: `1px solid ${t.border}`, paddingTop: 18 }}>
        <div style={lbl}>Color</div>
        <div style={{ ...row, marginTop: 12 }}>
          <div><div style={sw(t.bg)}></div><div style={{ ...lbl, marginTop: 6 }}>bg</div></div>
          <div><div style={sw(t.surface)}></div><div style={{ ...lbl, marginTop: 6 }}>surface</div></div>
          <div><div style={sw(t.surface2)}></div><div style={{ ...lbl, marginTop: 6 }}>raised</div></div>
          <div><div style={sw(t.text)}></div><div style={{ ...lbl, marginTop: 6 }}>text</div></div>
          <div><div style={sw(t.accent)}></div><div style={{ ...lbl, marginTop: 6, color: t.accent }}>accent</div></div>
        </div>
        <div style={{ ...row, marginTop: 14 }}>
          {Object.keys(D).map((k) => (
            <div key={k}>
              <div style={{ ...sw(D[k].color), width: 34, height: 34 }}></div>
              <div style={{ ...lbl, marginTop: 6, fontSize: 8 }}>{D[k].label.slice(0, 4)}</div>
            </div>
          ))}
          <div style={{ ...lbl, paddingBottom: 12, marginLeft: 4 }}>domain colors<br/>(shared)</div>
        </div>
      </div>

      <div style={{ borderTop: `1px solid ${t.border}`, paddingTop: 18 }}>
        <div style={lbl}>Components</div>
        <div style={{ display: "flex", gap: 10, marginTop: 12, alignItems: "center" }}>
          <button style={{ fontFamily: t.fontUI, fontSize: 13, fontWeight: 600, background: t.accent, color: t.accentInk, border: "none", borderRadius: t.radius, padding: "9px 16px" }}>Ask SOL</button>
          <button style={{ fontFamily: t.fontUI, fontSize: 13, fontWeight: 500, background: "transparent", color: t.text, border: `1px solid ${t.border}`, borderRadius: t.radius, padding: "8px 16px" }}>Open in KiCad</button>
          <span style={{ fontFamily: t.fontMono, fontSize: 10, color: D.ee.color, border: `1px solid ${D.ee.color}44`, background: `${D.ee.color}14`, borderRadius: 99, padding: "4px 10px" }}>● ELECTRICAL</span>
        </div>
        <div style={{ marginTop: 12, background: t.surface, border: `1px solid ${t.border}`, borderRadius: Math.min(t.radius, 8), padding: "10px 12px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <div style={{ fontSize: 12.5, fontWeight: 600 }}>Pin map mismatch · motor_driver.c</div>
            <div style={{ fontSize: 11, color: t.muted, marginTop: 2 }}>U4 swap breaks 3 firmware files</div>
          </div>
          <div style={{ width: 8, height: 8, borderRadius: 99, background: t.accent, boxShadow: `0 0 10px ${t.accent}` }}></div>
        </div>
      </div>
    </div>
  );
}
window.TokenCard = TokenCard;
