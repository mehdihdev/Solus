// Solus v3 — Connections (catalog-driven, quick-fill presets) + Home briefing + Store
const { useState: useC3, useEffect: useEC3 } = React;

/* ============ CONNECTIONS ============ */
function Conn3Card({ item, connected, busy, onConnect, onDisconnect, onProbe, onToast }) {
  const on = connected;
  return (
    <Card pad={0} style={{ borderColor: on ? "color-mix(in srgb, var(--ok) 28%, var(--bd))" : "var(--bd)" }}>
      <div style={{ display: "flex", gap: 12, alignItems: "center", padding: "12px 15px" }}>
        <span style={{ width: 36, height: 36, borderRadius: 4, background: "var(--sur2)", border: `1px solid ${item.honest && on ? "color-mix(in srgb, var(--warn) 45%, var(--bd))" : "var(--bd)"}`, display: "inline-flex", alignItems: "center", justifyContent: "center", fontFamily: "var(--mono)", fontSize: 12, fontWeight: 600, flexShrink: 0, color: item.honest ? "var(--warn)" : "var(--tx)" }}>{item.mark}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <span style={{ fontSize: 13, fontWeight: 600 }}>{item.name}</span>
            {item.role && <span style={{ fontFamily: "var(--mono)", fontSize: 8, letterSpacing: "0.08em", color: "var(--acc)", border: "1px solid color-mix(in srgb, var(--acc) 40%, transparent)", borderRadius: 3, padding: "1px 6px" }}>{item.role}</span>}
            <span style={{ display: "inline-flex", gap: 4 }}>{item.tags.slice(0, 3).map((t) => <Mono key={t} size={7.5} style={{ border: "1px solid var(--bd)", borderRadius: 99, padding: "1px 6px" }}>{t}</Mono>)}</span>
          </div>
          <div style={{ fontSize: 11, color: "var(--mut)", marginTop: 3, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{item.detail}</div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexShrink: 0 }}>
          {on ? <Mono size={8.5} color="var(--ok)">{item.sect === "local" ? (item.running ? "● RUNNING" : "○ INSTALLED") : "● " + (item.sect === "devices" ? "LIVE" : "CONNECTED")}</Mono> : <Mono size={8.5}>NOT CONNECTED</Mono>}
          {on
            ? <Btn kind="bare" size="sm" onClick={() => onDisconnect(item)}>Disconnect</Btn>
            : <Btn kind="primary" size="sm" onClick={() => onConnect(item)} disabled={busy === item.id}>{busy === item.id ? <><Spinner size={10} color="var(--acc-ink)" /> …</> : "Connect"}</Btn>}
        </div>
      </div>
      {on && (item.identity || item.honestIdle) && (
        <div style={{ borderTop: "1px solid var(--bd)", padding: "8px 15px", background: item.honest ? "color-mix(in srgb, var(--warn) 4%, var(--bg))" : "var(--bg)", display: "flex", gap: 9 }}>
          <span style={{ color: item.honest ? "var(--warn)" : "var(--mut)", marginTop: 1, flexShrink: 0 }}>{item.honest ? SI.warn({ size: 12 }) : SI.check({ size: 12 })}</span>
          <div style={{ flex: 1, fontSize: 11, lineHeight: 1.55 }}>
            {item.identity || item.honestIdle}
            <span style={{ display: "inline-flex", gap: 6, marginLeft: 8 }}>
              {item.honest && <Btn kind="ghost" size="sm" onClick={() => onProbe(item)}>Probe (approval)</Btn>}
              {item.swap && <Btn kind="bare" size="sm" onClick={() => onToast("Labels swapped", "Leader ↔ Follower. Signal names update to match.")}>Swap L/F labels</Btn>}
            </span>
          </div>
        </div>
      )}
    </Card>
  );
}

