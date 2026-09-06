// Solus v4 — Home: projects grid, whole-account connections (health + quota), "How I engineer"
const { useState: useHm4 } = React;

function QuotaBar({ q }) {
  if (!q) return null;
  const pct = q.used / q.limit, warn = pct > 0.8;
  return (
    <div style={{ minWidth: 150 }}>
      <div style={{ display: "flex", justifyContent: "space-between" }}><Mono size={7.5}>API QUOTA</Mono><span style={{ fontFamily: "var(--mono)", fontSize: 9, color: warn ? "var(--warn)" : "var(--mut)" }}>{q.used.toLocaleString()} / {q.limit.toLocaleString()} {q.unit}</span></div>
      <div style={{ height: 4, background: "var(--bg)", border: "1px solid var(--bd)", borderRadius: 99, marginTop: 4, overflow: "hidden" }}><div style={{ width: pct * 100 + "%", height: "100%", background: warn ? "var(--warn)" : "var(--ok)" }}></div></div>
      {warn && <div style={{ fontSize: 9.5, color: "var(--warn)", marginTop: 3 }}>{Math.round(pct * 100)}% — resets in {q.reset}. Syncs slow down before the limit hits, never fail silently.</div>}
    </div>);
}

function HomeScreen4({ projects, currentId, accounts, onOpen, onCreate, onArchive, onConnect, onDisconnect, prefs, setPrefs, onToast, rootSolus, onRootSolus, openSol }) {
  const [tab, setTab] = useHm4("Projects");
  const [creating, setCreating] = useHm4(false);
  const [newName, setNewName] = useHm4("");
  const [busy, setBusy] = useHm4(null);
  const [showArch, setShowArch] = useHm4(false);
  const connect = (a) => { setBusy(a.id); setTimeout(() => { setBusy(null); onConnect(a.id); onToast("Connected " + a.name + " — whole account", "Pick specific documents in any project's Workspace → Add."); }, 1400); };
  const live = projects.filter((p) => !p.archived), arch = projects.filter((p) => p.archived);
  return (
    <div style={{ flex: 1, overflowY: "auto", minWidth: 0 }} data-screen-label="Home">
      <div style={{ maxWidth: 940, margin: "0 auto", padding: "24px 28px 48px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 600, letterSpacing: "-0.015em" }}>Home</h1>
          <Seg options={["Projects", "Accounts", "Team", ".solus"]} value={tab} onChange={setTab} />
        </div>

        {tab === "Projects" && (
          <div style={{ marginTop: 20 }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(250px, 1fr))", gap: 12 }}>
              {live.map((p) => (
                <Card key={p.id} pad={0} style={{ borderColor: p.id === currentId ? "color-mix(in srgb, var(--acc) 55%, var(--bd))" : "var(--bd)", display: "flex", flexDirection: "column" }}>
                  <div style={{ padding: "14px 16px", flex: 1, cursor: "pointer" }} onClick={() => onOpen(p.id)}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                      <span style={{ fontSize: 14, fontWeight: 600, fontFamily: "var(--mono)" }}>{p.name}</span>
                      {p.id === currentId && <Mono size={7.5} color="var(--acc)">OPEN</Mono>}
                    </div>
                    <div style={{ fontSize: 10.5, color: "var(--mut)", marginTop: 4 }}>{p.robots.length} robot{p.robots.length === 1 ? "" : "s"} · {p.docs.length} document{p.docs.length === 1 ? "" : "s"} · {p.parts.length} parts · created {p.created}</div>
                    <div style={{ marginTop: 10 }}>{p.activity.slice(0, 3).map((a, i) => <div key={i} style={{ fontSize: 11, color: i === 0 ? "var(--tx)" : "var(--mut)", padding: "3px 0", borderBottom: "1px solid var(--bd)" }}>{a}</div>)}</div>
                  </div>
                  <div style={{ display: "flex", gap: 6, padding: "8px 12px", borderTop: "1px solid var(--bd)" }}>
                    <Btn kind="primary" size="sm" onClick={() => onOpen(p.id)}>{p.id === currentId ? "Workspace" : "Open"}</Btn>
                    <Btn kind="bare" size="sm" onClick={() => onArchive(p.id, true)}>Archive</Btn>
                  </div>
                </Card>))}
              <Card pad={0} onClick={() => setCreating(true)} style={{ cursor: "pointer", border: "1.5px dashed var(--bd)", background: "transparent", display: "flex", alignItems: "center", justifyContent: "center", minHeight: 150 }}>
                <div style={{ textAlign: "center", color: "var(--mut)" }}>{SI.plus({ size: 18 })}<div style={{ fontSize: 12.5, marginTop: 6 }}>New project</div><div style={{ fontSize: 10.5, marginTop: 2 }}>starts empty — or from a setup</div></div>
              </Card>
            </div>
            {arch.length > 0 && <div style={{ marginTop: 18 }}><span onClick={() => setShowArch(!showArch)} style={{ fontSize: 11.5, color: "var(--mut)", cursor: "pointer" }}>{showArch ? "▾" : "▸"} {arch.length} archived</span>{showArch && arch.map((p) => <div key={p.id} style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", borderBottom: "1px solid var(--bd)", fontSize: 12, opacity: 0.7 }}><span style={{ fontFamily: "var(--mono)" }}>{p.name}</span><Btn kind="bare" size="sm" onClick={() => onArchive(p.id, false)}>Restore</Btn></div>)}</div>}
            {creating && (
              <ChromeModal title="New project" onClose={() => setCreating(false)} width={460}>
                <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="project name" autoFocus style={{ width: "100%", boxSizing: "border-box", background: "var(--bg)", color: "var(--tx)", border: "1px solid var(--bd)", borderRadius: 3, padding: "10px 12px", fontSize: 13, fontFamily: "var(--mono)", outline: "none" }} />
                <div style={{ marginTop: 14, fontSize: 12, color: "var(--mut)", lineHeight: 1.55 }}>A project starts with an empty <span style={{ fontFamily: "var(--mono)" }}>.solus</span> and no nodes. Or start from a known setup — connections and hardware only, nothing else configured:</div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8, marginTop: 10 }}>
                  {Object.keys(V4.PRESETS).map((k) => <Card key={k} pad={11} onClick={() => { onCreate(newName || V4.PRESETS[k].name, k); setCreating(false); setNewName(""); }} style={{ cursor: "pointer" }}><div style={{ fontSize: 12, fontWeight: 600 }}>{V4.PRESETS[k].label}</div><div style={{ fontSize: 10, color: "var(--mut)", marginTop: 3 }}>{V4.PRESETS[k].name}</div></Card>)}
                </div>
                <div style={{ display: "flex", gap: 8, marginTop: 14, justifyContent: "flex-end" }}><Btn kind="ghost" size="sm" onClick={() => setCreating(false)}>Cancel</Btn><Btn kind="primary" size="sm" disabled={!newName} onClick={() => { onCreate(newName, null); setCreating(false); setNewName(""); }}>Create empty</Btn></div>
              </ChromeModal>)}
          </div>)}

        {tab === "Accounts" && (
          <div style={{ marginTop: 20 }}>
            <p style={{ fontSize: 12.5, color: "var(--mut)", margin: "0 0 14px", lineHeight: 1.6, maxWidth: 560 }}>Connecting here binds the <b style={{ color: "var(--tx)", fontWeight: 500 }}>whole account</b>. Picking specific documents happens in each project's Workspace. Health and quota are visible before a limit hits.</p>
            {[["CLOUD ACCOUNTS", "cloud", "OAuth once · remote"], ["LOCAL APPLICATIONS", "local", "found on this machine · running or not"]].map(([t, kind, sub]) => (
              <div key={kind} style={{ marginBottom: 20 }}>
                <div style={{ display: "flex", gap: 10, alignItems: "baseline", marginBottom: 9 }}><Mono size={9.5} color="var(--tx)">{t}</Mono><span style={{ fontSize: 11, color: "var(--mut)" }}>{sub}</span></div>
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {V4.ACCOUNTS.filter((a) => a.kind === kind).map((a) => { const on = accounts.includes(a.id); return (
                    <Card key={a.id} pad={0} style={{ borderColor: on ? "color-mix(in srgb, var(--ok) 28%, var(--bd))" : "var(--bd)" }}>
                      <div style={{ display: "flex", gap: 12, alignItems: "center", padding: "12px 15px" }}>
                        <span style={{ width: 36, height: 36, borderRadius: 4, background: "var(--sur2)", border: "1px solid var(--bd)", display: "inline-flex", alignItems: "center", justifyContent: "center", fontFamily: "var(--mono)", fontSize: 12, fontWeight: 600 }}>{a.mark}</span>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontSize: 13, fontWeight: 600 }}>{a.name}</div>
                          <div style={{ fontSize: 11, color: "var(--mut)", marginTop: 2 }}>{on ? `${a.docs.length} ${kind === "cloud" ? "documents" : "projects"} visible to Solus` : kind === "cloud" ? "not connected" : a.running ? "running · not connected to Solus" : "installed · not connected"}</div>
                        </div>
                        {on && kind === "cloud" && <QuotaBar q={a.quota} />}
                        {on && <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}><span style={{ width: 7, height: 7, borderRadius: 99, background: a.quota && a.quota.used / a.quota.limit > 0.8 ? "var(--warn)" : "var(--ok)" }}></span><Mono size={8.5} color={a.quota && a.quota.used / a.quota.limit > 0.8 ? "var(--warn)" : "var(--ok)"}>{a.quota && a.quota.used / a.quota.limit > 0.8 ? "NEAR LIMIT" : "HEALTHY"}</Mono></span>}
                        {on ? <Btn kind="bare" size="sm" onClick={() => onDisconnect(a.id)}>Disconnect</Btn> : <Btn kind="primary" size="sm" disabled={busy === a.id} onClick={() => connect(a)}>{busy === a.id ? <><Spinner size={10} color="var(--acc-ink)" /> …</> : kind === "cloud" ? "Connect account" : "Connect"}</Btn>}
                      </div>
                    </Card>); })}
                </div>
              </div>))}
          </div>)}

        {tab === "Team" && <TeamScreen wsName={(projects.find((x) => x.id === currentId) || { name: "your team" }).name} onOpenAlert={() => openSol && openSol(null)} />}

        {tab === ".solus" && <RootSolus root={rootSolus} onAdd={onRootSolus} openSol={openSol} />}
      </div>
    </div>);
}

