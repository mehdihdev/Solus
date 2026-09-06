// Solus v2 — Graph: semantic-zoom navigator (never hundreds of nodes) + proposals + scoping
const { useState: useStateG2, useEffect: useEffectG2 } = React;

function G2Node({ n, depth, expanded, onToggle, onScope, scoped }) {
  const hasKids = n.kids && n.kids.length > 0;
  return (
    <div>
      <div onClick={() => { onScope(n); hasKids && onToggle(n.id); }}
        style={{ display: "flex", alignItems: "center", gap: 9, padding: "7px 10px", paddingLeft: 10 + depth * 18, borderRadius: 4, cursor: "pointer", background: scoped === n.id ? "color-mix(in srgb, var(--acc) 8%, transparent)" : "transparent", borderLeft: scoped === n.id ? "2px solid var(--acc)" : "2px solid transparent" }}
        onMouseEnter={(e) => e.currentTarget.style.background = scoped === n.id ? "" : "var(--sur2)"} onMouseLeave={(e) => e.currentTarget.style.background = scoped === n.id ? "color-mix(in srgb, var(--acc) 8%, transparent)" : "transparent"}>
        <span style={{ width: 12, color: "var(--mut)", fontSize: 9, flexShrink: 0 }}>{hasKids ? (expanded.has(n.id) ? "▾" : "▸") : ""}</span>
        <span style={{ width: 7, height: 7, borderRadius: n.d === "me" ? 1 : 99, background: dcol(n.d), flexShrink: 0 }} className={n.hot ? "gm-orb" : ""}></span>
        <span style={{ fontFamily: "var(--mono)", fontSize: 11.5, color: n.honest ? "var(--warn)" : "var(--tx)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{n.label}</span>
        {n.honest && <Mono size={7.5} color="var(--warn)">UNCONFIRMED</Mono>}
      </div>
      {hasKids && expanded.has(n.id) && (
        <div>
          {n.kids.map((k) => <G2Node key={k.id} n={k} depth={depth + 1} expanded={expanded} onToggle={onToggle} onScope={onScope} scoped={scoped} />)}
          {n.more && <div style={{ paddingLeft: 28 + depth * 18, padding: "5px 10px 5px " + (28 + (depth + 1) * 18) + "px" }}><Mono size={8.5} style={{ cursor: "pointer" }}>+ {n.more.toLocaleString()} more — zoom in or search, never all at once</Mono></div>}
        </div>
      )}
    </div>
  );
}

function GraphScreen2({ world, scope, setScope, openChat, onToast }) {
  const [expanded, setExpanded] = useStateG2(new Set());
  const [confirmed, setConfirmed] = useStateG2({});
  useEffectG2(() => { setExpanded(new Set()); setConfirmed({}); }, [world.id]);

  const toggle = (id) => setExpanded((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const flat = [];
  const walk = (n) => { flat.push(n); if (n.kids && expanded.has(n.id)) n.kids.forEach(walk); };
  world.graph.roots.forEach(walk);
  const visibleIds = new Set(flat.map((n) => n.id));
  const links = world.graph.links.filter(([a, b]) => visibleIds.has(a) && visibleIds.has(b));

  const findLabel = (id) => { let out = null; const w = (n) => { if (n.id === id) out = n.label; (n.kids || []).forEach(w); }; world.graph.roots.forEach(w); return out || id; };

  return (
    <div style={{ flex: 1, display: "flex", minWidth: 0, minHeight: 0 }} data-screen-label="Graph">
      {/* navigator */}
      <div style={{ flex: 1, overflowY: "auto", minWidth: 0, padding: "18px 20px 40px" }}>
        <div style={{ maxWidth: 640, margin: "0 auto" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
            <h1 style={{ margin: 0, fontSize: 21, fontWeight: 600 }}>Graph</h1>
            <Mono size={9}>SEMANTIC ZOOM — ONE NODE PER INTEGRATION, DRILL IN</Mono>
          </div>
          <p style={{ fontSize: 12, color: "var(--mut)", margin: "6px 0 14px", lineHeight: 1.55 }}>A navigator, not a picture. Selecting a node scopes every other surface to it.</p>
          <Card pad={0}>
            <div style={{ padding: "6px 4px" }}>
              {world.graph.roots.map((r) => <G2Node key={r.id} n={r} depth={0} expanded={expanded} onToggle={toggle} onScope={(n) => setScope({ id: n.id, label: n.label, kind: "node" })} scoped={scope && scope.id} />)}
            </div>
          </Card>

          {/* cross-domain links between visible nodes */}
          <div style={{ marginTop: 16 }}>
            <Mono size={9}>CROSS-DOMAIN LINKS {links.length > 0 ? `· ${links.length} VISIBLE` : ""}</Mono>
            {links.length === 0
              ? <Card pad={12} style={{ marginTop: 8 }}><div style={{ fontSize: 11.5, color: "var(--mut)", lineHeight: 1.6 }}>None between what's expanded. Drill into two integrations — links appear when both ends are visible.</div></Card>
              : <Card pad={0} style={{ marginTop: 8 }}>
                  {links.map(([a, b, lbl], i) => (
                    <div key={i} style={{ display: "flex", alignItems: "center", gap: 9, padding: "9px 14px", borderBottom: "1px solid var(--bd)", fontSize: 11.5 }}>
                      <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--tx)" }}>{findLabel(a)}</span>
                      <span style={{ color: "var(--acc)", display: "inline-flex", alignItems: "center", gap: 4, flexShrink: 0 }}><span style={{ width: 18, height: 0, borderTop: "1.5px dashed var(--acc)" }}></span>{SI.arrowR({ size: 11 })}</span>
                      <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--tx)" }}>{findLabel(b)}</span>
                      <span style={{ color: "var(--mut)", fontSize: 10.5, marginLeft: "auto", flexShrink: 0 }}>{lbl}</span>
                    </div>
                  ))}
                </Card>}
          </div>

          {/* proposals */}
          <div style={{ marginTop: 16 }}>
            <Mono size={9}>PROPOSED MATCHES — CONFIRMED BY YOU, NEVER SILENTLY</Mono>
            <Card pad={0} style={{ marginTop: 8 }}>
              {world.graph.proposals.map((p, i) => {
                const st = confirmed[i];
                return (
                  <div key={i} style={{ padding: "11px 14px", borderBottom: "1px solid var(--bd)", opacity: st === "no" ? 0.5 : 1 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                      <span style={{ fontFamily: "var(--mono)", fontSize: 11 }}>{p.a}</span>
                      <span style={{ color: "var(--acc)" }}>≟</span>
                      <span style={{ fontFamily: "var(--mono)", fontSize: 11 }}>{p.b}</span>
                      <span style={{ fontFamily: "var(--mono)", fontSize: 9.5, color: p.conf >= 0.85 ? "var(--ok)" : "var(--warn)", marginLeft: "auto" }}>{Math.round(p.conf * 100)}%</span>
                    </div>
                    <div style={{ fontSize: 10.5, color: "var(--mut)", marginTop: 4 }}>evidence: {p.ev}</div>
                    <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
                      {st === "yes" ? <span style={{ fontSize: 11, color: "var(--ok)", display: "inline-flex", gap: 6, alignItems: "center" }}>{SI.check({ size: 12 })} confirmed — link is now solid</span>
                        : st === "no" ? <span style={{ fontSize: 11, color: "var(--mut)" }}>dismissed — stays visible as unlinked</span>
                        : <>
                            <Btn kind="primary" size="sm" onClick={() => { setConfirmed((c) => ({ ...c, [i]: "yes" })); onToast("Match confirmed", "The link is solid now and downstream findings can use it."); }}>Confirm</Btn>
                            <Btn kind="ghost" size="sm" onClick={() => setConfirmed((c) => ({ ...c, [i]: "no" }))}>Not the same</Btn>
                          </>}
                    </div>
                  </div>
                );
              })}
            </Card>
          </div>
        </div>
      </div>

      {/* scope panel */}
      <div style={{ width: 280, borderLeft: "1px solid var(--bd)", background: "var(--sur)", padding: "18px 16px", flexShrink: 0, overflowY: "auto" }}>
        {!scope ? (
          <div style={{ color: "var(--mut)", fontSize: 12, lineHeight: 1.65, paddingTop: 30, textAlign: "center" }}>
            {SI.graph({ size: 24 })}<br /><br />Select anything — the bench, experiments, and widgets re-scope to it.
          </div>
        ) : (
          <div>
            <Mono size={8.5} color="var(--acc)">CURRENT SCOPE</Mono>
            <div style={{ fontFamily: "var(--mono)", fontSize: 14, marginTop: 7, lineHeight: 1.4 }}>{scope.label}</div>
            <div style={{ fontSize: 11, color: "var(--mut)", marginTop: 4 }}>Every surface is filtered to this until you clear it.</div>
            <div style={{ display: "flex", gap: 6, marginTop: 12 }}>
              <Btn kind="ghost" size="sm" onClick={() => setScope(null)}>Clear</Btn>
              <Btn kind="primary" size="sm" onClick={() => openChat("hello")}>Ask SOL about it</Btn>
            </div>
            <div style={{ marginTop: 18, borderTop: "1px solid var(--bd)", paddingTop: 12 }}>
              <Mono size={8.5}>WHAT RE-SCOPES</Mono>
              {["Live Bench — highlights its signals", "Experiments — filters runs touching it", "Workspace — widgets mark related content"].map((s) => (
                <div key={s} style={{ fontSize: 11, color: "var(--mut)", padding: "6px 0", borderBottom: "1px solid var(--bd)", lineHeight: 1.5 }}>{s}</div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

Object.assign(window, { GraphScreen2 });
