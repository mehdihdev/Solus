// Solus v4 — Workspace: the graph made usable. Add (service / hardware), .solus panel w/ right-click, suggestions, part menus
const { useState: useW4, useEffect: useEW4 } = React;

const SOLUS_SECTIONS = [["hardware", "Hardware configs"], ["details", "Project details"], ["errors", "Error logging"], ["docs", "Documentation"], ["code", "Code environment"]];

function SolusPanel({ project, onAddEntry, openSol, onClose }) {
  const [menu, setMenu] = useW4(null);
  const [typing, setTyping] = useW4(null);
  const [txt, setTxt] = useW4("");
  const ctx = (e, sec) => { e.preventDefault(); setMenu({ x: e.clientX, y: e.clientY, sec }); };
  useEW4(() => { const h = () => setMenu(null); window.addEventListener("click", h); return () => window.removeEventListener("click", h); }, []);
  return (
    <div style={{ width: 290, borderLeft: "1px solid var(--bd)", background: "var(--sur)", display: "flex", flexDirection: "column", flexShrink: 0, minHeight: 0 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 14px", borderBottom: "1px solid var(--bd)" }}>
        <span style={{ fontFamily: "var(--mono)", fontSize: 12, fontWeight: 600 }}>.solus</span>
        <span style={{ display: "inline-flex", gap: 8, alignItems: "center" }}><Mono size={8}>RIGHT-CLICK A SECTION</Mono><span onClick={onClose} style={{ color: "var(--mut)", cursor: "pointer" }}>{SI.x({ size: 12 })}</span></span>
      </div>
      <div style={{ flex: 1, overflowY: "auto", padding: "6px 8px" }}>
        {SOLUS_SECTIONS.map(([k, label]) => (
          <div key={k} onContextMenu={(e) => ctx(e, k)} style={{ marginBottom: 6, borderRadius: 4, border: "1px solid var(--bd)", background: "var(--bg)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "7px 10px", borderBottom: project.solus[k].length ? "1px solid var(--bd)" : "none" }}>
              <span style={{ fontSize: 12, fontWeight: 600 }}>{label}</span>
              <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>{k === "errors" && <Mono size={7.5} color="var(--warn)">AUTO + YOU</Mono>}<Mono size={8}>{project.solus[k].length || "EMPTY"}</Mono></span>
            </div>
            {project.solus[k].map((e, i) => (
              <div key={i} style={{ display: "flex", gap: 8, padding: "6px 10px", borderBottom: i < project.solus[k].length - 1 ? "1px solid var(--bd)" : "none", alignItems: "flex-start" }}>
                <span style={{ color: e.t === "sol" ? "var(--acc)" : "var(--mut)", marginTop: 1, flexShrink: 0 }}>{e.t === "file" ? SI.file({ size: 11 }) : e.t === "sol" ? SI.sol({ size: 11 }) : SI.chip2({ size: 11 })}</span>
                <div style={{ minWidth: 0 }}><div style={{ fontFamily: e.t === "text" ? "var(--ui)" : "var(--mono)", fontSize: 11, lineHeight: 1.4, wordBreak: "break-word" }}>{e.title}</div>{e.sub && <div style={{ fontSize: 9.5, color: "var(--mut)", marginTop: 2 }}>{e.sub}</div>}</div>
              </div>))}
            {typing && typing.sec === k && (
              <div style={{ padding: 8, borderTop: "1px solid var(--bd)" }}>
                <textarea autoFocus value={txt} onChange={(e) => setTxt(e.target.value)} placeholder={typing.kind === "ask" ? "What should SOL find? e.g. 'FSAE EV rules on fusing'" : "Type it — plain text"} style={{ width: "100%", boxSizing: "border-box", height: 56, background: "var(--sur)", color: "var(--tx)", border: "1px solid var(--acc)", borderRadius: 3, padding: "7px 9px", fontSize: 11.5, fontFamily: "var(--ui)", resize: "none", outline: "none" }} />
                <div style={{ display: "flex", gap: 6, justifyContent: "flex-end", marginTop: 6 }}><Btn kind="bare" size="sm" onClick={() => setTyping(null)}>Cancel</Btn><Btn kind="primary" size="sm" disabled={!txt.trim()} onClick={() => { if (typing.kind === "ask") { onAddEntry(k, { t: "sol", title: "SOL found: " + txt.trim(), sub: "3 sources · confidence marked per item" }); openSol && openSol(null, "Find for .solus › " + label + ": " + txt.trim()); } else onAddEntry(k, { t: "text", title: txt.trim() }); setTyping(null); setTxt(""); }}>{typing.kind === "ask" ? "Ask SOL" : "Add"}</Btn></div>
              </div>)}
          </div>))}
        <div style={{ fontSize: 10.5, color: "var(--mut)", padding: "6px 4px", lineHeight: 1.55 }}>Project-level. SOL files artifacts here and auto-files errors it hits. Empty sections are fine — they're not placeholders, they're honest.</div>
      </div>
      {menu && (
        <div style={{ position: "fixed", left: Math.min(menu.x, window.innerWidth - 210), top: menu.y, zIndex: 160, background: "var(--sur)", border: "1px solid var(--bd)", borderRadius: 6, boxShadow: "0 16px 44px rgba(0,0,0,0.5)", padding: 5, minWidth: 200 }} onClick={(e) => e.stopPropagation()}>
          <div style={{ padding: "3px 9px 6px" }}><Mono size={7.5}>{SOLUS_SECTIONS.find((s) => s[0] === menu.sec)[1].toUpperCase()}</Mono></div>
          {[["Import files…", () => onAddEntry(menu.sec, { t: "file", title: menu.sec === "details" ? "FSAE Rules 2027.pdf" : "imported-file.pdf", sub: "imported just now · indexed", rules: menu.sec === "details" ? 38 : undefined })], ["Ask SOL to find…", () => setTyping({ sec: menu.sec, kind: "ask" })], ["Type it", () => setTyping({ sec: menu.sec, kind: "type" })]].map(([l, fn]) => (
            <div key={l} onClick={() => { setMenu(null); fn(); }} style={{ padding: "6px 9px", fontSize: 12.5, borderRadius: 4, cursor: "pointer" }} onMouseEnter={(e) => (e.currentTarget.style.background = "var(--sur2)")} onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}>{l}</div>))}
        </div>)}
    </div>);
}

function AddPanel({ d, accounts, act, onClose, openSol, onToast }) {
  const [tab, setTab] = useW4("From a service");
  const [open, setOpen] = useW4(null);
  const conn = V4.ACCOUNTS.filter((a) => accounts.includes(a.id));
  return (
    <div style={{ position: "absolute", left: 14, top: 52, width: 560, maxHeight: "calc(100% - 70px)", zIndex: 30, display: "flex", flexDirection: "column", background: "var(--sur)", border: "1px solid color-mix(in srgb, var(--acc) 35%, var(--bd))", borderRadius: 6, boxShadow: "0 24px 70px rgba(0,0,0,0.55)" }} onPointerDown={(e) => e.stopPropagation()} onWheel={(e) => e.stopPropagation()}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 14px", borderBottom: "1px solid var(--bd)" }}>
        <Seg size="sm" options={["From a service", "Hardware"]} value={tab} onChange={setTab} />
        <div style={{ flex: 1 }}></div>
        <span onClick={onClose} style={{ color: "var(--mut)", cursor: "pointer" }}>{SI.x({ size: 13 })}</span>
      </div>
      <div style={{ overflowY: "auto", padding: 14 }}>
        {tab === "From a service" && (conn.length === 0 ? (
          <div style={{ fontSize: 12.5, color: "var(--mut)", lineHeight: 1.6, padding: "8px 2px" }}>No accounts connected. Connect GitHub, Onshape, or a local app in <b style={{ color: "var(--tx)", fontWeight: 500 }}>Home → Accounts</b> — then their documents list here.</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <Mono size={8.5}>ACCOUNTS CONNECTED IN HOME · PICK A DOCUMENT → IT BECOMES A NODE AND SYNCS</Mono>
            {conn.map((a) => (
              <Card key={a.id} pad={0}>
                <div onClick={() => setOpen(open === a.id ? null : a.id)} style={{ display: "flex", gap: 10, alignItems: "center", padding: "10px 13px", cursor: "pointer" }}>
                  <span style={{ width: 28, height: 28, borderRadius: 4, background: "var(--sur2)", border: "1px solid var(--bd)", display: "inline-flex", alignItems: "center", justifyContent: "center", fontFamily: "var(--mono)", fontSize: 10.5 }}>{a.mark}</span>
                  <span style={{ fontSize: 12.5, fontWeight: 600, flex: 1 }}>{a.name}</span>
                  <Mono size={8.5}>{a.docs.length} {a.kind === "cloud" ? "DOCUMENTS" : "PROJECTS"} ▾</Mono>
                </div>
                {open === a.id && a.docs.map((doc) => { const inP = d.project.docs.includes(doc.id); return (
                  <div key={doc.id} style={{ display: "flex", gap: 10, alignItems: "center", padding: "8px 13px", borderTop: "1px solid var(--bd)" }}>
                    <span style={{ width: 7, height: 7, borderRadius: 99, background: dcol(a.domain) }}></span>
                    <div style={{ flex: 1, minWidth: 0 }}><div style={{ fontFamily: "var(--mono)", fontSize: 11.5 }}>{doc.name}</div><div style={{ fontSize: 10, color: "var(--mut)" }}>{doc.sub}{inP ? " · synced on first select, then only on change" : ""}</div></div>
                    {inP ? <Mono size={8.5} color="var(--ok)">● IN GRAPH</Mono> : <Btn kind="primary" size="sm" onClick={() => { act.addDoc(doc.id); onToast("Node created: " + doc.name, "Synced now; afterwards only when " + a.name + " changes. A document can live in more than one project."); }}>Add as node</Btn>}
                  </div>); })}
              </Card>))}
          </div>))}
        {tab === "Hardware" && <HardwarePanel d={d} act={act} openSol={openSol} onDone={(m) => onToast("Hardware added", m)} />}
      </div>
    </div>);
}

function WorkspaceScreen4({ d, accounts, act, sel, setSel, openSol, onToast, goBench }) {
  const [addOpen, setAddOpen] = useW4(false);
  const [solusOpen, setSolusOpen] = useW4(true);
  const [sugg, setSugg] = useW4(null);
  const nodes = d.graphNodes.map((n) => ({ ...n, alert: d.findings.some((f) => f.node === n.id) }));
  const selNode = nodes.find((n) => n.id === sel);
  const partMenu = (pid, node) => { const p = d.project.parts.find((x) => x.id === pid); if (!p) return []; return [
    { label: "Attach to robot…", run: () => onToast("Attach", "Drag onto a robot, or pick one — " + d.robots.map((r) => r.name).join(" / ")) },
    { label: "Edit config", run: () => openSol(null, `Edit hardware config for ${p.name}`) },
    { label: "Open in " + (p.doc ? V4.DOC(p.doc).serviceName : p.src === "detected" ? "device console" : "Solus"), run: () => onToast("Opening", p.name) },
    { label: "Show evidence", run: () => onToast("Evidence for " + p.name, p.ev || (p.src === "file" ? "parsed from " + V4.DOC(p.doc).name : p.src === "detected" ? "enumerated over USB" : "you authored it — no external evidence")) },
    { sep: true }, { label: "Set state → " + (V4.STATES[V4.STATES.indexOf(p.state) + 1] || "live"), run: () => act.setState(pid, V4.STATES[Math.min(V4.STATES.indexOf(p.state) + 1, 4)]) },
  ]; };
  const nodeMenu = (n) => n.kind === "robot" ? [{ label: "Rename robot…", run: () => { const nm = prompt("Robot name", n.name); nm && act.renameRobot(n.robot.id, nm); } }, { label: "Open in Live Bench", run: goBench }, { label: "Attach selected part…", run: () => onToast("Attach", "Right-click a part → Attach to robot") }, { sep: true }, { label: "Remove robot", danger: true, run: () => act.removeRobot(n.robot.id) }] : n.kind === "solus" ? [{ label: "Open project .solus panel", run: () => setSolusOpen(true) }, { label: "Open ~/.solus (root) in Home", run: () => onToast("Root .solus", "Home → .solus tab — applies to every project.") }] : n.kind === "widget" ? [{ label: "Open " + n.name, run: n.id === "widget:bench" ? goBench : () => {} }] : [{ label: "Re-sync now", run: () => onToast("Synced", n.name + " — no changes at source.") }, { label: "Open in " + (n.detail.split(" ·")[0]), run: () => {} }, { sep: true }, { label: "Remove from project", danger: true, run: () => act.removeDoc(n.id) }];

  return (
    <div style={{ flex: 1, display: "flex", minWidth: 0, minHeight: 0, position: "relative" }} data-screen-label="Workspace">
      <Graph4 nodes={nodes} links={d.links} suggestions={d.project.suggestions} sel={sel} setSel={setSel} onSuggest={setSugg} onPartMenu={partMenu} onNodeMenu={nodeMenu} resetKey={d.project.id}
        overlayTL={
          <>
            <div style={{ position: "absolute", left: 14, top: 12, display: "flex", gap: 8, alignItems: "center" }}>
              <Btn id="ws-add" kind="primary" size="sm" onClick={() => setAddOpen(!addOpen)}>{SI.plus({ size: 13 })} Add</Btn>
              <Btn kind={solusOpen ? "soft" : "ghost"} size="sm" onClick={() => setSolusOpen(!solusOpen)} style={{ fontFamily: "var(--mono)" }}>.solus</Btn>
              <Mono size={9} style={{ marginLeft: 6 }}>{nodes.filter((n) => n.kind !== "solus").length ? `${d.docs.length} DOCS · ${d.robots.length} ROBOT${d.robots.length === 1 ? "" : "S"} · ${d.links.length} LINKS · SCROLL INTO ANY NODE` : ""}</Mono>
            </div>
            {nodes.filter((n) => n.kind !== "solus").length === 0 && (
              <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", pointerEvents: "none" }}>
                <div style={{ textAlign: "center", maxWidth: 400, pointerEvents: "auto" }}>
                  <span style={{ color: "var(--mut)", opacity: 0.6 }}>{SI.graph({ size: 30 })}</span>
                  <div style={{ fontSize: 15, fontWeight: 600, marginTop: 12 }}>An empty project — on purpose</div>
                  <div style={{ fontSize: 12.5, color: "var(--mut)", marginTop: 8, lineHeight: 1.65 }}>Only the <span style={{ fontFamily: "var(--mono)", color: "var(--tx)" }}>.solus</span> node is here — nothing else is drawn until something real arrives. <b style={{ color: "var(--tx)", fontWeight: 500 }}>Add</b> a document from a connected account or bring in hardware — each becomes a node you can zoom into.</div>
                  <div style={{ marginTop: 14 }}><Btn kind="primary" size="sm" onClick={() => setAddOpen(true)}>{SI.plus({ size: 12 })} Add the first thing</Btn></div>
                </div>
              </div>)}
            {addOpen && <AddPanel d={d} accounts={accounts} act={act} onClose={() => setAddOpen(false)} openSol={openSol} onToast={onToast} />}
            {sugg && (
              <div style={{ position: "absolute", left: "50%", bottom: 60, transform: "translateX(-50%)", width: 420, zIndex: 35 }} onPointerDown={(e) => e.stopPropagation()}>
                <Card pad={14} style={{ borderColor: "color-mix(in srgb, var(--warn) 50%, var(--bd))", boxShadow: "0 16px 50px rgba(0,0,0,0.5)" }}>
                  <Mono size={8.5} color="var(--warn)">LINK SUGGESTION · {Math.round(sugg.conf * 100)}% · NOT ASSUMED</Mono>
                  <div style={{ fontSize: 13, fontWeight: 600, marginTop: 6 }}>{sugg.what} → {(d.robots.find((r) => r.id === sugg.to) || {}).name}?</div>
                  <div style={{ fontSize: 11.5, color: "var(--mut)", marginTop: 4 }}>evidence: {sugg.ev}</div>
                  <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
                    <Btn kind="primary" size="sm" onClick={() => { act.acceptSuggestion(sugg.id); setSugg(null); }}>Attach</Btn>
                    <Btn kind="ghost" size="sm" onClick={() => { act.declineSuggestion(sugg.id); setSugg(null); }}>Keep separate</Btn>
                    <Btn kind="bare" size="sm" onClick={() => { setSugg(null); openSol(null, `Is ${sugg.what} part of ${(d.robots.find((r) => r.id === sugg.to) || {}).name}?`); }}>Ask SOL</Btn>
                  </div>
                </Card>
              </div>)}
          </>} />
      {solusOpen && <SolusPanel project={d.project} onAddEntry={act.addSolus} openSol={openSol} onClose={() => setSolusOpen(false)} />}
      {!solusOpen && selNode && (
        <div style={{ width: 260, borderLeft: "1px solid var(--bd)", background: "var(--sur)", padding: 16, flexShrink: 0, overflowY: "auto" }}>
          <Mono size={9} color={selNode.kind === "robot" ? "var(--acc)" : dcol(selNode.domain)}>{selNode.kind === "robot" ? "PHYSICAL ROBOT" : selNode.kind.toUpperCase()}</Mono>
          <div style={{ fontFamily: "var(--mono)", fontSize: 15, marginTop: 6 }}>{selNode.name}</div>
          <div style={{ fontSize: 11, color: "var(--mut)", marginTop: 3, lineHeight: 1.5 }}>{selNode.detail}</div>
          {selNode.kind === "robot" && <div style={{ marginTop: 12 }}>{selNode.robot.parts.map((p) => <div key={p.id} style={{ display: "flex", justifyContent: "space-between", gap: 8, padding: "5px 0", borderBottom: "1px solid var(--bd)", alignItems: "center" }}><span style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: p.honest ? "var(--warn)" : "var(--tx)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{p.name}</span><StateChip state={p.state} small /></div>)}</div>}
          <div style={{ marginTop: 12, fontSize: 10.5, color: "var(--mut)", lineHeight: 1.5 }}>Right-click the node or any part for actions. Selection scopes Live Bench and BOM.</div>
        </div>)}
    </div>);
}
Object.assign(window, { WorkspaceScreen4, SOLUS_SECTIONS });
