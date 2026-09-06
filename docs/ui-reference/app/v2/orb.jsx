// Solus v2 — SOL orb: cursor companion with settle, semicircle tabs, draggable chat window, at-cursor ask
const { useState: useStateO2, useEffect: useEffectO2, useRef: useRefO2 } = React;

/* ---------- orb visual ---------- */
function Orb2({ size = 44, energy = 60, state = "idle", style }) {
  const e = Math.max(10, Math.min(100, energy)) / 100;
  const dur = (3.4 - 2 * e) * (state === "thinking" ? 0.4 : 1);
  return (
    <div style={{ width: size, height: size, position: "relative", flexShrink: 0, ...style }}>
      <div className="orb-halo" style={{ position: "absolute", inset: -size * 0.2, borderRadius: "50%", background: "radial-gradient(circle, color-mix(in srgb, var(--acc) 24%, transparent) 0%, transparent 65%)", animationDuration: dur * 2 + "s" }}></div>
      <div style={{ position: "absolute", inset: 0, borderRadius: "50%", background: "radial-gradient(circle at 36% 32%, color-mix(in srgb, var(--acc) 90%, white), color-mix(in srgb, var(--acc) 45%, transparent) 55%, transparent 74%)", boxShadow: `0 0 ${10 + 22 * e}px color-mix(in srgb, var(--acc) 55%, transparent), inset 0 0 ${size * 0.16}px color-mix(in srgb, var(--acc) 50%, transparent)` }}></div>
      <div className="orb-blob1" style={{ position: "absolute", inset: size * 0.14, borderRadius: "50%", background: "radial-gradient(circle at 62% 60%, color-mix(in srgb, var(--acc) 72%, white) 0%, transparent 55%)", animationDuration: dur + "s", mixBlendMode: "screen" }}></div>
      <div className="orb-core" style={{ position: "absolute", inset: size * 0.34, borderRadius: "50%", background: "color-mix(in srgb, var(--acc) 92%, white)", filter: `blur(${size * 0.06}px)`, opacity: 0.9, animationDuration: dur * 1.4 + "s" }}></div>
    </div>
  );
}

/* ---------- companion: follow + settle + expand tabs ---------- */
function SolCompanion2({ form = "orb", energy, parked, dismissed, mode, onMode, onChat, thinking }) {
  const wrapRef = useRefO2(null);
  const pos = useRefO2({ x: -999, y: -999 });
  const tgt = useRefO2({ x: -999, y: -999 });
  const lastMove = useRefO2(0);
  const [expanded, setExpanded] = useStateO2(false);
  const [settled, setSettled] = useStateO2(false);
  const expandedRef = useRefO2(false);
  expandedRef.current = expanded;

  const OFF = { x: 30, y: 26 }; // offset from cursor — never under the click target

  useEffectO2(() => {
    if (parked || dismissed) return;
    const paint = () => {
      const p = pos.current;
      if (wrapRef.current) wrapRef.current.style.transform = `translate(${p.x}px, ${p.y}px)`;
    };
    const mm = (ev) => {
      if (expandedRef.current) return; // frozen while tabs open
      lastMove.current = Date.now();
      const edgeX = ev.clientX > window.innerWidth - 150 ? -OFF.x - 44 : OFF.x;
      const edgeY = ev.clientY > window.innerHeight - 150 ? -OFF.y - 44 : OFF.y;
      tgt.current = { x: ev.clientX + edgeX, y: ev.clientY + edgeY };
      if (pos.current.x < -900) pos.current = { ...tgt.current };
      const p = pos.current, t = tgt.current;
      p.x += (t.x - p.x) * 0.3; p.y += (t.y - p.y) * 0.3;
      paint();
    };
    const iv = setInterval(() => {
      const idle = Date.now() - lastMove.current > 550;
      setSettled(idle && !expandedRef.current);
      const p = pos.current, t = tgt.current;
      if (t.x > -900 && (Math.abs(t.x - p.x) > 0.5 || Math.abs(t.y - p.y) > 0.5)) {
        p.x += (t.x - p.x) * 0.25; p.y += (t.y - p.y) * 0.25; paint();
      }
    }, 60);
    window.addEventListener("mousemove", mm);
    return () => { clearInterval(iv); window.removeEventListener("mousemove", mm); };
  }, [parked, dismissed]);

  useEffectO2(() => {
    if (!expanded) return;
    const away = (e) => { if (wrapRef.current && !wrapRef.current.contains(e.target)) setExpanded(false); };
    const esc = (e) => e.key === "Escape" && setExpanded(false);
    window.addEventListener("mousedown", away);
    window.addEventListener("keydown", esc);
    return () => { window.removeEventListener("mousedown", away); window.removeEventListener("keydown", esc); };
  }, [expanded]);

  if (dismissed) return null;
  const Visual = form === "hammer" ? SolHammer : Orb2;
  const vsize = form === "hammer" ? 52 : 44;

  const tabs = expanded && (
    <>
      <div className="sol-tab sol-tab-l" onClick={(e) => { e.stopPropagation(); onMode(mode === "Guide" ? "Auto" : "Guide"); }}
        title="Toggle Guide / Auto">
        <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.04em" }}>{mode.toUpperCase()}</span>
        <span style={{ fontSize: 8.5, color: "var(--mut)" }}>{mode === "Guide" ? "teaches" : "does, with approval"}</span>
      </div>
      <div className="sol-tab sol-tab-r" onClick={(e) => { e.stopPropagation(); setExpanded(false); onChat(); }} title="Open chat">
        <span style={{ display: "inline-flex", color: "var(--acc)" }}>{SI.sol({ size: 15 })}</span>
        <span style={{ fontSize: 8.5, color: "var(--mut)" }}>chat</span>
      </div>
    </>
  );

  if (parked) {
    return (
      <div ref={wrapRef} style={{ position: "fixed", right: 20, bottom: 20, zIndex: 200 }}>
        <div style={{ position: "relative" }}>
          {tabs}
          <div className="hmr-bob" style={{ cursor: "pointer" }} onClick={() => setExpanded(!expanded)} title="SOL">
            <Visual size={vsize} energy={energy} state={thinking ? "thinking" : "idle"} />
          </div>
        </div>
      </div>
    );
  }
  return (
    <div ref={wrapRef} style={{ position: "fixed", left: 0, top: 0, zIndex: 200, transform: "translate(-999px,-999px)", willChange: "transform" }}>
      <div style={{ position: "relative" }}>
        {tabs}
        <div onClick={() => setExpanded(!expanded)} style={{ cursor: "pointer", transition: "transform 0.4s, opacity 0.4s", transform: settled && !expanded ? "scale(0.78)" : "scale(1)", opacity: settled && !expanded ? 0.72 : 1 }} title="SOL — click to expand">
          <Visual size={vsize} energy={energy} state={thinking ? "thinking" : "idle"} />
        </div>
      </div>
    </div>
  );
}