function ConnectionsScreen3({ world, firstRun, onConnectIds, onDisconnectId, onQuickFill, onDone, onToast, onProbe }) {
  const [busy, setBusy] = useC3(null);
  const [derived, setDerived] = useC3([]); // derivation log lines shown as things connect
  const connect = (item) => {
    setBusy(item.id);
    setTimeout(() => {
      setBusy(null);
      onConnectIds([item.id]);
      const unlocked = V3.WIDGETS.filter((w) => !V3.reqMet(world.insts, w) && V3.reqMet([...world.insts, item], w));
      setDerived((d) => [...d, [item.name + " connected", unlocked.length ? "suggests " + unlocked.map((w) => w.name).join(", ") : "indexed into the graph"]]);
      onToast("Connected " + item.name, unlocked.length ? "New capability available: " + unlocked.map((w) => w.name).join(", ") + " — see the ghost slots on Home." : "Indexed into the graph.");
    }, 1300);
  };
  const sections = [["cloud", "CLOUD ACCOUNTS", "OAuth once · synced remotely"], ["local", "LOCAL APPLICATIONS", "found on this machine · running or not"], ["devices", "DEVICES & STREAMS", "live status · start and stop"]];
  return (
    <div style={{ flex: 1, overflowY: "auto", minWidth: 0 }} data-screen-label="Connections">
      <div style={{ maxWidth: 780, margin: "0 auto", padding: "24px 28px 48px" }}>
        <h1 style={{ margin: 0, fontSize: 21, fontWeight: 600, letterSpacing: "-0.015em" }}>{firstRun ? "Connect what you have" : "Connections"}</h1>
        <p style={{ fontSize: 12.5, color: "var(--mut)", margin: "6px 0 0", lineHeight: 1.6, maxWidth: 540 }}>
          Everything derives from this list — widgets, capabilities, the graph itself. Connect one thing at a time and watch, or quick-fill a known setup.
        </p>
        <div style={{ display: "flex", gap: 8, marginTop: 14, alignItems: "center", flexWrap: "wrap" }}>
          <Mono size={9}>QUICK-FILL A SETUP:</Mono>
          {Object.keys(V3.PRESETS).map((k) => (
            <Btn key={k} kind="soft" size="sm" onClick={() => { onQuickFill(k); setDerived([["Preset applied", V3.PRESETS[k].label]]); }}>{V3.PRESETS[k].label}</Btn>
          ))}
          <span style={{ fontSize: 10.5, color: "var(--mut)" }}>— just connections, nothing else configured</span>
        </div>
        {sections.map(([sect, title, sub]) => {
          const items = V3.CATALOG.filter((c) => c.sect === sect);
          return (
            <div key={sect} style={{ marginTop: 22 }}>
              <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 10 }}>
                <Mono size={9.5} color="var(--tx)">{title}</Mono>
                <span style={{ fontSize: 11, color: "var(--mut)" }}>{sub}</span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
                {items.map((c) => <Conn3Card key={c.id} item={c} connected={world.connectedIds.includes(c.id)} busy={busy} onConnect={connect} onDisconnect={(i) => { onDisconnectId(i.id); onToast("Disconnected " + i.name, "Its widgets grey out or leave — nothing pretends it's still here."); }} onProbe={onProbe} onToast={onToast} />)}
              </div>
            </div>
          );
        })}
        {derived.length > 0 && (
          <Card pad={0} style={{ marginTop: 20 }}>
            <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--bd)" }}><Mono size={9} color="var(--acc)">DERIVATION — BECAUSE X, THEREFORE Y</Mono></div>
            {derived.map(([x, y], i) => (
              <div key={i} className="ob-logline" style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 14px", borderBottom: "1px solid var(--bd)", fontSize: 12 }}>
                <span style={{ color: "var(--mut)" }}>{x}</span><span style={{ color: "var(--acc)" }}>{SI.arrowR({ size: 12 })}</span><span style={{ fontWeight: 600 }}>{y}</span>
              </div>
            ))}
          </Card>
        )}
        {firstRun && (
          <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 20 }}>
            <Btn kind="primary" size="lg" disabled={world.connectedIds.length === 0} onClick={onDone}>Open my workspace {SI.arrowR({ size: 14 })}</Btn>
          </div>
        )}
      </div>
    </div>
  );
}

