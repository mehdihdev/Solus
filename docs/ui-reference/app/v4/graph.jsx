// Solus v4 — generic Prezi graph: any node with a 2-level tree; fractal boxes; cursor zoom; fly-to; right-click menus
const { useState: useG4, useEffect: useEG4, useRef: useRG4, useMemo: useMG4 } = React;
const G4_SLOTS = [[250, 215], [720, 480], [880, 195], [300, 575], [1020, 545], [575, 118], [1040, 335], [150, 400], [560, 640], [820, 640]];
const VB4 = { w: 1160, h: 720 };
const KIND_RX = { robot: 14, widget: 30, doc: 11, repo: 11, sim: 11, log: 11, solus: 6 };

function g4Layout(node, i) {
  const [sx, sy] = G4_SLOTS[i % G4_SLOTS.length];
  const kids = node.tree || [];
  const W = node.kind === "widget" ? 150 : 252, colW = 113, gap = 7, colY = [0, 0];
  const children = kids.map((k) => {
    const h = k.kids ? 13 + k.kids.length * 11 + 4 : 20;
    const col = colY[0] <= colY[1] ? 0 : 1;
    const cell = { x: 9 + col * (colW + gap), y: 30 + colY[col], w: colW, h }; colY[col] += h + gap;
    return { ...k, box: cell, comps: (k.kids || []).map((sk, si) => ({ ...sk, box: { x: cell.x + 4, y: cell.y + 13 + si * 11, w: colW - 8, h: 9.5 } })) };
  });
  const H = node.kind === "widget" ? 56 : Math.max(92, 38 + Math.max(colY[0], colY[1]));
  const box = { x: sx - W / 2, y: sy - H / 2, w: W, h: H, cx: sx, cy: sy };
  const pos = {};
  children.forEach((c) => { pos[c.l] = { x: box.x + c.box.x + c.box.w / 2, y: box.y + c.box.y + c.box.h / 2 }; c.comps.forEach((s) => (pos[s.l] = { x: box.x + s.box.x + s.box.w / 2, y: box.y + s.box.y + s.box.h / 2 })); });
  return { node, box, children, pos };
}