/* root-level .solus — everything above any project; a node in every project's graph */
const ROOT_SECTIONS = [["conventions", "How I engineer", "code style · mechanical · electrical · documentation — SOL reads this every turn"], ["hardware", "Hardware library", "parts and platforms you own, across projects"], ["rules", "Standing rules", "compliance and house rules that apply everywhere"], ["errors", "Error logging", "cross-project failures SOL has filed"], ["docs", "Documentation", "team knowledge that outlives any one project"], ["env", "Environments", "toolchains, containers, machines"]];
function RootSolus({ root, onAdd, openSol }) {
  const [menu, setMenu] = React.useState(null);
  const [typing, setTyping] = React.useState(null);
  const [txt, setTxt] = React.useState("");
  React.useEffect(() => { const h = () => setMenu(null); window.addEventListener("click", h); return () => window.removeEventListener("click", h); }, []);
  return (
    <div style={{ marginTop: 20 }}>
      <div style={{ display: "flex", gap: 14, alignItems: "flex-start", flexWrap: "wrap" }}>
        <p style={{ fontSize: 12.5, color: "var(--mut)", margin: 0, lineHeight: 1.6, maxWidth: 560, flex: 1 }}><span style={{ fontFamily: "var(--mono)", color: "var(--tx)" }}>~/.solus</span> — root level. Everything here applies to every project and appears as a <b style={{ color: "var(--tx)", fontWeight: 500 }}>.solus node</b> in each project's graph (project-level <span style={{ fontFamily: "var(--mono)" }}>.solus</span> inherits it). Right-click a section: Import files · Ask SOL to find · Type it.</p>
        <Card pad={"10px 13px"} style={{ display: "flex", gap: 9, alignItems: "center", borderColor: "color-mix(in srgb, var(--acc) 40%, var(--bd))" }}><span style={{ width: 22, height: 22, borderRadius: 4, border: "1px dashed var(--acc)", display: "inline-flex", alignItems: "center", justifyContent: "center", fontFamily: "var(--mono)", fontSize: 9, color: "var(--acc)" }}>.s</span><div><div style={{ fontSize: 11.5, fontWeight: 600 }}>Node in every graph</div><div style={{ fontSize: 10, color: "var(--mut)" }}>zoom into it in any Workspace</div></div></Card>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(290px, 1fr))", gap: 10, marginTop: 16 }}>
        {ROOT_SECTIONS.map(([k, label, sub]) => (
          <Card key={k} pad={0} onContextMenu={(e) => { e.preventDefault(); setMenu({ x: e.clientX, y: e.clientY, sec: k, label }); }}>
            <div style={{ padding: "10px 13px", borderBottom: "1px solid var(--bd)" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}><span style={{ fontSize: 12.5, fontWeight: 600 }}>{label}</span><Mono size={8}>{(root[k] || []).length || "EMPTY"}</Mono></div>
              <div style={{ fontSize: 10.5, color: "var(--mut)", marginTop: 2 }}>{sub}</div>
            </div>
            <div style={{ minHeight: 44 }}>
              {(root[k] || []).map((e, i) => (
                <div key={i} style={{ display: "flex", gap: 8, padding: "7px 13px", borderBottom: "1px solid var(--bd)", alignItems: "flex-start" }}>
                  <span style={{ color: e.t === "sol" ? "var(--acc)" : "var(--mut)", marginTop: 1, flexShrink: 0 }}>{e.t === "file" ? SI.file({ size: 11 }) : e.t === "sol" ? SI.sol({ size: 11 }) : SI.chip2({ size: 11 })}</span>
                  <div style={{ minWidth: 0 }}><div style={{ fontFamily: e.t === "text" ? "var(--ui)" : "var(--mono)", fontSize: 11, lineHeight: 1.45, wordBreak: "break-word" }}>{e.title}</div>{e.sub && <div style={{ fontSize: 9.5, color: "var(--mut)", marginTop: 2 }}>{e.sub}</div>}</div>
                </div>))}
              {(root[k] || []).length === 0 && !(typing && typing.sec === k) && <div style={{ padding: "10px 13px", fontSize: 10.5, color: "var(--mut)" }}>Empty — honestly. Right-click to add.</div>}
              {typing && typing.sec === k && (
                <div style={{ padding: 10 }}>
                  <textarea autoFocus value={txt} onChange={(e) => setTxt(e.target.value)} placeholder={typing.kind === "ask" ? "What should SOL find?" : k === "conventions" ? "e.g. metric only · 2× fuse margin · Python: black + type hints" : "Type it — plain text"} style={{ width: "100%", boxSizing: "border-box", height: 60, background: "var(--bg)", color: "var(--tx)", border: "1px solid var(--acc)", borderRadius: 3, padding: "7px 9px", fontSize: 11.5, fontFamily: "var(--ui)", resize: "none", outline: "none" }} />
                  <div style={{ display: "flex", gap: 6, justifyContent: "flex-end", marginTop: 6 }}><Btn kind="bare" size="sm" onClick={() => setTyping(null)}>Cancel</Btn><Btn kind="primary" size="sm" disabled={!txt.trim()} onClick={() => { if (typing.kind === "ask") { onAdd(k, { t: "sol", title: "SOL found: " + txt.trim(), sub: "sources + confidence per item" }); openSol && openSol(null, "Find for ~/.solus › " + label + ": " + txt.trim()); } else onAdd(k, { t: "text", title: txt.trim() }); setTyping(null); setTxt(""); }}>{typing.kind === "ask" ? "Ask SOL" : "Add"}</Btn></div>
                </div>)}
            </div>
          </Card>))}
      </div>
      {menu && (
        <div style={{ position: "fixed", left: Math.min(menu.x, window.innerWidth - 210), top: menu.y, zIndex: 160, background: "var(--sur)", border: "1px solid var(--bd)", borderRadius: 6, boxShadow: "0 16px 44px rgba(0,0,0,0.5)", padding: 5, minWidth: 200 }} onClick={(e) => e.stopPropagation()}>
          <div style={{ padding: "3px 9px 6px" }}><Mono size={7.5}>~/.SOLUS › {menu.label.toUpperCase()}</Mono></div>
          {[["Import files…", () => onAdd(menu.sec, { t: "file", title: menu.sec === "rules" ? "FSAE Rules 2027.pdf" : "imported-file.pdf", sub: "imported · indexed · applies to all projects", rules: menu.sec === "rules" ? 38 : undefined })], ["Ask SOL to find…", () => setTyping({ sec: menu.sec, kind: "ask" })], ["Type it", () => setTyping({ sec: menu.sec, kind: "type" })]].map(([l, fn]) => (
            <div key={l} onClick={() => { setMenu(null); fn(); }} style={{ padding: "6px 9px", fontSize: 12.5, borderRadius: 4, cursor: "pointer" }} onMouseEnter={(e) => (e.currentTarget.style.background = "var(--sur2)")} onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}>{l}</div>))}
        </div>)}
    </div>);
}
Object.assign(window, { HomeScreen4 });
