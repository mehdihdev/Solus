// Solus — App shell: desktop window, routing, rail, command palette, menus, tweaks
const { useState: useStateM, useEffect: useEffectM, useRef: useRefM, useMemo: useMemoM } = React;

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "theme": "dark",
  "accent": "amber",
  "density": "regular",
  "solMode": "Guide",
  "orbMode": "corner",
  "orbEnergy": 60,
  "telemSpeed": 1
}/*EDITMODE-END*/;

const PERSIST_KEY = "solus_proto_state_v1";
const SCREEN_TITLES = { graph: "Context Model", bench: "Live Bench", sol: "SOL", team: "Team", settings: "Settings", alert: "Alert" };
const MAIN_ROUTES = ["graph", "bench", "sol", "team", "settings"];

function loadPersisted() {
  try { return JSON.parse(localStorage.getItem(PERSIST_KEY)) || {}; } catch (e) { return {}; }
}
function routeToHash(r) {
  if (!r) return "#/graph";
  if (r.name === "settings") return "#/settings/" + (r.section || "profile");
  if (r.name === "alert") return "#/alert/" + (r.alertId || "a1");
  return "#/" + r.name;
}
function hashToRoute(h) {
  const parts = (h || "").replace(/^#\/?/, "").split("/").filter(Boolean);
  if (!parts.length) return null;
  if (parts[0] === "settings") return { name: "settings", section: parts[1] || "profile" };
  if (parts[0] === "alert") return { name: "alert", alertId: parts[1] || "a1" };
  return { name: parts[0] };
}

function RailBtn({ id, icon, label, active, onClick, badge }) {
  return (
    <div id={id} className="railbtn" onClick={onClick} style={{ position: "relative", width: 36, height: 36, borderRadius: 3, display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", background: active ? "color-mix(in srgb, var(--acc) 12%, transparent)" : "transparent", color: active ? "var(--acc)" : "var(--mut)" }}>
      {icon}
      {badge > 0 && <span style={{ position: "absolute", top: 2, right: 2, width: 7, height: 7, borderRadius: 99, background: "var(--err)" }}></span>}
      <span className="flyout">{label}</span>
    </div>
  );
}

function NotifPopover({ alerts, onOpen, onClose, windowed }) {
  return (
    <div style={{ position: "fixed", top: (windowed ? 14 : 0) + 44, right: (windowed ? 14 : 0) + 14, width: 350, zIndex: 130 }} onClick={(e) => e.stopPropagation()}>
      <Card pad={0} style={{ boxShadow: "0 16px 50px rgba(0,0,0,0.5)" }}>
        <div style={{ padding: "11px 14px", borderBottom: "1px solid var(--bd)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <Mono size={9.5}>NOTIFICATIONS</Mono>
          <span onClick={onClose} style={{ color: "var(--mut)", cursor: "pointer" }}>{SI.x({ size: 12 })}</span>
        </div>
        {alerts.map((a) => (
          <div key={a.id} id={"notif-" + a.id} onClick={() => onOpen(a.id)} style={{ display: "flex", gap: 10, padding: "12px 14px", borderBottom: "1px solid var(--bd)", cursor: "pointer", opacity: a.state === "resolved" ? 0.55 : 1 }}>
            <span style={{ color: a.state === "resolved" ? "var(--ok)" : a.sev === "critical" ? "var(--err)" : "var(--warn)", marginTop: 1 }}>
              {a.state === "resolved" ? SI.check({ size: 14 }) : SI.warn({ size: 14 })}
            </span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 12, fontWeight: 600, lineHeight: 1.4 }}>{a.title}</div>
              <div style={{ display: "flex", gap: 7, alignItems: "center", marginTop: 4 }}>
                <Mono size={8.5} color={dcol(a.fromD)}>{SolusDomains[a.fromD].label}</Mono>
                <span style={{ color: "var(--mut)", fontSize: 9 }}>→</span>
                <Mono size={8.5} color={dcol(a.toD)}>{SolusDomains[a.toD].label}</Mono>
                <span style={{ fontSize: 10, color: "var(--mut)", whiteSpace: "nowrap" }}>· {a.actor} · {a.time}</span>
              </div>
            </div>
            {SI.arrowR({ size: 12 })}
          </div>
        ))}
        <div style={{ padding: "10px 14px", fontSize: 10.5, color: "var(--mut)" }}>SOL checks every change across domains, automatically.</div>
      </Card>
    </div>
  );
}

function Toast({ toast, onView, onClose }) {
  if (!toast) return null;
  return (
    <div className="toast-in" style={{ position: "fixed", top: 80, right: 22, width: 360, zIndex: 140 }}>
      <Card pad={14} style={{ borderColor: toast.kind === "err" ? "color-mix(in srgb, var(--err) 50%, var(--bd))" : "color-mix(in srgb, var(--ok) 45%, var(--bd))", boxShadow: "0 14px 44px rgba(0,0,0,0.55)", display: "flex", gap: 11, alignItems: "flex-start" }}>
        <span style={{ color: toast.kind === "err" ? "var(--err)" : "var(--ok)", marginTop: 1 }} className={toast.kind === "err" ? "gm-orb" : ""}>{toast.kind === "err" ? SI.warn({ size: 16 }) : toast.icon === "info" ? SI.sol({ size: 16 }) : SI.check({ size: 16 })}</span>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 12.5, fontWeight: 600, lineHeight: 1.4 }}>{toast.title}</div>
          {toast.body && <div style={{ fontSize: 11.5, color: "var(--mut)", marginTop: 3, lineHeight: 1.5 }}>{toast.body}</div>}
          {toast.action && <Btn kind="primary" size="sm" style={{ marginTop: 10 }} onClick={onView}>{toast.action}</Btn>}
        </div>
        <span onClick={onClose} style={{ color: "var(--mut)", cursor: "pointer", padding: 2 }}>{SI.x({ size: 12 })}</span>
      </Card>
    </div>
  );
}

function App() {
  const [tw, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const p = useRefM(loadPersisted()).current;
  const initRoute = (() => { const h = hashToRoute(location.hash); return h || p.route || { name: "landing" }; })();
  const [route, setRoute] = useStateM(initRoute);
  const [authed, setAuthed] = useStateM(!!p.authed);
  const [onboarded, setOnboarded] = useStateM(!!p.onboarded);
  const [connected, setConnected] = useStateM(p.connected || []);
  const [resolved, setResolved] = useStateM(p.resolved || {});
  const [anomaly, setAnomaly] = useStateM(p.anomaly || "none");
  const [toastShown, setToastShown] = useStateM(!!p.toastShown);
  const [toast, setToast] = useStateM(null);
  const [notifOpen, setNotifOpen] = useStateM(false);
  const [chat, setChat] = useStateM([]);
  const [tour, setTour] = useStateM(null);
  const [lastMain, setLastMain] = useStateM("graph");
  const [windowState, setWindowState] = useStateM("open"); // open | closed | min
  const [windowed, setWindowed] = useStateM(false);
  const [paletteOpen, setPaletteOpen] = useStateM(false);
  const [modal, setModal] = useStateM(null); // about | shortcuts
  const [focusNode, setFocusNode] = useStateM(null);
  const [modeHud, setModeHud] = useStateM(false);

  const fullApp = authed && onboarded;

  useEffectM(() => { applySolusTheme(tw.theme, tw.accent, tw.density); }, [tw.theme, tw.accent, tw.density]);
  useEffectM(() => {
    localStorage.setItem(PERSIST_KEY, JSON.stringify({ route, authed, onboarded, connected, resolved, anomaly, toastShown }));
  }, [route, authed, onboarded, connected, resolved, anomaly, toastShown]);
  // mirror route → hash
  useEffectM(() => { const h = routeToHash(route); if (location.hash !== h) location.hash = h; }, [route]);
  // hash (back/forward) → route
  useEffectM(() => {
    const onHash = () => { const r = hashToRoute(location.hash); if (r) setRoute((cur) => routeToHash(cur) === routeToHash(r) ? cur : r); };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  useEffectM(() => { if (toast && !toast.action) { const t = setTimeout(() => setToast(null), 3200); return () => clearTimeout(t); } }, [toast]);

  const alerts = ALERTS.map((a) => (resolved[a.id] ? { ...a, state: "resolved" } : a));
  const openCount = alerts.filter((a) => a.state === "open").length;

  const go = (name, extra) => {
    if (MAIN_ROUTES.includes(name)) setLastMain(name);
    setRoute({ name, ...extra });
    setNotifOpen(false); setPaletteOpen(false);
  };
  const navSettings = (section) => go("settings", { section });
  const setSection = (section) => setRoute({ name: "settings", section });
  const info = (title, body) => setToast({ kind: "ok", icon: "info", title, body });
  const toggleTheme = () => setTweak("theme", tw.theme === "dark" ? "light" : "dark");

  const onAuth = (email, returning) => {
    setAuthed(true);
    if (returning) { setOnboarded(true); setConnected(["github", "kicad", "onshape", "ros"]); go("graph"); }
    else go("onboarding");
  };
  const completeOnboarding = (conn) => { setOnboarded(true); setConnected(conn); go("graph"); };
  const openAlert = (id) => go("alert", { alertId: id });
  const askSol = (key) => {
    go("sol");
    const s = SOL_SCRIPTS[key];
    if (s && !chat.some((m) => m.role === "user" && m.text === s.q)) {
      setTimeout(() => {
        setChat((c) => [...c, { role: "user", text: s.q }]);
        setTimeout(() => setChat((c) => [...c, { role: "sol", key }]), 1700);
      }, 350);
    }
  };

  useEffectM(() => {
    if (!fullApp || toastShown || route.name !== "graph") return;
    const t = setTimeout(() => {
      setToast({ title: "SOL caught a cross-domain break", body: "Priya swapped U4 (DRV8833 → DRV8316C) 2h ago — it breaks the pin map in 3 firmware files.", action: "View alert", alertId: "a1" });
      setToastShown(true);
    }, 5000);
    return () => clearTimeout(t);
  }, [fullApp, toastShown, route.name]);

  const startTour = () => {
    setNotifOpen(false);
    const steps = [
      { target: "#rail-bell", text: "Alerts live here. The red badge means SOL found something that crosses domains. Let me open it for you.", action: "click" },
      { target: "#notif-a1", text: "This is the catch — Priya's U4 swap on the PCB silently breaks your firmware. Click through to see the full trace.", action: "click" },
      resolved.a1
        ? { target: "#rail-bench", text: "This one's already resolved — the patch is merged. Next time something breaks, you'll see it live on the Bench here.", action: null }
        : { target: "#btn-apply-fix", text: "SOL prepared the patch already — review the diff above, then apply it from here. It opens a PR, so nothing lands unreviewed.", action: null },
    ];
    setTour({ steps, idx: 0, advance: () => setTour((tr) => ({ ...tr, idx: tr.idx + 1 })) });
  };

  const flashDone = () => { setResolved((r) => ({ ...r, a1: true })); setAnomaly("resolved"); };
  const hudTimer = useRefM(null);
  const toggleCompanion = () => {
    setTweak("orbMode", tw.orbMode === "follow" ? "corner" : "follow");
    setModeHud(true);
    clearTimeout(hudTimer.current);
    hudTimer.current = setTimeout(() => setModeHud(false), 1800);
  };
  const jump = (v) => {
    if (MAIN_ROUTES.includes(v)) {
      setAuthed(true); setOnboarded(true);
      if (connected.length === 0) setConnected(["github", "kicad", "onshape", "ros"]);
    } else { setAuthed(false); setOnboarded(false); }
    go(v);
  };
  const signOut = () => { setAuthed(false); setNotifOpen(false); go("login"); };
  const focusGraphNode = (id) => { setFocusNode({ id, n: Date.now() }); go("graph"); };

  /* ---------- traffic lights ---------- */
  const onTraffic = (action) => {
    if (action === "close") setWindowState("closed");
    else if (action === "min") setWindowState("min");
    else setWindowed((w) => !w);
  };

  /* ---------- menus ---------- */
  const menus = [
    { id: "solus", label: "Solus", items: [
      { id: "about", label: "About Solus" }, { sep: true },
      { id: "prefs", label: "Preferences…", kbd: "⌘," }, { id: "checkupd", label: "Check for Updates…" }, { sep: true },
      { id: "signout", label: "Sign Out" }, { id: "quit", label: "Quit Solus", kbd: "⌘Q" },
    ] },
    { id: "file", label: "File", items: [
      { id: "newproject", label: "New Project…", kbd: "⌘N" }, { sep: true },
      { id: "c-github", label: "Connect GitHub" }, { id: "c-kicad", label: "Connect KiCad" }, { id: "c-onshape", label: "Connect Onshape" }, { id: "c-ros", label: "Connect ROS 2" }, { sep: true },
      { id: "import", label: "Import…", disabled: true }, { id: "export", label: "Export Context Model…" },
    ] },
    { id: "edit", label: "Edit", items: [
      { id: "undo", label: "Undo", kbd: "⌘Z", disabled: true }, { id: "redo", label: "Redo", kbd: "⇧⌘Z", disabled: true }, { sep: true },
      { id: "cut", label: "Cut", kbd: "⌘X", disabled: true }, { id: "copy", label: "Copy", kbd: "⌘C", disabled: true }, { id: "paste", label: "Paste", kbd: "⌘V", disabled: true }, { sep: true },
      { id: "find", label: "Find in Graph", kbd: "⌘F" },
    ] },
    { id: "view", label: "View", items: [
      { id: "view-graph", label: "Context Model", kbd: "⌘1" }, { id: "view-bench", label: "Live Bench", kbd: "⌘2" }, { id: "view-sol", label: "SOL", kbd: "⌘3" }, { id: "view-team", label: "Team", kbd: "⌘4" }, { sep: true },
      { id: "toggle-theme", label: "Toggle Theme", kbd: "⌘\\" }, { id: "toggle-density", label: "Toggle Density", kbd: "⌘B" },
    ] },
    { id: "robot", label: "Robot", items: [
      { id: "run-bench", label: "Run Bench (Sim)" }, { id: "connect-hw", label: "Connect Hardware…" }, { id: "inject", label: "Inject Anomaly" }, { sep: true },
      { id: "flash", label: "Flash Firmware…", disabled: true },
    ] },
    { id: "help", label: "Help", items: [
      { id: "docs", label: "Documentation" }, { id: "shortcuts", label: "Keyboard Shortcuts", kbd: "?" }, { sep: true }, { id: "support", label: "Contact Support" },
    ] },
  ];
  const menuAction = (id) => {
    if (id === "about") setModal("about");
    else if (id === "prefs") navSettings("preferences");
    else if (id === "checkupd") info("You're up to date", "Solus 0.9.0 is the latest version.");
    else if (id === "signout") signOut();
    else if (id === "quit") setWindowState("closed");
    else if (id === "newproject") info("New project", "Project creation is stubbed in this prototype.");
    else if (id.startsWith("c-")) { navSettings("integrations"); }
    else if (id === "import" || id === "export") info(id === "export" ? "Exporting context model…" : "Import", "Stubbed in this prototype.");
    else if (id === "find") setPaletteOpen(true);
    else if (id === "view-graph") go("graph");
    else if (id === "view-bench") go("bench");
    else if (id === "view-sol") go("sol");
    else if (id === "view-team") go("team");
    else if (id === "toggle-theme") toggleTheme();
    else if (id === "toggle-density") setTweak("density", tw.density === "regular" ? "compact" : "regular");
    else if (id === "run-bench") go("bench");
    else if (id === "connect-hw") { go("bench"); info("Connect hardware", "Switch the bench to Real mode to pair a device."); }
    else if (id === "inject") { setAnomaly("active"); go("bench"); }
    else if (id === "docs" || id === "support") info(id === "docs" ? "Opening documentation…" : "Contact support", "Stubbed in this prototype.");
    else if (id === "shortcuts") setModal("shortcuts");
  };

  /* ---------- command palette items ---------- */
  const paletteItems = useMemoM(() => {
    const pages = [
      { id: "p-graph", label: "Context Model", section: "page", kbd: "⌘1", icon: SI.graph({ size: 13 }), run: () => go("graph") },
      { id: "p-bench", label: "Live Bench", section: "page", kbd: "⌘2", icon: SI.bench({ size: 13 }), run: () => go("bench") },
      { id: "p-sol", label: "SOL", section: "page", kbd: "⌘3", icon: SI.sol({ size: 13 }), run: () => go("sol") },
      { id: "p-team", label: "Team", section: "page", kbd: "⌘4", icon: SI.team({ size: 13 }), run: () => go("team") },
      { id: "p-profile", label: "Profile", section: "settings", icon: SI.user({ size: 13 }), run: () => navSettings("profile") },
      { id: "p-prefs", label: "Preferences", section: "settings", kbd: "⌘,", icon: SI.sliders({ size: 13 }), run: () => navSettings("preferences") },
      { id: "p-model", label: "Model configuration", section: "settings", icon: SI.bolt({ size: 13 }), run: () => navSettings("model") },
      { id: "p-billing", label: "Billing & plan", section: "settings", icon: SI.card({ size: 13 }), run: () => navSettings("billing") },
      { id: "p-integrations", label: "Integrations", section: "settings", icon: SI.link({ size: 13 }), run: () => navSettings("integrations") },
      { id: "p-members", label: "Members", section: "settings", icon: SI.team({ size: 13 }), run: () => navSettings("members") },
    ];
    const actions = [
      { id: "a-tour", label: "Show me how to investigate the U4 alert", section: "action", kw: "tour sol guide", icon: SI.bolt({ size: 13 }), run: () => { go("sol"); setTimeout(startTour, 200); } },
      { id: "a-inject", label: "Inject bench anomaly", section: "action", kw: "anomaly fault", icon: SI.warn({ size: 13 }), run: () => { setAnomaly("active"); go("bench"); } },
      { id: "a-theme", label: "Toggle theme", section: "action", kbd: "⌘\\", icon: SI.monitor({ size: 13 }), run: toggleTheme, primary: false },
      { id: "a-density", label: "Toggle density", section: "action", kbd: "⌘B", icon: SI.sliders({ size: 13 }), run: () => setTweak("density", tw.density === "regular" ? "compact" : "regular"), primary: false },
      { id: "a-invite", label: "Invite a teammate", section: "action", icon: SI.plus({ size: 13 }), run: () => go("team"), primary: false },
      { id: "a-about", label: "About Solus", section: "action", icon: SI.sol({ size: 13 }), run: () => setModal("about"), primary: false },
      { id: "a-shortcuts", label: "Keyboard shortcuts", section: "action", kbd: "?", icon: SI.cmd({ size: 13 }), run: () => setModal("shortcuts"), primary: false },
      { id: "a-signout", label: "Sign out", section: "action", icon: SI.x({ size: 13 }), run: signOut, primary: false },
    ];
    const nodes = GRAPH.nodes.map((n) => ({ id: "n-" + n.id, label: n.l, section: "node", dot: dcol(n.d), kw: n.type + " " + n.sub, primary: false, run: () => focusGraphNode(n.id) }));
    return [...pages, ...actions, ...nodes];
  }, [tw.density, tw.theme, resolved]);

  /* ---------- keyboard ---------- */
  useEffectM(() => {
    const handler = (e) => {
      const mod = e.metaKey || e.ctrlKey;
      const typing = /^(INPUT|TEXTAREA|SELECT)$/.test((e.target && e.target.tagName) || "");
      if (mod && e.key.toLowerCase() === "k") { e.preventDefault(); setPaletteOpen((o) => !o); }
      else if (mod && e.key === ",") { e.preventDefault(); if (fullApp) navSettings("preferences"); }
      else if (mod && e.key === "\\") { e.preventDefault(); toggleTheme(); }
      else if (mod && e.key.toLowerCase() === "b" && fullApp) { e.preventDefault(); setTweak("density", tw.density === "regular" ? "compact" : "regular"); }
      else if (mod && ["1", "2", "3", "4"].includes(e.key) && fullApp) { e.preventDefault(); go(["graph", "bench", "sol", "team"][+e.key - 1]); }
      else if (e.key === "?" && !typing && fullApp) { setModal("shortcuts"); }
      else if (e.key === "Control" && !e.repeat && fullApp) { e.preventDefault(); toggleCompanion(); }
      else if (e.key === "Escape") { setPaletteOpen(false); setModal(null); setNotifOpen(false); }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [fullApp, tw.theme, tw.density, tw.orbMode]);

  /* ---------- chrome pieces ---------- */
  const name = route.name;
  const bellNode = (
    <div id="rail-bell" onClick={(e) => { e.stopPropagation(); setNotifOpen(!notifOpen); }} style={{ position: "relative", cursor: "pointer", padding: 4, color: "var(--mut)", display: fullApp ? "inline-flex" : "none" }}>
      {SI.bell({ size: 16 })}
      {openCount > 0 && <span style={{ position: "absolute", top: -2, right: -3, minWidth: 13, height: 13, borderRadius: 99, background: "var(--err)", color: "#fff", fontSize: 8.5, fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center" }}>{openCount}</span>}
    </div>
  );

  const desktopBg = "#05070a";
  const windowChrome = (
    <>
      <Titlebar minimal={!fullApp} onTraffic={onTraffic} onCommand={() => setPaletteOpen(true)} onNav={navSettings}
        onAction={menuAction} themeIsDark={tw.theme === "dark"} onToggleTheme={toggleTheme} bell={bellNode} />
      {fullApp && <MenuBar menus={menus} onAction={menuAction} />}
    </>
  );

  /* ---------- pre-app ---------- */
  let body;
  if (!fullApp) {
    body = (
      <div style={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
        {name === "landing" && <LandingPage go={go} />}
        {name === "signup" && <SignupPage go={go} onAuth={onAuth} />}
        {name === "login" && <LoginPage go={go} onAuth={onAuth} />}
        {name === "onboarding" && <Onboarding onComplete={completeOnboarding} />}
        {!["landing", "signup", "login", "onboarding"].includes(name) && <LandingPage go={go} />}
      </div>
    );
  } else {
    const alert = name === "alert" ? alerts.find((a) => a.id === route.alertId) : null;
    body = (
      <div style={{ flex: 1, display: "flex", minHeight: 0 }} onClick={() => notifOpen && setNotifOpen(false)}>
        {/* rail */}
        <div style={{ width: 56, borderRight: "1px solid var(--bd)", display: "flex", flexDirection: "column", alignItems: "center", padding: "14px 0", gap: 8, flexShrink: 0, background: "var(--sur)" }}>
          <div onClick={() => go("graph")} style={{ marginBottom: 12, cursor: "pointer" }}><SolHammer size={28} energy={tw.orbEnergy} /></div>
          <RailBtn id="rail-graph" icon={SI.graph({ size: 17 })} label="Context Model" active={name === "graph" || name === "alert"} onClick={() => go("graph")} />
          <RailBtn id="rail-bench" icon={SI.bench({ size: 17 })} label="Live Bench" active={name === "bench"} onClick={() => go("bench")} badge={anomaly === "active" ? 1 : 0} />
          <RailBtn id="rail-sol" icon={SI.sol({ size: 17 })} label="SOL" active={name === "sol"} onClick={() => go("sol")} />
          <RailBtn id="rail-team" icon={SI.team({ size: 17 })} label="Team" active={name === "team"} onClick={() => go("team")} />
          <div style={{ flex: 1 }}></div>
          <RailBtn id="rail-settings" icon={SI.gear({ size: 17 })} label="Settings" active={name === "settings"} onClick={() => navSettings("profile")} />
          <div style={{ marginTop: 4, cursor: "pointer" }} onClick={() => navSettings("profile")}><Avatar name="Maya Krishnan" size={26} /></div>
        </div>

        {/* main column */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, position: "relative" }}>
          {name !== "settings" && (
            <div style={{ height: 40, borderBottom: "1px solid var(--bd)", display: "flex", alignItems: "center", gap: 12, padding: "0 16px", flexShrink: 0, background: "var(--bg)" }}>
              <span style={{ fontSize: 12.5, fontWeight: 600 }}>strider-qd12</span>
              <span style={{ color: "var(--mut)", fontSize: 12 }}>/</span>
              <span style={{ fontSize: 12.5, color: "var(--mut)" }}>{SCREEN_TITLES[name] || ""}</span>
            </div>
          )}
          <div data-screen-label={SCREEN_TITLES[name]} style={{ flex: 1, display: "flex", minHeight: 0, position: "relative" }}>
            {name === "graph" && <GraphScreen alerts={alerts} onOpenAlert={openAlert} onAskSol={askSol} focus={focusNode} />}
            {name === "bench" && <BenchScreen anomaly={anomaly} telemSpeed={tw.telemSpeed} onTriggerAnomaly={() => setAnomaly("active")} onAskSol={askSol} />}
            {name === "sol" && <SolScreen solMode={tw.solMode} setSolMode={(v) => setTweak("solMode", v)} chat={chat} setChat={setChat} orbEnergy={tw.orbEnergy} onFlashDone={flashDone} onStartTour={startTour} />}
            {name === "team" && <TeamScreen onOpenAlert={openAlert} />}
            {name === "settings" && <SettingsLayout section={route.section || "profile"} setSection={setSection} tw={tw} setTweak={setTweak} connected={connected} onUpgrade={(pl) => pl.id === "ent" ? info("Contact sales", "We'll reach out about Enterprise.") : pl.id === "solo" ? info("Downgrade scheduled", "You'll move to Solo at the end of the cycle.") : null} />}
            {name === "alert" && alert && <AlertScreen key={alert.id} alert={alert} solMode={tw.solMode} onBack={() => go(lastMain === "settings" ? "graph" : lastMain)} onResolved={(id) => setResolved((r) => ({ ...r, [id]: true }))} onIssue={(a) => info(`Issue #144 created in ${a.issue.repo}`, "Linked to this alert with the full cross-domain trace.")} onAskSol={askSol} />}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div style={{ position: "fixed", inset: 0, background: desktopBg, display: "flex" }}>
      <div style={{ flex: 1, margin: windowed ? 14 : 0, borderRadius: windowed ? 10 : 0, overflow: "hidden", display: "flex", flexDirection: "column", background: "var(--bg)", color: "var(--tx)", fontFamily: "var(--ui)", border: windowed ? "1px solid var(--bd)" : "none", boxShadow: windowed ? "0 30px 90px rgba(0,0,0,0.6)" : "none", transition: "margin 0.2s, border-radius 0.2s" }}>
        {windowChrome}
        {body}
      </div>

      {fullApp && notifOpen && <NotifPopover alerts={alerts} onOpen={openAlert} onClose={() => setNotifOpen(false)} windowed={windowed} />}
      <Toast toast={toast} onView={() => { if (toast.alertId) openAlert(toast.alertId); setToast(null); }} onClose={() => setToast(null)} />
      {fullApp && <SolCompanion mode={tw.orbMode} energy={tw.orbEnergy} hidden={name === "sol" || !!tour || paletteOpen || windowState !== "open"} onClick={() => go("sol")} />}
      <ModeHud show={!!modeHud} mode={tw.orbMode} />
      {tour && <GuideTour tour={tour} onEnd={() => setTour(null)} energy={tw.orbEnergy} />}
      <CommandPalette open={paletteOpen} items={paletteItems} onClose={() => setPaletteOpen(false)} onRun={(it) => { setPaletteOpen(false); it.run(); }} />
      {modal === "about" && <AboutModal onClose={() => setModal(null)} />}
      {modal === "shortcuts" && <ShortcutsModal onClose={() => setModal(null)} />}
      <WindowSplash state={windowState} onReopen={() => setWindowState("open")} />
      <PrototypePanel tw={tw} setTweak={setTweak} jump={jump} anomalySet={setAnomaly} navSettings={fullApp ? navSettings : null} openPalette={() => setPaletteOpen(true)} />
    </div>
  );
}

/* ---------- Tweaks ---------- */
function PrototypePanel({ tw, setTweak, jump, anomalySet, navSettings, openPalette }) {
  const accentHexes = Object.keys(SolusAccents).map((k) => SolusAccents[k].c);
  const hexToKey = (hex) => Object.keys(SolusAccents).find((k) => SolusAccents[k].c === hex) || "amber";
  return (
    <TweaksPanel>
      <TweakSection label="Theme" />
      <TweakSelect label="Preset" value={tw.theme} options={Object.keys(SolusThemes).map((k) => ({ value: k, label: SolusThemes[k].name }))} onChange={(v) => setTweak("theme", v)} />
      <TweakColor label="Accent" value={SolusAccents[tw.accent].c} options={accentHexes} onChange={(v) => setTweak("accent", hexToKey(v))} />
      <TweakRadio label="Density" value={tw.density} options={["compact", "regular"]} onChange={(v) => setTweak("density", v)} />
      <TweakSection label="SOL" />
      <TweakRadio label="Answer mode" value={tw.solMode} options={["Guide", "Expert"]} onChange={(v) => setTweak("solMode", v)} />
      <TweakRadio label="Companion (Ctrl)" value={tw.orbMode} options={["corner", "follow"]} onChange={(v) => setTweak("orbMode", v)} />
      <TweakSlider label="Core energy" value={tw.orbEnergy} min={10} max={100} onChange={(v) => setTweak("orbEnergy", v)} />
      <TweakSection label="Bench" />
      <TweakSlider label="Telemetry speed" value={tw.telemSpeed} min={0.5} max={4} step={0.5} unit="×" onChange={(v) => setTweak("telemSpeed", v)} />
      <TweakButton label="Inject anomaly" onClick={() => { anomalySet("active"); jump("bench"); }} />
      <TweakSection label="Prototype" />
      <TweakButton label="Open command palette (⌘K)" onClick={openPalette} />
      {navSettings && <TweakButton label="Go to Billing" onClick={() => navSettings("billing")} />}
      <TweakSelect label="Jump to" value="" options={["", "landing", "signup", "login", "graph", "bench", "sol", "team", "settings"]} onChange={(v) => v && jump(v)} />
      <TweakButton label="Reset walkthrough" onClick={() => { localStorage.removeItem(PERSIST_KEY); location.hash = ""; location.reload(); }} />
    </TweaksPanel>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