function Graph4({ nodes, links, suggestions, sel, setSel, onSuggest, onPartMenu, onNodeMenu, resetKey, overlayTL }) {
  const [cam, setCam] = useG4({ cx: 580, cy: 360, s: 0.85 });
  const [ms, setMs] = useG4(700);
  const [menu, setMenu] = useG4(null);
  const svgRef = useRG4(null), drag = useRG4(null);
  useEG4(() => { setCam({ cx: 580, cy: 360, s: 0.85 }); setMenu(null); }, [resetKey]);
  const L = useMG4(() => { const m = {}; nodes.forEach((n, i) => (m[n.id] = g4Layout(n, i))); return m; }, [nodes]);
  const s = cam.s, lod = (a, b) => Math.max(0, Math.min(1, (s - a) / (b - a)));
  const childOp = lod(0.85, 1.3), compOp = lod(1.9, 2.8), topFade = 1 - lod(1.0, 1.5);
  const FADE = { transition: "opacity 0.55s cubic-bezier(.3,.7,.3,1)" };
  const toVb = (e) => { const r = svgRef.current.getBoundingClientRect(); const k = Math.min(r.width / VB4.w, r.height / VB4.h); return { px: (e.clientX - r.left - (r.width - VB4.w * k) / 2) / k, py: (e.clientY - r.top - (r.height - VB4.h * k) / 2) / k, k }; };
  const clampS = (v) => Math.min(6.2, Math.max(0.5, v));
  const onWheel = (e) => { const { px, py } = toVb(e); const wx = (px - VB4.w / 2) / s + cam.cx, wy = (py - VB4.h / 2) / s + cam.cy; const s2 = clampS(s * (e.deltaY < 0 ? 1.22 : 0.82)); setMs(300); setCam({ s: s2, cx: wx - (px - VB4.w / 2) / s2, cy: wy - (py - VB4.h / 2) / s2 }); };
  const flyTo = (cx, cy, s2) => { setMs(700); setCam({ cx, cy, s: clampS(s2) }); };
  const onDown = (e) => { setMenu(null); if (e.target.closest(".g4n") || e.button === 2) return; const { k } = toVb(e); drag.current = { x: e.clientX, y: e.clientY, cx: cam.cx, cy: cam.cy, k }; };
  const onMove = (e) => { const d = drag.current; if (!d) return; setMs(0); setCam((c) => ({ ...c, cx: d.cx - (e.clientX - d.x) / d.k / s, cy: d.cy - (e.clientY - d.y) / d.k / s })); };
  const onUp = () => (drag.current = null);
  const ctx = (e, items) => { e.preventDefault(); e.stopPropagation(); const r = svgRef.current.parentElement.getBoundingClientRect(); setMenu({ x: e.clientX - r.left, y: e.clientY - r.top, items }); };

  return (
    <div style={{ flex: 1, position: "relative", overflow: "hidden", minWidth: 0, backgroundImage: "radial-gradient(var(--bd) 1px, transparent 1px)", backgroundSize: "26px 26px", cursor: drag.current ? "grabbing" : "grab" }}
      onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerLeave={onUp} onWheel={onWheel} onContextMenu={(e) => e.preventDefault()}>
      <svg ref={svgRef} width="100%" height="100%" viewBox={`0 0 ${VB4.w} ${VB4.h}`} preserveAspectRatio="xMidYMid meet" style={{ position: "absolute", inset: 0 }}>
        <g style={{ transform: `translate(${VB4.w / 2}px, ${VB4.h / 2}px) scale(${s}) translate(${-cam.cx}px, ${-cam.cy}px)`, transition: ms ? `transform ${ms}ms cubic-bezier(.25,.85,.25,1)` : "none" }}>
          {links.map((l, k) => {
            const A = L[l.a], B = L[l.b]; if (!A || !B) return null;
            const a2 = l.a2 && A.pos[l.a2], b2 = l.b2 && B.pos[l.b2];
            const wpx = (1.4 + Math.min(l.n, 14) * 0.32) / Math.sqrt(s);
            const edge = (P, Q, op, label, fs, lift) => { const mx = (P.x + Q.x) / 2, my = (P.y + Q.y) / 2 - lift; return (<g opacity={op}><path d={`M${P.x} ${P.y} Q ${mx} ${my} ${Q.x} ${Q.y}`} fill="none" stroke={l.hot ? "var(--acc)" : "var(--tx)"} strokeWidth={wpx} strokeDasharray={l.hot ? "10 7" : "none"} className={l.hot ? "gm-flow" : ""} opacity={l.hot ? 0.75 : 0.45}></path><text x={mx} y={my + 11} textAnchor="middle" fontFamily="var(--mono)" fontSize={fs} fill={l.hot ? "var(--acc)" : "var(--mut)"}>{label}</text></g>); };
            return (<g key={k} style={FADE}>{edge({ x: A.box.cx, y: A.box.cy }, { x: B.box.cx, y: B.box.cy }, (l.hot ? 0.6 : 0.16) * (a2 ? Math.max(topFade, 0.12) : 1), `${l.n} link${l.n > 1 ? "s" : ""} · ${l.label}`, 10 / Math.sqrt(s), 26)}{a2 && b2 && childOp > 0.02 && edge(a2, b2, childOp, l.label2 || l.label, 5.2, 12)}</g>);
          })}
          {/* suggestion edges: dashed, unconfirmed */}
          {(suggestions || []).map((sg, k) => { const B = L["robot:" + sg.to]; if (!B) return null; const gx = B.box.x - 150, gy = B.box.y - 60; return (
            <g key={"sg" + k} className="g4n" style={{ cursor: "pointer" }} onClick={(e) => { e.stopPropagation(); onSuggest(sg); }}>
              <path d={`M${gx + 70} ${gy + 20} Q ${(gx + B.box.cx) / 2} ${gy - 30} ${B.box.x + 20} ${B.box.y}`} fill="none" stroke="var(--warn)" strokeWidth={1.4 / Math.sqrt(s)} strokeDasharray="4 4" opacity="0.8"></path>
              <rect x={gx} y={gy} width="140" height="40" rx="8" fill="var(--sur2)" stroke="var(--warn)" strokeDasharray="4 3" strokeWidth={1 / Math.sqrt(s)}></rect>
              <text x={gx + 10} y={gy + 16} fontFamily="var(--mono)" fontSize="8.5" fill="var(--tx)">{sg.what.length > 26 ? sg.what.slice(0, 26) + "…" : sg.what}</text>
              <text x={gx + 10} y={gy + 30} fontFamily="var(--mono)" fontSize="7.5" fill="var(--warn)">belongs to {nodes.find((n) => n.id === "robot:" + sg.to)?.name}? {Math.round(sg.conf * 100)}% — click</text>
            </g>); })}
          {nodes.map((n) => {
            const b = L[n.id].box, isSel = sel === n.id, rx = KIND_RX[n.kind] || 11, hasAlert = n.alert;
            return (
              <g key={n.id} className="g4n" style={{ cursor: "pointer" }} onClick={(e) => { e.stopPropagation(); setSel(n.id); flyTo(b.cx, b.cy, n.kind === "widget" ? 1.6 : 2.4); }} onContextMenu={(e) => onNodeMenu && ctx(e, onNodeMenu(n))}>
                {isSel && <rect x={b.x - 5} y={b.y - 5} width={b.w + 10} height={b.h + 10} rx={rx + 4} fill="none" stroke="var(--acc)" strokeWidth={1.5 / s} opacity="0.9"></rect>}
                <rect x={b.x} y={b.y} width={b.w} height={b.h} rx={rx} fill={n.kind === "widget" ? "var(--bg)" : "var(--sur2)"} stroke={hasAlert ? "color-mix(in srgb, var(--err) 55%, var(--bd))" : n.kind === "robot" ? "var(--acc)" : n.kind === "solus" ? "color-mix(in srgb, var(--acc) 60%, transparent)" : `color-mix(in srgb, ${dcol(n.domain)} 42%, transparent)`} strokeWidth={(n.kind === "robot" ? 1.8 : 1.5) / Math.sqrt(s)} strokeDasharray={n.kind === "widget" || n.kind === "solus" ? "3 3" : "none"} opacity={n.kind === "widget" ? 0.85 : 1}></rect>
                {n.kind === "robot" ? <g transform={`translate(${b.x + 12},${b.y + 10})`}><rect width="12" height="12" rx="2" fill="none" stroke="var(--acc)" strokeWidth="1.4"></rect><circle cx="6" cy="6" r="2" fill="var(--acc)"></circle></g> : n.kind === "solus" ? <text x={b.x + 12} y={b.y + 22} fontFamily="var(--mono)" fontSize="11" fill="var(--acc)">.s</text> : <circle cx={b.x + 18} cy={b.y + 17} r="5" fill={dcol(n.domain)}></circle>}
                <text x={b.x + 30} y={b.y + 21.5} fontSize="13" fontWeight="600" fill="var(--tx)" fontFamily={n.kind === "solus" ? "var(--mono)" : "var(--ui)"}>{n.name}</text>
                {n.kind === "robot" && <text x={b.x + b.w - 10} y={b.y + 21} textAnchor="end" fontFamily="var(--mono)" fontSize="7.5" fill="var(--acc)" letterSpacing="1">PHYSICAL ROBOT</text>}
                {n.kind === "solus" && <text x={b.x + b.w - 10} y={b.y + 21} textAnchor="end" fontFamily="var(--mono)" fontSize="7.5" fill="var(--acc)" letterSpacing="1">ROOT + PROJECT</text>}
                {hasAlert && <circle cx={b.x + b.w - 2} cy={b.y + 2} r={5 / Math.sqrt(s)} fill="var(--err)" className="gm-orb"></circle>}
                <text x={b.x + 12} y={b.y + b.h - 8} fontFamily="var(--mono)" fontSize="9" fill="var(--mut)" style={{ opacity: n.kind === "widget" ? 1 : 1 - childOp, ...FADE }}>{n.detail.length > 36 ? n.detail.slice(0, 36) + "…" : n.detail}</text>
                {n.kind !== "widget" && n.tree.length === 0 && <text x={b.x + 12} y={b.y + 48} fontFamily="var(--mono)" fontSize="8.5" fill="var(--mut)" style={{ opacity: childOp, ...FADE }}>empty — nothing inside yet, and nothing invented</text>}
                <g style={{ opacity: childOp, pointerEvents: childOp > 0.4 ? "auto" : "none", ...FADE }}>
                  {L[n.id].children.map((ch, j) => { const cb = { x: b.x + ch.box.x, y: b.y + ch.box.y, w: ch.box.w, h: ch.box.h }; return (
                    <g key={j} onClick={(e) => { e.stopPropagation(); setSel(n.id); flyTo(cb.x + cb.w / 2, cb.y + cb.h / 2, ch.comps.length ? 5 : 4.2); }}>
                      <rect x={cb.x} y={cb.y} width={cb.w} height={cb.h} rx="4" fill="var(--bg)" stroke={ch.hot ? "var(--acc)" : `color-mix(in srgb, ${dcol(ch.d)} 36%, transparent)`} strokeWidth={(ch.hot ? 1.1 : 0.8) / Math.sqrt(s)} opacity="0.97"></rect>
                      <circle cx={cb.x + 7} cy={cb.y + 6.8} r="2.1" fill={dcol(ch.d)}></circle>
                      <text x={cb.x + 12} y={cb.y + 9} fontFamily="var(--mono)" fontSize="6.4" fill={ch.honest ? "var(--warn)" : "var(--tx)"}>{ch.l.length > 21 ? ch.l.slice(0, 21) + "…" : ch.l}{ch.hot ? " ●" : ""}</text>
                      {ch.comps.length > 0 && <text x={cb.x + 12} y={cb.y + 18} fontFamily="var(--mono)" fontSize="4.6" fill="var(--mut)" style={{ opacity: 1 - compOp, ...FADE }}>{ch.comps.length} inside — keep zooming</text>}
                      <g style={{ opacity: compOp, pointerEvents: compOp > 0.4 ? "auto" : "none", ...FADE }}>
                        {ch.comps.map((sk, si) => (
                          <g key={si} onClick={(e) => { e.stopPropagation(); setSel(n.id); }} onContextMenu={(e) => sk.part && onPartMenu && ctx(e, onPartMenu(sk.part, n))}>
                            <rect x={b.x + sk.box.x} y={b.y + sk.box.y} width={sk.box.w} height={sk.box.h} rx="2.5" fill="var(--sur)" stroke={sk.hot ? "var(--acc)" : "var(--bd)"} strokeWidth={0.55 / Math.sqrt(s)} strokeDasharray={/planned|ordered/.test(sk.l) ? "1.5 1.5" : "none"}></rect>
                            <circle cx={b.x + sk.box.x + 5} cy={b.y + sk.box.y + 4.8} r="1.3" fill={dcol(sk.d)}></circle>
                            <text x={b.x + sk.box.x + 9} y={b.y + sk.box.y + 6.6} fontFamily="var(--mono)" fontSize="4.4" fill={sk.honest ? "var(--warn)" : sk.hot ? "var(--acc)" : "var(--tx)"}>{sk.l}</text>
                          </g>))}
                      </g>
                    </g>); })}
                </g>
              </g>);
          })}
        </g>
      </svg>
      {menu && (
        <div style={{ position: "absolute", left: menu.x, top: menu.y, zIndex: 40, background: "var(--sur)", border: "1px solid var(--bd)", borderRadius: 6, boxShadow: "0 16px 44px rgba(0,0,0,0.5)", padding: 5, minWidth: 190 }} onPointerDown={(e) => e.stopPropagation()}>
          {menu.items.map((it, i) => it.sep ? <div key={i} style={{ height: 1, background: "var(--bd)", margin: "4px 2px" }}></div> : (
            <div key={i} onClick={() => { setMenu(null); it.run && it.run(); }} style={{ padding: "6px 9px", fontSize: 12.5, borderRadius: 4, cursor: "pointer", color: it.danger ? "var(--err)" : "var(--tx)" }} onMouseEnter={(e) => (e.currentTarget.style.background = "var(--sur2)")} onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}>{it.label}</div>))}
        </div>)}
      <div style={{ position: "absolute", left: 16, bottom: 14, display: "flex", gap: 2, background: "var(--sur)", border: "1px solid var(--bd)", borderRadius: 3, overflow: "hidden" }}>
        {[["−", () => { setMs(300); setCam((c) => ({ ...c, s: clampS(c.s * 0.82) })); }], [Math.round(s * 100) + "%", null], ["+", () => { setMs(300); setCam((c) => ({ ...c, s: clampS(c.s * 1.22) })); }], ["⛶ overview", () => { setSel(null); flyTo(580, 360, 0.85); }]].map(([l, fn], i) => (
          <span key={i} onClick={fn || undefined} style={{ fontFamily: "var(--mono)", fontSize: fn && l.length === 1 ? 13 : 11, color: "var(--mut)", padding: fn && l.length === 1 ? "5px 11px" : "7px 10px", borderRight: i < 3 ? "1px solid var(--bd)" : "none", cursor: fn ? "pointer" : "default", userSelect: "none" }}>{l}</span>))}
      </div>
      {overlayTL}
    </div>
  );
}
Object.assign(window, { Graph4 });