/* ---------- finding card (cross-domain explanation) ---------- */
function FindingCard({ f, mode, onFix, onGuideFix, fixStates, compact, onOpen }) {
  return (
    <Card pad={0} style={{ borderColor: f.sev === "critical" ? "color-mix(in srgb, var(--err) 45%, var(--bd))" : "color-mix(in srgb, var(--warn) 45%, var(--bd))" }}>
      <div style={{ padding: "11px 14px", borderBottom: "1px solid var(--bd)", display: "flex", gap: 9, alignItems: "center" }}>
        <span style={{ color: f.sev === "critical" ? "var(--err)" : "var(--warn)" }} className="gm-orb">{SI.warn({ size: 14 })}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 12.5, fontWeight: 600, lineHeight: 1.4 }}>{f.title}</div>
          <Mono size={8.5} style={{ marginTop: 2 }}>{f.when}</Mono>
        </div>
        {compact && <Btn kind="primary" size="sm" onClick={onOpen}>Explain</Btn>}
      </div>
      {!compact && (
        <div style={{ padding: "12px 14px" }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
            {f.chain.map((c, i) => (
              <div key={i} style={{ display: "flex", gap: 10 }}>
                <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
                  <span style={{ width: 7, height: 7, borderRadius: 99, background: dcol(c.d), marginTop: 5, flexShrink: 0 }}></span>
                  {i < f.chain.length - 1 && <span style={{ width: 1, flex: 1, background: "var(--bd)", minHeight: 14 }}></span>}
                </div>
                <div style={{ paddingBottom: i < f.chain.length - 1 ? 9 : 0, minWidth: 0 }}>
                  <span style={{ fontFamily: "var(--mono)", fontSize: 11.5, color: "var(--tx)" }}>{c.l}</span>
                  <div style={{ fontSize: 11, color: "var(--mut)", lineHeight: 1.5 }}>{c.n}</div>
                </div>
              </div>
            ))}
          </div>
          <div style={{ borderTop: "1px solid var(--bd)", marginTop: 12, paddingTop: 11, display: "flex", flexDirection: "column", gap: 8 }}>
            {[["What happened", f.what], ["Why it matters", f.why], ["What to do", f.next]].map(([k, v]) => (
              <div key={k}><Mono size={8.5} color="var(--acc)">{k.toUpperCase()}</Mono><div style={{ fontSize: 12, lineHeight: 1.6, marginTop: 3 }}>{v}</div></div>
            ))}
          </div>
          {f.fixes && f.fixes.length > 0 && (
            <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
              {f.fixes.map((id) => {
                const st = fixStates && fixStates[id];
                return st === "approved"
                  ? <span key={id} style={{ display: "inline-flex", gap: 6, alignItems: "center", fontSize: 11.5, color: "var(--ok)" }}>{SI.check({ size: 12 })} applied</span>
                  : <Btn key={id} kind={mode === "Auto" ? "primary" : "ghost"} size="sm" onClick={() => (mode === "Auto" ? onFix(id) : onGuideFix(id))}>
                      {mode === "Auto" ? "Queue fix for approval" : "Show me how"}
                    </Btn>;
              })}
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

/* ---------- guide steps card ---------- */
function GuideSteps({ g, onPoint, onDo, activeStep, setActiveStep }) {
  return (
    <Card pad={0}>
      <div style={{ padding: "11px 14px", borderBottom: "1px solid var(--bd)", display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <div>
          <div style={{ fontSize: 12.5, fontWeight: 600 }}>{g.task}</div>
          <Mono size={8.5} style={{ marginTop: 2 }}>{g.tool}</Mono>
        </div>
        <Mono size={8.5} color="var(--acc)">STEP {Math.min(activeStep + 1, g.steps.length)} / {g.steps.length}</Mono>
      </div>
      <div style={{ padding: "8px 14px 12px" }}>
        {g.steps.map((s, i) => {
          const cur = i === activeStep, done = i < activeStep;
          return (
            <div key={i} onClick={() => setActiveStep(i)} style={{ display: "flex", gap: 10, padding: "8px 0", borderBottom: i < g.steps.length - 1 ? "1px solid var(--bd)" : "none", opacity: done ? 0.5 : 1, cursor: "pointer", background: cur ? "color-mix(in srgb, var(--acc) 4%, transparent)" : "transparent", margin: cur ? "0 -14px" : 0, paddingLeft: cur ? 14 : 0, paddingRight: cur ? 14 : 0, borderLeft: cur ? "2px solid var(--acc)" : "2px solid transparent" }}>
              <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: done ? "var(--ok)" : cur ? "var(--acc)" : "var(--mut)", width: 16, flexShrink: 0, marginTop: 2 }}>{done ? "✓" : i + 1}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 12, lineHeight: 1.5 }}>{s.t}</div>
                {s.gap
                  ? <div style={{ marginTop: 5, fontSize: 11, lineHeight: 1.55, color: "var(--warn)", background: "color-mix(in srgb, var(--warn) 7%, transparent)", border: "1px solid color-mix(in srgb, var(--warn) 30%, transparent)", borderRadius: 3, padding: "7px 9px" }}>
                      <Mono size={8} color="var(--warn)">HONEST GAP · NOT SURE</Mono>
                      <div style={{ marginTop: 3, color: "var(--tx)" }}>{s.gap}</div>
                    </div>
                  : <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 3 }}>
                      <span style={{ fontFamily: "var(--mono)", fontSize: 9, color: s.conf >= 0.9 ? "var(--ok)" : "var(--warn)" }}>{Math.round(s.conf * 100)}% sure</span>
                      {s.note && <span style={{ fontSize: 10, color: "var(--mut)" }}>· {s.note}</span>}
                    </div>}
                {cur && !s.gap && (
                  <div style={{ display: "flex", gap: 6, marginTop: 7 }}>
                    <Btn kind="ghost" size="sm" onClick={(e) => { e.stopPropagation(); onPoint(i); }}>Point at it</Btn>
                    <Btn kind="soft" size="sm" onClick={(e) => { e.stopPropagation(); onDo(i); }}>Do it for me</Btn>
                    <Btn kind="bare" size="sm" onClick={(e) => { e.stopPropagation(); setActiveStep(i + 1); }}>Done, next</Btn>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

/* ---------- provenance card ---------- */
function ProvCard({ rows }) {
  return (
    <Card pad={0}>
      <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--bd)" }}><Mono size={9}>PROVENANCE · FROM PDM + GIT + TEAM DRIVE</Mono></div>
      <div style={{ padding: "4px 14px 8px" }}>
        {rows.map(([k, v]) => (
          <div key={k} style={{ display: "flex", gap: 12, padding: "7px 0", borderBottom: "1px solid var(--bd)" }}>
            <span style={{ fontSize: 11.5, color: "var(--mut)", width: 96, flexShrink: 0 }}>{k}</span>
            <span style={{ fontSize: 12, lineHeight: 1.5 }}>{v}</span>
          </div>
        ))}
      </div>
    </Card>
  );
}

/* ---------- chat window: draggable, resizable, remembered ---------- */
const CHAT_GEOM_KEY = "solus_v2_chat_geom";
function ChatWindow({ world, open, onClose, msgs, busy, mode, onMode, onSend, approvals, onApprove, onReject, guideState, energy, form }) {
  const [geom, setGeom] = useStateO2(() => {
    try { const g = JSON.parse(localStorage.getItem(CHAT_GEOM_KEY)); if (g && g.w) return g; } catch (e) {}
    return { x: Math.max(12, window.innerWidth - 430), y: 92, w: 400, h: 500 };
  });
  const [input, setInput] = useStateO2("");
  const drag = useRefO2(null);
  const bodyRef = useRefO2(null);

  useEffectO2(() => { localStorage.setItem(CHAT_GEOM_KEY, JSON.stringify(geom)); }, [geom]);
  useEffectO2(() => { if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight; }, [msgs, busy, open]);

  useEffectO2(() => {
    const mv = (e) => {
      const d = drag.current; if (!d) return;
      if (d.kind === "move") setGeom((g) => ({ ...g, x: Math.min(Math.max(0, d.gx + e.clientX - d.x), window.innerWidth - 120), y: Math.min(Math.max(40, d.gy + e.clientY - d.y), window.innerHeight - 60) }));
      else setGeom((g) => ({ ...g, w: Math.max(320, d.gw + e.clientX - d.x), h: Math.max(300, d.gh + e.clientY - d.y) }));
    };
    const up = () => (drag.current = null);
    window.addEventListener("pointermove", mv);
    window.addEventListener("pointerup", up);
    return () => { window.removeEventListener("pointermove", mv); window.removeEventListener("pointerup", up); };
  }, []);

  if (!open) return null;
  const Visual = form === "hammer" ? SolHammer : Orb2;

  return (
    <div style={{ position: "fixed", left: geom.x, top: geom.y, width: geom.w, height: geom.h, zIndex: 190, display: "flex", flexDirection: "column", background: "var(--sur)", border: "1px solid color-mix(in srgb, var(--acc) 30%, var(--bd))", borderRadius: 8, boxShadow: "0 26px 80px rgba(0,0,0,0.6)", overflow: "hidden" }}>
      <div onPointerDown={(e) => { drag.current = { kind: "move", x: e.clientX, y: e.clientY, gx: geom.x, gy: geom.y }; }}
        style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 12px", borderBottom: "1px solid var(--bd)", cursor: "grab", userSelect: "none", background: "var(--sur2)", flexShrink: 0 }}>
        <Visual size={22} energy={energy} state={busy ? "thinking" : "idle"} />
        <div style={{ flex: 1 }}>
          <span style={{ fontSize: 12.5, fontWeight: 700, letterSpacing: "0.04em" }}>SOL</span>
          <Mono size={8} style={{ marginLeft: 8 }}>{busy ? "TRACING ACROSS DOMAINS…" : "GROUNDED IN WHAT'S CONNECTED"}</Mono>
        </div>
        <Seg size="sm" options={["Guide", "Auto"]} value={mode} onChange={onMode} />
        <span onClick={onClose} style={{ color: "var(--mut)", cursor: "pointer", padding: 4 }}>{SI.x({ size: 13 })}</span>
      </div>

      <div ref={bodyRef} style={{ flex: 1, overflowY: "auto", padding: "12px 12px 6px", display: "flex", flexDirection: "column", gap: 12, minHeight: 0 }}>
        {msgs.length === 0 && !busy && (
          <div style={{ textAlign: "center", padding: "26px 18px", color: "var(--mut)", fontSize: 12, lineHeight: 1.6 }}>
            Ask about anything connected.<br />{world.id === "sam" ? "Try “how do I add a ground pour?”" : world.id === "priya" ? "Try “why did the car cut power at turn 3?”" : "Try “diagnose run 41.”"}
          </div>
        )}
        {msgs.map((m, i) => {
          if (m.role === "user") return <div key={i} style={{ alignSelf: "flex-end", maxWidth: "82%", background: "var(--sur2)", border: "1px solid var(--bd)", borderRadius: "10px 10px 2px 10px", padding: "8px 12px", fontSize: 12.5, lineHeight: 1.55 }}>{m.text}</div>;
          if (m.type === "finding") return <FindingCard key={i} f={m.finding} mode={mode} fixStates={approvals} onFix={m.onFix} onGuideFix={m.onGuideFix} />;
          if (m.type === "approval") return <ApprovalCard key={i} spec={m.spec} state={approvals[m.spec.id] || "pending"} busyLines={m.busyLines} onApprove={() => onApprove(m.spec.id)} onReject={() => onReject(m.spec.id)} />;
          if (m.type === "guide") return <GuideSteps key={i} g={m.guide} activeStep={guideState.step} setActiveStep={guideState.setStep} onPoint={m.onPoint} onDo={m.onDo} />;
          if (m.type === "prov") return <div key={i} style={{ display: "flex", flexDirection: "column", gap: 8 }}><div style={{ fontSize: 12.5, lineHeight: 1.65 }}>{m.text}</div><ProvCard rows={m.rows} /></div>;
          if (m.type === "status") return <div key={i} style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: m.ok ? "var(--ok)" : "var(--mut)", padding: "0 2px" }}>{m.ok ? "✓ " : ""}{m.text}</div>;
          return <div key={i} style={{ fontSize: 12.5, lineHeight: 1.65, maxWidth: "94%" }}>{m.text}</div>;
        })}
        {busy && <div style={{ display: "flex", gap: 9, alignItems: "center" }}><Orb2 size={20} energy={energy} state="thinking" /><span className="sol-think" style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--mut)" }}>reading the graph…</span></div>}
      </div>

      <div style={{ padding: "9px 12px 12px", borderTop: "1px solid var(--bd)", flexShrink: 0 }}>
        <div style={{ display: "flex", gap: 7 }}>
          <input value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && input.trim()) { onSend(input.trim()); setInput(""); } }}
            placeholder="Ask about a signal, a part, a run…"
            style={{ flex: 1, background: "var(--bg)", color: "var(--tx)", border: "1px solid var(--bd)", borderRadius: 3, padding: "8px 11px", fontSize: 12.5, fontFamily: "var(--ui)", outline: "none" }} />
          <Btn kind="primary" size="sm" onClick={() => { if (input.trim()) { onSend(input.trim()); setInput(""); } }}>Send</Btn>
        </div>
      </div>
      <div onPointerDown={(e) => { drag.current = { kind: "resize", x: e.clientX, y: e.clientY, gw: geom.w, gh: geom.h }; }}
        style={{ position: "absolute", right: 0, bottom: 0, width: 16, height: 16, cursor: "nwse-resize", background: "linear-gradient(135deg, transparent 50%, var(--bd) 50%)" }}></div>
    </div>
  );
}

/* ---------- at-cursor ask (hotkey) ---------- */
function AtCursorAsk({ open, at, selection, onSubmit, onClose }) {
  const [q, setQ] = useStateO2("");
  const ref = useRefO2(null);
  useEffectO2(() => { if (open) { setQ(""); setTimeout(() => ref.current && ref.current.focus(), 30); } }, [open]);
  if (!open) return null;
  const x = Math.min(at.x + 14, window.innerWidth - 340), y = Math.min(at.y + 14, window.innerHeight - 90);
  return (
    <div style={{ position: "fixed", left: x, top: y, width: 320, zIndex: 210 }}>
      <Card pad={0} style={{ borderColor: "color-mix(in srgb, var(--acc) 45%, var(--bd))", boxShadow: "0 14px 44px rgba(0,0,0,0.55)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 10px" }}>
          <Orb2 size={18} energy={70} />
          <input ref={ref} value={q} onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && q.trim()) { onSubmit(q.trim()); } if (e.key === "Escape") onClose(); }}
            placeholder="Ask SOL here…" style={{ flex: 1, background: "transparent", border: "none", outline: "none", color: "var(--tx)", fontSize: 12.5, fontFamily: "var(--ui)" }} />
          <Mono size={8}>ESC</Mono>
        </div>
        {selection && (
          <div style={{ display: "flex", gap: 7, alignItems: "center", padding: "0 10px 9px" }}>
            <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--acc)", background: "color-mix(in srgb, var(--acc) 10%, transparent)", border: "1px solid color-mix(in srgb, var(--acc) 35%, transparent)", borderRadius: 99, padding: "3px 9px" }}>◈ {selection.label}</span>
            <span style={{ fontSize: 9.5, color: "var(--mut)" }}>from {selection.source} selection</span>
          </div>
        )}
      </Card>
    </div>
  );
}

Object.assign(window, { Orb2, SolCompanion2, ChatWindow, FindingCard, GuideSteps, ProvCard, AtCursorAsk });
