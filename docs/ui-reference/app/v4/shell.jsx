// Solus v4 — shell: projects + accounts state, tab nav w/ separator + widget tabs, SOL engine (modes, float, filing), tweaks
const { useState: useS6, useEffect: useES6, useRef: useRS6, useMemo: useMS6 } = React;
const V4_TWEAKS = /*EDITMODE-BEGIN*/{ "theme": "dark", "accent": "amber", "density": "regular", "solMode": "Build", "orbEnergy": 62, "telemSpeed": 1 }/*EDITMODE-END*/;
const V4_KEY = "solus_v4_state";
const load4 = () => { try { return JSON.parse(localStorage.getItem(V4_KEY)) || {}; } catch (e) { return {}; } };

function RailNav({ tabs, cur, go, widgets, pinned, onTabMenu, energy, findings, onSettings }) {
  const icons = { home: "home", workspace: "graph", bench: "bench", sol: "sol", store: "plus" };
  const B = ({ id, label, wid, icon, badge }) => (
    <div id={"rail-" + id.replace(":", "-")} className="railbtn" onClick={() => go(id)} onContextMenu={wid ? (e) => onTabMenu(e, wid) : undefined}
      style={{ position: "relative", width: 36, height: 36, borderRadius: 3, display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", background: cur === id ? "color-mix(in srgb, var(--acc) 12%, transparent)" : "transparent", color: cur === id ? "var(--acc)" : "var(--mut)" }}>
      {(SI[icon] || SI.file)({ size: 17 })}
      {badge > 0 && <span style={{ position: "absolute", top: 1, right: 1, minWidth: 13, height: 13, borderRadius: 99, background: "var(--err)", color: "#fff", fontSize: 8.5, fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center" }}>{badge}</span>}
      {wid && pinned.includes(wid) && <span style={{ position: "absolute", bottom: 1, right: 2, fontSize: 8 }} title="Pinned for all projects">📌</span>}
      <span className="flyout">{label}{wid ? (pinned.includes(wid) ? " · pinned for all projects" : " · widget · right-click to pin") : ""}</span>
    </div>);
  return (
    <div style={{ width: 56, borderRight: "1px solid var(--bd)", display: "flex", flexDirection: "column", alignItems: "center", padding: "14px 0", gap: 8, flexShrink: 0, background: "var(--sur)" }}>
      <div onClick={() => go("home")} style={{ marginBottom: 12, cursor: "pointer" }}><Orb2 size={24} energy={energy} /></div>
      {tabs.map((t) => <B key={t[0]} id={t[0]} label={t[1]} icon={icons[t[0]]} badge={t[0] === "workspace" ? findings : 0} />)}
      <div style={{ width: 24, height: 1, background: "var(--bd)", margin: "4px 0" }} title="Widgets installed from the Store"></div>
      {widgets.map((w) => <B key={w} id={"w:" + w} label={V4.WIDGETS.find((x) => x.id === w).name} wid={w} icon={V4.WIDGETS.find((x) => x.id === w).icon} />)}
      {widgets.length === 0 && <div className="railbtn" style={{ position: "relative", width: 36, height: 36, borderRadius: 3, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--bd)", border: "1px dashed var(--bd)" }} onClick={() => go("store")}>{SI.download({ size: 14 })}<span className="flyout">Widgets from the Store get a slot here</span></div>}
      <div style={{ flex: 1 }}></div>
      <div className="railbtn" onClick={onSettings} style={{ position: "relative", width: 36, height: 36, borderRadius: 3, display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", color: cur === "settings" ? "var(--acc)" : "var(--mut)", background: cur === "settings" ? "color-mix(in srgb, var(--acc) 12%, transparent)" : "transparent" }}>{SI.gear({ size: 17 })}<span className="flyout">Settings</span></div>
      <div style={{ marginTop: 4, cursor: "pointer" }} onClick={() => go("home")}><Avatar name="You X" size={26} /></div>
    </div>);
}

function V4App() {
  const [tw, setTweak] = useTweaks(V4_TWEAKS);
  const p = useRS6(load4()).current;
  const [authed, setAuthed] = useS6(!!p.authed);
  const [route, setRoute] = useS6(p.route || (p.authed ? "home" : "landing"));
  const [accounts, setAccounts] = useS6(p.accounts || []);
  const [projects, setProjects] = useS6(p.projects || []);
  const [curId, setCurId] = useS6(p.curId || null);
  const [pinned, setPinned] = useS6(p.pinned || []);
  const [prefs, setPrefs] = useS6(p.prefs || { code: "", mech: "", elec: "", docs: "" });
  const [rootSolus, setRootSolus] = useS6(p.rootSolus || { conventions: [{ t: "text", title: "Metric only · M3 default · 2× current margin on fuses · Python: black + type hints" }], hardware: [], rules: [], errors: [], docs: [], env: [{ t: "text", title: "Python 3.11 · torch 2.4 · arm-none-eabi 13" }] });
  const [sel, setSel] = useS6(null);
  const [chats, setChats] = useS6([{ id: "c1", title: "New chat", when: "now", msgs: [] }]);
  const [curChat, setCurChat] = useS6("c1");
  const [busy, setBusy] = useS6(false);
  const [approvals, setApprovals] = useS6({});
  const [guideStep, setGuideStep] = useS6(0);
  const [anomalyLive, setAnomalyLive] = useS6(false);
  const [run, setRun] = useS6(null);
  const [toast, setToast] = useS6(null);
  const [hud, setHud] = useS6(false);
  const [floatOpen, setFloatOpen] = useS6(false);
  const [floatAt, setFloatAt] = useS6({ x: 300, y: 200 });
  const [grab, setGrab] = useS6(null);
  const [tabMenu, setTabMenu] = useS6(null);
  const [notifOpen, setNotifOpen] = useS6(false);
  const [paletteOpen, setPaletteOpen] = useS6(false);
  const [modal, setModal] = useS6(null);
  const [windowState, setWindowState] = useS6("open");
  const [settingsSection, setSettingsSection] = useS6("preferences");
  const mouse = useRS6({ x: 400, y: 300 }), lastCtrl = useRS6(0), hudT = useRS6(null);

  const project = projects.find((x) => x.id === curId) || null;
  const d = useMS6(() => project ? V4.derive(project, accounts, pinned, rootSolus) : null, [project, accounts, pinned, rootSolus]);
  const fullApp = authed;
  const mode = tw.solMode;

  useES6(() => { applySolusTheme(tw.theme, tw.accent, tw.density); }, [tw.theme, tw.accent, tw.density]);
  useES6(() => { localStorage.setItem(V4_KEY, JSON.stringify({ authed, route, accounts, projects, curId, pinned, prefs, rootSolus })); }, [authed, route, accounts, projects, curId, pinned, prefs, rootSolus]);
  useES6(() => { if (toast) { const t = setTimeout(() => setToast(null), 3800); return () => clearTimeout(t); } }, [toast]);
  const info = (title, body) => setToast({ title, body });
  const go = (r) => { setRoute(r); setNotifOpen(false); setPaletteOpen(false); setTabMenu(null); };
  window.__go = go;

  /* ---- project mutations ---- */
  const patch = (fn) => setProjects((ps) => ps.map((x) => x.id === curId ? fn(JSON.parse(JSON.stringify(x))) : x));
  const act = {
    addDoc: (id) => patch((x) => { if (!x.docs.includes(id)) { x.docs.push(id); x.activity.unshift("added " + (V4.DOC(id) || {}).name); } return x; }),
    removeDoc: (id) => patch((x) => { x.docs = x.docs.filter((y) => y !== id); return x; }),
    addRobot: (name, dev, platform) => { const rid = "r" + Math.random().toString(36).slice(2, 6); patch((x) => { x.robots.push({ id: rid, name: name || x.name, platform: platform || (dev && dev.platform) || "custom", device: dev && dev.id, mapped: false }); x.activity.unshift("Physical Robot created: " + (name || x.name)); x.solus.hardware.push({ t: "sol", title: (name || x.name) + ".yaml", sub: "written automatically" }); return x; }); return rid; },
    renameRobot: (rid, nm) => patch((x) => { const r = x.robots.find((y) => y.id === rid); if (r) r.name = nm; return x; }),
    removeRobot: (rid) => patch((x) => { x.robots = x.robots.filter((y) => y.id !== rid); x.parts = x.parts.filter((y) => y.robotId !== rid); return x; }),
    addParts: (rid, parts, mapped) => patch((x) => { parts.forEach((pt) => x.parts.push({ id: "p" + Math.random().toString(36).slice(2, 7), robotId: rid, ...pt })); const r = x.robots.find((y) => y.id === rid); if (r && mapped) r.mapped = true; x.activity.unshift(parts.length + " part" + (parts.length > 1 ? "s" : "") + " added"); return x; }),
    setState: (pid, st) => patch((x) => { const pt = x.parts.find((y) => y.id === pid); if (pt) pt.state = st; return x; }),
    addSolus: (sec, e) => patch((x) => { x.solus[sec].unshift(e); return x; }),
    acceptSuggestion: (sid) => patch((x) => { const s = x.suggestions.find((y) => y.id === sid); if (s) { x.parts.push({ id: "p" + Math.random().toString(36).slice(2, 7), robotId: s.to, name: s.what.replace(/ \(.*\)| · .*/, ""), cat: s.cat || "structure", state: "installed", src: "file", ev: s.ev }); x.suggestions = x.suggestions.filter((y) => y.id !== sid); x.activity.unshift("attached " + s.what); } return x; }),
    declineSuggestion: (sid) => patch((x) => { x.suggestions = x.suggestions.filter((y) => y.id !== sid); return x; }),
    install: (wid, on) => { patch((x) => { x.installed = on ? [...new Set([...x.installed, wid])] : x.installed.filter((y) => y !== wid); return x; }); const w = V4.WIDGETS.find((x) => x.id === wid); info(on ? "Installed " + w.name : "Uninstalled " + w.name, on ? "New tab after the separator, a node in the graph, and SOL can now " + w.adds[w.adds.length - 1].replace(/^SOL: /, "") : "Its tab and node are gone. Nothing else changed."); if (!on && route === "w:" + wid) go("workspace"); },
  };
  const createProject = (name, preset) => { const np = V4.newProject(name, preset); if (preset) setAccounts((a) => [...new Set([...a, ...V4.PRESETS[preset].accounts])]); setProjects((ps) => [np, ...ps]); setCurId(np.id); setSel(null); setApprovals({}); setRun(null); setAnomalyLive(false); setChats([{ id: "c1", title: "New chat", when: "now", msgs: [] }]); setCurChat("c1"); go("workspace"); };
  const openProject = (id) => { if (id !== curId) { setCurId(id); setSel(null); setApprovals({}); setRun(null); setAnomalyLive(false); setChats([{ id: "c1", title: "New chat", when: "now", msgs: [] }]); setCurChat("c1"); } go("workspace"); };

  /* ---- SOL engine ---- */
  const msgs = (chats.find((c) => c.id === curChat) || { msgs: [] }).msgs;
  const setMsgs = (fn) => setChats((cs) => cs.map((c) => c.id === curChat ? { ...c, msgs: fn(c.msgs), title: c.msgs.length === 0 && typeof fn === "function" ? (fn(c.msgs).find((m) => m.role === "user") || {}).text?.slice(0, 40) || c.title : c.title } : c));
  const requestApproval = (id) => { const spec = d && d.approvals[id]; if (!spec) return; setMsgs((c) => c.some((m) => m.type === "approval" && m.spec.id === id) ? c : [...c, { role: "sol", type: "approval", spec }]); };
  const guideFix = (id) => { const spec = d.approvals[id]; setMsgs((c) => [...c, { role: "sol", stream: true, text: `Guide mode — I'll show you, not do it. ${spec.note || spec.title} Switch to Build (double-tap Ctrl) and I'll queue it for your approval.` }]); };
  const artifactFor = (key) => key === "diagnose" ? { title: "M2 current-limit flash procedure", kind: "wiring + flash steps · 4 images", body: "1. Power off the bus (XT60).\n2. Keep only M2 on the chain (unplug the JST after it).\n3. In Solus › Build: approve “Flash M2 I_limit 2.4 A”.\n4. Re-chain, power on, watch τ on the bench for 30 s.", suggest: "hardware" } : key === "pour" ? { title: "ground-pour.md", kind: "notes · KiCad 8 steps with confidence", body: "Place ▸ Zone (moved in 8.0) → net GND → clearance 0.25 mm → outline → B to refill.\nStep 5 (remove islands) — location unconfirmed for 8.0.", suggest: "docs" } : key === "cutout" ? { title: "fuse-harness-alignment.md", kind: "decision record", body: "Inverter limit 40 A → F3 35 A → W-12 12 AWG. Each part sized alone was fine; together the weakest decided.\nOwners: PDU (A. Osei), loom (J. Park).", suggest: "docs" } : null;
  const reply = (key, qText, extra) => {
    if (!d) return;
    const s = d.sol[key] || d.sol.hello;
    setMsgs((c) => c.some((m) => m.role === "user" && m.text === qText) ? c : [...c, { role: "user", text: qText, ...(extra || {}) }]);
    setBusy(true);
    setTimeout(() => {
      setBusy(false);
      setMsgs((c) => {
        const base = { role: "sol", stream: true, text: s.text };
        let out = [...c];
        if (s.finding && d.finding) out.push(base, { role: "sol", type: "finding", finding: d.finding, onFix: requestApproval, onGuideFix: guideFix });
        else if (s.guide && d.guide) out.push(base, { role: "sol", type: "guide", guide: d.guide, onPoint: () => info("Pointing in KiCad", "Guide mode puts the orb next to the control in the real app — View → Outside Solus."), onDo: () => requestApproval("ap-pour") });
        else if (s.prov) out.push({ role: "sol", type: "prov", text: s.text, rows: s.provRows });
        else out.push(base);
        const a = artifactFor(key); if (a) out.push({ role: "sol", type: "artifact", artifact: a });
        return out;
      });
    }, 1500);
  };
  const openSol = (key, freeText) => {
    go("sol");
    if (freeText) return sendFree(freeText);
    if (!key || !d) return;
    const q = { diagnose: "Diagnose run 41.", jitter: "Why do my servos shake?", cutout: "Why did the car cut power at turn 3?", pour: "How do I add a ground pour?", harness: "Who designed the accumulator harness?", hello: "What can you see?" }[key] || key;
    reply(key, q);
  };
  const keyFor = (q) => { const l = q.toLowerCase(); if (!d) return "hello"; if (d.affinity === "maya") return /run|41|stall|diagno|joint|fail/.test(l) ? "diagnose" : /flash|register|limit/.test(l) ? "whatflash" : "hello"; if (d.affinity === "sam") return /pour|ground|zone|kicad/.test(l) ? "pour" : /jitter|shake|servo|wobble/.test(l) ? "jitter" : "hello"; if (d.affinity === "priya") return /cut|power|turn|fault|lap/.test(l) ? "cutout" : /harness|who|design|w-12|awg/.test(l) ? "harness" : "hello"; return "hello"; };
  const sendFree = (q, extra) => {
    if (/run (the|this|it)|execute|script/.test(q.toLowerCase())) { setMsgs((c) => [...c, { role: "user", text: q, ...(extra || {}) }]); setBusy(true); setTimeout(() => { setBusy(false); setMsgs((c) => [...c, { role: "sol", stream: true, text: "Running calibrate.py against the follower…" }, { role: "sol", type: "status", err: true, text: "SerialException: [Errno 13] Permission denied: /dev/ttyACM0 — filed to Error logging automatically" }, { role: "sol", stream: true, text: "You're not in the dialout group. Fix: `sudo usermod -aG dialout $USER`, then log out and back in. I filed the error so it's in the project's history." }]); act.addSolus("errors", { t: "sol", title: "SerialException: Permission denied /dev/ttyACM0", sub: "auto-filed by SOL · just now" }); info("Error filed", ".solus › Error logging"); }, 1600); return; }
    reply(keyFor(q), q, extra);
  };
  const fileArtifact = (i, sec) => { setMsgs((c) => c.map((m, k) => k === i ? { ...m, artifact: { ...m.artifact, filed: sec || "skip" } } : m)); if (sec) { act.addSolus(sec, { t: "sol", title: msgs[i].artifact.title, sub: "filed from SOL · " + msgs[i].artifact.kind }); info("Filed", ".solus › " + SOLUS_SECTIONS.find((s) => s[0] === sec)[1]); } };
  const onApprove = (id) => {
    setApprovals((a) => ({ ...a, [id]: "approved" }));
    if (id === "ap-flash") { setMsgs((c) => [...c, { role: "sol", type: "status", text: "flashing M2 · servos disabled · verifying…" }]); setTimeout(() => { setMsgs((c) => [...c, { role: "sol", type: "status", ok: true, text: "flash verified — I_limit 2.4 A. Backup saved." }]); setAnomalyLive(false); info("Flash complete", "M2 current limit 2.4 A"); }, 2000); }
    else if (id === "ap-clamp") setTimeout(() => setMsgs((c) => [...c, { role: "sol", type: "status", ok: true, text: "clamp committed — branch sol/clamp-limits, tests pass." }]), 800);
    else if (id === "ap-probe") setTimeout(() => { setMsgs((c) => [...c, { role: "sol", type: "status", ok: true, text: "probe: ATmega328P @ 16 MHz — Uno-compatible confirmed." }]); patch((x) => { x.parts.forEach((pt) => { if (pt.honest && /MCU/.test(pt.name)) { pt.name = "Arduino Uno (ATmega328P)"; pt.honest = 0; } }); return x; }); }, 1800);
    else info("Approved", (d.approvals[id] || { title: id }).title);
  };
  const onReject = (id) => setApprovals((a) => ({ ...a, [id]: "rejected" }));
  const runTest = () => { setRun({ eps: 20, progress: 0, done: false }); let ep = 0; const iv = setInterval(() => { ep++; setRun({ eps: 20, progress: ep, done: ep >= 20 }); if (ep >= 20) { clearInterval(iv); info("Capture complete", "20 episodes · compared against the previous run"); } }, 380); };

  /* ---- keyboard: double-tap Ctrl = mode, Ctrl+Space = float, ⌘K, ⌘1-5 ---- */
  useES6(() => {
    const mm = (e) => (mouse.current = { x: e.clientX, y: e.clientY });
    const h = (e) => {
      const mod = e.metaKey || e.ctrlKey;
      if (e.key === "Control" && !e.repeat && fullApp) { const now = Date.now(); if (now - lastCtrl.current < 420) { const nm = mode === "Guide" ? "Build" : "Guide"; setTweak("solMode", nm); setHud(true); clearTimeout(hudT.current); hudT.current = setTimeout(() => setHud(false), 1800); lastCtrl.current = 0; } else lastCtrl.current = now; }
      else if (e.ctrlKey && e.code === "Space" && fullApp) { e.preventDefault(); setFloatAt({ ...mouse.current }); setFloatOpen(true); }
      else if (mod && e.key.toLowerCase() === "k") { e.preventDefault(); setPaletteOpen((o) => !o); }
      else if (mod && ["1", "2", "3", "4", "5"].includes(e.key) && fullApp) { e.preventDefault(); go(["home", "workspace", "bench", "sol", "store"][+e.key - 1]); }
      else if (mod && e.key === "," && fullApp) { e.preventDefault(); go("settings"); }
      else if (mod && e.key === "\\") { e.preventDefault(); setTweak("theme", tw.theme === "dark" ? "light" : "dark"); }
      else if (e.key === "Escape") { setFloatOpen(false); setPaletteOpen(false); setModal(null); setNotifOpen(false); setTabMenu(null); }
    };
    window.addEventListener("mousemove", mm); window.addEventListener("keydown", h);
    return () => { window.removeEventListener("mousemove", mm); window.removeEventListener("keydown", h); };
  }, [fullApp, mode, tw.theme]);

  /* ---- chrome ---- */
  const TABS = [["home", "Home"], ["workspace", "Workspace"], ["bench", "Live Bench"], ["sol", "SOL"], ["store", "Store"]];
  const menus = [
    { id: "solus", label: "Solus", items: [{ id: "about", label: "About Solus" }, { sep: true }, { id: "prefs", label: "How I engineer…" }, { id: "settings", label: "Settings…", kbd: "⌘," }, { sep: true }, { id: "signout", label: "Sign Out" }, { id: "quit", label: "Quit", kbd: "⌘Q" }] },
    { id: "view", label: "View", items: [...TABS.map((t, i) => ({ id: "v-" + t[0], label: t[1], kbd: "⌘" + (i + 1) })), { sep: true }, { id: "v-external", label: "Outside Solus (Guide orb over Onshape)" }, { id: "toggle-theme", label: "Toggle Theme", kbd: "⌘\\" }] },
    { id: "robot", label: "Robot", items: [{ id: "r-anom", label: "Inject anomaly", disabled: !d || d.signals.length === 0 }, { id: "r-test", label: "Run live test", disabled: !d || d.signals.length === 0 }, { sep: true }, { id: "r-estop", label: "E-stop (Space)", danger: true }] },
    { id: "sol", label: "SOL", items: [{ id: "s-mode", label: (mode === "Guide" ? "Switch to Build" : "Switch to Guide"), kbd: "Ctrl ×2" }, { id: "s-float", label: "SOL anywhere", kbd: "Ctrl+Space" }] },
  ];
  const menuAction = (id) => {
    if (id === "about") setModal("about"); else if (id === "prefs") { go("home"); } else if (id === "settings") { go("settings"); } else if (id === "signout") window.__reset(); else if (id === "quit") setWindowState("closed");
    else if (id === "v-external") go("external"); else if (id.startsWith("v-")) go(id.slice(2)); else if (id === "toggle-theme") setTweak("theme", tw.theme === "dark" ? "light" : "dark");
    else if (id === "r-anom") { setAnomalyLive(true); go("bench"); } else if (id === "r-test") { go("bench"); runTest(); } else if (id === "r-estop") info("E-stop", "All motion halted (simulated).");
    else if (id === "s-mode") { setTweak("solMode", mode === "Guide" ? "Build" : "Guide"); setHud(true); setTimeout(() => setHud(false), 1800); } else if (id === "s-float") { setFloatAt({ x: window.innerWidth / 2 - 195, y: 160 }); setFloatOpen(true); }
  };
  window.__reset = () => { setAuthed(false); setProjects([]); setCurId(null); setAccounts([]); setPinned([]); setChats([{ id: "c1", title: "New chat", when: "now", msgs: [] }]); go("landing"); };
  const paletteItems = useMS6(() => [...TABS.map((t, i) => ({ id: "p" + t[0], label: t[1], section: "page", kbd: "⌘" + (i + 1), icon: SI[["home", "graph", "bench", "sol", "plus"][i]]({ size: 13 }), run: () => go(t[0]) })), ...(d ? d.tabs.map((w) => ({ id: "pw" + w, label: V4.WIDGETS.find((x) => x.id === w).name, section: "widget", icon: SI.file({ size: 13 }), run: () => go("w:" + w) })) : []), { id: "a-float", label: "SOL anywhere", section: "sol", kbd: "Ctrl+Space", icon: SI.sol({ size: 13 }), run: () => { setFloatAt({ x: 300, y: 160 }); setFloatOpen(true); } }, { id: "a-ext", label: "Outside Solus — Guide orb over Onshape", section: "page", icon: SI.monitor({ size: 13 }), run: () => go("external"), primary: false }, ...(d ? d.signals.map((s) => ({ id: "s" + s.id, label: s.name, section: "signal", dot: dcol("rt"), primary: false, run: () => go("bench") })) : [])], [d]);

  const thread = d && <SolThread d={d} msgs={msgs} busy={busy} mode={mode} approvals={approvals} onApprove={onApprove} onReject={onReject} onFile={fileArtifact} guideStep={guideStep} setGuideStep={setGuideStep} energy={tw.orbEnergy} />;
  const bell = d && (
    <div id="rail-bell" onClick={(e) => { e.stopPropagation(); setNotifOpen(!notifOpen); }} style={{ position: "relative", cursor: "pointer", padding: 4, color: "var(--mut)", display: "inline-flex" }}>
      {SI.bell({ size: 16 })}{d.findings.length > 0 && <span style={{ position: "absolute", top: -2, right: -3, minWidth: 13, height: 13, borderRadius: 99, background: "var(--err)", color: "#fff", fontSize: 8.5, fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center" }}>{d.findings.length}</span>}
    </div>);
  const modeChip = fullApp && <span onClick={() => menuAction("s-mode")} title="Double-tap Ctrl" style={{ display: "inline-flex", alignItems: "center", gap: 6, cursor: "pointer", border: "1px solid var(--bd)", borderRadius: 99, padding: "3px 10px 3px 4px" }}><Orb2 size={16} energy={tw.orbEnergy} state={busy ? "thinking" : "idle"} /><Mono size={8} color={mode === "Build" ? "var(--acc)" : "var(--mut)"}>{mode.toUpperCase()}</Mono></span>;

  if (route === "external" && fullApp && d) return (
    <>
      <ExternalScreen world={d} onBack={() => go("workspace")} mode={mode} onMode={(v) => setTweak("solMode", v)} approvals={approvals} onApprove={(id) => setApprovals((a) => ({ ...a, [id]: "approved" }))} onReject={onReject} energy={tw.orbEnergy} onToast={info} />
      <SolFloat open={floatOpen} at={floatAt} onClose={() => setFloatOpen(false)} thread={thread} onSend={(q) => sendFree(q, grab ? { grab } : null)} grab={grab} onGrab={() => setGrab(grab ? null : "Onshape — Part Studio 1 · Sketch 2")} mode={mode} />
      <ModeHud4 show={hud} mode={mode} />
      <V4Toast toast={toast} onClose={() => setToast(null)} />
      <V4Panel tw={tw} setTweak={setTweak} createProject={createProject} go={go} setAnomalyLive={setAnomalyLive} />
    </>);

  let body;
  if (!fullApp) body = (<div style={{ flex: 1, minHeight: 0, overflowY: "auto", display: "flex", flexDirection: "column" }}>{route === "signup" ? <SignupPage go={go} onAuth={() => { setAuthed(true); go("home"); }} /> : route === "login" ? <LoginPage go={go} onAuth={() => { setAuthed(true); go("home"); }} /> : <LandingPage go={go} />}</div>);
  else body = (
    <div style={{ flex: 1, display: "flex", minHeight: 0 }} onClick={() => { notifOpen && setNotifOpen(false); tabMenu && setTabMenu(null); }}>
      <RailNav tabs={TABS} cur={route} go={go} widgets={d ? d.tabs : pinned} pinned={pinned} energy={tw.orbEnergy} findings={d ? d.findings.length : 0} onSettings={() => go("settings")} onTabMenu={(e, w) => { e.preventDefault(); setTabMenu({ x: e.clientX, y: e.clientY, w }); }} />
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        {route !== "settings" && (
          <div style={{ height: 40, borderBottom: "1px solid var(--bd)", display: "flex", alignItems: "center", gap: 12, padding: "0 16px", flexShrink: 0, background: "var(--bg)" }}>
            <span style={{ fontSize: 12.5, fontWeight: 600, fontFamily: "var(--mono)" }}>{project ? project.name : "Solus"}</span>
            <span style={{ color: "var(--mut)", fontSize: 12 }}>/</span>
            <span style={{ fontSize: 12.5, color: "var(--mut)" }}>{route.startsWith("w:") ? V4.WIDGETS.find((x) => x.id === route.slice(2)).name + " · widget" : (TABS.find((t) => t[0] === route) || ["", ""])[1]}</span>
            {d && d.tabs.length > 0 && route.startsWith("w:") && <Mono size={8} color={pinned.includes(route.slice(2)) ? "var(--acc)" : "var(--mut)"}>{pinned.includes(route.slice(2)) ? "📌 PINNED FOR ALL PROJECTS" : "THIS PROJECT ONLY · RIGHT-CLICK ICON TO PIN"}</Mono>}
          </div>)}
        <div style={{ flex: 1, display: "flex", minHeight: 0, position: "relative" }}>
        {route === "home" && <HomeScreen4 projects={projects} currentId={curId} accounts={accounts} onOpen={openProject} onCreate={createProject} onArchive={(id, on) => setProjects((ps) => ps.map((x) => x.id === id ? { ...x, archived: on } : x))} onConnect={(id) => setAccounts((a) => [...new Set([...a, id])])} onDisconnect={(id) => setAccounts((a) => a.filter((x) => x !== id))} prefs={prefs} setPrefs={setPrefs} onToast={info} rootSolus={rootSolus} onRootSolus={(sec, e) => { setRootSolus((r) => ({ ...r, [sec]: [e, ...(r[sec] || [])] })); info("Added to ~/.solus › " + sec, "Applies to every project."); }} openSol={openSol} />}
        {route !== "home" && !d && <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}><div style={{ textAlign: "center", maxWidth: 380 }}><div style={{ fontSize: 15, fontWeight: 600 }}>No project open</div><div style={{ fontSize: 12.5, color: "var(--mut)", marginTop: 8, lineHeight: 1.6 }}>Create or open one from Home. A new project starts empty — that's deliberate.</div><div style={{ marginTop: 14 }}><Btn kind="primary" size="sm" onClick={() => go("home")}>Go to Home</Btn></div></div></div>}
        {d && route === "workspace" && <WorkspaceScreen4 d={d} accounts={accounts} act={act} sel={sel} setSel={setSel} openSol={openSol} onToast={info} goBench={() => go("bench")} />}
        {d && route === "bench" && <BenchScreen4 d={d} anomalyLive={anomalyLive} setAnomalyLive={setAnomalyLive} scope={sel ? { id: sel } : null} setScope={() => {}} openSol={openSol} telemSpeed={tw.telemSpeed} run={run} onRun={runTest} />}
        {d && route === "sol" && <SolTab d={d} chats={chats} cur={curChat} setCur={setCurChat} newChat={() => { const id = "c" + Date.now(); setChats((cs) => [{ id, title: "New chat", when: "now", msgs: [] }, ...cs]); setCurChat(id); }} thread={<>{thread}<SolInput onSend={(q) => sendFree(q)} mode={mode} /></>} mode={mode} setMode={(v) => setTweak("solMode", v)} energy={tw.orbEnergy} />}
        {d && route === "store" && <StoreScreen4 d={d} pinned={pinned} onInstall={act.install} onPin={(w) => setPinned((pn) => pn.includes(w) ? pn.filter((x) => x !== w) : [...pn, w])} onToast={info} />}
        {d && route === "w:bom" && <BomScreen d={d} act={act} openSol={openSol} onToast={info} />}
        {d && route.startsWith("w:") && route !== "w:bom" && <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--mut)", fontSize: 12.5 }}>{V4.WIDGETS.find((x) => x.id === route.slice(2)).name} — installed; its surface is stubbed in this prototype.</div>}
        {route === "settings" && <SettingsLayout section={settingsSection} setSection={setSettingsSection} tw={tw} setTweak={setTweak} connected={accounts.map((a) => a === "github" ? "github" : a === "kicad" ? "kicad" : a === "onshape" ? "onshape" : null).filter(Boolean)} onUpgrade={(pl) => info("Plans", pl && pl.id === "ent" ? "We'll reach out about Enterprise." : "Plan change scheduled for the next cycle.")} />}
        </div>
      </div>
    </div>);

  return (
    <div style={{ position: "fixed", inset: 0, background: "#05070a", display: "flex", fontFamily: "var(--ui)", color: "var(--tx)" }}>
      <div style={{ flex: 1, display: "flex", flexDirection: "column", background: "var(--bg)", color: "var(--tx)", fontFamily: "var(--ui)", overflow: "hidden" }}>
        <Titlebar minimal={!fullApp} onTraffic={(a) => (a === "close" ? setWindowState("closed") : a === "min" ? setWindowState("min") : null)} onCommand={() => setPaletteOpen(true)} onNav={(s) => { setSettingsSection(s || "preferences"); go("settings"); }} onAction={menuAction} onToggleTheme={() => setTweak("theme", tw.theme === "dark" ? "light" : "dark")} bell={<>{modeChip}{bell}</>} wsName={project ? project.name : "no project"} wsSub={project ? `${project.robots.length} robots · ${project.docs.length} docs` : "Home"} />
        {fullApp && <MenuBar menus={menus} onAction={menuAction} />}
        {body}
      </div>
      {tabMenu && <div style={{ position: "fixed", left: tabMenu.x, top: tabMenu.y, zIndex: 160, background: "var(--sur)", border: "1px solid var(--bd)", borderRadius: 6, boxShadow: "0 16px 44px rgba(0,0,0,0.5)", padding: 5, minWidth: 200 }} onClick={(e) => e.stopPropagation()}>
        {[[pinned.includes(tabMenu.w) ? "Unpin from all projects" : "Pin for all projects", () => setPinned((pn) => pn.includes(tabMenu.w) ? pn.filter((x) => x !== tabMenu.w) : [...pn, tabMenu.w])], ["Show in graph", () => { setSel("widget:" + tabMenu.w); go("workspace"); }], ["Uninstall", () => act.install(tabMenu.w, false)]].map(([l, fn]) => <div key={l} onClick={() => { setTabMenu(null); fn(); }} style={{ padding: "6px 9px", fontSize: 12.5, borderRadius: 4, cursor: "pointer", color: l === "Uninstall" ? "var(--err)" : "var(--tx)" }} onMouseEnter={(e) => (e.currentTarget.style.background = "var(--sur2)")} onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}>{l}</div>)}
        <div style={{ padding: "5px 9px 3px", fontSize: 9.5, color: "var(--mut)" }}>{pinned.includes(tabMenu.w) ? "Pinned: this tab shows in every project." : "Per-project unless pinned."}</div>
      </div>}
      {d && notifOpen && <div style={{ position: "fixed", top: 44, right: 14, width: 340, zIndex: 130 }} onClick={(e) => e.stopPropagation()}><Card pad={0} style={{ boxShadow: "0 16px 50px rgba(0,0,0,0.5)" }}><div style={{ padding: "11px 14px", borderBottom: "1px solid var(--bd)" }}><Mono size={9.5}>FINDINGS · {project.name}</Mono></div>{d.findings.length === 0 && <div style={{ padding: "18px 14px", fontSize: 12, color: "var(--mut)", lineHeight: 1.6 }}>Nothing right now. Findings appear when connected domains disagree.</div>}{d.findings.map((f) => <div key={f.key} onClick={() => { setNotifOpen(false); openSol(f.key); }} style={{ display: "flex", gap: 10, padding: "12px 14px", borderBottom: "1px solid var(--bd)", cursor: "pointer" }}><span style={{ color: "var(--err)" }}>{SI.warn({ size: 13 })}</span><div style={{ flex: 1 }}><div style={{ fontSize: 12, fontWeight: 600, lineHeight: 1.4 }}>{f.finding.title}</div><div style={{ fontSize: 10.5, color: "var(--mut)", marginTop: 2 }}>{f.finding.when}</div></div>{SI.arrowR({ size: 12 })}</div>)}</Card></div>}
      <V4Toast toast={toast} onClose={() => setToast(null)} />
      {d && <SolFloat open={floatOpen} at={floatAt} onClose={() => setFloatOpen(false)} thread={thread} onSend={(q) => sendFree(q, grab ? { grab } : null)} grab={grab} onGrab={() => setGrab(grab ? null : "Solus — " + (TABS.find((t) => t[0] === route) || ["", route])[1])} mode={mode} />}
      <ModeHud4 show={hud} mode={mode} />
      <CommandPalette open={paletteOpen} items={paletteItems} onClose={() => setPaletteOpen(false)} onRun={(it) => { setPaletteOpen(false); it.run(); }} />
      {modal === "about" && <AboutModal onClose={() => setModal(null)} />}
      <WindowSplash state={windowState} onReopen={() => setWindowState("open")} />
      <V4Panel tw={tw} setTweak={setTweak} createProject={createProject} go={go} setAnomalyLive={setAnomalyLive} />
    </div>);
}

function V4Toast({ toast, onClose }) {
  if (!toast) return null;
  return (<div className="toast-in" style={{ position: "fixed", top: 78, right: 22, width: 340, zIndex: 240 }}><Card pad={13} style={{ borderColor: "color-mix(in srgb, var(--ok) 40%, var(--bd))", boxShadow: "0 14px 44px rgba(0,0,0,0.55)", display: "flex", gap: 10, alignItems: "flex-start" }}><span style={{ color: "var(--ok)", marginTop: 1 }}>{SI.check({ size: 15 })}</span><div style={{ flex: 1 }}><div style={{ fontSize: 12.5, fontWeight: 600, lineHeight: 1.4 }}>{toast.title}</div>{toast.body && <div style={{ fontSize: 11.5, color: "var(--mut)", marginTop: 3, lineHeight: 1.5 }}>{toast.body}</div>}</div><span onClick={onClose} style={{ color: "var(--mut)", cursor: "pointer", padding: 2 }}>{SI.x({ size: 12 })}</span></Card></div>);
}
function V4Panel({ tw, setTweak, createProject, go, setAnomalyLive }) {
  const accentHexes = Object.keys(SolusAccents).map((k) => SolusAccents[k].c);
  return (
    <TweaksPanel>
      <TweakSection label="First-run paths (create project)" />
      <TweakButton label="ML researcher — lerobot-act-cube" onClick={() => createProject(null, "maya")} />
      <TweakButton label="Hobbyist — desk-arm-v1" onClick={() => createProject(null, "sam")} />
      <TweakButton label="FSAE lead — fsae-ev-2027" onClick={() => createProject(null, "priya")} />
      <TweakButton label="Empty project" onClick={() => createProject("untitled", null)} />
      <TweakSection label="SOL" />
      <TweakRadio label="Mode (Ctrl ×2)" value={tw.solMode} options={["Guide", "Build"]} onChange={(v) => setTweak("solMode", v)} />
      <TweakSlider label="Orb energy" value={tw.orbEnergy} min={10} max={100} onChange={(v) => setTweak("orbEnergy", v)} />
      <TweakSection label="Theme" />
      <TweakSelect label="Preset" value={tw.theme} options={Object.keys(SolusThemes).map((k) => ({ value: k, label: SolusThemes[k].name }))} onChange={(v) => setTweak("theme", v)} />
      <TweakColor label="Accent" value={SolusAccents[tw.accent].c} options={accentHexes} onChange={(v) => setTweak("accent", Object.keys(SolusAccents).find((k) => SolusAccents[k].c === v) || "amber")} />
      <TweakRadio label="Density" value={tw.density} options={["compact", "regular"]} onChange={(v) => setTweak("density", v)} />
      <TweakSection label="Bench" />
      <TweakSlider label="Telemetry speed" value={tw.telemSpeed} min={0.5} max={4} step={0.5} unit="×" onChange={(v) => setTweak("telemSpeed", v)} />
      <TweakButton label="Inject anomaly" onClick={() => { setAnomalyLive(true); go("bench"); }} />
      <TweakSection label="Prototype" />
      <TweakButton label="Outside Solus (Guide orb demo)" onClick={() => go("external")} />
      <TweakButton label="Reset to landing" onClick={() => window.__reset()} />
    </TweaksPanel>);
}
ReactDOM.createRoot(document.getElementById("root")).render(<V4App />);
