// Solus — desktop shell chrome: titlebar, menu bar, command palette, avatar menu, window splash
const { useState: useStateC, useEffect: useEffectC, useRef: useRefC, useMemo: useMemoC } = React;

/* ---------- traffic lights ---------- */
function TrafficLights({ onClose, onMin, onMax }) {
  const [hover, setHover] = useStateC(false);
  const dot = (color, glyph, fn, key) => (
    <span key={key} onClick={(e) => { e.stopPropagation(); fn(); }}
      style={{ width: 12, height: 12, borderRadius: 99, background: color, display: "inline-flex", alignItems: "center", justifyContent: "center", cursor: "pointer", border: "0.5px solid rgba(0,0,0,0.25)" }}>
      <span style={{ fontSize: 8.5, lineHeight: 1, color: "rgba(0,0,0,0.55)", fontWeight: 700, opacity: hover ? 1 : 0, fontFamily: "var(--mono)" }}>{glyph}</span>
    </span>
  );
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center", WebkitAppRegion: "no-drag" }}
      onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}>
      {dot("#FF5F57", "×", onClose, "c")}
      {dot("#FEBC2E", "−", onMin, "m")}
      {dot("#28C840", "+", onMax, "x")}
    </div>
  );
}

/* ---------- generic chrome dropdown ---------- */
function ChromeMenu({ open, onClose, children, style }) {
  useEffectC(() => {
    if (!open) return;
    const h = () => onClose();
    window.addEventListener("click", h);
    return () => window.removeEventListener("click", h);
  }, [open]);
  if (!open) return null;
  return (
    <div onClick={(e) => e.stopPropagation()} style={{ position: "absolute", zIndex: 120, background: "var(--sur)", border: "1px solid var(--bd)", borderRadius: 6, boxShadow: "0 18px 50px rgba(0,0,0,0.5)", padding: 5, minWidth: 200, ...style }}>
      {children}
    </div>
  );
}
function MenuItem({ label, kbd, onClick, disabled, danger, icon }) {
  return (
    <div onClick={disabled ? undefined : onClick} style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 9px", borderRadius: 4, cursor: disabled ? "default" : "pointer", color: disabled ? "var(--mut)" : danger ? "var(--err)" : "var(--tx)", fontSize: 12.5, opacity: disabled ? 0.5 : 1 }}
      onMouseEnter={(e) => !disabled && (e.currentTarget.style.background = "var(--sur2)")}
      onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}>
      {icon && <span style={{ color: "var(--mut)", display: "inline-flex" }}>{icon}</span>}
      <span style={{ flex: 1 }}>{label}</span>
      {kbd && <span style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--mut)", textTransform: "none" }}>{kbd}</span>}
    </div>
  );
}
const MenuSep = () => <div style={{ height: 1, background: "var(--bd)", margin: "5px 4px" }}></div>;

