// Solus v2 — SOL outside the app: over a generic CAD window (labelled Onshape), hotkey ask, selection → subject, pointing
const { useState: useStateX, useEffect: useEffectX, useRef: useRefX } = React;

function ExternalScreen({ world, onBack, mode, onMode, approvals, onApprove, onReject, energy, onToast }) {
  const [selection, setSelection] = useStateX(null);
  const [askOpen, setAskOpen] = useStateX(false);
  const [askAt, setAskAt] = useStateX({ x: 400, y: 300 });
  const [convo, setConvo] = useStateX([]); // local mini-thread rendered as floating card
  const [busy, setBusy] = useStateX(false);
  const [dim, setDim] = useStateX(120);
  const [pointing, setPointing] = useStateX(null); // step index being pointed at
  const [applying, setApplying] = useStateX(false);
  const fakeCursor = useRefX(null);
  const mousePos = useRefX({ x: 400, y: 300 });

  useEffectX(() => {
    const mm = (e) => (mousePos.current = { x: e.clientX, y: e.clientY });
    const key = (e) => {
      if ((e.altKey || e.ctrlKey) && e.code === "Space") { e.preventDefault(); setAskAt({ ...mousePos.current }); setAskOpen(true); }
      if (e.key === "Escape") { setAskOpen(false); setPointing(null); }
    };
    window.addEventListener("mousemove", mm);
    window.addEventListener("keydown", key);
    return () => { window.removeEventListener("mousemove", mm); window.removeEventListener("keydown", key); };
  }, []);

  const spec = { ...world.approvals["ap-ext"] || {
    id: "ap-ext", type: "cad", risk: "low", title: "Edit dimension in Onshape — beam_bracket", params: [["width", "120 mm", "150 mm"]],
    note: "Applied through the Onshape API as one feature edit — appears in the part's history, undoable there.",
  } };

  const ask = (q) => {
    setAskOpen(false);
    setConvo((c) => [...c, { role: "user", text: q, sel: selection }]);
    setBusy(true);
    setTimeout(() => {
      setBusy(false);
      if (selection) {
        setConvo((c) => [...c, { role: "sol", text: `That 120 mm width is the mounting face — your rail spec in the repo says 150 mm center-to-center. I can change it here in Onshape; the sketch stays fully constrained.` }, { role: "approval" }]);
      } else {
        setConvo((c) => [...c, { role: "sol", text: "Select something first — click a dimension and it becomes the subject. Or ask me anything about this part; I can see the feature tree." }]);
      }
    }, 1500);
  };

  const approve = () => {
    onApprove("ap-ext");
    setApplying(true);
    // fake cursor flies to the dimension and edits it
    setTimeout(() => { if (fakeCursor.current) { fakeCursor.current.style.opacity = 1; fakeCursor.current.style.transform = "translate(520px, 318px)"; } }, 100);
    setTimeout(() => setDim(150), 1600);
    setTimeout(() => { if (fakeCursor.current) fakeCursor.current.style.opacity = 0; setApplying(false); setConvo((c) => [...c, { role: "status", text: "Applied via Onshape API — “width 150” now in the feature history. Undo lives in Onshape (⌘Z)." }]); onToast("CAD edit applied", "beam_bracket width: 120 → 150 mm"); }, 2300);
  };

  const guideSteps = [
    { t: "The Sketch dimension tool lives in the top toolbar", conf: 0.94, target: { x: 318, y: 74 } },
    { t: "Double-click the 120 dimension to edit it", conf: 0.9, target: { x: 508, y: 312 } },
    { t: "Where the constraints panel is in your Onshape version", conf: null, gap: "Onshape moved this recently — I'm not sure for your account. Look under the ⋮ menu on the sketch toolbar; tell me if you find it." },
  ];

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 150, background: "#1e1f22", display: "flex", flexDirection: "column" }} data-screen-label="Outside Solus — external app">
      {/* fake OS strip */}
      <div style={{ height: 30, background: "#0c0d0f", display: "flex", alignItems: "center", gap: 10, padding: "0 12px", flexShrink: 0 }}>
        <span style={{ display: "flex", gap: 6 }}>{["#FF5F57", "#FEBC2E", "#28C840"].map((c) => <span key={c} style={{ width: 10, height: 10, borderRadius: 99, background: c }}></span>)}</span>
        <span style={{ fontSize: 11.5, color: "#9a9ba1", fontFamily: "var(--ui)" }}>Onshape — beam_bracket · Part Studio 1</span>
        <div style={{ flex: 1 }}></div>
        <span style={{ fontSize: 10.5, color: "#6c6d73", fontFamily: "var(--mono)" }}>Solus running in tray · orb stays with you</span>
        <Btn kind="primary" size="sm" onClick={onBack}>← Back to Solus</Btn>
      </div>

      {/* generic CAD chrome (deliberately generic — not Onshape's real UI) */}
      <div style={{ height: 40, background: "#2a2b2f", borderBottom: "1px solid #3a3b40", display: "flex", alignItems: "center", gap: 6, padding: "0 12px", flexShrink: 0 }}>
        {["Sketch", "Extrude", "Revolve", "Fillet", "Dim", "Mate"].map((tl, i) => (
          <span key={tl} id={"ext-tool-" + i} style={{ fontSize: 11, color: "#b9bac0", background: "#333438", border: "1px solid #414247", borderRadius: 4, padding: "5px 10px", fontFamily: "var(--ui)", position: "relative" }}>
            {tl}
            {pointing === 0 && i === 4 && <PointerTip step={guideSteps[0]} energy={energy} />}
          </span>
        ))}
        <div style={{ flex: 1 }}></div>
        <span style={{ fontSize: 10, color: "#6c6d73", fontFamily: "var(--mono)" }}>generic stand-in chrome — not the real app</span>
      </div>

      <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
        {/* feature tree */}
        <div style={{ width: 190, background: "#252629", borderRight: "1px solid #3a3b40", padding: "10px 0", flexShrink: 0 }}>
          <div style={{ padding: "0 12px 8px", fontSize: 10, color: "#7c7d83", fontFamily: "var(--mono)", letterSpacing: "0.08em" }}>FEATURES</div>
          {["Sketch 1", "Extrude 1", "Fillet 2", "Hole pattern", "Sketch 2 (width)"].map((ftr, i) => (
            <div key={ftr} style={{ padding: "6px 14px", fontSize: 11.5, color: i === 4 ? "#e8c66a" : "#b9bac0", background: i === 4 && selection ? "#33342e" : "transparent", fontFamily: "var(--ui)" }}>{ftr}</div>
          ))}
        </div>

        {/* canvas with the bracket */}
        <div style={{ flex: 1, position: "relative", background: "radial-gradient(#2c2d31 1px, transparent 1px) 0 0 / 24px 24px, #202124" }}>
          <svg viewBox="0 0 760 480" style={{ width: "100%", height: "100%", position: "absolute", inset: 0 }}>
            <path d="M280 160 h200 v60 h-60 v120 h-140 z" fill="none" stroke="#8a8b90" strokeWidth="2"></path>
            <circle cx="316" cy="196" r="9" fill="none" stroke="#8a8b90" strokeWidth="1.6"></circle>
            <circle cx="444" cy="196" r="9" fill="none" stroke="#8a8b90" strokeWidth="1.6"></circle>
            {/* width dimension — selectable */}
            <g onClick={() => setSelection({ label: `width ${dim} mm`, source: "Onshape" })} style={{ cursor: "pointer" }}>
              <line x1="280" y1="300" x2="480" y2="300" stroke={selection ? "var(--acc)" : "#6f7076"} strokeWidth="1.2"></line>
              <line x1="280" y1="292" x2="280" y2="308" stroke={selection ? "var(--acc)" : "#6f7076"}></line>
              <line x1="480" y1="292" x2="480" y2="308" stroke={selection ? "var(--acc)" : "#6f7076"}></line>
              <rect x="352" y="288" width="56" height="24" rx="3" fill={selection ? "color-mix(in srgb, var(--acc) 18%, #202124)" : "#26272b"} stroke={selection ? "var(--acc)" : "#4a4b50"} strokeWidth="1.2" className={applying ? "gm-orb" : ""}></rect>
              <text x="380" y="304" textAnchor="middle" fontFamily="var(--mono)" fontSize="13" fill={selection ? "var(--acc)" : "#c9cacf"}>{dim}</text>
            </g>
            <text x="380" y="330" textAnchor="middle" fontFamily="var(--mono)" fontSize="9" fill="#6f7076">click the dimension — selection becomes SOL's subject</text>
            <g>
              <line x1="510" y1="160" x2="510" y2="340" stroke="#6f7076" strokeWidth="1"></line>
              <text x="522" y="254" fontFamily="var(--mono)" fontSize="11" fill="#c9cacf">180</text>
            </g>
          </svg>
          {pointing === 1 && <div style={{ position: "absolute", left: "46%", top: "58%" }}><PointerTip step={guideSteps[1]} energy={energy} /></div>}

          {/* honest-gap pointer demo */}
          {pointing === 2 && (
            <div style={{ position: "absolute", right: 24, top: 18, width: 300 }}>
              <Card pad={12} style={{ borderColor: "color-mix(in srgb, var(--warn) 50%, var(--bd))" }}>
                <Mono size={8} color="var(--warn)">HONEST GAP — NOT POINTING</Mono>
                <div style={{ fontSize: 11.5, lineHeight: 1.6, marginTop: 5 }}>{guideSteps[2].gap}</div>
                <div style={{ marginTop: 8 }}><Btn kind="ghost" size="sm" onClick={() => setPointing(null)}>Got it</Btn></div>
              </Card>
            </div>
          )}

          {/* floating convo */}
          {convo.length > 0 && (
            <div style={{ position: "absolute", right: 20, bottom: 20, width: 340, display: "flex", flexDirection: "column", gap: 8, maxHeight: "70%", overflowY: "auto" }}>
              {convo.map((m, i) => m.role === "user" ? (
                <div key={i} style={{ alignSelf: "flex-end", maxWidth: "90%", background: "var(--sur2)", border: "1px solid var(--bd)", borderRadius: "10px 10px 2px 10px", padding: "7px 11px", fontSize: 12, color: "var(--tx)" }}>
                  {m.sel && <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--acc)", marginBottom: 3 }}>◈ {m.sel.label}</div>}{m.text}
                </div>
              ) : m.role === "approval" ? (
                <ApprovalCard key={i} spec={spec} state={approvals["ap-ext"] || "pending"} onApprove={approve} onReject={() => onReject("ap-ext")} />
              ) : m.role === "status" ? (
                <div key={i} style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ok)", background: "var(--sur)", border: "1px solid var(--bd)", borderRadius: 4, padding: "7px 10px" }}>✓ {m.text}</div>
              ) : (
                <div key={i} style={{ display: "flex", gap: 8, alignItems: "flex-start", background: "var(--sur)", border: "1px solid var(--bd)", borderRadius: 8, padding: "9px 11px" }}>
                  <Orb2 size={18} energy={energy} />
                  <span style={{ fontSize: 12, lineHeight: 1.6, color: "var(--tx)" }}>{m.text}</span>
                </div>
              ))}
              {busy && <div style={{ display: "flex", gap: 8, alignItems: "center", background: "var(--sur)", border: "1px solid var(--bd)", borderRadius: 8, padding: "8px 11px" }}><Orb2 size={16} energy={energy} state="thinking" /><span className="sol-think" style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--mut)" }}>reading the part + your repo…</span></div>}
            </div>
          )}

          {/* fake applying cursor */}
          <div ref={fakeCursor} style={{ position: "absolute", left: 0, top: 0, opacity: 0, transition: "transform 1.4s cubic-bezier(.4,.9,.3,1), opacity 0.3s", pointerEvents: "none", zIndex: 40 }}>
            <svg width="18" height="18" viewBox="0 0 18 18"><path d="M2 1l5 14 2.2-5.2L14.5 8z" fill="var(--acc)" stroke="var(--acc-ink)" strokeWidth="1"></path></svg>
            <span style={{ fontFamily: "var(--mono)", fontSize: 8.5, color: "var(--acc)", background: "var(--bg)", border: "1px solid var(--acc)", borderRadius: 3, padding: "2px 6px", marginLeft: 6 }}>SOL is editing…</span>
          </div>
        </div>
      </div>

      {/* bottom hint bar */}
      <div style={{ height: 40, background: "#141518", borderTop: "1px solid #2c2d31", display: "flex", alignItems: "center", gap: 14, padding: "0 14px", flexShrink: 0 }}>
        <Mono size={9} color="var(--acc)">CTRL+SPACE — ASK AT CURSOR</Mono>
        <Btn kind="soft" size="sm" onClick={() => { setAskAt({ x: window.innerWidth / 2 - 160, y: window.innerHeight / 2 }); setAskOpen(true); }}>Simulate hotkey</Btn>
        <Btn kind="ghost" size="sm" onClick={() => setSelection({ label: `width ${dim} mm`, source: "Onshape" })}>Select the width dim</Btn>
        <div style={{ flex: 1 }}></div>
        <Mono size={9}>GUIDE POINTING:</Mono>
        {guideSteps.map((s, i) => (
          <Btn key={i} kind={pointing === i ? "primary" : "bare"} size="sm" onClick={() => setPointing(pointing === i ? null : i)}>step {i + 1}{s.gap ? " (gap)" : ""}</Btn>
        ))}
      </div>

      <AtCursorAsk open={askOpen} at={askAt} selection={selection} onSubmit={ask} onClose={() => setAskOpen(false)} />
    </div>
  );
}

function PointerTip({ step, energy }) {
  return (
    <div style={{ position: "absolute", left: -8, top: 26, width: 250, zIndex: 50 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
        <div className="tour-orbit" style={{ flexShrink: 0 }}><Orb2 size={26} energy={energy} state="speaking" /></div>
        <Card pad={10} style={{ borderColor: "color-mix(in srgb, var(--acc) 50%, var(--bd))", boxShadow: "0 10px 34px rgba(0,0,0,0.5)" }}>
          <div style={{ fontSize: 11.5, lineHeight: 1.55 }}>{step.t}</div>
          <Mono size={8} color={step.conf >= 0.9 ? "var(--ok)" : "var(--warn)"} style={{ marginTop: 4, display: "block" }}>{Math.round(step.conf * 100)}% SURE OF THIS LOCATION</Mono>
        </Card>
      </div>
    </div>
  );
}

Object.assign(window, { ExternalScreen });
