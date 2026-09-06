// Solus v4 — SOL: chat tab (sol-reasoner-1, streaming), Guide/Build, floating Ctrl+Space panel w/ screen-grab, artifact filing
const { useState: useS5, useEffect: useES5, useRef: useRS5 } = React;

function Stream({ text, speed = 18 }) {
  const [n, setN] = useS5(0);
  useES5(() => { setN(0); const iv = setInterval(() => setN((k) => { if (k >= text.length) { clearInterval(iv); return k; } return k + 3; }), speed); return () => clearInterval(iv); }, [text]);
  return <span>{text.slice(0, n)}{n < text.length && <span style={{ display: "inline-block", width: 6, height: 12, background: "var(--acc)", marginLeft: 2, verticalAlign: "-2px", animation: "solThink 0.8s infinite" }}></span>}</span>;
}

function ArtifactCard({ a, onFile }) {
  return (
    <Card pad={0} style={{ borderColor: "color-mix(in srgb, var(--acc) 40%, var(--bd))" }}>
      <div style={{ display: "flex", gap: 10, alignItems: "center", padding: "10px 13px", borderBottom: "1px solid var(--bd)" }}>
        <span style={{ color: "var(--acc)" }}>{SI.file({ size: 14 })}</span>
        <div style={{ flex: 1 }}><div style={{ fontSize: 12.5, fontWeight: 600 }}>{a.title}</div><Mono size={8.5}>{a.kind}</Mono></div>
        {a.filed ? <Mono size={8.5} color="var(--ok)">✓ FILED → {SOLUS_SECTIONS.find((s) => s[0] === a.filed)[1].toUpperCase()}</Mono> : null}
      </div>
      <div style={{ padding: "10px 13px", fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--mut)", lineHeight: 1.6, whiteSpace: "pre-wrap" }}>{a.body}</div>
      {!a.filed && (
        <div style={{ padding: "9px 13px", borderTop: "1px solid var(--bd)" }}>
          <div style={{ fontSize: 12, marginBottom: 7 }}>File this to…?</div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>{SOLUS_SECTIONS.map(([k, l]) => <Btn key={k} kind={k === a.suggest ? "primary" : "ghost"} size="sm" onClick={() => onFile(k)}>{l}</Btn>)}<Btn kind="bare" size="sm" onClick={() => onFile(null)}>Don't file</Btn></div>
        </div>)}
    </Card>);
}

function SolThread({ d, msgs, busy, mode, approvals, onApprove, onReject, onFile, guideStep, setGuideStep, energy, compact }) {
  const ref = useRS5(null);
  useES5(() => { if (ref.current) ref.current.scrollTop = ref.current.scrollHeight; }, [msgs, busy]);
  return (
    <div ref={ref} style={{ flex: 1, overflowY: "auto", padding: compact ? "10px 10px 4px" : "14px 16px 6px", display: "flex", flexDirection: "column", gap: 12, minHeight: 0 }}>
      {msgs.length === 0 && !busy && <div style={{ textAlign: "center", padding: "34px 16px", color: "var(--mut)", fontSize: 12, lineHeight: 1.65 }}>{d.graphNodes.length ? (d.affinity === "sam" ? "Try “how do I add a ground pour?”" : d.affinity === "priya" ? "Try “why did the car cut power at turn 3?”" : d.affinity === "maya" ? "Try “diagnose run 41.”" : "Ask about anything in this project's graph.") : "This project is empty — I can only speak from what's here. Add something in Workspace first."}</div>}
      {msgs.map((m, i) => {
        if (m.role === "user") return <div key={i} style={{ alignSelf: "flex-end", maxWidth: "84%", background: "var(--sur2)", border: "1px solid var(--bd)", borderRadius: "10px 10px 2px 10px", padding: "8px 12px", fontSize: 12.5, lineHeight: 1.55 }}>{m.grab && <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--acc)", marginBottom: 4 }}>◈ screen: {m.grab}</div>}{m.text}</div>;
        if (m.type === "finding") return <FindingCard key={i} f={m.finding} mode={mode === "Build" ? "Auto" : "Guide"} fixStates={approvals} onFix={m.onFix} onGuideFix={m.onGuideFix} />;
        if (m.type === "approval") return <ApprovalCard key={i} spec={m.spec} state={approvals[m.spec.id] || "pending"} onApprove={() => onApprove(m.spec.id)} onReject={() => onReject(m.spec.id)} />;
        if (m.type === "guide") return <GuideSteps key={i} g={m.guide} activeStep={guideStep} setActiveStep={setGuideStep} onPoint={m.onPoint} onDo={m.onDo} />;
        if (m.type === "prov") return <div key={i} style={{ display: "flex", flexDirection: "column", gap: 8 }}><div style={{ fontSize: 12.5, lineHeight: 1.65 }}>{m.text}</div><ProvCard rows={m.rows} /></div>;
        if (m.type === "artifact") return <ArtifactCard key={i} a={m.artifact} onFile={(sec) => onFile(i, sec)} />;
        if (m.type === "status") return <div key={i} style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: m.err ? "var(--err)" : m.ok ? "var(--ok)" : "var(--mut)" }}>{m.ok ? "✓ " : m.err ? "✕ " : ""}{m.text}</div>;
        return <div key={i} style={{ fontSize: 12.5, lineHeight: 1.65 }}>{m.stream ? <Stream text={m.text} /> : m.text}</div>;
      })}
      {busy && <div style={{ display: "flex", gap: 9, alignItems: "center" }}><Orb2 size={18} energy={energy} state="thinking" /><span className="sol-think" style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--mut)" }}>sol-reasoner-1 · reading the graph…</span></div>}
    </div>);
}

