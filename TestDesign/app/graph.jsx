// Solus — Context Model graph screen (hi-fi, interactive)
const { useState: useStateG, useEffect: useEffectG, useRef: useRefG, useMemo: useMemoG } = React;

function GraphScreen({ alerts, onOpenAlert, onAskSol }) {
  const [sel, setSel] = useStateG("drv");
  const [domains, setDomains] = useStateG({ sw: true, ee: true, me: true, rt: true });
  const [xOnly, setXOnly] = useStateG(false);
  const [view, setView] = useStateG({ s: 1, x: 0, y: 0 });
  const [loaded, setLoaded] = useStateG(false);
  const [hover, setHover] = useStateG(null);
  const dragRef = useRefG(null);

  useEffectG(() => { const t = setTimeout(() => setLoaded(true), 250); return () => clearTimeout(t); }, []);

  const byId = useMemoG(() => { const m = {}; GRAPH.nodes.forEach((n) => (m[n.id] = n)); return m; }, []);
  const selNode = sel ? byId[sel] : null;
  const neighbors = useMemoG(() => {
    const m = {};
    GRAPH.edges.forEach(([a, b, label]) => {
      (m[a] = m[a] || []).push({ id: b, label });
      (m[b] = m[b] || []).push({ id: a, label });
    });
    return m;
  }, []);

  const visible = (n) => domains[n.d];
  const edgeVisible = ([a, b]) => {
    const A = byId[a], B = byId[b];
    if (!visible(A) || !visible(B)) return false;
    if (xOnly && A.d === B.d) return false;
    return true;
  };
  const openAlertFor = (n) => n.alert && alerts.find((al) => al.id === n.alert && al.state === "open");

  // pan handlers
  const onDown = (e) => {
    if (e.target.closest(".gnode")) return;
    dragRef.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y };
  };
  const onMove = (e) => {
    if (!dragRef.current) return;
    const d = dragRef.current;
    setView((v) => ({ ...v, x: d.vx + (e.clientX - d.x), y: d.vy + (e.clientY - d.y) }));
  };
  const onUp = () => (dragRef.current = null);
  const zoom = (f) => setView((v) => ({ ...v, s: Math.min(1.6, Math.max(0.55, v.s * f)) }));

  const hotSet = hover ? new Set([hover, ...(neighbors[hover] || []).map((n) => n.id)]) : null;

  return (
    <div style={{ flex: 1, display: "flex", minWidth: 0, minHeight: 0 }}>
      {/* canvas */}
      <div style={{ flex: 1, position: "relative", overflow: "hidden", minWidth: 0, backgroundImage: "radial-gradient(var(--bd) 1px, transparent 1px)", backgroundSize: "26px 26px", cursor: dragRef.current ? "grabbing" : "grab" }}
        onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerLeave={onUp}>
        {!loaded && (
          <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", gap: 10, color: "var(--mut)", fontFamily: "var(--mono)", fontSize: 11 }}>
            <Spinner /> LOADING CONTEXT MODEL…
          </div>
        )}
        <svg width="100%" height="100%" viewBox={`0 0 ${GRAPH.vb[0]} ${GRAPH.vb[1]}`} preserveAspectRatio="xMidYMid meet"
          style={{ position: "absolute", inset: 0, opacity: loaded ? 1 : 0, transition: "opacity 0.4s" }}>
          <g transform={`translate(${view.x},${view.y}) scale(${view.s})`} style={{ transformOrigin: "550px 410px", transition: dragRef.current ? "none" : "transform 0.18s ease-out" }}>
            {GRAPH.hulls.map((h) => domains[h.d] && (
              <g key={h.d} style={{ pointerEvents: "none" }}>
                <rect x={h.x} y={h.y} width={h.w} height={h.h} rx="14" fill={dcol(h.d)} opacity="0.045"></rect>
                <rect x={h.x} y={h.y} width={h.w} height={h.h} rx="14" fill="none" stroke={dcol(h.d)} opacity="0.18" strokeDasharray="3 4"></rect>
                <text x={h.x + 14} y={h.y + 20} fontFamily="var(--mono)" fontSize="9.5" letterSpacing="2" fill={dcol(h.d)} opacity="0.8">{SolusDomains[h.d].label}</text>
              </g>
            ))}
            {GRAPH.edges.map((e, i) => {
              if (!edgeVisible(e)) return null;
              const [a, b, , hot] = e;
              const A = byId[a], B = byId[b];
              const dim = hotSet && !(hotSet.has(a) && hotSet.has(b));
              return hot ? (
                <line key={i} x1={A.x} y1={A.y} x2={B.x} y2={B.y} stroke="var(--acc)" strokeWidth="1.6" strokeDasharray="6 5" opacity={dim ? 0.2 : 0.9} className="gm-flow"></line>
              ) : (
                <line key={i} x1={A.x} y1={A.y} x2={B.x} y2={B.y} stroke="var(--tx)" strokeWidth="1" opacity={dim ? 0.04 : 0.13}></line>
              );
            })}
            {GRAPH.nodes.map((n, i) => {
              if (!visible(n)) return null;
              const w = n.l.length * 6.7 + 30;
              const isSel = sel === n.id;
              const al = openAlertFor(n);
              const dim = hotSet && !hotSet.has(n.id);
              return (
                <g key={n.id} className="gnode" transform={`translate(${n.x - w / 2}, ${n.y - 13})`}
                  style={{ cursor: "pointer", opacity: loaded ? (dim ? 0.35 : 1) : 0, transition: `opacity 0.3s ${i * 0.025}s` }}
                  onClick={() => setSel(n.id)} onMouseEnter={() => setHover(n.id)} onMouseLeave={() => setHover(null)}>
                  {isSel && <rect x="-4" y="-4" width={w + 8} height="34" rx="8" fill="none" stroke="var(--acc)" strokeWidth="1.5"></rect>}
                  <rect width={w} height="26" rx="5" fill="var(--sur2)" stroke={n.hot ? `color-mix(in srgb, ${dcol(n.d)} 65%, transparent)` : `color-mix(in srgb, ${dcol(n.d)} 32%, transparent)`} strokeWidth="1"></rect>
                  <circle cx="14" cy="13" r="3.2" fill={dcol(n.d)}></circle>
                  <text x="24" y="17" fontFamily="var(--mono)" fontSize="10.5" fill="var(--tx)">{n.l}</text>
                  {al && <circle cx={w - 1} cy="1" r="4.5" fill={al.sev === "critical" ? "var(--err)" : "var(--warn)"} className="gm-orb"></circle>}
                </g>
              );
            })}
          </g>
        </svg>

        <div style={{ position: "absolute", left: 16, bottom: 52, pointerEvents: "none" }}>
          <Mono size={10} style={{ letterSpacing: "0.08em" }}>247 NODES · 31 CROSS-DOMAIN LINKS · SYNCED 2 MIN AGO</Mono>
        </div>
        <div style={{ position: "absolute", left: 16, bottom: 14, display: "flex", gap: 2, background: "var(--sur)", border: "1px solid var(--bd)", borderRadius: 3, overflow: "hidden" }}>
          <span onClick={() => zoom(0.85)} style={{ fontFamily: "var(--mono)", fontSize: 13, color: "var(--mut)", padding: "5px 11px", borderRight: "1px solid var(--bd)", cursor: "pointer", userSelect: "none" }}>−</span>
          <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--mut)", padding: "7px 10px", borderRight: "1px solid var(--bd)" }}>{Math.round(view.s * 100)}%</span>
          <span onClick={() => zoom(1.18)} style={{ fontFamily: "var(--mono)", fontSize: 13, color: "var(--mut)", padding: "5px 11px", borderRight: "1px solid var(--bd)", cursor: "pointer", userSelect: "none" }}>+</span>
          <span onClick={() => setView({ s: 1, x: 0, y: 0 })} style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--mut)", padding: "7px 11px", cursor: "pointer", userSelect: "none" }}>⛶</span>
        </div>
        <div style={{ position: "absolute", right: 16, bottom: 14, display: "flex", gap: 8, alignItems: "center" }}>
          <span onClick={() => setXOnly(!xOnly)} style={{ fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.05em", padding: "5px 10px", borderRadius: 99, cursor: "pointer", userSelect: "none", color: xOnly ? "var(--acc)" : "var(--mut)", background: xOnly ? "color-mix(in srgb, var(--acc) 10%, transparent)" : "var(--sur)", border: `1px solid ${xOnly ? "color-mix(in srgb, var(--acc) 40%, transparent)" : "var(--bd)"}` }}>
            CROSS-DOMAIN ONLY
          </span>
        </div>

        {/* domain filter bar */}
        <div style={{ position: "absolute", top: 12, left: "50%", transform: "translateX(-50%)", display: "flex", gap: 6, background: "color-mix(in srgb, var(--sur) 88%, transparent)", backdropFilter: "blur(6px)", border: "1px solid var(--bd)", borderRadius: 99, padding: "5px 8px" }}>
          {["sw", "ee", "me", "rt"].map((k) => (
            <DomainChip key={k} d={k} small on={domains[k]} onClick={() => setDomains((d) => ({ ...d, [k]: !d[k] }))} />
          ))}
        </div>
      </div>

      {/* detail panel */}
      <div style={{ width: 318, borderLeft: "1px solid var(--bd)", background: "var(--sur)", display: "flex", flexDirection: "column", flexShrink: 0, overflowY: "auto" }}>
        {!selNode && (
          <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 12, padding: 32, textAlign: "center" }}>
            <span style={{ color: "var(--mut)", opacity: 0.6 }}>{SI.graph({ size: 28 })}</span>
            <div style={{ fontSize: 13, color: "var(--mut)", lineHeight: 1.6 }}>Select a node to inspect it —<br />properties, sources, and its links across domains.</div>
          </div>
        )}
        {selNode && (() => {
          const al = openAlertFor(selNode);
          const conns = (neighbors[selNode.id] || []).map((c) => ({ ...byId[c.id], elabel: c.label }));
          return (
            <div style={{ padding: "18px 18px 14px", display: "flex", flexDirection: "column", minHeight: "100%", boxSizing: "border-box" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    <Mono size={9.5} color={dcol(selNode.d)}>● {SolusDomains[selNode.d].label} · {selNode.type}</Mono>
                  </div>
                  <div style={{ fontSize: 19, fontWeight: 650, marginTop: 6, letterSpacing: "-0.01em", fontFamily: "var(--mono)" }}>{selNode.l}</div>
                  <div style={{ fontSize: 12, color: "var(--mut)", marginTop: 2 }}>{selNode.sub}</div>
                </div>
                <span onClick={() => setSel(null)} style={{ color: "var(--mut)", cursor: "pointer", padding: 4 }}>{SI.x({ size: 13 })}</span>
              </div>

              {al && (
                <div id="panel-alert-chip" onClick={() => onOpenAlert(al.id)} style={{ marginTop: 14, background: "color-mix(in srgb, var(--err) 8%, transparent)", border: "1px solid color-mix(in srgb, var(--err) 40%, transparent)", borderRadius: 3, padding: "9px 11px", display: "flex", gap: 9, alignItems: "center", cursor: "pointer" }}>
                  <span style={{ width: 7, height: 7, borderRadius: 99, background: "var(--err)", boxShadow: "0 0 8px var(--err)", flexShrink: 0 }} className="gm-orb"></span>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 11.5, fontWeight: 600 }}>{al.title}</div>
                    <div style={{ fontSize: 10.5, color: "var(--mut)" }}>{al.actor} · {al.time} — view alert</div>
                  </div>
                  {SI.arrowR({ size: 12 })}
                </div>
              )}

              <div style={{ marginTop: 14 }}>
                {selNode.props.map(([k, v]) => <KV key={k} k={k} v={v} />)}
              </div>

              <Mono size={9.5} style={{ marginTop: 18, marginBottom: 2 }}>CONNECTED ACROSS DOMAINS</Mono>
              {conns.map((c) => (
                <div key={c.id} onClick={() => setSel(c.id)} style={{ display: "flex", alignItems: "center", gap: 9, padding: "8px 0", borderBottom: "1px solid var(--bd)", cursor: "pointer" }}>
                  <span style={{ width: 6, height: 6, borderRadius: 99, background: dcol(c.d), flexShrink: 0 }}></span>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--tx)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{c.l}</div>
                    <div style={{ fontSize: 10, color: "var(--mut)" }}>{c.elabel || c.sub}</div>
                  </div>
                  <span style={{ color: "var(--mut)" }}>{SI.arrowR({ size: 11 })}</span>
                </div>
              ))}

              <div style={{ flex: 1, minHeight: 18 }}></div>
              <div style={{ display: "flex", gap: 8, paddingBottom: 4 }}>
                <Btn kind="ghost" style={{ flex: 1 }} size="sm">Open in {selNode.d === "ee" ? "KiCad" : selNode.d === "me" ? "Onshape" : selNode.d === "sw" ? "GitHub" : "ROS"}</Btn>
                <Btn kind="primary" style={{ flex: 1 }} size="sm" onClick={() => onAskSol(selNode.alert ? "alertq" : "hello")}>Ask SOL</Btn>
              </div>
            </div>
          );
        })()}
      </div>
    </div>
  );
}

Object.assign(window, { GraphScreen });