/* ============ HOME — composed briefing ============ */
/* canvas derivation: installed capabilities + connections → v2 widget types */
function deriveCanvas(world) {
  const L = [];
  const has = (id) => world.installed.includes(id);
  const tag = (t) => world.insts.some((i) => i.tags.includes(t));
  if (has("experiments")) L.push({ id: "exp", type: "exp", title: "Experiments", because: "repo + robot/sim connected" });
  if (has("signals") && world.signals.length) L.push({ id: "bench", type: "bench", title: "Live Bench", because: "signals streaming" });
  if (tag("repo")) { const r = world.insts.find((i) => i.tags.includes("repo")); L.push({ id: "repo", type: "repo", title: r.detail.split(" ·")[0], because: r.name + " connected" }); }
  if (world.guide && has("guide")) L.push({ id: "guide", type: "guide", title: "Guide · " + world.guide.task, because: "KiCad installed, task in progress" });
  if (has("bom")) L.push({ id: "board", type: "board", title: "BOM · board", because: "EDA project indexed" });
  if (has("can")) L.push({ id: "can", type: "can", title: "CAN health", because: "CAN interface configured" });
  if (has("provenance")) L.push({ id: "knowledge", type: "knowledge", title: "Ask the history", because: "team history indexed" });
  const honest = world.insts.find((i) => i.honest);
  if (honest) L.push({ id: "identify", type: "identify", title: "Unknown board", because: "device identity unconfirmed" });
  if (tag("sim") && has("scene")) L.push({ id: "sim", type: "sim", title: "Simulator", because: "simulator connected" });
  return L;
}

function GhostSlot({ w, onInstall, onDetail }) {
  return (
    <div style={{ border: "1.5px dashed color-mix(in srgb, var(--acc) 40%, var(--bd))", borderRadius: 4, padding: "13px 15px", display: "flex", alignItems: "center", gap: 12, background: "color-mix(in srgb, var(--acc) 2.5%, transparent)" }}>
      <span style={{ color: "var(--acc)", opacity: 0.8 }}>{(SI[w.icon] || SI.box)({ size: 16 })}</span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <span style={{ fontSize: 12.5, fontWeight: 600 }}>{w.name}</span> <span style={{ fontSize: 11.5, color: "var(--mut)" }}>would appear here — you have what it needs.</span>
      </div>
      <Btn kind="bare" size="sm" onClick={() => onDetail(w)}>What it does</Btn>
      <Btn kind="primary" size="sm" onClick={() => onInstall(w.id)}>Install</Btn>
    </div>
  );
}