function SolInput({ onSend, placeholder, mode }) {
  const [v, setV] = useS5("");
  const go = () => { if (v.trim()) { onSend(v.trim()); setV(""); } };
  return (
    <div style={{ padding: "9px 12px 11px", borderTop: "1px solid var(--bd)", flexShrink: 0 }}>
      <div style={{ display: "flex", gap: 7 }}>
        <input value={v} onChange={(e) => setV(e.target.value)} onKeyDown={(e) => e.key === "Enter" && go()} placeholder={placeholder || "Ask about a signal, a part, a run…"} style={{ flex: 1, background: "var(--bg)", color: "var(--tx)", border: "1px solid var(--bd)", borderRadius: 3, padding: "8px 11px", fontSize: 12.5, fontFamily: "var(--ui)", outline: "none" }} />
        <Btn kind="primary" size="sm" onClick={go}>Send</Btn>
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6 }}><Mono size={8}>SOL-REASONER-1 · ROUTING IS INVISIBLE</Mono><Mono size={8} color={mode === "Build" ? "var(--acc)" : "var(--mut)"}>{mode === "Build" ? "BUILD — DOES IT, WITH APPROVAL" : "GUIDE — POINTS AND EXPLAINS, NEVER EXECUTES"} · DOUBLE-TAP CTRL</Mono></div>
    </div>);
}

