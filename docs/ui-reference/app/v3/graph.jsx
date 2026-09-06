// Solus v3 — Graph: Prezi-style constellation. Boxes within boxes, cursor-anchored zoom,
// click-to-fly camera, and edges that re-anchor to specific children as you zoom in.
const { useState: useG3, useEffect: useEG3, useRef: useRG3, useMemo: useMG3 } = React;

const G3_SLOTS = [[240, 210], [720, 480], [870, 190], [300, 575], [1010, 545], [565, 115], [1030, 330], [150, 400]];
const VB = { w: 1160, h: 720 };

/* fractal layout: an inner box has the same proportions an outer box has, one zoom level up.
   scale ratio per level ≈ 250/115 ≈ 2.2 — fly-in zooms match it so each level fills the frame alike. */
function layoutInst(inst, slotI) {
  const [sx, sy] = G3_SLOTS[slotI % G3_SLOTS.length];
  const kids = V3.CHILDREN[inst.id] || [];
  const W = 252, colW = 113, gap = 7;
  const colY = [0, 0];
  const children = kids.map((k) => {
    const h = k.kids ? 13 + k.kids.length * 11 + 4 : 20;
    const col = colY[0] <= colY[1] ? 0 : 1;
    const cell = { x: 9 + col * (colW + gap), y: 30 + colY[col], w: colW, h };
    colY[col] += h + gap;
    const comps = (k.kids || []).map((sk, si) => ({ ...sk, box: { x: cell.x + 4, y: cell.y + 13 + si * 11, w: colW - 8, h: 9.5 } }));
    return { ...k, box: cell, comps };
  });
  const H = Math.max(92, 38 + Math.max(colY[0], colY[1]));
  const box = { x: sx - W / 2, y: sy - H / 2, w: W, h: H, cx: sx, cy: sy };
  const childPos = {};
  children.forEach((c) => (childPos[c.l] = { x: box.x + c.box.x + c.box.w / 2, y: box.y + c.box.y + c.box.h / 2 }));
  return { inst, box, children, childPos };
}

