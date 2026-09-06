// Solus v3 — SOL docked panel (pushes content) + shell: derivation state, routes, tweaks
const { useState: useS4, useEffect: useES4, useRef: useRS4, useMemo: useMS4 } = React;

const V3_TWEAKS = /*EDITMODE-BEGIN*/{
  "theme": "dark",
  "accent": "amber",
  "density": "regular",
  "solMode": "Auto",
  "orbMode": "corner",
  "orbEnergy": 62,
  "telemSpeed": 1
}/*EDITMODE-END*/;
const V3_KEY = "solus_v3_state";
function v3load() { try { return JSON.parse(localStorage.getItem(V3_KEY)) || {}; } catch (e) { return {}; } }

/* ---------- docked SOL panel ---------- */
function SolPanel({ world, open, onClose, msgs, busy, mode, onMode, onSend, approvals, onApprove, onReject, guideStep, setGuideStep, energy }) {
  const bodyRef = useRS4(null);
  const [input, setInput] = useS4("");
  useES4(() => { if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight; }, [msgs, busy, open]);
  if (!open) return null;
  return (
    <div style={{ width: 390, flexShrink: 0, borderLeft: "1px solid color-mix(in srgb, var(--acc) 25%, var(--bd))", background: "var(--sur)", display: "flex", flexDirection: "column", minHeight: 0 }} data-screen-label="SOL panel">
      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 14px", borderBottom: "1px solid var(--bd)", flexShrink: 0 }}>
        <Orb2 size={26} energy={energy} state={busy ? "thinking" : "idle"} />
        <div style={{ flex: 1 }}>
          <span style={{ fontSize: 13, fontWeight: 700, letterSpacing: "0.04em" }}>SOL</span>
          <Mono size={8} style={{ display: "block", marginTop: 1 }}>{busy ? "TRACING ACROSS DOMAINS…" : world.insts.length ? "GROUNDED IN " + world.insts.length + " CONNECTIONS" : "NOTHING CONNECTED — I ONLY SPEAK FROM WHAT'S HERE"}</Mono>
        </div>
        <Seg size="sm" options={["Guide", "Auto"]} value={mode} onChange={onMode} />
        <span onClick={onClose} style={{ color: "var(--mut)", cursor: "pointer", padding: 4 }}>{SI.x({ size: 13 })}</span>
      </div>
      <div ref={bodyRef} style={{ flex: 1, overflowY: "auto", padding: "12px 12px 6px", display: "flex", flexDirection: "column", gap: 12, minHeight: 0 }}>
        {msgs.length === 0 && !busy && (
          <div style={{ textAlign: "center", padding: "30px 18px", color: "var(--mut)", fontSize: 12, lineHeight: 1.65 }}>
            {world.id === "sam" ? "Try “how do I add a ground pour?”" : world.id === "priya" ? "Try “why did the car cut power at turn 3?”" : world.id === "maya" ? "Try “diagnose run 41.”" : "Connect something, then ask me about it."}
          </div>
        )}
        {msgs.map((m, i) => {
          if (m.role === "user") return <div key={i} style={{ alignSelf: "flex-end", maxWidth: "84%", background: "var(--sur2)", border: "1px solid var(--bd)", borderRadius: "10px 10px 2px 10px", padding: "8px 12px", fontSize: 12.5, lineHeight: 1.55 }}>{m.text}</div>;
          if (m.type === "finding") return <FindingCard key={i} f={m.finding} mode={mode} fixStates={approvals} onFix={m.onFix} onGuideFix={m.onGuideFix} />;
          if (m.type === "approval") return <ApprovalCard key={i} spec={m.spec} state={approvals[m.spec.id] || "pending"} onApprove={() => onApprove(m.spec.id)} onReject={() => onReject(m.spec.id)} />;
          if (m.type === "guide") return <GuideSteps key={i} g={m.guide} activeStep={guideStep} setActiveStep={setGuideStep} onPoint={m.onPoint} onDo={m.onDo} />;
          if (m.type === "prov") return <div key={i} style={{ display: "flex", flexDirection: "column", gap: 8 }}><div style={{ fontSize: 12.5, lineHeight: 1.65 }}>{m.text}</div><ProvCard rows={m.rows} /></div>;
          if (m.type === "status") return <div key={i} style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: m.ok ? "var(--ok)" : "var(--mut)" }}>{m.ok ? "✓ " : ""}{m.text}</div>;
          return <div key={i} style={{ fontSize: 12.5, lineHeight: 1.65 }}>{m.text}</div>;
        })}
        {busy && <div style={{ display: "flex", gap: 9, alignItems: "center" }}><Orb2 size={18} energy={energy} state="thinking" /><span className="sol-think" style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--mut)" }}>reading the graph…</span></div>}
      </div>
      <div style={{ padding: "9px 12px 12px", borderTop: "1px solid var(--bd)", flexShrink: 0 }}>
        <div style={{ display: "flex", gap: 7 }}>
          <input value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && input.trim()) { onSend(input.trim()); setInput(""); } }}
            placeholder="Ask about a signal, a part, a run…" style={{ flex: 1, background: "var(--bg)", color: "var(--tx)", border: "1px solid var(--bd)", borderRadius: 3, padding: "8px 11px", fontSize: 12.5, fontFamily: "var(--ui)", outline: "none" }} />
          <Btn kind="primary" size="sm" onClick={() => { if (input.trim()) { onSend(input.trim()); setInput(""); } }}>Send</Btn>
        </div>
        <Mono size={8} style={{ display: "block", marginTop: 7 }}>⌥ SPACE ANYWHERE — ASK AT CURSOR · {mode === "Guide" ? "GUIDE: TEACHES, POINTS" : "AUTO: ACTS, WITH APPROVAL"}</Mono>
      </div>
    </div>
  );
}