/* ---- the SOL tab: chats list + thread ---- */
function SolTab({ d, chats, cur, setCur, newChat, thread, mode, setMode, energy }) {
  return (
    <div style={{ flex: 1, display: "flex", minWidth: 0, minHeight: 0 }} data-screen-label="SOL">
      <div style={{ width: 230, borderRight: "1px solid var(--bd)", background: "var(--sur)", display: "flex", flexDirection: "column", flexShrink: 0 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "12px 12px 8px" }}><Mono size={9}>CHATS</Mono><Btn kind="bare" size="sm" onClick={newChat}>{SI.plus({ size: 12 })} New</Btn></div>
        <div style={{ flex: 1, overflowY: "auto", padding: "0 8px" }}>
          {chats.map((c) => <div key={c.id} onClick={() => setCur(c.id)} style={{ padding: "8px 9px", borderRadius: 4, cursor: "pointer", background: c.id === cur ? "var(--sur2)" : "transparent", marginBottom: 2 }}><div style={{ fontSize: 12, fontWeight: c.id === cur ? 600 : 400, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{c.title}</div><div style={{ fontSize: 10, color: "var(--mut)", marginTop: 2 }}>{c.msgs.length ? c.msgs.length + " messages" : "empty"} · {c.when}</div></div>)}
        </div>
        <div style={{ padding: 12, borderTop: "1px solid var(--bd)" }}>
          <div style={{ display: "flex", gap: 9, alignItems: "center" }}><Orb2 size={22} energy={energy} /><div><div style={{ fontSize: 11.5, fontWeight: 600 }}>SOL</div><Mono size={7.5}>SOL-REASONER-1</Mono></div></div>
          <div style={{ marginTop: 10 }}><Seg size="sm" options={["Guide", "Build"]} value={mode} onChange={setMode} /></div>
          <div style={{ fontSize: 10, color: "var(--mut)", marginTop: 6, lineHeight: 1.5 }}>{mode === "Guide" ? "Points at controls in your tools and explains. Never executes." : "Operates tools through their APIs. Destructive actions wait for your approval — same card for CAD, flash, motion."}</div>
        </div>
      </div>
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>{thread}</div>
    </div>);
}

/* ---- floating Ctrl+Space panel ---- */
function SolFloat({ open, at, onClose, thread, onSend, grab, onGrab, mode }) {
  const [pos, setPos] = useS5(at);
  const drag = useRS5(null);
  useES5(() => { if (open) setPos({ x: Math.min(at.x, window.innerWidth - 400), y: Math.min(at.y, window.innerHeight - 380) }); }, [open, at]);
  useES5(() => { const mv = (e) => { if (!drag.current) return; setPos({ x: drag.current.px + e.clientX - drag.current.x, y: drag.current.py + e.clientY - drag.current.y }); }; const up = () => (drag.current = null); window.addEventListener("pointermove", mv); window.addEventListener("pointerup", up); return () => { window.removeEventListener("pointermove", mv); window.removeEventListener("pointerup", up); }; }, []);
  if (!open) return null;
  return (
    <div style={{ position: "fixed", left: pos.x, top: pos.y, width: 390, height: 370, zIndex: 210, display: "flex", flexDirection: "column", background: "var(--sur)", border: "1px solid color-mix(in srgb, var(--acc) 40%, var(--bd))", borderRadius: 8, boxShadow: "0 26px 80px rgba(0,0,0,0.6)", overflow: "hidden" }}>
      <div onPointerDown={(e) => (drag.current = { x: e.clientX, y: e.clientY, px: pos.x, py: pos.y })} style={{ display: "flex", alignItems: "center", gap: 9, padding: "8px 11px", borderBottom: "1px solid var(--bd)", background: "var(--sur2)", cursor: "grab", userSelect: "none" }}>
        <Orb2 size={18} energy={70} />
        <span style={{ fontSize: 12, fontWeight: 700, letterSpacing: "0.04em" }}>SOL</span>
        <Mono size={7.5}>ANYWHERE · CTRL+SPACE</Mono>
        <div style={{ flex: 1 }}></div>
        <span onClick={onGrab} title="Screen-grab the active window for context" style={{ display: "inline-flex", gap: 5, alignItems: "center", cursor: "pointer", fontFamily: "var(--mono)", fontSize: 8.5, color: grab ? "var(--acc)" : "var(--mut)", border: `1px solid ${grab ? "color-mix(in srgb, var(--acc) 50%, transparent)" : "var(--bd)"}`, borderRadius: 99, padding: "3px 8px" }}>{SI.monitor({ size: 11 })} {grab ? "GRABBED: " + grab : "GRAB SCREEN"}</span>
        <span onClick={onClose} style={{ color: "var(--mut)", cursor: "pointer" }}>{SI.x({ size: 12 })}</span>
      </div>
      {grab && <div style={{ display: "flex", gap: 7, alignItems: "center", padding: "5px 11px", background: "color-mix(in srgb, var(--acc) 7%, transparent)", borderBottom: "1px solid color-mix(in srgb, var(--acc) 30%, transparent)", fontSize: 10.5 }}><span style={{ width: 7, height: 7, borderRadius: 99, background: "var(--acc)" }} className="gm-orb"></span>Context from screen: <b style={{ fontWeight: 600 }}>{grab}</b> — one capture, not recording.</div>}
      {thread}
      <SolInput onSend={onSend} placeholder={grab ? "Ask about what's on screen…" : "Ask SOL here…"} mode={mode} />
    </div>);
}

function ModeHud4({ show, mode }) {
  if (!show) return null;
  return (
    <div className="toast-in" style={{ position: "fixed", bottom: 26, left: "50%", transform: "translateX(-50%)", zIndex: 220, pointerEvents: "none" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 11, background: "color-mix(in srgb, var(--sur) 94%, transparent)", border: "1px solid color-mix(in srgb, var(--acc) 45%, var(--bd))", borderRadius: 99, padding: "8px 16px 8px 10px", boxShadow: "0 12px 40px rgba(0,0,0,0.5)" }}>
        <Orb2 size={22} energy={70} />
        <div><div style={{ fontSize: 12.5, fontWeight: 600 }}>{mode} mode</div><div style={{ fontSize: 10.5, color: "var(--mut)" }}>{mode === "Guide" ? "SOL points and explains — never executes" : "SOL does it — destructive steps wait for approval"}</div></div>
        <Mono size={8} style={{ border: "1px solid var(--bd)", borderRadius: 4, padding: "3px 7px", marginLeft: 4 }}>CTRL ×2</Mono>
      </div>
    </div>);
}
Object.assign(window, { SolThread, SolInput, SolTab, SolFloat, ModeHud4, ArtifactCard });