/* ---------- menu bar ---------- */
function MenuBar({ menus, onAction }) {
  const [open, setOpen] = useStateC(null);
  useEffectC(() => {
    if (!open) return;
    const h = () => setOpen(null);
    window.addEventListener("click", h);
    return () => window.removeEventListener("click", h);
  }, [open]);
  return (
    <div style={{ height: 28, display: "flex", alignItems: "stretch", padding: "0 6px", background: "var(--bg)", borderBottom: "1px solid var(--bd)", flexShrink: 0, WebkitAppRegion: "no-drag", position: "relative", zIndex: 60 }}
      onClick={(e) => e.stopPropagation()}>
      {menus.map((m) => (
        <div key={m.id} style={{ position: "relative", display: "flex", alignItems: "center" }}>
          <span onClick={() => setOpen(open === m.id ? null : m.id)} onMouseEnter={() => open && setOpen(m.id)}
            style={{ padding: "0 10px", height: "100%", display: "flex", alignItems: "center", fontSize: 12, fontWeight: m.id === "solus" ? 600 : 400, color: open === m.id ? "var(--tx)" : "var(--mut)", background: open === m.id ? "var(--sur2)" : "transparent", cursor: "pointer", borderRadius: 4 }}>
            {m.label}
          </span>
          {open === m.id && (
            <div style={{ position: "absolute", top: 30, left: 0, zIndex: 120, background: "var(--sur)", border: "1px solid var(--bd)", borderRadius: 6, boxShadow: "0 18px 50px rgba(0,0,0,0.5)", padding: 5, minWidth: 215 }}>
              {m.items.map((it, i) => it.sep ? <MenuSep key={i} /> : (
                <MenuItem key={i} label={it.label} kbd={it.kbd} disabled={it.disabled} danger={it.danger}
                  onClick={() => { setOpen(null); onAction(it.id); }} />
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

/* ---------- workspace switcher ---------- */
function WorkspaceSwitcher({ onAction, name = "strider-qd12", sub = "Team · 4 members" }) {
  const [open, setOpen] = useStateC(false);
  return (
    <div style={{ position: "relative", WebkitAppRegion: "no-drag" }} onClick={(e) => e.stopPropagation()}>
      <span onClick={() => setOpen(!open)} style={{ display: "inline-flex", alignItems: "center", gap: 7, fontSize: 12.5, fontWeight: 600, padding: "4px 9px", borderRadius: 5, cursor: "pointer", background: open ? "var(--sur2)" : "transparent", border: "1px solid var(--bd)" }}>
        <SolHammer size={16} energy={50} />
        {name}
        <span style={{ color: "var(--mut)" }}>{SI.chevD({ size: 12 })}</span>
      </span>
      <ChromeMenu open={open} onClose={() => setOpen(false)} style={{ top: 30, left: 0, minWidth: 240 }}>
        <div style={{ padding: "4px 9px 8px" }}><Mono size={8.5}>WORKSPACE</Mono></div>
        <div style={{ display: "flex", alignItems: "center", gap: 9, padding: "6px 9px", borderRadius: 4, background: "var(--sur2)" }}>
          <span style={{ width: 22, height: 22, borderRadius: 5, background: "var(--bg)", border: "1px solid var(--bd)", display: "inline-flex", alignItems: "center", justifyContent: "center", fontFamily: "var(--mono)", fontSize: 10 }}>QD</span>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 12.5, fontWeight: 600 }}>{name}</div>
            <div style={{ fontSize: 10, color: "var(--mut)" }}>{sub}</div>
          </div>
          <span style={{ color: "var(--ok)" }}>{SI.check({ size: 13 })}</span>
        </div>
        <div style={{ opacity: 0.5, display: "flex", alignItems: "center", gap: 9, padding: "6px 9px" }}>
          <span style={{ width: 22, height: 22, borderRadius: 5, background: "var(--bg)", border: "1px solid var(--bd)", display: "inline-flex", alignItems: "center", justifyContent: "center", fontFamily: "var(--mono)", fontSize: 10 }}>AR</span>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 12.5, fontWeight: 600 }}>armlab-6dof</div>
            <div style={{ fontSize: 10, color: "var(--mut)" }}>Solo · archived</div>
          </div>
        </div>
        <MenuSep />
        <MenuItem label="New project…" icon={SI.plus({ size: 13 })} onClick={() => { setOpen(false); onAction("newproject"); }} />
        <MenuItem label="Workspace settings" icon={SI.gear({ size: 13 })} onClick={() => { setOpen(false); onAction("ws-general"); }} />
      </ChromeMenu>
    </div>
  );
}

/* ---------- avatar menu ---------- */
function AvatarMenu({ onNav, onAction }) {
  const [open, setOpen] = useStateC(false);
  const item = (label, section, icon) => <MenuItem label={label} icon={icon} onClick={() => { setOpen(false); onNav(section); }} />;
  return (
    <div style={{ position: "relative", WebkitAppRegion: "no-drag" }} onClick={(e) => e.stopPropagation()}>
      <span id="chrome-avatar" onClick={() => setOpen(!open)} style={{ cursor: "pointer", display: "inline-flex" }}><Avatar name="Maya Krishnan" size={24} /></span>
      <ChromeMenu open={open} onClose={() => setOpen(false)} style={{ top: 32, right: 0, minWidth: 230 }}>
        <div style={{ display: "flex", gap: 10, alignItems: "center", padding: "6px 9px 10px" }}>
          <Avatar name="Maya Krishnan" size={32} />
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 12.5, fontWeight: 600 }}>Signed in</div>
            <div style={{ fontSize: 10.5, color: "var(--mut)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>demo account</div>
          </div>
          <span style={{ fontFamily: "var(--mono)", fontSize: 8.5, letterSpacing: "0.06em", color: "var(--acc)", border: "1px solid color-mix(in srgb, var(--acc) 40%, transparent)", borderRadius: 99, padding: "2px 6px" }}>TEAM</span>
        </div>
        <MenuSep />
        {item("Profile", "profile", SI.user({ size: 13 }))}
        {item("Preferences", "preferences", SI.sliders({ size: 13 }))}
        {item("Model configuration", "model", SI.bolt({ size: 13 }))}
        {item("Billing & plan", "billing", SI.card({ size: 13 }))}
        <MenuSep />
        {item("Settings", "general", SI.gear({ size: 13 }))}
        <MenuItem label="Keyboard shortcuts" kbd="?" icon={SI.cmd({ size: 13 })} onClick={() => { setOpen(false); onAction("shortcuts"); }} />
        <MenuSep />
        <MenuItem label="Sign out" danger onClick={() => { setOpen(false); onAction("signout"); }} />
      </ChromeMenu>
    </div>
  );
}

/* ---------- titlebar ---------- */
function Titlebar({ onTraffic, onCommand, onNav, onAction, themeIsDark, onToggleTheme, bell, minimal, wsName, wsSub }) {
  if (minimal) {
    return (
      <div style={{ height: 38, display: "flex", alignItems: "center", padding: "0 12px", background: "var(--sur)", borderBottom: "1px solid var(--bd)", flexShrink: 0, position: "relative", zIndex: 70 }}>
        <TrafficLights onClose={() => onTraffic("close")} onMin={() => onTraffic("min")} onMax={() => onTraffic("max")} />
        <div style={{ position: "absolute", left: 0, right: 0, textAlign: "center", pointerEvents: "none" }}>
          <span style={{ fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.18em", color: "var(--mut)" }}>SOLUS</span>
        </div>
      </div>
    );
  }
  return (
    <div style={{ height: 38, display: "flex", alignItems: "center", gap: 12, padding: "0 12px", background: "var(--sur)", borderBottom: "1px solid var(--bd)", flexShrink: 0, WebkitAppRegion: "drag", position: "relative", zIndex: 70 }}>
      <TrafficLights onClose={() => onTraffic("close")} onMin={() => onTraffic("min")} onMax={() => onTraffic("max")} />
      <div style={{ width: 6 }}></div>
      <WorkspaceSwitcher onAction={onAction} name={wsName} sub={wsSub} />
      <div style={{ flex: 1 }}></div>
      {/* command bar */}
      <div onClick={onCommand} style={{ WebkitAppRegion: "no-drag", width: "min(420px, 38vw)", background: "var(--bg)", border: "1px solid var(--bd)", borderRadius: 6, padding: "5px 10px", display: "flex", alignItems: "center", justifyContent: "space-between", cursor: "text", color: "var(--mut)" }}>
        <span style={{ fontSize: 12, display: "inline-flex", gap: 8, alignItems: "center", whiteSpace: "nowrap", overflow: "hidden" }}>{SI.search({ size: 12 })} Search or run a command…</span>
        <span style={{ fontFamily: "var(--mono)", fontSize: 10.5 }}>⌘K</span>
      </div>
      <div style={{ flex: 1 }}></div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, WebkitAppRegion: "no-drag" }}>
        <span title="Toggle theme" onClick={onToggleTheme} style={{ cursor: "pointer", color: "var(--mut)", display: "inline-flex", padding: 3 }}>{SI.monitor({ size: 15 })}</span>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontFamily: "var(--mono)", fontSize: 9.5, color: "var(--mut)" }}>
          <span style={{ width: 6, height: 6, borderRadius: 99, background: "var(--ok)" }}></span>SYNCED
        </span>
        {bell}
        <AvatarMenu onNav={onNav} onAction={onAction} />
      </div>
    </div>
  );
}

/* ---------- command palette ---------- */
function CommandPalette({ open, items, onClose, onRun }) {
  const [q, setQ] = useStateC("");
  const [idx, setIdx] = useStateC(0);
  const inputRef = useRefC(null);
  useEffectC(() => { if (open) { setQ(""); setIdx(0); setTimeout(() => inputRef.current && inputRef.current.focus(), 30); } }, [open]);

  const filtered = useMemoC(() => {
    const s = q.toLowerCase().trim();
    if (!s) return items.filter((i) => i.primary !== false).slice(0, 9);
    return items.filter((i) => (i.label + " " + (i.section || "") + " " + (i.kw || "")).toLowerCase().includes(s)).slice(0, 12);
  }, [q, items, open]);

  useEffectC(() => { if (idx >= filtered.length) setIdx(0); }, [filtered.length]);

  const key = (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setIdx((i) => Math.min(i + 1, filtered.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setIdx((i) => Math.max(i - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); const it = filtered[idx]; if (it) { onRun(it); } }
    else if (e.key === "Escape") { onClose(); }
  };
  if (!open) return null;
  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 150, background: "rgba(0,0,0,0.45)", display: "flex", justifyContent: "center", alignItems: "flex-start", paddingTop: "12vh" }} onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()} style={{ width: 560, maxWidth: "92vw", background: "var(--sur)", border: "1px solid var(--bd)", borderRadius: 10, boxShadow: "0 30px 80px rgba(0,0,0,0.6)", overflow: "hidden" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "13px 16px", borderBottom: "1px solid var(--bd)" }}>
          <span style={{ color: "var(--mut)" }}>{SI.search({ size: 16 })}</span>
          <input ref={inputRef} value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={key} placeholder="Search pages, actions, nodes…"
            style={{ flex: 1, background: "transparent", border: "none", outline: "none", color: "var(--tx)", fontSize: 14.5, fontFamily: "var(--ui)" }} />
          <span style={{ fontFamily: "var(--mono)", fontSize: 9.5, color: "var(--mut)", border: "1px solid var(--bd)", borderRadius: 4, padding: "2px 6px" }}>ESC</span>
        </div>
        <div style={{ maxHeight: 360, overflowY: "auto", padding: 6 }}>
          {filtered.length === 0 && <div style={{ padding: "24px 16px", textAlign: "center", color: "var(--mut)", fontSize: 12.5 }}>No matches for “{q}”</div>}
          {filtered.map((it, i) => (
            <div key={it.id} onMouseEnter={() => setIdx(i)} onClick={() => onRun(it)}
              style={{ display: "flex", alignItems: "center", gap: 11, padding: "9px 11px", borderRadius: 6, cursor: "pointer", background: i === idx ? "var(--sur2)" : "transparent" }}>
              <span style={{ color: it.dot ? it.dot : "var(--mut)", display: "inline-flex", width: 16, justifyContent: "center" }}>
                {it.dot ? <span style={{ width: 7, height: 7, borderRadius: 99, background: it.dot }}></span> : (it.icon || SI.arrowR({ size: 13 }))}
              </span>
              <span style={{ flex: 1, fontSize: 13, color: "var(--tx)" }}>{it.label}</span>
              {it.kbd && <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--mut)" }}>{it.kbd}</span>}
              <span style={{ fontFamily: "var(--mono)", fontSize: 8.5, letterSpacing: "0.08em", color: "var(--mut)", textTransform: "uppercase" }}>{it.section}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ---------- modal shell ---------- */
function ChromeModal({ title, onClose, children, width = 440 }) {
  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 150, background: "rgba(0,0,0,0.55)", display: "flex", alignItems: "center", justifyContent: "center" }} onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()}>
        <Card pad={0} style={{ width, maxWidth: "92vw", boxShadow: "0 24px 70px rgba(0,0,0,0.55)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "14px 18px", borderBottom: "1px solid var(--bd)" }}>
            <span style={{ fontSize: 14, fontWeight: 600 }}>{title}</span>
            <span onClick={onClose} style={{ color: "var(--mut)", cursor: "pointer" }}>{SI.x({ size: 14 })}</span>
          </div>
          <div style={{ padding: 18 }}>{children}</div>
        </Card>
      </div>
    </div>
  );
}

function AboutModal({ onClose }) {
  return (
    <ChromeModal title="About Solus" onClose={onClose} width={380}>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center", gap: 12, padding: "8px 0 4px" }}>
        <SolHammer size={72} energy={70} />
        <div>
          <div style={{ fontSize: 18, fontWeight: 700, letterSpacing: "0.06em" }}>SOLUS</div>
          <div style={{ fontSize: 12, color: "var(--mut)", marginTop: 4 }}>Cross-domain integrity for robotics teams</div>
        </div>
        <div style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--mut)", lineHeight: 1.8 }}>
          Version 0.9.0 (build 2026.06)<br />Electron 30 · Chromium 124<br />© 2026 Solus Robotics, Inc.
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
          <Btn kind="ghost" size="sm">Release notes</Btn>
          <Btn kind="ghost" size="sm">Licenses</Btn>
        </div>
      </div>
    </ChromeModal>
  );
}

function ShortcutsModal({ onClose }) {
  return (
    <ChromeModal title="Keyboard shortcuts" onClose={onClose} width={420}>
      <div>
        {SHORTCUTS.map(([k, label]) => (
          <div key={label} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 0", borderBottom: "1px solid var(--bd)" }}>
            <span style={{ fontSize: 12.5 }}>{label}</span>
            <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--tx)", background: "var(--bg)", border: "1px solid var(--bd)", borderRadius: 4, padding: "3px 8px" }}>{k}</span>
          </div>
        ))}
      </div>
    </ChromeModal>
  );
}

/* ---------- window splash (closed / minimized) ---------- */
function WindowSplash({ state, onReopen }) {
  if (state !== "closed" && state !== "min") return null;
  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 200, background: "var(--bg)", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 22 }}>
      <SolHammer size={96} energy={40} state="idle" />
      <div style={{ textAlign: "center" }}>
        <div style={{ fontFamily: "var(--mono)", fontSize: 11, letterSpacing: "0.14em", color: "var(--mut)" }}>SOLUS</div>
        <div style={{ fontSize: 14, color: "var(--tx)", marginTop: 8 }}>{state === "closed" ? "Application closed" : "Minimized to dock"}</div>
      </div>
      <Btn kind="primary" onClick={onReopen}>{state === "closed" ? "Reopen Solus" : "Restore window"}</Btn>
    </div>
  );
}

Object.assign(window, { Titlebar, MenuBar, CommandPalette, AvatarMenu, AboutModal, ShortcutsModal, WindowSplash, ChromeModal });