/* ---------- app ---------- */
function V3App() {
  const [tw, setTweak] = useTweaks(V3_TWEAKS);
  const p = useRS4(v3load()).current;
  const [route, setRoute] = useS4(p.route || { name: "landing" });
  const [authed, setAuthed] = useS4(!!p.authed);
  const [firstRunDone, setFirstRunDone] = useS4(!!p.firstRunDone);
  const [connectedIds, setConnectedIds] = useS4(p.connectedIds || []);
  const [installed, setInstalled] = useS4(p.installed || []);
  const [approvals, setApprovals] = useS4({});
  const [msgs, setMsgs] = useS4([]);
  const [busy, setBusy] = useS4(false);
  const [panelOpen, setPanelOpen] = useS4(false);
  const [scope, setScope] = useS4(null);
  const [anomalyLive, setAnomalyLive] = useS4(false);
  const [run42, setRun42] = useS4({ status: "none", progress: 0 });
  const [notifOpen, setNotifOpen] = useS4(false);
  const [toast, setToast] = useS4(null);
  const [paletteOpen, setPaletteOpen] = useS4(false);
  const [modal, setModal] = useS4(null);
  const [windowState, setWindowState] = useS4("open");
  const [guideStep, setGuideStep] = useS4(0);
  const [askOpen, setAskOpen] = useS4(false);
  const [askAt, setAskAt] = useS4({ x: 300, y: 260 });
  const [storeDetail, setStoreDetail] = useS4(null);
  const mousePos = useRS4({ x: 400, y: 300 });

  const world = useMS4(() => V3.deriveWorld(connectedIds, installed), [connectedIds, installed]);
  window.__v2world = world; // v2 bench/experiments sample from this

  useES4(() => { applySolusTheme(tw.theme, tw.accent, tw.density); }, [tw.theme, tw.accent, tw.density]);
  useES4(() => { localStorage.setItem(V3_KEY, JSON.stringify({ route, authed, firstRunDone, connectedIds, installed })); }, [route, authed, firstRunDone, connectedIds, installed]);
  useES4(() => { if (toast) { const t = setTimeout(() => setToast(null), 3600); return () => clearTimeout(t); } }, [toast]);

  const fullApp = authed && firstRunDone;
  const go = (name, extra) => { setRoute({ name, ...(extra || {}) }); setNotifOpen(false); setPaletteOpen(false); };
  const info = (title, body) => setToast({ title, body });
  window.__go = go;
  window.__reset = () => { setAuthed(false); setFirstRunDone(false); setConnectedIds([]); setInstalled([]); setApprovals({}); setMsgs([]); setPanelOpen(false); setScope(null); setAnomalyLive(false); setRun42({ status: "none", progress: 0 }); go("landing"); };
  window.__quickFill = (k) => { const pr = V3.PRESETS[k]; setConnectedIds(pr.ids); setInstalled(pr.installs); };

  const connectIds = (ids) => {
    setConnectedIds((c) => [...new Set([...c, ...ids])]);
    // auto-install core viewers the first time their requirement appears (spec: signals/scene are suggested; keep them ghost-slots too — install only 'signals' visualizers when a preset)  
  };
  const disconnectId = (id) => setConnectedIds((c) => c.filter((x) => x !== id));
  const quickFill = (k) => { window.__quickFill(k); info("Preset applied — connections only", V3.PRESETS[k].label + ". The workspace derives from these; change any of it."); };
  const install = (id, on = true) => {
    setInstalled((s) => on ? [...new Set([...s, id])] : s.filter((x) => x !== id));
    const w = V3.WIDGETS.find((x) => x.id === id);
    info(on ? "Installed " + w.name : "Uninstalled " + w.name, on ? (V3.reqMet(world.insts, w) ? "It's live — derived from what's connected." : "Dormant until you connect " + V3.reqMissing(world.insts, w).join(", ") + ".") : "Its panels leave the workspace. Nothing else changes.");
  };

  /* ---------- SOL engine ---------- */
  const requestApproval = (id) => {
    const spec = world.approvals[id]; if (!spec) return;
    setPanelOpen(true);
    setMsgs((c) => c.some((m) => m.type === "approval" && m.spec.id === id) ? c : [...c, { role: "sol", type: "approval", spec }]);
  };
  const guideFix = (id) => {
    const spec = world.approvals[id];
    setMsgs((c) => [...c, { role: "sol", text: `Guide mode — before I touch anything: ${spec.note || spec.title} Flip me to Auto and I'll queue it for your approval.` }]);
  };
  const openSol = (key) => {
    setPanelOpen(true);
    if (!key) return;
    const s = world.sol[key]; if (!s) return;
    const qText = { diagnose: "Diagnose run 41.", jitter: "Why do my servos shake?", cutout: "Why did the car cut power at turn 3?", pour: "How do I add a ground pour?", harness: "Who designed the accumulator harness?", hello: "What can you see?" }[key] || (s.q || key);
    setMsgs((c) => c.some((m) => m.role === "user" && m.text === qText) ? c : [...c, { role: "user", text: qText }]);
    setBusy(true);
    setTimeout(() => {
      setBusy(false);
      setMsgs((c) => {
        if (c.some((m) => m.__key === key)) return c;
        const base = { role: "sol", __key: key };
        if (s.finding && world.finding) return [...c, { ...base, text: s.text }, { role: "sol", type: "finding", finding: world.finding, onFix: requestApproval, onGuideFix: guideFix }];
        if (s.guide && world.guide) return [...c, { ...base, text: s.text }, { role: "sol", type: "guide", guide: world.guide, onPoint: () => info("Pointing", "In the real product the orb hovers next to the control in KiCad itself — see the Outside Solus demo."), onDo: () => requestApproval("ap-pour") }];
        if (s.prov) return [...c, { ...base, type: "prov", text: s.text, rows: s.provRows }];
        return [...c, { ...base, text: s.text }];
      });
    }, 1500);
  };
  const sendFree = (q) => {
    const l = q.toLowerCase();
    let key = "hello";
    if (world.affinity === "maya") key = /run|41|stall|diagno|joint|fail/.test(l) ? "diagnose" : /flash|register|limit/.test(l) ? "whatflash" : /some|episode|spawn/.test(l) ? "why42" : "hello";
    if (world.affinity === "sam") key = /pour|ground|zone|kicad/.test(l) ? "pour" : /jitter|shake|servo|wobble/.test(l) ? "jitter" : "hello";
    if (world.affinity === "priya") key = /cut|power|turn|fault|lap/.test(l) ? "cutout" : /harness|who|design|w-12|awg/.test(l) ? "harness" : "hello";
    setMsgs((c) => [...c, { role: "user", text: q }]);
    setBusy(true);
    setTimeout(() => {
      setBusy(false);
      const s = world.sol[key] || world.sol.hello;
      setMsgs((c) => {
        const base = { role: "sol" };
        if (s.finding && world.finding) return [...c, { ...base, text: s.text }, { role: "sol", type: "finding", finding: world.finding, onFix: requestApproval, onGuideFix: guideFix }];
        if (s.guide && world.guide) return [...c, { ...base, text: s.text }, { role: "sol", type: "guide", guide: world.guide, onPoint: () => info("Pointing", "See the Outside Solus demo."), onDo: () => requestApproval("ap-pour") }];
        if (s.prov) return [...c, { ...base, type: "prov", text: s.text, rows: s.provRows }];
        return [...c, { ...base, text: s.text }];
      });
    }, 1400);
  };
  const onApprove = (id) => {
    setApprovals((a) => ({ ...a, [id]: "approved" }));
    if (id === "ap-flash") { setMsgs((c) => [...c, { role: "sol", type: "status", text: "flashing M2 · servos disabled · verifying…" }]); setTimeout(() => { setMsgs((c) => [...c, { role: "sol", type: "status", ok: true, text: "flash verified — I_limit 2.4 A. Backup saved." }]); info("Flash complete", "M2 current limit is 2.4 A."); }, 2100); }
    else if (id === "ap-clamp") setTimeout(() => setMsgs((c) => [...c, { role: "sol", type: "status", ok: true, text: "clamp committed — branch sol/clamp-limits, tests pass." }]), 800);
    else if (id === "ap-rerun") { setRun42({ status: "running", progress: 0 }); go("experiments"); let ep = 0; const iv = setInterval(() => { ep++; setRun42({ status: ep >= 20 ? "done" : "running", progress: ep }); if (ep >= 20) { clearInterval(iv); info("Run 42 passed", "0 of 20 anomalous — was 14. Compare is ready."); } }, 420); }
    else if (id === "ap-probe") setTimeout(() => { setMsgs((c) => [...c, { role: "sol", type: "status", ok: true, text: "probe: ATmega328P @ 16 MHz — Uno-compatible confirmed. Signals renamed D9/D10/D11." }]); }, 1900);
    else info("Approved", (world.approvals[id] || { title: id }).title);
  };
  const onReject = (id) => setApprovals((a) => ({ ...a, [id]: "rejected" }));
  const bothFixed = approvals["ap-clamp"] === "approved" && approvals["ap-flash"] === "approved";

  /* ---------- keyboard ---------- */
  useES4(() => {
    const mm = (e) => (mousePos.current = { x: e.clientX, y: e.clientY });
    const h = (e) => {
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key.toLowerCase() === "k") { e.preventDefault(); setPaletteOpen((o) => !o); }
      else if (e.altKey && e.code === "Space" && fullApp && route.name !== "external") { e.preventDefault(); setAskAt({ ...mousePos.current }); setAskOpen(true); }
      else if (mod && e.key.toLowerCase() === "j" && fullApp) { e.preventDefault(); setPanelOpen((o) => !o); }
      else if (mod && ["1", "2", "3", "4", "5", "6"].includes(e.key) && fullApp) { e.preventDefault(); go(["home", "bench", "experiments", "graph", "connections", "store"][+e.key - 1]); }
      else if (mod && e.key === "," && fullApp) { e.preventDefault(); go("settings", { section: "preferences" }); }
      else if (mod && e.key === "\\") { e.preventDefault(); setTweak("theme", tw.theme === "dark" ? "light" : "dark"); }
      else if (e.key === "Escape") { setPaletteOpen(false); setModal(null); setNotifOpen(false); setAskOpen(false); }
    };
    window.addEventListener("mousemove", mm); window.addEventListener("keydown", h);
    return () => { window.removeEventListener("mousemove", mm); window.removeEventListener("keydown", h); };
  }, [fullApp, tw.theme, route.name]);

  /* ---------- chrome ---------- */
  const menus = [
    { id: "solus", label: "Solus", items: [{ id: "about", label: "About Solus" }, { sep: true }, { id: "prefs", label: "Preferences…", kbd: "⌘," }, { sep: true }, { id: "signout", label: "Sign Out" }, { id: "quit", label: "Quit", kbd: "⌘Q" }] },
    { id: "view", label: "View", items: [{ id: "v-home", label: "Home", kbd: "⌘1" }, { id: "v-bench", label: "Live Bench", kbd: "⌘2" }, { id: "v-experiments", label: "Experiments", kbd: "⌘3" }, { id: "v-graph", label: "Graph", kbd: "⌘4" }, { id: "v-connections", label: "Connections", kbd: "⌘5" }, { id: "v-store", label: "Store", kbd: "⌘6" }, { sep: true }, { id: "v-sol", label: "Toggle SOL panel", kbd: "⌘J" }, { id: "v-external", label: "Outside Solus (Onshape demo)" }, { id: "toggle-theme", label: "Toggle Theme", kbd: "⌘\\" }] },
    { id: "robot", label: "Robot", items: [{ id: "r-anom", label: "Inject anomaly", disabled: world.signals.length === 0 }, { id: "r-rerun", label: "Re-run experiment…", disabled: !(world.affinity === "maya" && bothFixed) }, { sep: true }, { id: "r-estop", label: "E-stop (Space)", danger: true }] },
    { id: "help", label: "Help", items: [{ id: "h-ask", label: "Ask SOL at cursor", kbd: "⌥Space" }, { id: "docs", label: "Documentation" }] },
  ];
  const menuAction = (id) => {
    if (id === "about") setModal("about");
    else if (id === "prefs") go("settings", { section: "preferences" });
    else if (id === "signout" || id === "quit") (id === "quit" ? setWindowState("closed") : window.__reset());
    else if (id === "v-sol") setPanelOpen((o) => !o);
    else if (id === "v-external") go("external");
    else if (id.startsWith("v-")) go(id.slice(2));
    else if (id === "toggle-theme") setTweak("theme", tw.theme === "dark" ? "light" : "dark");
    else if (id === "r-anom") { setAnomalyLive(true); go("bench"); }
    else if (id === "r-rerun") requestApproval("ap-rerun");
    else if (id === "r-estop") info("E-stop", "All motion halted (simulated).");
    else if (id === "h-ask") { setAskAt({ x: window.innerWidth / 2 - 160, y: 200 }); setAskOpen(true); }
    else if (id === "docs") info("Documentation", "Stubbed in this prototype.");
  };
  const paletteItems = useMS4(() => {
    const pages = [["home", "Home", "box"], ["bench", "Live Bench", "bench"], ["experiments", "Experiments", "play"], ["graph", "Graph", "graph"], ["connections", "Connections", "link"], ["store", "Store", "download"]].map(([r, l, ic], i) => ({ id: "p" + r, label: l, section: "page", kbd: "⌘" + (i + 1), icon: SI[ic]({ size: 13 }), run: () => go(r) }));
    const acts = [
      { id: "a-sol", label: "Toggle SOL panel", section: "sol", kbd: "⌘J", icon: SI.sol({ size: 13 }), run: () => setPanelOpen((o) => !o) },
      world.finding && { id: "a-diag", label: "Ask: " + world.findings[0].finding.title.slice(0, 40) + "…", section: "sol", icon: SI.warn({ size: 13 }), run: () => openSol(world.findings[0].solKey) },
      { id: "a-settings", label: "Settings · Preferences", section: "page", kbd: "⌘,", icon: SI.gear({ size: 13 }), run: () => go("settings", { section: "preferences" }), primary: false },
      { id: "a-billing", label: "Settings · Billing & plan", section: "page", icon: SI.card({ size: 13 }), run: () => go("settings", { section: "billing" }), primary: false },
      { id: "a-ext", label: "Outside Solus — Onshape demo", section: "page", icon: SI.monitor({ size: 13 }), run: () => go("external"), primary: false },
    ].filter(Boolean);
    const ents = world.signals.map((s) => ({ id: "s-" + s.id, label: s.name, section: "signal", dot: dcol("rt"), primary: false, run: () => { setScope({ id: s.id, label: s.name, kind: "signal" }); go("bench"); } }));
    return [...pages, ...acts, ...ents];
  }, [world]);

  const bell = (
    <div id="rail-bell" onClick={(e) => { e.stopPropagation(); setNotifOpen(!notifOpen); }} style={{ position: "relative", cursor: "pointer", padding: 4, color: "var(--mut)", display: fullApp ? "inline-flex" : "none" }}>
      {SI.bell({ size: 16 })}
      {world.notifications.length > 0 && <span style={{ position: "absolute", top: -2, right: -3, minWidth: 13, height: 13, borderRadius: 99, background: "var(--err)", color: "#fff", fontSize: 8.5, fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center" }}>{world.notifications.length}</span>}
    </div>
  );
  const solChip = fullApp && (
    <span onClick={() => setPanelOpen((o) => !o)} title="Toggle SOL (⌘J)" style={{ display: "inline-flex", alignItems: "center", gap: 6, cursor: "pointer", border: `1px solid ${panelOpen ? "color-mix(in srgb, var(--acc) 50%, transparent)" : "var(--bd)"}`, borderRadius: 99, padding: "3px 10px 3px 4px" }}>
      <Orb2 size={18} energy={tw.orbEnergy} state={busy ? "thinking" : "idle"} />
      <Mono size={8.5} color={panelOpen ? "var(--acc)" : "var(--mut)"}>SOL</Mono>
    </span>
  );

  const name = route.name;
  if (name === "external" && fullApp) {
    return (
      <>
        <ExternalScreen world={world} onBack={() => go("home")} mode={tw.solMode} onMode={(v) => setTweak("solMode", v)} approvals={approvals} onApprove={(id) => setApprovals((a) => ({ ...a, [id]: "approved" }))} onReject={onReject} energy={tw.orbEnergy} onToast={info} />
        <V3Toast toast={toast} onClose={() => setToast(null)} />
        <V3Panel tw={tw} setTweak={setTweak} quickFill={quickFill} anomalySet={setAnomalyLive} go={go} />
      </>
    );
  }

  let body;
  if (!fullApp) {
    body = (
      <div style={{ flex: 1, minHeight: 0, overflowY: "auto", display: "flex", flexDirection: "column" }}>
        {name === "landing" && <LandingPage go={go} />}
        {name === "signup" && <SignupPage go={go} onAuth={() => { setAuthed(true); go("connect"); }} />}
        {name === "login" && <LoginPage go={go} onAuth={() => { setAuthed(true); setFirstRunDone(true); if (connectedIds.length === 0) window.__quickFill("maya"); go("home"); }} />}
        {name === "connect" && authed && <ConnectionsScreen3 world={world} firstRun onConnectIds={connectIds} onDisconnectId={disconnectId} onQuickFill={quickFill} onDone={() => { setFirstRunDone(true); go("home"); }} onToast={info} onProbe={() => requestApproval("ap-probe")} />}
        {!["landing", "signup", "login", "connect"].includes(name) && <LandingPage go={go} />}
      </div>
    );
  } else {
    body = (
      <div style={{ flex: 1, display: "flex", minHeight: 0 }} onClick={() => notifOpen && setNotifOpen(false)}>
        <div style={{ width: 56, borderRight: "1px solid var(--bd)", display: "flex", flexDirection: "column", alignItems: "center", padding: "14px 0", gap: 8, flexShrink: 0, background: "var(--sur)" }}>
          <div onClick={() => go("home")} style={{ marginBottom: 12, cursor: "pointer" }}><Orb2 size={24} energy={tw.orbEnergy} /></div>
          <RailBtn3 id="r-home" icon={SI.home({ size: 17 })} label="Home" active={name === "home"} onClick={() => go("home")} />
          <RailBtn3 id="r-bench" icon={SI.bench({ size: 17 })} label="Live Bench" active={name === "bench"} onClick={() => go("bench")} badge={anomalyLive ? 1 : 0} />
          <RailBtn3 id="r-exp" icon={SI.play({ size: 17 })} label="Experiments" active={name === "experiments"} onClick={() => go("experiments")} />
          <RailBtn3 id="r-graph" icon={SI.graph({ size: 17 })} label="Graph" active={name === "graph"} onClick={() => go("graph")} />
          <RailBtn3 id="r-conn" icon={SI.link({ size: 17 })} label="Connections" active={name === "connect" || name === "connections"} onClick={() => go("connections")} />
          <RailBtn3 id="r-store" icon={SI.plus({ size: 17 })} label="Store" active={name === "store"} onClick={() => go("store")} badge={world.widgets.suggested.length} />
          <div style={{ flex: 1 }}></div>
          <RailBtn3 id="r-settings" icon={SI.gear({ size: 17 })} label="Settings" active={name === "settings"} onClick={() => go("settings", { section: "preferences" })} />
          <RailBtn3 id="r-sol" icon={SI.sol({ size: 17 })} label="SOL (⌘J)" active={panelOpen} onClick={() => setPanelOpen((o) => !o)} />
          <div style={{ marginTop: 4 }}><Avatar name="You X" size={26} /></div>
        </div>
        <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
          {scope && (
            <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 16px", borderBottom: "1px solid var(--bd)", background: "color-mix(in srgb, var(--acc) 4%, var(--bg))", flexShrink: 0 }}>
              <Mono size={8.5} color="var(--acc)">SCOPE</Mono>
              <span style={{ fontFamily: "var(--mono)", fontSize: 11 }}>{scope.label}</span>
              <span onClick={() => setScope(null)} style={{ marginLeft: "auto", cursor: "pointer", color: "var(--mut)", display: "inline-flex", gap: 4, alignItems: "center", fontSize: 10.5 }}>{SI.x({ size: 11 })} clear</span>
            </div>
          )}
          <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
            <div style={{ flex: 1, display: "flex", minWidth: 0, minHeight: 0 }}>
              {name === "home" && <HomeScreen3 world={world} go={go} openSol={openSol} onInstall={install} onDetail={setStoreDetail} anomalyLive={anomalyLive} run42={run42} fixes={approvals} requestProbe={() => requestApproval("ap-probe")} onToast={info} />}
              {name === "bench" && <BenchScreen2 world={world} anomalyLive={anomalyLive} scope={scope} setScope={setScope} openChat={openSol} telemSpeed={tw.telemSpeed} />}
              {name === "experiments" && <ExperimentsScreen world={world} run42={run42} startRerun={() => requestApproval("ap-rerun")} fixes={approvals} openChat={openSol} requestApproval={requestApproval} />}
              {name === "graph" && <GraphScreen3 world={world} scope={scope} setScope={setScope} openSol={openSol} onToast={info} />}
              {(name === "connections" || name === "connect") && <ConnectionsScreen3 world={world} firstRun={false} onConnectIds={connectIds} onDisconnectId={disconnectId} onQuickFill={quickFill} onToast={info} onProbe={() => requestApproval("ap-probe")} />}
              {name === "store" && <StoreScreen world={world} onInstall={install} onToast={info} />}
              {name === "settings" && <SettingsLayout section={route.section || "preferences"} setSection={(s) => go("settings", { section: s })} tw={tw} setTweak={setTweak} connected={[world.connectedIds.includes("ghRepo") || world.connectedIds.includes("ghOrg") ? "github" : null, world.connectedIds.includes("kicadApp") ? "kicad" : null, world.connectedIds.includes("onshapeFree") ? "onshape" : null].filter(Boolean)} onUpgrade={(pl) => info("Plans", pl && pl.id === "ent" ? "We'll reach out about Enterprise." : "Plan change scheduled for the next cycle.")} />}
            </div>
            <SolPanel world={world} open={panelOpen} onClose={() => setPanelOpen(false)} msgs={msgs} busy={busy} mode={tw.solMode} onMode={(v) => setTweak("solMode", v)} onSend={sendFree} approvals={approvals} onApprove={onApprove} onReject={onReject} guideStep={guideStep} setGuideStep={setGuideStep} energy={tw.orbEnergy} />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div style={{ position: "fixed", inset: 0, background: "#05070a", display: "flex" }}>
      <div style={{ flex: 1, display: "flex", flexDirection: "column", background: "var(--bg)", color: "var(--tx)", fontFamily: "var(--ui)", overflow: "hidden" }}>
        <Titlebar minimal={!fullApp} onTraffic={(a) => (a === "close" ? setWindowState("closed") : a === "min" ? setWindowState("min") : null)} onCommand={() => setPaletteOpen(true)} onNav={(s) => go("settings", { section: s })} onAction={menuAction} onToggleTheme={() => setTweak("theme", tw.theme === "dark" ? "light" : "dark")} bell={<>{solChip}{bell}</>} wsName={world.wsName} wsSub={world.wsSub} />
        {fullApp && <MenuBar menus={menus} onAction={menuAction} />}
        {body}
      </div>
      {fullApp && notifOpen && (
        <div style={{ position: "fixed", top: 44, right: 14, width: 340, zIndex: 130 }} onClick={(e) => e.stopPropagation()}>
          <Card pad={0} style={{ boxShadow: "0 16px 50px rgba(0,0,0,0.5)" }}>
            <div style={{ padding: "11px 14px", borderBottom: "1px solid var(--bd)", display: "flex", justifyContent: "space-between" }}><Mono size={9.5}>FINDINGS</Mono><span onClick={() => setNotifOpen(false)} style={{ color: "var(--mut)", cursor: "pointer" }}>{SI.x({ size: 12 })}</span></div>
            {world.notifications.length === 0 && <div style={{ padding: "18px 14px", fontSize: 12, color: "var(--mut)", lineHeight: 1.6 }}>Nothing right now. Findings appear when connected domains disagree.</div>}
            {world.notifications.map((n) => (
              <div key={n.id} onClick={() => { setNotifOpen(false); openSol(n.action); }} style={{ display: "flex", gap: 10, padding: "12px 14px", borderBottom: "1px solid var(--bd)", cursor: "pointer" }}>
                <span style={{ color: n.sev === "critical" ? "var(--err)" : "var(--warn)", marginTop: 1 }}>{SI.warn({ size: 13 })}</span>
                <div style={{ flex: 1 }}><div style={{ fontSize: 12, fontWeight: 600, lineHeight: 1.4 }}>{n.title}</div><div style={{ fontSize: 10.5, color: "var(--mut)", marginTop: 2 }}>{n.sub}</div></div>
                {SI.arrowR({ size: 12 })}
              </div>
            ))}
          </Card>
        </div>
      )}
      <V3Toast toast={toast} onClose={() => setToast(null)} />
      <AtCursorAsk open={askOpen} at={askAt} selection={scope ? { label: scope.label, source: "Solus" } : null} onSubmit={(q) => { setAskOpen(false); setPanelOpen(true); sendFree(q); }} onClose={() => setAskOpen(false)} />
      <CommandPalette open={paletteOpen} items={paletteItems} onClose={() => setPaletteOpen(false)} onRun={(it) => { setPaletteOpen(false); it.run(); }} />
      {modal === "about" && <AboutModal onClose={() => setModal(null)} />}
      {storeDetail && <StoreDetail w={storeDetail} world={world} installed={installed.includes(storeDetail.id)} onClose={() => setStoreDetail(null)} onInstall={install} />}
      <WindowSplash state={windowState} onReopen={() => setWindowState("open")} />
      <V3Panel tw={tw} setTweak={setTweak} quickFill={quickFill} anomalySet={setAnomalyLive} go={go} />
    </div>
  );
}

function RailBtn3({ id, icon, label, active, onClick, badge }) {
  return (
    <div id={id} className="railbtn" onClick={onClick} style={{ position: "relative", width: 36, height: 36, borderRadius: 3, display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", background: active ? "color-mix(in srgb, var(--acc) 12%, transparent)" : "transparent", color: active ? "var(--acc)" : "var(--mut)" }}>
      {icon}
      {badge > 0 && <span style={{ position: "absolute", top: 1, right: 1, minWidth: 13, height: 13, borderRadius: 99, background: "var(--acc)", color: "var(--acc-ink)", fontSize: 8.5, fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center" }}>{badge}</span>}
      <span className="flyout">{label}</span>
    </div>
  );
}

function V3Toast({ toast, onClose }) {
  if (!toast) return null;
  return (
    <div className="toast-in" style={{ position: "fixed", top: 78, right: 22, width: 340, zIndex: 140 }}>
      <Card pad={13} style={{ borderColor: "color-mix(in srgb, var(--ok) 40%, var(--bd))", boxShadow: "0 14px 44px rgba(0,0,0,0.55)", display: "flex", gap: 10, alignItems: "flex-start" }}>
        <span style={{ color: "var(--ok)", marginTop: 1 }}>{SI.check({ size: 15 })}</span>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 12.5, fontWeight: 600, lineHeight: 1.4 }}>{toast.title}</div>
          {toast.body && <div style={{ fontSize: 11.5, color: "var(--mut)", marginTop: 3, lineHeight: 1.5 }}>{toast.body}</div>}
        </div>
        <span onClick={onClose} style={{ color: "var(--mut)", cursor: "pointer", padding: 2 }}>{SI.x({ size: 12 })}</span>
      </Card>
    </div>
  );
}

function V3Panel({ tw, setTweak, quickFill, anomalySet, go }) {
  const accentHexes = Object.keys(SolusAccents).map((k) => SolusAccents[k].c);
  const hexToKey = (hex) => Object.keys(SolusAccents).find((k) => SolusAccents[k].c === hex) || "amber";
  return (
    <TweaksPanel>
      <TweakSection label="Setup presets (connections only)" />
      <TweakButton label="Fill as Maya — ML researcher" onClick={() => quickFill("maya")} />
      <TweakButton label="Fill as Sam — hobbyist" onClick={() => quickFill("sam")} />
      <TweakButton label="Fill as Priya — FSAE lead" onClick={() => quickFill("priya")} />
      <TweakSection label="SOL" />
      <TweakRadio label="Mode" value={tw.solMode} options={["Guide", "Auto"]} onChange={(v) => setTweak("solMode", v)} />
      <TweakSlider label="Orb energy" value={tw.orbEnergy} min={10} max={100} onChange={(v) => setTweak("orbEnergy", v)} />
      <TweakSection label="Theme" />
      <TweakSelect label="Preset" value={tw.theme} options={Object.keys(SolusThemes).map((k) => ({ value: k, label: SolusThemes[k].name }))} onChange={(v) => setTweak("theme", v)} />
      <TweakColor label="Accent" value={SolusAccents[tw.accent].c} options={accentHexes} onChange={(v) => setTweak("accent", hexToKey(v))} />
      <TweakRadio label="Density" value={tw.density} options={["compact", "regular"]} onChange={(v) => setTweak("density", v)} />
      <TweakSection label="Bench" />
      <TweakSlider label="Telemetry speed" value={tw.telemSpeed} min={0.5} max={4} step={0.5} unit="×" onChange={(v) => setTweak("telemSpeed", v)} />
      <TweakButton label="Inject anomaly" onClick={() => { anomalySet(true); go("bench"); }} />
      <TweakSection label="Prototype" />
      <TweakButton label="Outside Solus (Onshape demo)" onClick={() => go("external")} />
      <TweakButton label="Reset to landing" onClick={() => window.__reset()} />
    </TweaksPanel>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<V3App />);
