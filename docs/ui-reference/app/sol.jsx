// Solus — SOL agent: orb, chat screen, guided tour engine
const { useState: useStateS, useEffect: useEffectS, useRef: useRefS } = React;

/* ---------- guided tour ---------- */
function GuideTour({ tour, onEnd, energy }) {
  const [rect, setRect] = useStateS(null);
  const step = tour.steps[tour.idx];
  useEffectS(() => {
    if (!step) return;
    let alive = true;
    const find = () => {
      const el = document.querySelector(step.target);
      if (el && alive) setRect(el.getBoundingClientRect());
      else if (alive) setRect(null);
    };
    find();
    const iv = setInterval(find, 300);
    return () => { alive = false; clearInterval(iv); };
  }, [tour.idx]);
  if (!step) return null;
  const r = rect;
  const ox = r ? r.left + r.width / 2 : window.innerWidth / 2;
  const oy = r ? r.top + r.height / 2 : window.innerHeight / 2;
  const doIt = () => {
    const el = document.querySelector(step.target);
    if (el) el.click();
    setTimeout(() => {
      if (tour.idx + 1 < tour.steps.length) tour.advance();
      else onEnd();
    }, 700);
  };
  const tipBelow = oy < window.innerHeight - 180;
  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 80, pointerEvents: "none" }}>
      {r && (
        <div style={{ position: "absolute", left: r.left - 6, top: r.top - 6, width: r.width + 12, height: r.height + 12, border: "1.5px solid var(--acc)", borderRadius: 6, boxShadow: "0 0 0 4000px rgba(0,0,0,0.45), 0 0 18px color-mix(in srgb, var(--acc) 60%, transparent)", transition: "all 0.5s cubic-bezier(.35,1.2,.35,1)" }}></div>
      )}
      <div style={{ position: "absolute", left: ox, top: oy, transition: "all 0.7s cubic-bezier(.35,1.1,.3,1)" }}>
        <div className="tour-orbit" style={{ position: "absolute", left: -(r ? r.width / 2 + 34 : 30), top: -16 }}>
          <SolHammer size={34} energy={energy} state="speaking" />
        </div>
      </div>
      <div style={{
        position: "absolute", left: Math.min(Math.max(ox - 150, 16), window.innerWidth - 320),
        top: tipBelow ? (r ? r.bottom + 18 : oy + 40) : (r ? r.top - 120 : oy - 130),
        width: 300, pointerEvents: "auto", transition: "all 0.6s cubic-bezier(.35,1.1,.3,1)",
      }}>
        <Card pad={14} style={{ borderColor: "color-mix(in srgb, var(--acc) 50%, var(--bd))", boxShadow: "0 12px 40px rgba(0,0,0,0.5)" }}>
          <Mono size={9} color="var(--acc)">SOL · STEP {tour.idx + 1} OF {tour.steps.length}</Mono>
          <div style={{ fontSize: 12.5, lineHeight: 1.6, marginTop: 7 }}>{step.text}</div>
          <div style={{ display: "flex", gap: 8, marginTop: 12, justifyContent: "flex-end" }}>
            <Btn kind="bare" size="sm" onClick={onEnd}>End tour</Btn>
            {step.action === "click"
              ? <Btn kind="primary" size="sm" onClick={doIt}>Do it for me</Btn>
              : <Btn kind="primary" size="sm" onClick={() => (tour.idx + 1 < tour.steps.length ? tour.advance() : onEnd())}>{tour.idx + 1 < tour.steps.length ? "Next" : "Done"}</Btn>}
          </div>
        </Card>
      </div>
    </div>
  );
}