function HomeScreen3({ world, go, openSol, onInstall, onDetail, anomalyLive, run42, fixes, requestProbe, onToast }) {
  const [order, setOrder] = useC3(null);
  const dragIdx = React.useRef(null);
  useEC3(() => setOrder(null), [world.connectedIds.join(",") + "|" + world.installed.join(",")]);
  const canvasBase = deriveCanvas(world);
  const canvas = order || canvasBase;
  const f = world.finding;
  const r = world.runs[0];
  const strip = [
    { k: "Connections", v: world.insts.length + " live", go: "connections" },
    world.signals.length && { k: "Signals", v: world.signals.length + " streaming", go: "bench" },
    world.widgets.installed.some((w) => w.id === "experiments") && { k: "Last run", v: r ? `${r.id} · ${r.bad.length ? r.bad.length + "/" + r.eps + " anomalous" : "passed"}` : "none yet", go: "experiments" },
    world.widgets.installed.some((w) => w.id === "can") && { k: "CAN", v: "46% load · log", go: "bench" },
  ].filter(Boolean);
  return (
    <div style={{ flex: 1, overflowY: "auto", minWidth: 0 }} data-screen-label="Home">
      <div style={{ maxWidth: 900, margin: "0 auto", padding: "26px 28px 48px" }}>
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 22, fontWeight: 600, letterSpacing: "-0.015em" }}>{world.wsName}</h1>
            <div style={{ fontSize: 11.5, color: "var(--mut)", marginTop: 4 }}>{world.tagline}</div>
          </div>
          <Mono size={9}>{new Date().toLocaleDateString("en-US", { weekday: "long", month: "short", day: "numeric" })}</Mono>
        </div>

        {/* status strip */}
        {strip.length > 0 && (
          <div style={{ display: "flex", gap: 10, marginTop: 18, flexWrap: "wrap" }}>
            {strip.map((s) => (
              <div key={s.k} onClick={() => go(s.go)} style={{ display: "flex", gap: 9, alignItems: "baseline", background: "var(--sur)", border: "1px solid var(--bd)", borderRadius: 3, padding: "8px 13px", cursor: "pointer" }}>
                <Mono size={8.5}>{s.k}</Mono>
                <span style={{ fontFamily: "var(--mono)", fontSize: 12 }}>{s.v}</span>
              </div>
            ))}
          </div>
        )}

        {/* hero: the finding, or honest quiet */}
        <div style={{ marginTop: 16 }}>
          {f ? (
            <Card pad={0} style={{ borderColor: "color-mix(in srgb, var(--err) 40%, var(--bd))" }}>
              <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1.5fr) minmax(0,1fr)", gap: 0 }}>
                <div style={{ padding: "20px 22px" }}>
                  <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    <span style={{ color: "var(--err)" }} className="gm-orb">{SI.warn({ size: 15 })}</span>
                    <Mono size={9} color="var(--err)">{f.sev.toUpperCase()} · {f.when}</Mono>
                  </div>
                  <div style={{ fontSize: 19, fontWeight: 600, lineHeight: 1.3, marginTop: 10, letterSpacing: "-0.01em" }}>{f.title}</div>
                  <div style={{ fontSize: 12.5, color: "var(--mut)", lineHeight: 1.65, marginTop: 10 }}>{f.what}</div>
                  <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
                    <Btn kind="primary" onClick={() => openSol(world.findings[0].solKey)}>{SI.sol({ size: 13 })} Explain & fix</Btn>
                    <Btn kind="ghost" onClick={() => go("graph")}>See it in the graph</Btn>
                  </div>
                </div>
                <div style={{ borderLeft: "1px solid var(--bd)", padding: "20px 22px", background: "var(--bg)" }}>
                  <Mono size={8.5}>THE CHAIN · {new Set(f.chain.map((c) => c.d)).size} DOMAINS</Mono>
                  <div style={{ marginTop: 10 }}>
                    {f.chain.map((c, i) => (
                      <div key={i} style={{ display: "flex", gap: 9, padding: "5px 0" }}>
                        <span style={{ width: 7, height: 7, borderRadius: 99, background: dcol(c.d), marginTop: 4, flexShrink: 0 }}></span>
                        <span style={{ fontFamily: "var(--mono)", fontSize: 10.5, lineHeight: 1.5 }}>{c.l}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </Card>
          ) : (
            <Card pad={22}>
              <div style={{ display: "flex", gap: 14, alignItems: "center" }}>
                <Orb2 size={34} energy={50} />
                <div>
                  <div style={{ fontSize: 15, fontWeight: 600 }}>{world.insts.length === 0 ? "Nothing connected — and nothing invented" : "All quiet"}</div>
                  <div style={{ fontSize: 12, color: "var(--mut)", marginTop: 4, lineHeight: 1.6 }}>
                    {world.insts.length === 0 ? "This workspace is deliberately empty. Connect a tool, repo, or device and it starts filling itself in." : "No cross-domain conflicts in what's connected. SOL re-checks on every change."}
                  </div>
                </div>
                {world.insts.length === 0 && <Btn kind="primary" style={{ marginLeft: "auto" }} onClick={() => go("connections")}>Open Connections</Btn>}
              </div>
            </Card>
          )}
        </div>

        {/* ghost slots — suggestions where the widget would live */}
        {world.widgets.suggested.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 9, marginTop: 14 }}>
            {world.widgets.suggested.slice(0, 2).map((w) => <GhostSlot key={w.id} w={w} onInstall={onInstall} onDetail={onDetail} />)}
          </div>
        )}

        {/* workspace canvas — derived, arrangeable widgets */}
        {canvas.length > 0 && (
          <div style={{ marginTop: 20 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
              <Mono size={9}>WORKSPACE · DERIVED FROM CONNECTIONS · DRAG TO ARRANGE</Mono>
              <span onClick={() => go("store")} style={{ fontSize: 11, color: "var(--acc)", cursor: "pointer" }}>Store →</span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 12, marginTop: 10 }}>
              {canvas.map((w, i) => (
                <WidgetShell key={w.id} w={w} scoped={false}
                  onDragStart={() => (dragIdx.current = i)}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={() => { const from = dragIdx.current; if (from == null || from === i) return; const n = [...canvas]; const [m] = n.splice(from, 1); n.splice(i, 0, m); setOrder(n); onToast && onToast("Layout saved", "This arrangement persists for this workspace."); }}
                  footer={w.type === "exp" ? <Btn kind="bare" size="sm" onClick={() => go("experiments")}>Open →</Btn> : w.type === "bench" ? <Btn kind="bare" size="sm" onClick={() => go("bench")}>Open →</Btn> : w.type === "guide" ? <Btn kind="bare" size="sm" onClick={() => openSol("pour")}>Continue →</Btn> : null}>
                  <WidgetBody w={w} world={world} go={go} openChat={openSol} fixes={fixes || {}} run42={run42} anomalyLive={anomalyLive} requestProbe={requestProbe} />
                </WidgetShell>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ============ STORE ============ */
function StoreDetail({ w, world, onClose, onInstall, installed }) {
  const met = V3.reqMet(world.insts, w);
  const missing = V3.reqMissing(world.insts, w);
  return (
    <ChromeModal title={w.name} onClose={onClose} width={440}>
      <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
        <span style={{ width: 38, height: 38, borderRadius: 6, background: "var(--sur2)", border: "1px solid var(--bd)", display: "inline-flex", alignItems: "center", justifyContent: "center", color: "var(--acc)" }}>{(SI[w.icon] || SI.box)({ size: 17 })}</span>
        <div>
          <Mono size={8.5} color={w.fp ? "var(--ok)" : "var(--warn)"}>{w.fp ? "FIRST-PARTY · SOLUS" : w.by.toUpperCase()}</Mono>
          <div style={{ fontSize: 11.5, color: "var(--mut)", marginTop: 2 }}>needs: {w.req.length ? w.req.join(" + ") : "nothing"}</div>
        </div>
      </div>
      <p style={{ fontSize: 12.5, lineHeight: 1.65, margin: "14px 0 0" }}>{w.does}</p>
      <Mono size={8.5} style={{ display: "block", marginTop: 14 }}>INSTALLING ADDS</Mono>
      <div style={{ marginTop: 6 }}>
        {w.adds.map((a) => <div key={a} style={{ display: "flex", gap: 8, fontSize: 12, padding: "5px 0", borderBottom: "1px solid var(--bd)" }}><span style={{ color: "var(--ok)" }}>{SI.check({ size: 12 })}</span>{a}</div>)}
      </div>
      {!met && (
        <div style={{ marginTop: 12, background: "color-mix(in srgb, var(--warn) 6%, transparent)", border: "1px solid color-mix(in srgb, var(--warn) 35%, transparent)", borderRadius: 3, padding: "9px 11px", fontSize: 11.5, lineHeight: 1.55 }}>
          Won't do anything yet — missing <b>{missing.join(", ")}</b>. It installs fine, but stays dormant until you connect one.
        </div>
      )}
      <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
        {installed
          ? <Btn kind="ghost" style={{ flex: 1 }} onClick={() => { onInstall(w.id, false); onClose(); }}>Uninstall</Btn>
          : <Btn kind="primary" style={{ flex: 1 }} onClick={() => { onInstall(w.id, true); onClose(); }}>Install{met ? "" : " anyway"}</Btn>}
      </div>
    </ChromeModal>
  );
}

function StoreScreen({ world, onInstall, onToast }) {
  const [detail, setDetail] = useC3(null);
  const row = (w, state) => (
    <Card key={w.id} pad={0} onClick={() => setDetail(w)} style={{ cursor: "pointer" }}>
      <div style={{ display: "flex", gap: 12, alignItems: "center", padding: "12px 15px" }}>
        <span style={{ width: 34, height: 34, borderRadius: 5, background: "var(--sur2)", border: "1px solid var(--bd)", display: "inline-flex", alignItems: "center", justifyContent: "center", color: state === "locked" ? "var(--mut)" : "var(--acc)", flexShrink: 0 }}>{(SI[w.icon] || SI.box)({ size: 15 })}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <span style={{ fontSize: 13, fontWeight: 600 }}>{w.name}</span>
            <Mono size={7.5} color={w.fp ? "var(--ok)" : "var(--warn)"} style={{ border: `1px solid ${w.fp ? "color-mix(in srgb, var(--ok) 35%, transparent)" : "color-mix(in srgb, var(--warn) 35%, transparent)"}`, borderRadius: 99, padding: "1px 7px" }}>{w.fp ? "FIRST-PARTY" : "COMMUNITY"}</Mono>
          </div>
          <div style={{ fontSize: 11, color: "var(--mut)", marginTop: 3, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{w.does}</div>
        </div>
        {state === "installed" && <Mono size={8.5} color="var(--ok)">● INSTALLED</Mono>}
        {state === "suggested" && <Btn kind="primary" size="sm" onClick={(e) => { e.stopPropagation(); onInstall(w.id, true); }}>Install</Btn>}
        {state === "locked" && <Mono size={8.5} title={"missing: " + w.missing.join(", ")}>NEEDS {w.missing.join(" + ").toUpperCase()}</Mono>}
      </div>
    </Card>
  );
  return (
    <div style={{ flex: 1, overflowY: "auto", minWidth: 0 }} data-screen-label="Store">
      <div style={{ maxWidth: 720, margin: "0 auto", padding: "24px 28px 48px" }}>
        <h1 style={{ margin: 0, fontSize: 21, fontWeight: 600 }}>Store</h1>
        <p style={{ fontSize: 12.5, color: "var(--mut)", margin: "6px 0 0", lineHeight: 1.6 }}>Capabilities are installed, not built in. Suggestions come from what's connected — never from what sells.</p>
        {[["SUGGESTED — YOU HAVE WHAT THESE NEED", world.widgets.suggested, "suggested"], ["INSTALLED", world.widgets.installed, "installed"], ["EVERYTHING ELSE", world.widgets.locked, "locked"]].map(([t, list, state]) => list.length > 0 && (
          <div key={t} style={{ marginTop: 20 }}>
            <Mono size={9}>{t}</Mono>
            <div style={{ display: "flex", flexDirection: "column", gap: 9, marginTop: 9 }}>{list.map((w) => row(w, state))}</div>
          </div>
        ))}
      </div>
      {detail && <StoreDetail w={detail} world={world} installed={world.installed.includes(detail.id)} onClose={() => setDetail(null)} onInstall={onInstall} />}
    </div>
  );
}

Object.assign(window, { ConnectionsScreen3, HomeScreen3, StoreScreen, StoreDetail });