function GraphScreen3({ world, scope, setScope, openSol, onToast }) {
  const [cam, setCam] = useG3({ cx: 580, cy: 360, s: 0.85 });
  const [transMs, setTransMs] = useG3(700);
  const [sel, setSel] = useG3(null);
  const svgRef = useRG3(null);
  const dragRef = useRG3(null);
  useEG3(() => { setSel(null); setCam({ cx: 580, cy: 360, s: 0.85 }); }, [world.connectedIds.join(",")]);

  const insts = world.graph.insts;
  const layouts = useMG3(() => { const m = {}; insts.forEach((c, i) => (m[c.id] = layoutInst(c, i))); return m; }, [insts]);
  const findingNodes = new Set(world.findings.map((f) => f.node));
  const selInst = insts.find((c) => c.id === sel);
  const s = cam.s;
  const lod = (a, b) => Math.max(0, Math.min(1, (s - a) / (b - a)));
  const childOp = lod(0.85, 1.3), compOp = lod(1.9, 2.8), topEdgeFade = 1 - lod(1.0, 1.5);
  const FADE = { transition: "opacity 0.55s cubic-bezier(.3,.7,.3,1)" };

  /* screen px → viewBox coords (preserveAspectRatio meet) */
  const toVb = (e) => {
    const r = svgRef.current.getBoundingClientRect();
    const k = Math.min(r.width / VB.w, r.height / VB.h);
    return { px: (e.clientX - r.left - (r.width - VB.w * k) / 2) / k, py: (e.clientY - r.top - (r.height - VB.h * k) / 2) / k, k };
  };
  const clampS = (v) => Math.min(6.2, Math.max(0.55, v));

  const onWheel = (e) => {
    const { px, py } = toVb(e);
    const wx = (px - VB.w / 2) / s + cam.cx, wy = (py - VB.h / 2) / s + cam.cy;
    const s2 = clampS(s * (e.deltaY < 0 ? 1.22 : 0.82));
    setTransMs(300);
    setCam({ s: s2, cx: wx - (px - VB.w / 2) / s2, cy: wy - (py - VB.h / 2) / s2 });
  };
  const flyTo = (cx, cy, s2) => { setTransMs(700); setCam({ cx, cy, s: clampS(s2) }); };
  const onDown = (e) => { if (e.target.closest(".g3n")) return; const { k } = toVb(e); dragRef.current = { x: e.clientX, y: e.clientY, cx: cam.cx, cy: cam.cy, k }; };
  const onMove = (e) => { const d = dragRef.current; if (!d) return; setTransMs(0); setCam((c) => ({ ...c, cx: d.cx - (e.clientX - d.x) / d.k / s, cy: d.cy - (e.clientY - d.y) / d.k / s })); };
  const onUp = () => (dragRef.current = null);

  if (insts.length === 0) return (
    <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }} data-screen-label="Graph">
      <div style={{ textAlign: "center", maxWidth: 380 }}>
        <span style={{ color: "var(--mut)", opacity: 0.6 }}>{SI.graph({ size: 30 })}</span>
        <div style={{ fontSize: 15, fontWeight: 600, marginTop: 12 }}>The graph is what you connect</div>
        <div style={{ fontSize: 12.5, color: "var(--mut)", marginTop: 8, lineHeight: 1.65 }}>Nothing here yet — and nothing invented to fill the space. Each tool, repo, or device you connect becomes a node; the links between them appear on their own.</div>
      </div>
    </div>
  );

  return (
    <div style={{ flex: 1, display: "flex", minWidth: 0, minHeight: 0 }} data-screen-label="Graph">
      <div style={{ flex: 1, position: "relative", overflow: "hidden", minWidth: 0, backgroundImage: "radial-gradient(var(--bd) 1px, transparent 1px)", backgroundSize: "26px 26px", cursor: dragRef.current ? "grabbing" : "grab" }}
        onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerLeave={onUp} onWheel={onWheel}>
        <svg ref={svgRef} width="100%" height="100%" viewBox={`0 0 ${VB.w} ${VB.h}`} preserveAspectRatio="xMidYMid meet" style={{ position: "absolute", inset: 0 }}>
            <g style={{ transform: `translate(${VB.w / 2}px, ${VB.h / 2}px) scale(${s}) translate(${-cam.cx}px, ${-cam.cy}px)`, transition: transMs ? `transform ${transMs}ms cubic-bezier(.25,.85,.25,1)` : "none" }}>
            {/* edges: integration-level fades out, child-level fades in */}
            {world.graph.links.map((l, k) => {
              const A = layouts[l.a].box, B = layouts[l.b].box;
              const a2 = l.a2 && layouts[l.a].childPos[l.a2], b2 = l.b2 && layouts[l.b].childPos[l.b2];
              const wpx = (1.4 + Math.min(l.n, 14) * 0.32) / Math.sqrt(s);
              const topOp = (l.hot ? 0.6 : 0.16) * (a2 ? Math.max(topEdgeFade, 0.12) : 1);
              const edge = (P, Q, op, label, fs, lift) => {
                const mx = (P.x + Q.x) / 2, my = (P.y + Q.y) / 2 - lift;
                return (
                  <g opacity={op}>
                    <path d={`M${P.x} ${P.y} Q ${mx} ${my} ${Q.x} ${Q.y}`} fill="none" stroke={l.hot ? "var(--acc)" : "var(--tx)"} strokeWidth={wpx} strokeDasharray={l.hot ? "10 7" : "none"} className={l.hot ? "gm-flow" : ""} opacity={l.hot ? 0.75 : 0.5}></path>
                    <text x={mx} y={my + 11} textAnchor="middle" fontFamily="var(--mono)" fontSize={fs} fill={l.hot ? "var(--acc)" : "var(--mut)"}>{label}</text>
                  </g>
                );
              };
              return (
                <g key={k} style={FADE}>
                  {edge({ x: A.cx, y: A.cy }, { x: B.cx, y: B.cy }, topOp, `${l.n} link${l.n > 1 ? "s" : ""} · ${l.label}`, 10 / Math.sqrt(s), 26)}
                  {a2 && b2 && childOp > 0.02 && edge(a2, b2, childOp, l.label2 || l.label, 5.2, 12)}
                </g>
              );
            })}

            {/* boxes within boxes */}
            {insts.map((c) => {
              const L = layouts[c.id];
              const b = L.box;
              const isSel = sel === c.id;
              const hasAlert = findingNodes.has(c.id);
              return (
                <g key={c.id} className="g3n" style={{ cursor: "pointer" }}
                  onClick={(e) => { e.stopPropagation(); setSel(c.id); setScope({ id: c.id, label: c.name, kind: "node" }); flyTo(b.cx, b.cy, 2.4); }}>
                  {isSel && <rect x={b.x - 5} y={b.y - 5} width={b.w + 10} height={b.h + 10} rx="14" fill="none" stroke="var(--acc)" strokeWidth={1.5 / s} opacity="0.9"></rect>}
                  <rect x={b.x} y={b.y} width={b.w} height={b.h} rx="11" fill="var(--sur2)" stroke={hasAlert ? "color-mix(in srgb, var(--err) 55%, var(--bd))" : `color-mix(in srgb, ${dcol(c.domain)} 42%, transparent)`} strokeWidth={1.5 / Math.sqrt(s)}></rect>
                  <circle cx={b.x + 18} cy={b.y + 17} r="5" fill={dcol(c.domain)}></circle>
                  <text x={b.x + 30} y={b.y + 21.5} fontSize="13" fontWeight="600" fill="var(--tx)" fontFamily="var(--ui)">{c.name}</text>
                  {hasAlert && <circle cx={b.x + b.w - 2} cy={b.y + 2} r={5 / Math.sqrt(s)} fill="var(--err)" className="gm-orb"></circle>}
                  {c.honest && <text x={b.x + b.w - 12} y={b.y + 20} textAnchor="end" fontFamily="var(--mono)" fontSize="10" fill="var(--warn)">?</text>}
                  {/* far-out summary */}
                  <text x={b.x + 12} y={b.y + b.h - 8} fontFamily="var(--mono)" fontSize="9" fill="var(--mut)" style={{ opacity: 1 - childOp, ...FADE }}>{c.detail.length > 34 ? c.detail.slice(0, 34) + "…" : c.detail}</text>
                  {/* children: fractal cards — same proportions as this box, one level down */}
                  <g style={{ opacity: childOp, pointerEvents: childOp > 0.4 ? "auto" : "none", ...FADE }}>
                    {L.children.map((ch, j) => {
                      const cb = { x: b.x + ch.box.x, y: b.y + ch.box.y, w: ch.box.w, h: ch.box.h };
                      return (
                        <g key={j} onClick={(e) => { e.stopPropagation(); setSel(c.id); setScope({ id: c.id + "/" + ch.l, label: ch.l, kind: "node" }); flyTo(cb.x + cb.w / 2, cb.y + cb.h / 2, ch.comps.length ? 5.0 : 4.2); }}>
                          <rect x={cb.x} y={cb.y} width={cb.w} height={cb.h} rx="4" fill="var(--bg)" stroke={ch.hot ? "var(--acc)" : `color-mix(in srgb, ${dcol(ch.d)} 36%, transparent)`} strokeWidth={(ch.hot ? 1.1 : 0.8) / Math.sqrt(s)} opacity="0.97"></rect>
                          <circle cx={cb.x + 7} cy={cb.y + 6.8} r="2.1" fill={dcol(ch.d)}></circle>
                          <text x={cb.x + 12} y={cb.y + 9} fontFamily="var(--mono)" fontSize="6.4" fill={ch.honest ? "var(--warn)" : "var(--tx)"}>{ch.l.length > 21 ? ch.l.slice(0, 21) + "…" : ch.l}{ch.hot ? " ●" : ""}</text>
                          {ch.comps.length > 0 && <text x={cb.x + 12} y={cb.y + 18} fontFamily="var(--mono)" fontSize="4.6" fill="var(--mut)" style={{ opacity: 1 - compOp, ...FADE }}>{ch.comps.length} components — keep zooming</text>}
                          <g style={{ opacity: compOp, ...FADE }}>
                            {ch.comps.map((sk, si) => (
                              <g key={si} onClick={(e) => { e.stopPropagation(); setSel(c.id); setScope({ id: c.id + "/" + sk.l, label: sk.l, kind: "node" }); }}>
                                <rect x={b.x + sk.box.x} y={b.y + sk.box.y} width={sk.box.w} height={sk.box.h} rx="2.5" fill="var(--sur)" stroke={sk.hot ? "var(--acc)" : "var(--bd)"} strokeWidth={0.55 / Math.sqrt(s)}></rect>
                                <circle cx={b.x + sk.box.x + 5} cy={b.y + sk.box.y + 4.8} r="1.3" fill={dcol(sk.d)}></circle>
                                <text x={b.x + sk.box.x + 9} y={b.y + sk.box.y + 6.6} fontFamily="var(--mono)" fontSize="4.4" fill={sk.hot ? "var(--acc)" : "var(--tx)"}>{sk.l}</text>
                              </g>
                            ))}
                          </g>
                        </g>
                      );
                    })}
                  </g>
                </g>
              );
            })}

            {/* honest ghost */}
            {insts.length < 6 && (() => {
              const ghost = V3.CATALOG.find((c) => !world.connectedIds.includes(c.id) && c.sect === "cloud");
              if (!ghost) return null;
              const [gx, gy] = G3_SLOTS[insts.length % G3_SLOTS.length];
              return (
                <g opacity="0.42" style={{ cursor: "pointer" }} className="g3n" onClick={() => onToast("Not connected", ghost.name + " appears here the moment you connect it.")}>
                  <rect x={gx - 78} y={gy - 40} width="156" height="80" rx="10" fill="none" stroke="var(--bd)" strokeDasharray="5 5"></rect>
                  <text x={gx - 62} y={gy - 8} fontSize="12.5" fill="var(--mut)" fontFamily="var(--ui)">{ghost.name}</text>
                  <text x={gx - 62} y={gy + 12} fontFamily="var(--mono)" fontSize="9.5" fill="var(--mut)">not connected</text>
                </g>
              );
            })()}
          </g>
        </svg>

        <div style={{ position: "absolute", left: 16, bottom: 14, display: "flex", gap: 2, background: "var(--sur)", border: "1px solid var(--bd)", borderRadius: 3, overflow: "hidden" }}>
          <span onClick={() => { setTransMs(300); setCam((c) => ({ ...c, s: clampS(c.s * 0.82) })); }} style={{ fontFamily: "var(--mono)", fontSize: 13, color: "var(--mut)", padding: "5px 11px", borderRight: "1px solid var(--bd)", cursor: "pointer", userSelect: "none" }}>−</span>
          <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--mut)", padding: "7px 10px", borderRight: "1px solid var(--bd)" }}>{Math.round(s * 100)}%</span>
          <span onClick={() => { setTransMs(300); setCam((c) => ({ ...c, s: clampS(c.s * 1.22) })); }} style={{ fontFamily: "var(--mono)", fontSize: 13, color: "var(--mut)", padding: "5px 11px", borderRight: "1px solid var(--bd)", cursor: "pointer", userSelect: "none" }}>+</span>
          <span onClick={() => { setSel(null); flyTo(580, 360, 0.85); }} style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--mut)", padding: "7px 11px", cursor: "pointer", userSelect: "none" }}>⛶ overview</span>
        </div>
        <div style={{ position: "absolute", left: 16, top: 12, pointerEvents: "none", maxWidth: "58%", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          <Mono size={10} style={{ letterSpacing: "0.08em" }}>{insts.length} INTEGRATIONS · SCROLL FLIES INTO WHAT'S UNDER THE CURSOR · CONNECTIONS SHARPEN AS YOU ZOOM</Mono>
        </div>
      </div>

      {/* detail panel */}
      <div style={{ width: 300, borderLeft: "1px solid var(--bd)", background: "var(--sur)", flexShrink: 0, overflowY: "auto", overflowX: "hidden" }}>
        {!selInst ? (
          <div style={{ padding: 32, textAlign: "center", color: "var(--mut)", fontSize: 12.5, lineHeight: 1.65, marginTop: 30 }}>
            {SI.graph({ size: 24 })}<br /><br />Click a box to fly into it — integrations hold assemblies, assemblies hold components. Selection scopes every other surface.
          </div>
        ) : (() => {
          const links = world.graph.links.filter((l) => l.a === selInst.id || l.b === selInst.id);
          const f = world.findings.find((x) => x.node === selInst.id);
          return (
            <div style={{ padding: "18px 16px", display: "flex", flexDirection: "column", minHeight: "100%", boxSizing: "border-box" }}>
              <Mono size={9.5} color={dcol(selInst.domain)}>● {SolusDomains[selInst.domain].label} · {selInst.sect === "devices" ? "DEVICE / STREAM" : selInst.sect === "local" ? "LOCAL APP" : "CLOUD"}</Mono>
              <div style={{ fontSize: 17, fontWeight: 650, marginTop: 7, fontFamily: "var(--mono)" }}>{selInst.name}</div>
              <div style={{ fontSize: 11.5, color: "var(--mut)", marginTop: 3, lineHeight: 1.5 }}>{selInst.detail}</div>
              {scope && scope.id.startsWith(selInst.id + "/") && <div style={{ marginTop: 8, fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--acc)" }}>scoped to: {scope.label}</div>}
              {f && (
                <div onClick={() => openSol(f.solKey)} style={{ marginTop: 13, background: "color-mix(in srgb, var(--err) 8%, transparent)", border: "1px solid color-mix(in srgb, var(--err) 40%, transparent)", borderRadius: 3, padding: "9px 11px", cursor: "pointer" }}>
                  <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    <span style={{ width: 7, height: 7, borderRadius: 99, background: "var(--err)", flexShrink: 0 }} className="gm-orb"></span>
                    <span style={{ fontSize: 11.5, fontWeight: 600, lineHeight: 1.4 }}>{f.finding.title}</span>
                  </div>
                  <div style={{ fontSize: 10.5, color: "var(--mut)", marginTop: 4 }}>{f.finding.when} — ask SOL →</div>
                </div>
              )}
              {selInst.identity && (
                <div style={{ marginTop: 13, background: selInst.honest ? "color-mix(in srgb, var(--warn) 5%, transparent)" : "var(--bg)", border: `1px solid ${selInst.honest ? "color-mix(in srgb, var(--warn) 35%, transparent)" : "var(--bd)"}`, borderRadius: 3, padding: "8px 10px", fontSize: 11, lineHeight: 1.55 }}>
                  {selInst.honest && <Mono size={8} color="var(--warn)" style={{ display: "block", marginBottom: 3 }}>IDENTITY — HONEST</Mono>}
                  {selInst.identity}
                </div>
              )}
              <Mono size={9} style={{ marginTop: 16, marginBottom: 2 }}>CROSS-DOMAIN LINKS</Mono>
              {links.length === 0 && <div style={{ fontSize: 11, color: "var(--mut)", padding: "8px 0" }}>None yet — links appear as more of the project connects.</div>}
              {links.map((l, i) => {
                const other = insts.find((c) => c.id === (l.a === selInst.id ? l.b : l.a));
                return (
                  <div key={i} onClick={() => { setSel(other.id); const ob = layouts[other.id].box; flyTo(ob.cx, ob.cy, 1.9); }} style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 0", borderBottom: "1px solid var(--bd)", cursor: "pointer" }}>
                    <span style={{ width: 6, height: 6, borderRadius: 99, background: dcol(other.domain), flexShrink: 0 }}></span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontFamily: "var(--mono)", fontSize: 11, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{other.name}</div>
                      <div style={{ fontSize: 10, color: "var(--mut)" }}>{l.label2 || l.label}</div>
                    </div>
                    <Mono size={9} color={l.hot ? "var(--acc)" : "var(--mut)"}>{l.n}</Mono>
                  </div>
                );
              })}
              <div style={{ flex: 1, minHeight: 16 }}></div>
              <div style={{ display: "flex", gap: 8 }}>
                <Btn kind="ghost" size="sm" style={{ flex: 1 }} onClick={() => { const b = layouts[selInst.id].box; flyTo(b.cx, b.cy, 2.6); }}>Fly in</Btn>
                <Btn kind="primary" size="sm" style={{ flex: 1 }} onClick={() => openSol(f ? f.solKey : "hello")}>Ask SOL</Btn>
              </div>
            </div>
          );
        })()}
      </div>
    </div>
  );
}

Object.assign(window, { GraphScreen3 });
