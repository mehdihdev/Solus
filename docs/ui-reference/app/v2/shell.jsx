// Solus v2 — shell: persona worlds, routing, chat engine, approvals, first-run, tweaks
const { useState: useStateS3, useEffect: useEffectS3, useRef: useRefS3, useMemo: useMemoS3 } = React;

const V2_TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "persona": "maya",
  "theme": "dark",
  "accent": "amber",
  "density": "regular",
  "solMode": "Auto",
  "orbForm": "orb",
  "orbEnergy": 62,
  "telemSpeed": 1
}/*EDITMODE-END*/;
const V2_KEY = "solus_v2_state";

function v2load() { try { return JSON.parse(localStorage.getItem(V2_KEY)) || {}; } catch (e) { return {}; } }

function V2RailBtn({ id, icon, label, active, onClick, badge }) {
  return (
    <div id={id} className="railbtn" onClick={onClick} style={{ position: "relative", width: 36, height: 36, borderRadius: 3, display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", background: active ? "color-mix(in srgb, var(--acc) 12%, transparent)" : "transparent", color: active ? "var(--acc)" : "var(--mut)" }}>
      {icon}
      {badge > 0 && <span style={{ position: "absolute", top: 1, right: 1, minWidth: 13, height: 13, borderRadius: 99, background: "var(--err)", color: "#fff", fontSize: 8.5, fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center" }}>{badge}</span>}
      <span className="flyout">{label}</span>
    </div>
  );
}

function V2NotifPopover({ items, onClose, onAct }) {
  return (
    <div style={{ position: "fixed", top: 44, right: 14, width: 340, zIndex: 130 }} onClick={(e) => e.stopPropagation()}>
      <Card pad={0} style={{ boxShadow: "0 16px 50px rgba(0,0,0,0.5)" }}>
        <div style={{ padding: "11px 14px", borderBottom: "1px solid var(--bd)", display: "flex", justifyContent: "space-between" }}>
          <Mono size={9.5}>FINDINGS & NOTES</Mono>
          <span onClick={onClose} style={{ color: "var(--mut)", cursor: "pointer" }}>{SI.x({ size: 12 })}</span>
        </div>
        {items.map((n) => (
          <div key={n.id} onClick={() => n.action && onAct(n.action)} style={{ display: "flex", gap: 10, padding: "12px 14px", borderBottom: "1px solid var(--bd)", cursor: n.action ? "pointer" : "default" }}>
            <span style={{ color: n.sev === "critical" ? "var(--err)" : n.sev === "warning" ? "var(--warn)" : "var(--mut)", marginTop: 1 }}>{n.sev === "info" ? SI.sol({ size: 13 }) : SI.warn({ size: 13 })}</span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 12, fontWeight: 600, lineHeight: 1.4 }}>{n.title}</div>
              <div style={{ fontSize: 10.5, color: "var(--mut)", marginTop: 2, lineHeight: 1.45 }}>{n.sub}</div>
            </div>
            {n.action && SI.arrowR({ size: 12 })}
          </div>
        ))}
      </Card>
    </div>
  );
}

function V2Toast({ toast, onClose }) {
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

function V2App() {
  const [tw, setTweak] = useTweaks(V2_TWEAK_DEFAULTS);
  const world = V2P[tw.persona] || V2P.maya;
  window.__v2world = world;
  const p = useRefS3(v2load()).current;
  const [route, setRoute] = useStateS3(p.route || { name: "landing" });
  const [authed, setAuthed] = useStateS3(!!p.authed);
  const [firstRunDone, setFirstRunDone] = useStateS3(!!p.firstRunDone);
  const [scope, setScope] = useStateS3(null);
  const [chatOpen, setChatOpen] = useStateS3(false);
  const [msgs, setMsgs] = useStateS3([]);
  const [busy, setBusy] = useStateS3(false);
  const [approvals, setApprovals] = useStateS3(p.approvals || {});
  const [run42, setRun42] = useStateS3(p.run42 || { status: "none", progress: 0 });
  const [anomalyLive, setAnomalyLive] = useStateS3(false);
  const [orbParked, setOrbParked] = useStateS3(false);
  const [orbDismissed, setOrbDismissed] = useStateS3(false);
  const [notifOpen, setNotifOpen] = useStateS3(false);
  const [apOpen, setApOpen] = useStateS3(false);
  const [toast, setToast] = useStateS3(null);
  const [paletteOpen, setPaletteOpen] = useStateS3(false);
  const [modal, setModal] = useStateS3(null);
  const [windowState, setWindowState] = useStateS3("open");
  const [guideStep, setGuideStep] = useStateS3(0);
  const [askOpen, setAskOpen] = useStateS3(false);
  const [askAt, setAskAt] = useStateS3({ x: 300, y: 300 });
  const mousePos = useRefS3({ x: 400, y: 300 });
  const lastWorld = useRefS3(tw.persona);

  useEffectS3(() => { applySolusTheme(tw.theme, tw.accent, tw.density); }, [tw.theme, tw.accent, tw.density]);
  useEffectS3(() => { localStorage.setItem(V2_KEY, JSON.stringify({ route, authed, firstRunDone, approvals, run42 })); }, [route, authed, firstRunDone, approvals, run42]);
  useEffectS3(() => {
    if (lastWorld.current !== tw.persona) {
      lastWorld.current = tw.persona;
      setMsgs([]); setChatOpen(false); setScope(null); setApprovals({}); setRun42({ status: "none", progress: 0 }); setAnomalyLive(false); setGuideStep(0);
      if (authed && firstRunDone) go("workspace");
    }
  }, [tw.persona]);
  useEffectS3(() => { if (toast && !toast.action) { const t = setTimeout(() => setToast(null), 3400); return () => clearTimeout(t); } }, [toast]);

  const fullApp = authed && firstRunDone;
  const go = (name, extra) => { setRoute({ name, ...(extra || {}) }); setNotifOpen(false); setPaletteOpen(false); };
  window.__go = go; window.__setPersona = (v) => setTweak("persona", v);
  window.__reset = () => { setAuthed(false); setFirstRunDone(false); setApprovals({}); setRun42({ status: "none", progress: 0 }); setAnomalyLive(false); setMsgs([]); setChatOpen(false); setScope(null); go("landing"); };
  const info = (title, body) => setToast({ title, body });

  /* ---------- chat engine ---------- */
  const pushSol = (m) => setMsgs((c) => [...c, m]);
  const requestApproval = (id) => {
    const spec = world.approvals[id];
    if (!spec) return;
    setChatOpen(true);
    setMsgs((c) => c.some((m) => m.type === "approval" && m.spec.id === id) ? c : [...c, { role: "sol", type: "approval", spec }]);
  };
  const guideFix = (id) => {
    const spec = world.approvals[id];
    pushSol({ role: "sol", text: `Guide mode — here's what the fix does before you let me touch anything: ${spec.note || spec.title}. Flip to Auto (the left tab on my orb, or the toggle above) and I'll queue it for approval.` });
  };
  const openChat = (key) => {
    setChatOpen(true);
    if (!key) return;
    const s = world.sol[key];
    if (!s) return;
    const qText = { diagnose: "Diagnose run 41.", jitter: "Why do my servos shake?", cutout: "Why did the car cut power at turn 3?", pour: "How do I add a ground pour?", harness: "Who designed the accumulator harness, and why is it 16 AWG?", hello: "What can you see?", why42: world.sol.why42 && world.sol.why42.q, whatflash: world.sol.whatflash && world.sol.whatflash.q }[key] || key;
    setMsgs((c) => {
      if (c.some((m) => m.role === "user" && m.text === qText)) return c;
      return [...c, { role: "user", text: qText }];
    });
    setBusy(true);
    setTimeout(() => {
      setBusy(false);
      setMsgs((c) => {
        if (c.some((m) => m.__key === key)) return c;
        const base = { role: "sol", __key: key };
        if (s.finding) return [...c, { ...base, text: s.text }, { role: "sol", type: "finding", finding: world.finding, onFix: requestApproval, onGuideFix: guideFix }];
        if (s.guide) return [...c, { ...base, text: s.text }, { role: "sol", type: "guide", guide: world.guide, onPoint: () => info("Pointing in KiCad", "SOL's orb hovers next to the control in the real app — see “Outside Solus” for the demo."), onDo: () => requestApproval("ap-pour") }];
        if (s.prov) return [...c, { ...base, type: "prov", text: s.text, rows: s.provRows }];
        return [...c, { ...base, text: s.text }];
      });
    }, 1600);
  };
  const sendFree = (q) => {
    const lower = q.toLowerCase();
    let key = "hello";
    if (world.id === "maya") key = /run|41|stall|diagno|joint|fail/.test(lower) ? "diagnose" : /flash|register|limit/.test(lower) ? "whatflash" : /why.*(some|episode)|spawn/.test(lower) ? "why42" : "hello";
    if (world.id === "sam") key = /pour|ground|zone|kicad/.test(lower) ? "pour" : /jitter|shake|servo|wobble/.test(lower) ? "jitter" : "hello";
    if (world.id === "priya") key = /cut|power|turn|fault|lap/.test(lower) ? "cutout" : /harness|who|design|w-12|awg/.test(lower) ? "harness" : "hello";
    setMsgs((c) => [...c, { role: "user", text: q }]);
    setBusy(true);
    setTimeout(() => {
      setBusy(false);
      const s = world.sol[key];
      setMsgs((c) => {
        const base = { role: "sol" };
        if (s.finding) return [...c, { ...base, text: s.text }, { role: "sol", type: "finding", finding: world.finding, onFix: requestApproval, onGuideFix: guideFix }];
        if (s.guide) return [...c, { ...base, text: s.text }, { role: "sol", type: "guide", guide: world.guide, onPoint: () => info("Pointing in KiCad", "See “Outside Solus” for the external-app demo."), onDo: () => requestApproval("ap-pour") }];
        if (s.prov) return [...c, { ...base, type: "prov", text: s.text, rows: s.provRows }];
        return [...c, { ...base, text: s.text }];
      });
    }, 1500);
  };

  /* ---------- approval resolution + effects ---------- */
  const onApprove = (id) => {
    setApprovals((a) => ({ ...a, [id]: "approved" }));
    const spec = world.approvals[id] || { title: id };
    if (id === "ap-flash") {
      pushSol({ role: "sol", type: "status", text: "flashing M2 · servos disabled · verifying…" });
      setTimeout(() => { pushSol({ role: "sol", type: "status", ok: true, text: "flash verified — I_limit now 2.4 A. Backup saved." }); info("Flash complete", "M2 current limit is 2.4 A."); }, 2200);
    } else if (id === "ap-clamp") {
      setTimeout(() => pushSol({ role: "sol", type: "status", ok: true, text: "clamp committed to main — branch sol/clamp-limits, tests pass." }), 900);
    } else if (id === "ap-rerun") {
      startRun42();
    } else if (id === "ap-probe") {
      setTimeout(() => pushSol({ role: "sol", type: "status", ok: true, text: "probe result: ATmega328P @ 16 MHz — it IS an Uno-compatible. Renaming signals to D9/D10/D11." }), 2000);
    } else {
      info("Approved", spec.title);
    }
  };
  const onReject = (id) => setApprovals((a) => ({ ...a, [id]: "rejected" }));
  const bothFixed = approvals["ap-clamp"] === "approved" && approvals["ap-flash"] === "approved";
  const startRerun = () => requestApproval("ap-rerun");
  const startRun42 = () => {
    setRun42({ status: "running", progress: 0 });
    go("experiments");
    let ep = 0;
    const iv = setInterval(() => {
      ep += 1;
      setRun42({ status: ep >= 20 ? "done" : "running", progress: ep });
      if (ep >= 20) { clearInterval(iv); info("Run 42 passed", "0 of 20 episodes anomalous — was 14. Compare is ready."); }
    }, 420);
  };

  /* ---------- keyboard ---------- */
  useEffectS3(() => {
    const mm = (e) => (mousePos.current = { x: e.clientX, y: e.clientY });
    const handler = (e) => {
      const mod = e.metaKey || e.ctrlKey;
      const typing = /^(INPUT|TEXTAREA|SELECT)$/.test((e.target && e.target.tagName) || "");
      if (mod && e.key.toLowerCase() === "k") { e.preventDefault(); setPaletteOpen((o) => !o); }
      else if (e.altKey && e.code === "Space" && fullApp && route.name !== "external") { e.preventDefault(); setAskAt({ ...mousePos.current }); setAskOpen(true); }
      else if (e.key === "Control" && !e.repeat && fullApp && !typing) { setOrbParked((v) => !v); }
      else if (mod && ["1", "2", "3", "4", "5"].includes(e.key) && fullApp) { e.preventDefault(); go(["workspace", "bench", "experiments", "graph", "connections"][+e.key - 1]); }
      else if (mod && e.key === "\\") { e.preventDefault(); setTweak("theme", tw.theme === "dark" ? "light" : "dark"); }
      else if (e.key === "Escape") { setPaletteOpen(false); setModal(null); setNotifOpen(false); setApOpen(false); setAskOpen(false); }
    };
    window.addEventListener("mousemove", mm);
    window.addEventListener("keydown", handler);
    return () => { window.removeEventListener("mousemove", mm); window.removeEventListener("keydown", handler); };
  }, [fullApp, tw.theme, route.name]);

  /* ---------- menus + palette ---------- */
  const menus = [
    { id: "solus", label: "Solus", items: [{ id: "about", label: "About Solus" }, { sep: true }, { id: "prefs", label: "Preferences…", kbd: "⌘," }, { sep: true }, { id: "signout", label: "Sign Out" }, { id: "quit", label: "Quit Solus", kbd: "⌘Q" }] },
    { id: "view", label: "View", items: [
      { id: "v-workspace", label: "Workspace", kbd: "⌘1" }, { id: "v-bench", label: "Live Bench", kbd: "⌘2" }, { id: "v-experiments", label: "Experiments", kbd: "⌘3" }, { id: "v-graph", label: "Graph", kbd: "⌘4" }, { id: "v-connections", label: "Connections", kbd: "⌘5" }, { sep: true },
      { id: "v-external", label: "Outside Solus (Onshape demo)" }, { sep: true }, { id: "toggle-theme", label: "Toggle Theme", kbd: "⌘\\" },
    ] },
    { id: "robot", label: "Robot", items: [{ id: "r-anom", label: "Inject anomaly" }, { id: "r-rerun", label: "Re-run experiment…", disabled: world.id !== "maya" || !bothFixed }, { sep: true }, { id: "r-estop", label: "E-stop (Space)", danger: true }] },
    { id: "help", label: "Help", items: [{ id: "h-ask", label: "Ask SOL at cursor", kbd: "⌥Space" }, { id: "h-park", label: "Park / unpark orb", kbd: "Ctrl" }, { id: "docs", label: "Documentation" }] },
  ];
  const menuAction = (id) => {
    if (id === "about") setModal("about");
    else if (id === "prefs") go("settings", { section: "preferences" });
    else if (id === "signout") { setAuthed(false); setFirstRunDone(false); go("landing"); }
    else if (id === "quit") setWindowState("closed");
    else if (id.startsWith("v-")) go(id.slice(2));
    else if (id === "toggle-theme") setTweak("theme", tw.theme === "dark" ? "light" : "dark");
    else if (id === "r-anom") { setAnomalyLive(true); go("bench"); }
    else if (id === "r-rerun") startRerun();
    else if (id === "r-estop") info("E-stop", "All motion halted (simulated).");
    else if (id === "h-ask") { setAskAt({ x: window.innerWidth / 2 - 160, y: 200 }); setAskOpen(true); }
    else if (id === "h-park") setOrbParked((v) => !v);
    else if (id === "docs") info("Documentation", "Stubbed in this prototype.");
  };
  const paletteItems = useMemoS3(() => {
    const pages = [["workspace", "Workspace", "box"], ["bench", "Live Bench", "bench"], ["experiments", "Experiments", "play"], ["graph", "Graph", "graph"], ["connections", "Connections", "link"], ["external", "Outside Solus — Onshape demo", "monitor"]].map(([r, l, ic], i) => ({ id: "p" + r, label: l, section: "page", kbd: i < 5 ? "⌘" + (i + 1) : null, icon: SI[ic]({ size: 13 }), run: () => go(r) }));
    const acts = [
      { id: "a-diag", label: world.id === "sam" ? "Ask: why do my servos shake?" : world.id === "priya" ? "Ask: why did the car cut power?" : "Ask: diagnose run 41", section: "sol", icon: SI.sol({ size: 13 }), run: () => openChat(world.id === "sam" ? "jitter" : world.id === "priya" ? "cutout" : "diagnose") },
      { id: "a-anom", label: "Inject anomaly", section: "action", icon: SI.warn({ size: 13 }), run: () => { setAnomalyLive(true); go("bench"); } },
      { id: "a-park", label: "Park / unpark SOL", section: "action", kbd: "Ctrl", icon: SI.sol({ size: 13 }), run: () => setOrbParked((v) => !v), primary: false },
    ];
    const ents = world.signals.map((s) => ({ id: "s-" + s.id, label: s.name, section: "signal", dot: dcol("rt"), primary: false, run: () => { setScope({ id: s.id, label: s.name, kind: "signal" }); go("bench"); } }));
    return [...pages, ...acts, ...ents];
  }, [world.id]);

  const pendingAp = Object.keys(world.approvals).map((id) => ({ spec: world.approvals[id], state: approvals[id] || (msgs.some((m) => m.type === "approval" && m.spec.id === id) ? "pending" : "suggested") })).filter((x) => x.state !== "suggested");
  const pendingCount = pendingAp.filter((x) => x.state === "pending").length;

  /* ---------- chrome ---------- */
  const bellNode = (
    <div id="rail-bell" onClick={(e) => { e.stopPropagation(); setNotifOpen(!notifOpen); setApOpen(false); }} style={{ position: "relative", cursor: "pointer", padding: 4, color: "var(--mut)", display: fullApp ? "inline-flex" : "none" }}>
      {SI.bell({ size: 16 })}
      {world.notifications.length > 0 && <span style={{ position: "absolute", top: -2, right: -3, minWidth: 13, height: 13, borderRadius: 99, background: "var(--err)", color: "#fff", fontSize: 8.5, fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center" }}>{world.notifications.length}</span>}
    </div>
  );
  const approvalsPill = fullApp && (
    <span onClick={(e) => { e.stopPropagation(); setApOpen(!apOpen); setNotifOpen(false); }} style={{ display: "inline-flex", gap: 6, alignItems: "center", fontFamily: "var(--mono)", fontSize: 9, letterSpacing: "0.06em", color: pendingCount ? "var(--acc)" : "var(--mut)", border: `1px solid ${pendingCount ? "color-mix(in srgb, var(--acc) 45%, transparent)" : "var(--bd)"}`, borderRadius: 99, padding: "4px 10px", cursor: "pointer" }}>
      {SI.check({ size: 11 })} APPROVALS{pendingCount ? " · " + pendingCount : ""}
    </span>
  );

  const name = route.name;
  if (name === "external" && fullApp) {
    return (
      <>
        <ExternalScreen world={world} onBack={() => go("workspace")} mode={tw.solMode} onMode={(v) => setTweak("solMode", v)} approvals={approvals} onApprove={onApprove} onReject={onReject} energy={tw.orbEnergy} onToast={info} />
        <SolCompanion2 form={tw.orbForm} energy={tw.orbEnergy} parked={orbParked} dismissed={orbDismissed} mode={tw.solMode} onMode={(v) => setTweak("solMode", v)} onChat={() => setChatOpen(true)} thinking={busy} />
        <ChatWindow world={world} open={chatOpen} onClose={() => setChatOpen(false)} msgs={msgs} busy={busy} mode={tw.solMode} onMode={(v) => setTweak("solMode", v)} onSend={sendFree} approvals={approvals} onApprove={onApprove} onReject={onReject} guideState={{ step: guideStep, setStep: setGuideStep }} energy={tw.orbEnergy} form={tw.orbForm} />
        <V2Toast toast={toast} onClose={() => setToast(null)} />
        <V2Panel tw={tw} setTweak={setTweak} go={go} setAnomalyLive={setAnomalyLive} setAuthed={setAuthed} setFirstRunDone={setFirstRunDone} />
      </>
    );
  }

  let body;
  if (!fullApp) {
    body = (
      <div style={{ flex: 1, minHeight: 0, overflowY: "auto", display: "flex", flexDirection: "column" }}>
        {name === "landing" && <LandingPage go={go} />}
        {name === "signup" && <SignupPage go={go} onAuth={() => { setAuthed(true); go("connect"); }} />}
        {name === "login" && <LoginPage go={go} onAuth={() => { setAuthed(true); setFirstRunDone(true); go("workspace"); }} />}
        {name === "connect" && authed && <ConnectionsScreen world={world} firstRun onDone={() => { setFirstRunDone(true); go("workspace"); }} onToast={info} onProbe={() => {}} />}
        {!["landing", "signup", "login", "connect"].includes(name) && <LandingPage go={go} />}
      </div>
    );
  } else {
    body = (
      <div style={{ flex: 1, display: "flex", minHeight: 0 }} onClick={() => { notifOpen && setNotifOpen(false); apOpen && setApOpen(false); }}>
        <div style={{ width: 56, borderRight: "1px solid var(--bd)", display: "flex", flexDirection: "column", alignItems: "center", padding: "14px 0", gap: 8, flexShrink: 0, background: "var(--sur)" }}>
          <div onClick={() => go("workspace")} style={{ marginBottom: 12, cursor: "pointer" }}><Orb2 size={24} energy={tw.orbEnergy} /></div>
          <V2RailBtn id="rail-ws" icon={SI.box({ size: 17 })} label="Workspace" active={name === "workspace"} onClick={() => go("workspace")} />
          <V2RailBtn id="rail-bench" icon={SI.bench({ size: 17 })} label="Live Bench" active={name === "bench"} onClick={() => go("bench")} badge={anomalyLive ? 1 : 0} />
          <V2RailBtn id="rail-exp" icon={SI.play({ size: 17 })} label="Experiments" active={name === "experiments"} onClick={() => go("experiments")} badge={world.id === "maya" && !bothFixed ? 1 : 0} />
          <V2RailBtn id="rail-graph" icon={SI.graph({ size: 17 })} label="Graph" active={name === "graph"} onClick={() => go("graph")} />
          <V2RailBtn id="rail-conn" icon={SI.link({ size: 17 })} label="Connections" active={name === "connections"} onClick={() => go("connections")} />
          <div style={{ flex: 1 }}></div>
          <V2RailBtn id="rail-settings" icon={SI.gear({ size: 17 })} label="Settings" active={name === "settings"} onClick={() => go("settings", { section: "preferences" })} />
          <div style={{ marginTop: 4 }}><Avatar name={world.label.split(" ")[0] + " X"} size={26} /></div>
        </div>
        <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, position: "relative" }}>
          {scope && name !== "settings" && (
            <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 16px", borderBottom: "1px solid var(--bd)", background: "color-mix(in srgb, var(--acc) 4%, var(--bg))", flexShrink: 0 }}>
              <Mono size={8.5} color="var(--acc)">SCOPE</Mono>
              <span style={{ fontFamily: "var(--mono)", fontSize: 11 }}>{scope.label}</span>
              <span style={{ fontSize: 10.5, color: "var(--mut)" }}>— every surface filtered to this</span>
              <span onClick={() => setScope(null)} style={{ marginLeft: "auto", cursor: "pointer", color: "var(--mut)", display: "inline-flex", gap: 4, alignItems: "center", fontSize: 10.5 }}>{SI.x({ size: 11 })} clear</span>
            </div>
          )}
          <div style={{ flex: 1, display: "flex", minHeight: 0, position: "relative" }}>
            {name === "workspace" && <WorkspaceScreen world={world} scope={scope} go={go} openChat={openChat} fixes={approvals} run42={run42} anomalyLive={anomalyLive} requestProbe={() => requestApproval("ap-probe")} onToast={info} />}
            {name === "bench" && <BenchScreen2 world={world} anomalyLive={anomalyLive} scope={scope} setScope={setScope} openChat={openChat} telemSpeed={tw.telemSpeed} />}
            {name === "experiments" && <ExperimentsScreen world={world} run42={run42} startRerun={startRerun} fixes={approvals} openChat={openChat} requestApproval={requestApproval} />}
            {name === "graph" && <GraphScreen2 world={world} scope={scope} setScope={setScope} openChat={openChat} onToast={info} />}
            {name === "connections" && <ConnectionsScreen world={world} firstRun={false} onDone={() => {}} onToast={info} onProbe={() => requestApproval("ap-probe")} />}
            {name === "settings" && <SettingsLayout section={route.section || "preferences"} setSection={(s) => go("settings", { section: s })} tw={tw} setTweak={setTweak} connected={["github", "kicad", "onshape", "ros"]} onUpgrade={() => info("Plans", "Billing lives in the v1 prototype too.")} />}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div style={{ position: "fixed", inset: 0, background: "#05070a", display: "flex" }}>
      <div style={{ flex: 1, display: "flex", flexDirection: "column", background: "var(--bg)", color: "var(--tx)", fontFamily: "var(--ui)", overflow: "hidden" }}>
        <Titlebar minimal={!fullApp} onTraffic={(a) => (a === "close" ? setWindowState("closed") : a === "min" ? setWindowState("min") : null)} onCommand={() => setPaletteOpen(true)} onNav={(s) => go("settings", { section: s })} onAction={menuAction} onToggleTheme={() => setTweak("theme", tw.theme === "dark" ? "light" : "dark")} bell={<>{approvalsPill}{bellNode}</>} wsName={world.wsName} wsSub={world.wsSub} />
        {fullApp && <MenuBar menus={menus} onAction={menuAction} />}
        {body}
      </div>

      {fullApp && notifOpen && <V2NotifPopover items={world.notifications} onClose={() => setNotifOpen(false)} onAct={(k) => { setNotifOpen(false); openChat(k); }} />}
      {fullApp && apOpen && <ApprovalsPopover items={pendingAp} onClose={() => setApOpen(false)} onJump={() => { setApOpen(false); setChatOpen(true); }} />}
      <V2Toast toast={toast} onClose={() => setToast(null)} />
      {fullApp && <SolCompanion2 form={tw.orbForm} energy={tw.orbEnergy} parked={orbParked} dismissed={orbDismissed} mode={tw.solMode} onMode={(v) => setTweak("solMode", v)} onChat={() => setChatOpen(true)} thinking={busy} />}
      {fullApp && <ChatWindow world={world} open={chatOpen} onClose={() => setChatOpen(false)} msgs={msgs} busy={busy} mode={tw.solMode} onMode={(v) => setTweak("solMode", v)} onSend={sendFree} approvals={approvals} onApprove={onApprove} onReject={onReject} guideState={{ step: guideStep, setStep: setGuideStep }} energy={tw.orbEnergy} form={tw.orbForm} />}
      <AtCursorAsk open={askOpen} at={askAt} selection={scope ? { label: scope.label, source: "Solus" } : null} onSubmit={(q) => { setAskOpen(false); setChatOpen(true); sendFree(q); }} onClose={() => setAskOpen(false)} />
      <CommandPalette open={paletteOpen} items={paletteItems} onClose={() => setPaletteOpen(false)} onRun={(it) => { setPaletteOpen(false); it.run(); }} />
      {modal === "about" && <AboutModal onClose={() => setModal(null)} />}
      <WindowSplash state={windowState} onReopen={() => setWindowState("open")} />
      <V2Panel tw={tw} setTweak={setTweak} go={go} setAnomalyLive={setAnomalyLive} setAuthed={setAuthed} setFirstRunDone={setFirstRunDone} />
    </div>
  );
}

function V2Panel({ tw, setTweak, go, setAnomalyLive, setAuthed, setFirstRunDone }) {
  const accentHexes = Object.keys(SolusAccents).map((k) => SolusAccents[k].c);
  const hexToKey = (hex) => Object.keys(SolusAccents).find((k) => SolusAccents[k].c === hex) || "amber";
  return (
    <TweaksPanel>
      <TweakSection label="Persona (derived workspace)" />
      <TweakRadio label="Play as" value={tw.persona} options={["maya", "sam", "priya"]} onChange={(v) => { setTweak("persona", v); }} />
      <TweakSection label="SOL" />
      <TweakRadio label="Mode" value={tw.solMode} options={["Guide", "Auto"]} onChange={(v) => setTweak("solMode", v)} />
      <TweakRadio label="Companion form" value={tw.orbForm} options={["orb", "hammer"]} onChange={(v) => setTweak("orbForm", v)} />
      <TweakSlider label="Orb energy" value={tw.orbEnergy} min={10} max={100} onChange={(v) => setTweak("orbEnergy", v)} />
      <TweakSection label="Theme" />
      <TweakSelect label="Preset" value={tw.theme} options={Object.keys(SolusThemes).map((k) => ({ value: k, label: SolusThemes[k].name }))} onChange={(v) => setTweak("theme", v)} />
      <TweakColor label="Accent" value={SolusAccents[tw.accent].c} options={accentHexes} onChange={(v) => setTweak("accent", hexToKey(v))} />
      <TweakRadio label="Density" value={tw.density} options={["compact", "regular"]} onChange={(v) => setTweak("density", v)} />
      <TweakSection label="Bench" />
      <TweakSlider label="Telemetry speed" value={tw.telemSpeed} min={0.5} max={4} step={0.5} unit="×" onChange={(v) => setTweak("telemSpeed", v)} />
      <TweakButton label="Inject anomaly" onClick={() => { setAnomalyLive(true); go("bench"); }} />
      <TweakSection label="Prototype" />
      <TweakButton label="Outside Solus (Onshape demo)" onClick={() => go("external")} />
      <TweakButton label="Restart first-run" onClick={() => { setAuthed(true); setFirstRunDone(false); go("connect"); }} />
      <TweakButton label="Reset to landing" onClick={() => window.__reset && window.__reset()} />
      <TweakButton label="Reset everything" onClick={() => { localStorage.removeItem(V2_KEY); location.reload(); }} />
    </TweaksPanel>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<V2App />);