/* ---------- diagnosis card ---------- */
function DiagnosisCard({ script, mode, onFlash, flashState, flashStep }) {
  const FLASH_STEPS = ["Compiling firmware (gcc-arm, -O2)…", "Flashing STM32H743 over SWD…", "Verifying — watching τ_FL_knee…"];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {script.likely && (
        <Card pad={14} style={{ background: "var(--sur)" }}>
          <Mono size={9} color="var(--acc)">DIAGNOSIS</Mono>
          <div style={{ marginTop: 10 }}>
            <div style={{ fontSize: 11.5, color: "var(--mut)", padding: "2px 0" }}>Likely cause</div>
            <div style={{ fontSize: 12.5, lineHeight: 1.55, padding: "4px 0 8px", borderBottom: "1px solid var(--bd)" }}>{script.likely}</div>
            <div style={{ fontSize: 11.5, color: "var(--mut)", padding: "8px 0 2px" }}>Root cause</div>
            <div style={{ fontSize: 12.5, lineHeight: 1.55 }}>{script.root}</div>
          </div>
          {script.evidence && (
            <div style={{ marginTop: 12 }}>
              <Mono size={9}>EVIDENCE FROM THE GRAPH</Mono>
              <div style={{ display: "flex", flexDirection: "column", gap: 5, marginTop: 8 }}>
                {script.evidence.map((ev) => (
                  <div key={ev.l} style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
                    <span style={{ width: 6, height: 6, borderRadius: 99, background: dcol(ev.d), flexShrink: 0, position: "relative", top: -1 }}></span>
                    <span style={{ fontFamily: "var(--mono)", fontSize: 11 }}>{ev.l}</span>
                    <span style={{ fontSize: 10.5, color: "var(--mut)" }}>— {ev.n}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {script.fixDesc && (
            <div style={{ marginTop: 12, borderTop: "1px solid var(--bd)", paddingTop: 12 }}>
              <Mono size={9} color="var(--acc)">SUGGESTED FIX</Mono>
              <div style={{ fontSize: 12.5, lineHeight: 1.55, marginTop: 6 }}>{script.fixDesc}</div>
              {onFlash && flashState === "idle" && (
                <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
                  <Btn kind="primary" size="sm" onClick={onFlash}>Apply & flash to robot</Btn>
                  <Btn kind="ghost" size="sm">Review diff</Btn>
                </div>
              )}
              {flashState === "busy" && (
                <div style={{ marginTop: 10, fontFamily: "var(--mono)", fontSize: 10.5 }}>
                  {FLASH_STEPS.map((s, i) => (
                    <div key={s} style={{ display: "flex", gap: 9, alignItems: "center", padding: "3px 0", color: i < flashStep ? "var(--ok)" : i === flashStep ? "var(--acc)" : "var(--mut)", opacity: i > flashStep ? 0.45 : 1 }}>
                      {i < flashStep ? <span>✓</span> : i === flashStep ? <Spinner size={10} /> : <span style={{ width: 10 }}></span>}{s}
                    </div>
                  ))}
                </div>
              )}
              {flashState === "done" && (
                <div style={{ marginTop: 10, display: "flex", gap: 8, alignItems: "center", fontSize: 12, color: "var(--ok)" }}>
                  {SI.check({ size: 14 })} Flashed · τ_FL_knee stable for 30 s · alert resolved
                </div>
              )}
            </div>
          )}
        </Card>
      )}
      <div style={{ fontSize: mode === "Expert" ? 12 : 12.8, lineHeight: 1.7, color: "var(--tx)", fontFamily: mode === "Expert" ? "var(--mono)" : "var(--ui)", whiteSpace: "pre-wrap" }}>
        {mode === "Expert" ? script.expert : script.guide}
      </div>
    </div>
  );
}

/* ---------- SOL screen ---------- */
function SolScreen({ solMode, setSolMode, chat, setChat, orbEnergy, onFlashDone, onStartTour }) {
  const [input, setInput] = useStateS("");
  const [thinking, setThinking] = useStateS(false);
  const [flashState, setFlashState] = useStateS("idle");
  const [flashStep, setFlashStep] = useStateS(0);
  const endRef = useRefS(null);

  useEffectS(() => { if (endRef.current) endRef.current.scrollTop = endRef.current.scrollHeight; }, [chat, thinking, flashState]);

  const lastSol = [...chat].reverse().find((m) => m.role === "sol" && m.key);
  const lastScript = lastSol && SOL_SCRIPTS[lastSol.key];

  const send = (key, text) => {
    if (thinking) return;
    setChat((c) => [...c, { role: "user", text }]);
    setThinking(true);
    setTimeout(() => {
      setThinking(false);
      setChat((c) => [...c, { role: "sol", key }]);
    }, 1700);
    setInput("");
  };
  const sendFollowup = (f) => {
    if (thinking) return;
    setChat((c) => [...c, { role: "user", text: f.q }]);
    setThinking(true);
    setTimeout(() => {
      setThinking(false);
      setChat((c) => [...c, { role: "sol", fGuide: f.guide, fExpert: f.expert }]);
    }, 1400);
  };
  const sendFree = () => {
    const q = input.trim();
    if (!q) return;
    const lower = q.toLowerCase();
    let key = "hello";
    if (/oscill|4\.2|knee|anomal|ripple|vibrat/.test(lower)) key = "anomaly";
    else if (/u4|drv|driver|alert|swap|pin/.test(lower)) key = "alertq";
    setChat((c) => [...c, { role: "user", text: q }]);
    setThinking(true);
    setTimeout(() => { setThinking(false); setChat((c) => [...c, { role: "sol", key }]); }, 1700);
    setInput("");
  };

  const flash = () => {
    setFlashState("busy");
    [1, 2].forEach((i) => setTimeout(() => setFlashStep(i), i * 1100));
    setTimeout(() => { setFlashState("done"); onFlashDone(); }, 3 * 1100 + 600);
  };

  const asked = new Set(chat.filter((m) => m.role === "sol" && m.key).map((m) => m.key));
  const chips = [];
  if (!asked.has("anomaly")) chips.push({ label: SOL_SCRIPTS.anomaly.q, fn: () => send("anomaly", SOL_SCRIPTS.anomaly.q) });
  if (!asked.has("alertq")) chips.push({ label: SOL_SCRIPTS.alertq.q, fn: () => send("alertq", SOL_SCRIPTS.alertq.q) });
  if (!asked.has("hello")) chips.push({ label: SOL_SCRIPTS.hello.q, fn: () => send("hello", SOL_SCRIPTS.hello.q) });
  if (lastScript && lastScript.followups) lastScript.followups.forEach((f) => {
    if (!chat.some((m) => m.role === "user" && m.text === f.q)) chips.push({ label: f.q, fn: () => sendFollowup(f) });
  });
  const shownChips = chips.slice(0, 2);
  shownChips.push({ label: "Show me how to investigate the U4 alert", fn: onStartTour, tour: true });

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, minHeight: 0 }}>
      {/* header strip */}
      <div style={{ display: "flex", alignItems: "center", gap: 16, padding: "16px 24px 10px", maxWidth: 800, width: "100%", margin: "0 auto", boxSizing: "border-box" }}>
        <SolHammer size={58} energy={orbEnergy} state={thinking ? "thinking" : "idle"} />
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 16, fontWeight: 600 }}>SOL</div>
          <Mono size={9.5} color={thinking ? "var(--acc)" : "var(--mut)"}>{thinking ? "REASONING OVER THE GRAPH…" : "GROUNDED IN 247 NODES · 31 CROSS-DOMAIN LINKS"}</Mono>
        </div>
        <div style={{ textAlign: "right" }}>
          <Seg options={["Guide", "Expert"]} value={solMode} onChange={setSolMode} ids={["seg-guide", "seg-expert"]} />
          <div style={{ fontSize: 10, color: "var(--mut)", marginTop: 5 }}>{solMode === "Guide" ? "explains and teaches" : "terse, direct"}</div>
        </div>
      </div>

      {/* messages */}
      <div ref={endRef} style={{ flex: 1, overflowY: "auto", minHeight: 0 }}>
        <div style={{ maxWidth: 800, margin: "0 auto", padding: "8px 24px 16px", display: "flex", flexDirection: "column", gap: 16 }}>
          {chat.length === 0 && !thinking && (
            <div style={{ textAlign: "center", padding: "48px 24px", color: "var(--mut)" }}>
              <div style={{ fontSize: 13.5, lineHeight: 1.6 }}>Ask SOL anything about your robot.<br />It answers with the cross-domain chain of evidence.</div>
            </div>
          )}
          {chat.map((m, i) => m.role === "user" ? (
            <div key={i} style={{ alignSelf: "flex-end", maxWidth: "78%", background: "var(--sur2)", border: "1px solid var(--bd)", borderRadius: "10px 10px 2px 10px", padding: "10px 14px", fontSize: 13, lineHeight: 1.55 }}>{m.text}</div>
          ) : (
            <div key={i} style={{ display: "flex", gap: 12, maxWidth: "94%" }}>
              <SolHammer size={28} energy={orbEnergy} style={{ marginTop: 2 }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                {m.key
                  ? <DiagnosisCard script={SOL_SCRIPTS[m.key]} mode={solMode}
                      onFlash={m.key === "anomaly" ? flash : null} flashState={m.key === "anomaly" ? flashState : "idle"} flashStep={flashStep} />
                  : <div style={{ fontSize: solMode === "Expert" ? 12 : 12.8, lineHeight: 1.7, fontFamily: solMode === "Expert" ? "var(--mono)" : "var(--ui)" }}>{solMode === "Expert" ? m.fExpert : m.fGuide}</div>}
              </div>
            </div>
          ))}
          {thinking && (
            <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
              <SolHammer size={28} energy={orbEnergy} state="thinking" />
              <span className="sol-think" style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--mut)" }}>tracing FL knee through 4 domains…</span>
            </div>
          )}
        </div>
      </div>

      {/* input */}
      <div style={{ borderTop: "1px solid var(--bd)", background: "var(--sur)" }}>
        <div style={{ maxWidth: 800, margin: "0 auto", padding: "12px 24px 16px" }}>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
            {shownChips.map((c) => (
              <span key={c.label} onClick={c.fn} style={{ fontSize: 11.5, color: c.tour ? "var(--acc)" : "var(--tx)", background: "var(--bg)", border: `1px solid ${c.tour ? "color-mix(in srgb, var(--acc) 45%, transparent)" : "var(--bd)"}`, borderRadius: 99, padding: "6px 12px", cursor: "pointer", userSelect: "none" }}>
                {c.tour && "✦ "}{c.label}
              </span>
            ))}
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <input value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => e.key === "Enter" && sendFree()}
              placeholder="Ask about a signal, a change, a part…"
              style={{ flex: 1, background: "var(--bg)", color: "var(--tx)", border: "1px solid var(--bd)", borderRadius: 3, padding: "10px 14px", fontSize: 13, fontFamily: "var(--ui)", outline: "none" }} />
            <Btn kind="primary" onClick={sendFree}>Send</Btn>
          </div>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { GuideTour, SolScreen });
