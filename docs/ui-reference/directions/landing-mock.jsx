// LandingMock — landing hero for one direction (1280×760)
function LandingMock({ t }) {
  const D = window.SOLUS_DOMAINS;
  const centered = t.variant === "meridian";
  const mono = (extra) => ({ fontFamily: t.fontMono, ...extra });

  const chainChips = [
    { l: "motor_driver.c", d: "sw" },
    { l: "M3_PWM", d: "ee" },
    { l: "DRV8316C · U4", d: "ee" },
    { l: "knee gearbox 9:1", d: "me" },
    { l: "τ3 torque", d: "rt" },
  ];

  const btnPrimary = {
    fontFamily: t.fontUI, fontSize: 14.5, fontWeight: 600,
    background: t.accent, color: t.accentInk, border: "none",
    borderRadius: t.variant === "meridian" ? 99 : t.radius, padding: "12px 22px",
  };
  const btnGhost = {
    ...btnPrimary, background: "transparent", color: t.text,
    border: `1px solid ${t.border}`, fontWeight: 500,
  };

  return (
    <div style={{
      width: "100%", height: "100%", background: t.bg, color: t.text,
      fontFamily: t.fontUI, position: "relative", overflow: "hidden",
      display: "flex", flexDirection: "column", boxSizing: "border-box",
    }}>
      {t.variant === "signal" && (
        <div style={{ ...mono({}), fontSize: 9.5, letterSpacing: "0.14em", color: t.muted, borderBottom: `1px solid ${t.border}`, padding: "7px 28px", display: "flex", justifyContent: "space-between" }}>
          <span>SOLUS // CROSS-DOMAIN INTEGRITY FOR ROBOTICS TEAMS</span>
          <span>EST. 2026 · v0.9</span>
        </div>
      )}
      {centered && (
        <div style={{ position: "absolute", top: "30%", left: "50%", transform: "translate(-50%,-50%)", width: 620, height: 620, borderRadius: "50%", background: `radial-gradient(circle, ${t.accent}1E 0%, transparent 62%)`, pointerEvents: "none" }}></div>
      )}

      {/* nav */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "20px 48px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ width: 18, height: 18, borderRadius: "50%", background: `radial-gradient(circle at 35% 32%, ${t.accent}, ${t.accent}33 70%)`, boxShadow: `0 0 14px ${t.accent}66` }}></div>
          <span style={{ fontWeight: 700, fontSize: 16, letterSpacing: t.variant === "signal" ? "0.12em" : "0.01em" }}>{t.variant === "signal" ? "SOLUS" : "Solus"}</span>
        </div>
        <div style={{ display: "flex", gap: 28, fontSize: 13.5, color: t.muted }}>
          <span>Product</span><span>Docs</span><span>Pricing</span>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <span style={{ fontSize: 13.5, color: t.muted }}>Sign in</span>
          <button style={{ ...btnPrimary, fontSize: 13, padding: "8px 16px" }}>Get started</button>
        </div>
      </div>

      {/* hero */}
      <div style={{
        flex: 1, display: "flex", flexDirection: "column",
        justifyContent: "center", padding: centered ? "0 160px" : "0 96px",
        alignItems: centered ? "center" : "flex-start",
        textAlign: centered ? "center" : "left", position: "relative",
      }}>
        <div style={mono({ fontSize: 11, letterSpacing: "0.16em", color: t.accent, marginBottom: 18 })}>
          CODE · PCB · CAD · HARDWARE — ONE GRAPH
        </div>
        <h1 style={{
          margin: 0, fontWeight: t.variant === "field" ? 700 : 600,
          fontSize: t.variant === "field" ? 72 : 64, lineHeight: 1.04,
          letterSpacing: "-0.025em", maxWidth: 880,
        }}>
          Your robot is one system.{" "}
          <span style={
            t.variant === "field"
              ? { boxShadow: `inset 0 -0.28em 0 ${t.accent}55` }
              : t.variant === "meridian"
              ? { background: `linear-gradient(90deg, ${t.text}, ${t.accent})`, WebkitBackgroundClip: "text", color: "transparent" }
              : { color: t.accent }
          }>Your tools aren't.</span>
        </h1>
        <p style={{ fontSize: 17, lineHeight: 1.6, color: t.muted, maxWidth: 560, marginTop: 22 }}>
          Solus connects firmware, schematics, CAD, and live telemetry into one
          context model — and catches the integration bugs that only exist
          between them, before they break the robot.
        </p>
        <div style={{ display: "flex", gap: 12, marginTop: 32 }}>
          <button style={btnPrimary}>Create account</button>
          <button style={btnGhost}>See it catch a bug →</button>
        </div>

        {/* cross-domain chain motif */}
        <div style={{
          display: "flex", alignItems: "center", gap: 0, marginTop: 64,
          ...(centered ? {} : {}),
        }}>
          {chainChips.map((c, i) => (
            <React.Fragment key={c.l}>
              {i > 0 && <div style={{ width: 36, height: 1, background: `linear-gradient(90deg, ${D[chainChips[i-1].d].color}66, ${D[c.d].color}66)` }}></div>}
              <span style={mono({
                fontSize: 11, color: t.text, background: t.surface,
                border: `1px solid ${D[c.d].color}55`, borderRadius: Math.min(t.radius, 8),
                padding: "6px 11px", display: "inline-flex", alignItems: "center", gap: 7, whiteSpace: "nowrap",
              })}>
                <span style={{ width: 6, height: 6, borderRadius: 99, background: D[c.d].color, display: "inline-block" }}></span>
                {c.l}
              </span>
            </React.Fragment>
          ))}
        </div>
        <div style={mono({ fontSize: 10.5, color: t.muted, marginTop: 14, letterSpacing: "0.06em" })}>
          one broken assumption, traced across four domains — in 90 ms
        </div>
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", padding: "18px 48px", borderTop: `1px solid ${t.border}`, ...mono({ fontSize: 10, color: t.muted, letterSpacing: "0.08em" }) }}>
        <span>WORKS WITH GITHUB · KICAD · ONSHAPE · ROS 2</span>
        <span>SOC 2 · SELF-HOST AVAILABLE</span>
      </div>
    </div>
  );
}
window.LandingMock = LandingMock;
