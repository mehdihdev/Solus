// Solus — Team & activity (medium fidelity) + Settings (light fidelity)
const { useState: useStateT } = React;

function TeamScreen({ onOpenAlert, wsName = "strider-qd12" }) {
  const [inviteOpen, setInviteOpen] = useStateT(false);
  const [inviteEmail, setInviteEmail] = useStateT("");
  const [pending, setPending] = useStateT([]);
  const [sent, setSent] = useStateT(false);

  const sendInvite = () => {
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(inviteEmail)) return;
    setSent(true);
    setTimeout(() => {
      setPending((p) => [...p, inviteEmail]);
      setInviteOpen(false); setSent(false); setInviteEmail("");
    }, 1100);
  };

  return (
    <div style={{ flex: 1, overflowY: "auto", minWidth: 0 }}>
      <div style={{ maxWidth: 920, margin: "0 auto", padding: "22px 24px 48px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 22, fontWeight: 600, letterSpacing: "-0.015em" }}>Team</h1>
            <div style={{ fontSize: 12.5, color: "var(--mut)", marginTop: 4 }}>{wsName} · 4 members across 4 domains</div>
          </div>
          <Btn id="btn-invite" kind="primary" size="sm" onClick={() => setInviteOpen(true)}>{SI.plus({ size: 13 })} Invite teammate</Btn>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 380px", gap: 16, marginTop: 20, alignItems: "start" }}>
          {/* activity feed */}
          <Card pad={0}>
            <div style={{ padding: "13px 16px", borderBottom: "1px solid var(--bd)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <Mono size={9.5}>CROSS-DOMAIN ACTIVITY</Mono>
              <Mono size={9}>LAST 7 DAYS</Mono>
            </div>
            {ACTIVITY.map((a, i) => (
              <div key={i} onClick={a.alert ? () => onOpenAlert(a.alert) : undefined}
                style={{ display: "flex", gap: 12, padding: "12px 16px", borderBottom: "1px solid var(--bd)", cursor: a.alert ? "pointer" : "default", background: a.affects ? "color-mix(in srgb, var(--warn) 4%, transparent)" : "transparent" }}>
                <Avatar name={a.who} size={26} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12.5, lineHeight: 1.5 }}>
                    <strong style={{ fontWeight: 600 }}>{a.who.split(" ")[0]}</strong> {a.what}
                  </div>
                  <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 4 }}>
                    <span style={{ width: 5, height: 5, borderRadius: 99, background: dcol(a.d) }}></span>
                    <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--mut)" }}>{a.where}</span>
                    <span style={{ fontSize: 10, color: "var(--mut)" }}>· {a.time}</span>
                    {a.affects && (
                      <span style={{ fontFamily: "var(--mono)", fontSize: 8.5, letterSpacing: "0.08em", color: "var(--warn)", border: "1px solid color-mix(in srgb, var(--warn) 40%, transparent)", borderRadius: 99, padding: "2px 7px" }}>AFFECTS YOUR CODE</span>
                    )}
                    {a.you && <Mono size={8.5} color="var(--mut)">YOU</Mono>}
                  </div>
                </div>
                {a.alert && <span style={{ color: "var(--mut)", alignSelf: "center" }}>{SI.arrowR({ size: 12 })}</span>}
              </div>
            ))}
          </Card>

          {/* members */}
          <Card pad={0}>
            <div style={{ padding: "13px 16px", borderBottom: "1px solid var(--bd)" }}><Mono size={9.5}>MEMBERS</Mono></div>
            {TEAM.map((m) => (
              <div key={m.name} style={{ display: "flex", gap: 11, alignItems: "center", padding: "11px 16px", borderBottom: "1px solid var(--bd)" }}>
                <Avatar name={m.name} size={28} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12.5, fontWeight: 600 }}>{m.name} {m.you && <span style={{ fontWeight: 400, color: "var(--mut)", fontSize: 11 }}>(you)</span>}</div>
                  <div style={{ fontSize: 10.5, color: "var(--mut)" }}>{m.email}</div>
                </div>
                <div style={{ textAlign: "right" }}>
                  <Mono size={8.5} color={dcol(m.d)}>● {m.role.toUpperCase()}</Mono>
                  <div style={{ fontSize: 10, color: "var(--mut)", marginTop: 3 }}>{m.last}</div>
                </div>
              </div>
            ))}
            {pending.map((e) => (
              <div key={e} style={{ display: "flex", gap: 11, alignItems: "center", padding: "11px 16px", borderBottom: "1px solid var(--bd)", opacity: 0.7 }}>
                <span style={{ width: 28, height: 28, borderRadius: 99, border: "1px dashed var(--bd)", display: "inline-flex", alignItems: "center", justifyContent: "center", color: "var(--mut)" }}>{SI.team({ size: 13 })}</span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 12.5 }}>{e}</div>
                  <Mono size={8.5} color="var(--warn)">INVITE PENDING</Mono>
                </div>
              </div>
            ))}
            <div style={{ padding: "12px 16px", fontSize: 11, color: "var(--mut)", lineHeight: 1.55 }}>
              Teammates get notified when their changes affect each other's domains — like the U4 swap above.
            </div>
          </Card>
        </div>
      </div>

      {/* invite modal */}
      {inviteOpen && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.55)", zIndex: 70, display: "flex", alignItems: "center", justifyContent: "center" }} onClick={() => setInviteOpen(false)}>
          <div onClick={(e) => e.stopPropagation()}>
            <Card pad={24} style={{ width: 380, boxShadow: "0 18px 60px rgba(0,0,0,0.5)" }}>
              <div style={{ fontSize: 16, fontWeight: 600 }}>Invite a teammate</div>
              <div style={{ fontSize: 12, color: "var(--mut)", marginTop: 4, lineHeight: 1.5 }}>They'll join strider-qd12 with access to all four domains.</div>
              <input value={inviteEmail} onChange={(e) => setInviteEmail(e.target.value)} placeholder="teammate@team.dev" autoFocus
                onKeyDown={(e) => e.key === "Enter" && sendInvite()}
                style={{ width: "100%", boxSizing: "border-box", marginTop: 16, background: "var(--bg)", color: "var(--tx)", border: "1px solid var(--bd)", borderRadius: 3, padding: "10px 12px", fontSize: 13, fontFamily: "var(--ui)", outline: "none" }} />
              <div style={{ display: "flex", gap: 8, marginTop: 16, justifyContent: "flex-end" }}>
                <Btn kind="ghost" size="sm" onClick={() => setInviteOpen(false)}>Cancel</Btn>
                <Btn kind="primary" size="sm" onClick={sendInvite}>{sent ? <><Spinner size={11} color="var(--acc-ink)" /> Sending…</> : "Send invite"}</Btn>
              </div>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}

