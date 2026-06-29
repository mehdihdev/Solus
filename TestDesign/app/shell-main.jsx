// Solus — App shell: routing, rail, topbar, notifications, toasts, tour, tweaks
const { useState: useStateM, useEffect: useEffectM, useRef: useRefM } = React;

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

function loadPersisted() {
  try { return JSON.parse(localStorage.getItem(PERSIST_KEY)) || {}; } catch (e) { return {}; }
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

function NotifPopover({ alerts, onOpen, onClose }) {
  return (
    <div style={{ position: "absolute", top: 46, right: 12, width: 350, zIndex: 50 }} onClick={(e) => e.stopPropagation()}>
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
    <div className="toast-in" style={{ position: "fixed", top: 58, right: 16, width: 360, zIndex: 75 }}>
      <Card pad={14} style={{ borderColor: toast.kind === "ok" ? "color-mix(in srgb, var(--ok) 45%, var(--bd))" : "color-mix(in srgb, var(--err) 50%, var(--bd))", boxShadow: "0 14px 44px rgba(0,0,0,0.55)", display: "flex", gap: 11, alignItems: "flex-start" }}>
      <span style={{ color: toast.kind === "ok" ? "var(--ok)" : "var(--err)", marginTop: 1 }} className={toast.kind === "ok" ? "" : "gm-orb"}>{toast.kind === "ok" ? SI.check({ size: 16 }) : SI.warn({ size: 16 })}</span>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 12.5, fontWeight: 600, lineHeight: 1.4 }}>{toast.title}</div>
          <div style={{ fontSize: 11.5, color: "var(--mut)", marginTop: 3, lineHeight: 1.5 }}>{toast.body}</div>
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
  const [route, setRoute] = useStateM(p.route || { name: "landing" });
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

  useEffectM(() => { applySolusTheme(tw.theme, tw.accent, tw.density); }, [tw.theme, tw.accent, tw.density]);
  useEffectM(() => {
    localStorage.setItem(PERSIST_KEY, JSON.stringify({ route, authed, onboarded, connected, resolved, anomaly, toastShown }));
  }, [route, authed, onboarded, connected, resolved, anomaly, toastShown]);

  const alerts = ALERTS.map((a) => (resolved[a.id] ? { ...a, state: "resolved" } : a));
  const openCount = alerts.filter((a) => a.state === "open").length;

  const go = (name, extra) => {
    if (["graph", "bench", "sol", "team", "settings"].includes(name)) setLastMain(name);
    setRoute({ name, ...extra });
    setNotifOpen(false);
  };
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

  // magic-moment toast: fires shortly after first landing in the workspace
  useEffectM(() => {
    if (!onboarded || toastShown || route.name !== "graph") return;
    const t = setTimeout(() => {
      setToast({ title: "SOL caught a cross-domain break", body: "Priya swapped U4 (DRV8833 → DRV8316C) 2h ago — it breaks the pin map in 3 firmware files.", action: "View alert", alertId: "a1" });
      setToastShown(true);
    }, 5000);
    return () => clearTimeout(t);
  }, [onboarded, toastShown, route.name]);

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
  const jump = (v) => {
    if (["graph", "bench", "sol", "team", "settings"].includes(v)) {
      setAuthed(true); setOnboarded(true);
      if (connected.length === 0) setConnected(["github", "kicad", "onshape", "ros"]);
    } else { setAuthed(false); setOnboarded(false); }
    go(v);
  };

  /* ---------- pre-app routes ---------- */
  if (!authed || !onboarded) {
    return (
      <>
        {route.name === "landing" && <LandingPage go={go} />}
        {route.name === "signup" && <SignupPage go={go} onAuth={onAuth} />}
        {route.name === "login" && <LoginPage go={go} onAuth={onAuth} />}
        {route.name === "onboarding" && <Onboarding onComplete={completeOnboarding} />}
        {!["landing", "signup", "login", "onboarding"].includes(route.name) && <LandingPage go={go} />}
        <PrototypePanel tw={tw} setTweak={setTweak} jump={jump} anomalySet={setAnomaly} />
      </>
    );
  }

  /* ---------- app shell ---------- */
  const name = route.name;
  const alert = name === "alert" ? alerts.find((a) => a.id === route.alertId) : null;

  return (
    <div style={{ height: "100vh", display: "flex", background: "var(--bg)", color: "var(--tx)", fontFamily: "var(--ui)", overflow: "hidden" }} onClick={() => notifOpen && setNotifOpen(false)}>
      {/* rail */}
      <div style={{ width: 56, borderRight: "1px solid var(--bd)", display: "flex", flexDirection: "column", alignItems: "center", padding: "14px 0", gap: 8, flexShrink: 0, background: "var(--sur)" }}>
        <div onClick={() => go("graph")} style={{ marginBottom: 12, cursor: "pointer" }}><SolOrb size={24} energy={tw.orbEnergy} /></div>
        <RailBtn id="rail-graph" icon={SI.graph({ size: 17 })} label="Context Model" active={name === "graph" || name === "alert"} onClick={() => go("graph")} />
        <RailBtn id="rail-bench" icon={SI.bench({ size: 17 })} label="Live Bench" active={name === "bench"} onClick={() => go("bench")} badge={anomaly === "active" ? 1 : 0} />
        <RailBtn id="rail-sol" icon={SI.sol({ size: 17 })} label="SOL" active={name === "sol"} onClick={() => go("sol")} />
        <RailBtn id="rail-team" icon={SI.team({ size: 17 })} label="Team" active={name === "team"} onClick={() => go("team")} />
        <div style={{ flex: 1 }}></div>
        <RailBtn id="rail-settings" icon={SI.gear({ size: 17 })} label="Settings" active={name === "settings"} onClick={() => go("settings")} />
        <div style={{ marginTop: 4 }}><Avatar name="Maya Krishnan" size={26} /></div>
      </div>

      {/* main column */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, position: "relative" }}>
        {/* topbar */}
        <div style={{ height: 48, borderBottom: "1px solid var(--bd)", display: "flex", alignItems: "center", gap: 14, padding: "0 16px", flexShrink: 0, position: "relative", zIndex: 40, background: "var(--bg)" }}>
          <span style={{ fontSize: 13, fontWeight: 600 }}>strider-qd12</span>
          <span style={{ color: "var(--mut)", fontSize: 12 }}>/</span>
          <span style={{ fontSize: 13, color: "var(--mut)" }}>{SCREEN_TITLES[name] || ""}</span>
          <div style={{ flex: 1 }}></div>
          <div style={{ width: 280, background: "var(--sur)", border: "1px solid var(--bd)", borderRadius: 3, padding: "6px 11px", display: "flex", justifyContent: "space-between", alignItems: "center", color: "var(--mut)" }}>
            <span style={{ fontSize: 12, display: "inline-flex", gap: 8, alignItems: "center" }}>{SI.search({ size: 12 })} Search nodes, nets, files…</span>
            <Mono size={9.5} style={{ textTransform: "none" }}>⌘K</Mono>
          </div>
          <div id="rail-bell" onClick={(e) => { e.stopPropagation(); setNotifOpen(!notifOpen); }} style={{ position: "relative", cursor: "pointer", padding: 6, color: "var(--mut)" }}>
            {SI.bell({ size: 17 })}
            {openCount > 0 && <span style={{ position: "absolute", top: 0, right: -2, minWidth: 14, height: 14, borderRadius: 99, background: "var(--err)", color: "#fff", fontSize: 9, fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center" }}>{openCount}</span>}
          </div>
        </div>
        {notifOpen && <NotifPopover alerts={alerts} onOpen={openAlert} onClose={() => setNotifOpen(false)} />}

        {/* screen */}
        <div data-screen-label={SCREEN_TITLES[name]} style={{ flex: 1, display: "flex", minHeight: 0, position: "relative" }}>
          {name === "graph" && <GraphScreen alerts={alerts} onOpenAlert={openAlert} onAskSol={askSol} />}
          {name === "bench" && <BenchScreen anomaly={anomaly} telemSpeed={tw.telemSpeed} onTriggerAnomaly={() => setAnomaly("active")} onAskSol={askSol} />}
          {name === "sol" && <SolScreen solMode={tw.solMode} setSolMode={(v) => setTweak("solMode", v)} chat={chat} setChat={setChat} orbEnergy={tw.orbEnergy} onFlashDone={flashDone} onStartTour={startTour} />}
          {name === "team" && <TeamScreen onOpenAlert={openAlert} />}
          {name === "settings" && <SettingsScreen tw={tw} setTweak={setTweak} connected={connected} />}
          {name === "alert" && alert && <AlertScreen key={alert.id} alert={alert} solMode={tw.solMode} onBack={() => go(lastMain)} onResolved={(id) => setResolved((r) => ({ ...r, [id]: true }))} onIssue={(a) => setToast({ kind: "ok", title: `Issue #144 created in ${a.issue.repo}`, body: "Linked to this alert with the full cross-domain trace attached." })} onAskSol={askSol} />}
        </div>
      </div>

      <Toast toast={toast} onView={() => { if (toast.alertId) openAlert(toast.alertId); setToast(null); }} onClose={() => setToast(null)} />
      <MiniOrb orbMode={tw.orbMode} energy={tw.orbEnergy} hidden={name === "sol" || !!tour} onClick={() => go("sol")} />
      {tour && <GuideTour tour={tour} onEnd={() => setTour(null)} energy={tw.orbEnergy} />}
      <PrototypePanel tw={tw} setTweak={setTweak} jump={jump} anomalySet={setAnomaly} />
    </div>
  );
}

/* ---------- Tweaks ---------- */
function PrototypePanel({ tw, setTweak, jump, anomalySet }) {
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
      <TweakRadio label="Orb behavior" value={tw.orbMode} options={["corner", "follow"]} onChange={(v) => setTweak("orbMode", v)} />
      <TweakSlider label="Orb energy" value={tw.orbEnergy} min={10} max={100} onChange={(v) => setTweak("orbEnergy", v)} />
      <TweakSection label="Bench" />
      <TweakSlider label="Telemetry speed" value={tw.telemSpeed} min={0.5} max={4} step={0.5} unit="×" onChange={(v) => setTweak("telemSpeed", v)} />
      <TweakButton label="Inject anomaly" onClick={() => { anomalySet("active"); jump("bench"); }} />
      <TweakSection label="Prototype" />
      <TweakSelect label="Jump to" value="" options={["", "landing", "signup", "login", "graph", "bench", "sol", "team", "settings"]} onChange={(v) => v && jump(v)} />
      <TweakButton label="Reset walkthrough" onClick={() => { localStorage.removeItem(PERSIST_KEY); location.reload(); }} />
    </TweaksPanel>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