/* ================= SETTINGS ================= */
function SettingsScreen({ tw, setTweak, connected }) {
  const usageUsed = 1840, usageTotal = 5000;
  const usageRows = [["Cross-domain checks", 940], ["SOL conversations", 612], ["Bench anomaly watch", 288]];
  const Section = ({ title, sub, children }) => (
    <Card pad={20} style={{ marginBottom: 14 }}>
      <div style={{ fontSize: 14, fontWeight: 600 }}>{title}</div>
      {sub && <div style={{ fontSize: 11.5, color: "var(--mut)", marginTop: 3, lineHeight: 1.5 }}>{sub}</div>}
      <div style={{ marginTop: 14 }}>{children}</div>
    </Card>
  );
  const Row = ({ label, children }) => (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 16, padding: "9px 0", borderBottom: "1px solid var(--bd)" }}>
      <span style={{ fontSize: 12.5 }}>{label}</span>
      <div>{children}</div>
    </div>
  );
  return (
    <div style={{ flex: 1, overflowY: "auto", minWidth: 0 }}>
      <div style={{ maxWidth: 680, margin: "0 auto", padding: "22px 24px 48px" }}>
        <h1 style={{ margin: "0 0 18px", fontSize: 22, fontWeight: 600, letterSpacing: "-0.015em" }}>Settings</h1>

        <Section title="Profile">
          <div style={{ display: "flex", gap: 14, alignItems: "center" }}>
            <Avatar name="Maya Krishnan" size={42} />
            <div>
              <div style={{ fontSize: 13.5, fontWeight: 600 }}>Maya Krishnan</div>
              <div style={{ fontSize: 11.5, color: "var(--mut)" }}>maya@strider.dev · Firmware · workspace owner</div>
            </div>
          </div>
        </Section>

        <Section title="SOL" sub="How the agent talks to you, and where the orb lives.">
          <Row label="Answer mode">
            <Seg size="sm" options={["Guide", "Expert"]} value={tw.solMode} onChange={(v) => setTweak("solMode", v)} />
          </Row>
          <Row label="Orb behavior">
            <Seg size="sm" options={["corner", "follow"]} value={tw.orbMode} onChange={(v) => setTweak("orbMode", v)} />
          </Row>
          <Row label="Orb energy">
            <input type="range" min="10" max="100" value={tw.orbEnergy} onChange={(e) => setTweak("orbEnergy", +e.target.value)} style={{ accentColor: "var(--acc)", width: 140 }} />
          </Row>
        </Section>

        <Section title="Usage" sub="SOL meters AI reasoning by credit. Resets on the 1st.">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
            <span style={{ fontFamily: "var(--mono)", fontSize: 18 }}>{usageUsed.toLocaleString()}<span style={{ fontSize: 11, color: "var(--mut)" }}> / {usageTotal.toLocaleString()} credits</span></span>
            <Mono size={9.5}>TEAM PLAN</Mono>
          </div>
          <div style={{ height: 6, background: "var(--bg)", border: "1px solid var(--bd)", borderRadius: 99, marginTop: 10, overflow: "hidden" }}>
            <div style={{ width: (usageUsed / usageTotal) * 100 + "%", height: "100%", background: "var(--acc)" }}></div>
          </div>
          <div style={{ marginTop: 12 }}>
            {usageRows.map(([k, v]) => <KV key={k} k={k} v={v.toLocaleString() + " cr"} />)}
          </div>
        </Section>

        <Section title="Appearance" sub="Theme presets include editor schemes — set Solus to match your IDE.">
          <Row label="Theme">
            <select value={tw.theme} onChange={(e) => setTweak("theme", e.target.value)}
              style={{ background: "var(--bg)", color: "var(--tx)", border: "1px solid var(--bd)", borderRadius: 3, padding: "6px 10px", fontSize: 12, fontFamily: "var(--ui)", outline: "none" }}>
              {Object.keys(SolusThemes).map((k) => <option key={k} value={k}>{SolusThemes[k].name}</option>)}
            </select>
          </Row>
          <Row label="Accent">
            <div style={{ display: "flex", gap: 8 }}>
              {Object.keys(SolusAccents).map((k) => (
                <span key={k} onClick={() => setTweak("accent", k)} style={{ width: 22, height: 22, borderRadius: 99, background: SolusAccents[k].c, cursor: "pointer", border: tw.accent === k ? "2px solid var(--tx)" : "2px solid transparent", boxSizing: "border-box" }}></span>
              ))}
            </div>
          </Row>
          <Row label="Density">
            <Seg size="sm" options={["compact", "regular"]} value={tw.density} onChange={(v) => setTweak("density", v)} />
          </Row>
        </Section>

        <Section title="Integrations">
          {INTEGRATIONS.map((i) => (
            <Row key={i.id} label={<span style={{ display: "inline-flex", gap: 10, alignItems: "center" }}><span style={{ fontFamily: "var(--mono)", fontSize: 10.5, width: 26, height: 26, borderRadius: 3, background: "var(--sur2)", border: "1px solid var(--bd)", display: "inline-flex", alignItems: "center", justifyContent: "center" }}>{i.mark}</span>{i.name}</span>}>
              {connected.includes(i.id)
                ? <Mono size={9} color="var(--ok)">● CONNECTED</Mono>
                : <Mono size={9} color="var(--mut)">○ NOT CONNECTED</Mono>}
            </Row>
          ))}
        </Section>

        <Section title="Workspace">
          <Row label="Name"><span style={{ fontFamily: "var(--mono)", fontSize: 12 }}>strider-qd12</span></Row>
          <Row label="Danger zone"><Btn kind="danger" size="sm">Delete workspace</Btn></Row>
        </Section>
      </div>
    </div>
  );
}

Object.assign(window, { TeamScreen });
