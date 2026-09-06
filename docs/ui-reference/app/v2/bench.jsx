// Solus v2 — Live Bench: sim scene + per-signal widgets (rename, units, anomaly markers) + video
const { useState: useStateB2, useEffect: useEffectB2, useRef: useRefB2 } = React;
const B2_BUF = 56;

/* ---------- sparkline with anomaly markers ---------- */
function Spark2({ values, w = 200, h = 34, color = "var(--rt)", markers }) {
  if (!values || values.length < 2) return <svg width={w} height={h}></svg>;
  const mn = Math.min(...values), mx = Math.max(...values), rg = mx - mn || 1;
  const px = (i) => (i / (values.length - 1)) * w;
  const py = (v) => h - 2 - ((v - mn) / rg) * (h - 4);
  const pts = values.map((v, i) => `${px(i)},${py(v)}`);
  return (
    <svg width={w} height={h} style={{ display: "block", width: "100%" }} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
      <polygon points={`0,${h} ${pts.join(" ")} ${w},${h}`} fill={color} opacity="0.1"></polygon>
      <polyline points={pts.join(" ")} fill="none" stroke={color} strokeWidth="1.4" strokeLinejoin="round"></polyline>
      {(markers || []).map((mIdx, k) => mIdx >= 0 && mIdx < values.length && (
        <g key={k}><line x1={px(mIdx)} y1="0" x2={px(mIdx)} y2={h} stroke="var(--err)" strokeWidth="1" opacity="0.55"></line><circle cx={px(mIdx)} cy={py(values[mIdx])} r="2.4" fill="var(--err)"></circle></g>
      ))}
    </svg>
  );
}

/* ---------- one signal widget ---------- */
function SignalWidget({ sig, buf, bad, cmdGhost, scoped, onScope, renamed, onRename }) {
  const [editing, setEditing] = useStateB2(false);
  const [unit, setUnit] = useStateB2(sig.unit);
  const name = renamed || sig.name;
  const raw = buf[buf.length - 1];
  const val = sig.unit ? v2conv(raw, sig.unit, unit) : raw;
  const alts = sig.unit ? (V2_ALT_UNITS[sig.unit] || [sig.unit]) : [];
  const markers = bad ? [buf.length - 4, buf.length - 12, buf.length - 22].filter((i) => i > 0) : [];
  return (
    <Card pad={0} onClick={onScope} style={{ borderColor: bad ? "var(--err)" : scoped ? "color-mix(in srgb, var(--acc) 55%, var(--bd))" : "var(--bd)", overflow: "hidden", cursor: "pointer", transition: "border-color 0.3s" }}>
      <div style={{ padding: "9px 11px 2px", display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8 }}>
        {editing
          ? <input autoFocus defaultValue={name} onClick={(e) => e.stopPropagation()}
              onKeyDown={(e) => { if (e.key === "Enter") { onRename(e.target.value); setEditing(false); } if (e.key === "Escape") setEditing(false); }}
              onBlur={(e) => { onRename(e.target.value); setEditing(false); }}
              style={{ fontFamily: "var(--mono)", fontSize: 10.5, background: "var(--bg)", color: "var(--tx)", border: "1px solid var(--acc)", borderRadius: 2, padding: "1px 5px", width: "60%", outline: "none" }} />
          : <span onClick={(e) => { e.stopPropagation(); setEditing(true); }} title="Click to rename" style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: bad ? "var(--err)" : "var(--mut)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", cursor: "text", borderBottom: "1px dashed transparent" }}
              onMouseEnter={(e) => e.currentTarget.style.borderBottomColor = "var(--bd)"} onMouseLeave={(e) => e.currentTarget.style.borderBottomColor = "transparent"}>{name}</span>}
        <span style={{ fontFamily: "var(--mono)", fontSize: 14, color: bad ? "var(--err)" : "var(--tx)", flexShrink: 0 }}>
          {v2fmt(val, unit)}
          {sig.unit
            ? <select value={unit} onClick={(e) => e.stopPropagation()} onChange={(e) => setUnit(e.target.value)}
                style={{ marginLeft: 4, background: "transparent", color: "var(--mut)", border: "none", fontSize: 9, fontFamily: "var(--mono)", outline: "none", cursor: "pointer" }}>
                {alts.map((u) => <option key={u} value={u} style={{ background: "var(--sur)" }}>{u}</option>)}
              </select>
            : <span title={sig.unitNote} style={{ fontSize: 8.5, color: "var(--warn)", marginLeft: 4, borderBottom: "1px dotted var(--warn)" }}>no unit</span>}
        </span>
      </div>
      {cmdGhost && bad && <div style={{ padding: "0 11px", fontFamily: "var(--mono)", fontSize: 9, color: "var(--err)" }}>cmd {cmdGhost}° / meas {v2fmt(val, unit)}° — pinned at the stop</div>}
      <div style={{ padding: "2px 0 0" }}><Spark2 values={buf} color={bad ? "var(--err)" : "var(--rt)"} markers={markers} /></div>
    </Card>
  );
}

/* ---------- sim scenes ---------- */
function ArmFig({ t, anomaly, ghost, x = 0 }) {
  const sh = anomaly ? 88 : 40 + 26 * Math.sin(t / 1.4);
  const el = anomaly ? 12 + 3 * Math.sin(t * 9) : -30 + 34 * Math.sin(t / 1.1 + 1);
  const wr = 20 * Math.sin(t / 0.9 + 2);
  const c = anomaly ? "var(--err)" : ghost ? "var(--mut)" : "var(--rt)";
  return (
    <g transform={`translate(${x},0)`} opacity={ghost ? 0.35 : 1}>
      <rect x="70" y="150" width="60" height="14" rx="3" fill="var(--sur2)" stroke="var(--bd)"></rect>
      <g transform={`translate(100,150) rotate(${-sh})`}>
        <line x1="0" y1="0" x2="0" y2="-52" stroke={c} strokeWidth="6" strokeLinecap="round" strokeDasharray={ghost ? "4 4" : "none"}></line>
        <g transform={`translate(0,-52) rotate(${-el})`}>
          <line x1="0" y1="0" x2="0" y2="-44" stroke={c} strokeWidth="5" strokeLinecap="round" strokeDasharray={ghost ? "4 4" : "none"}></line>
          <g transform={`translate(0,-44) rotate(${-wr})`}>
            <line x1="0" y1="0" x2="0" y2="-18" stroke={c} strokeWidth="4" strokeLinecap="round"></line>
            <path d="M-7 -18 l4 -10 M7 -18 l-4 -10" stroke={c} strokeWidth="3" fill="none" strokeLinecap="round"></path>
          </g>
        </g>
        <circle cx="0" cy="0" r="6" fill={anomaly ? "var(--err)" : "var(--sur2)"} stroke={c} strokeWidth="2" className={anomaly ? "gm-orb" : ""}></circle>
        <circle cx="0" cy="-52" r="5" fill="var(--sur2)" stroke={c} strokeWidth="2"></circle>
      </g>
    </g>
  );
}
function ServoFig({ t, anomaly }) {
  const a = anomaly ? 30 * Math.sin(t * 14) * Math.exp(-((t * 3) % 1)) + 20 : 45 * Math.sin(t / 1.6);
  return (
    <g>
      <rect x="70" y="90" width="60" height="44" rx="5" fill="var(--sur2)" stroke="var(--bd)"></rect>
      <text x="100" y="115" textAnchor="middle" fontFamily="var(--mono)" fontSize="9" fill="var(--mut)">PWM-9</text>
      <g transform={`translate(100,90) rotate(${a})`}>
        <line x1="0" y1="0" x2="0" y2="-42" stroke={anomaly ? "var(--err)" : "var(--rt)"} strokeWidth="5" strokeLinecap="round"></line>
      </g>
      <circle cx="100" cy="90" r="6" fill="var(--sur2)" stroke={anomaly ? "var(--err)" : "var(--rt)"} strokeWidth="2" className={anomaly ? "gm-orb" : ""}></circle>
      {anomaly && <text x="100" y="160" textAnchor="middle" fontFamily="var(--mono)" fontSize="8.5" fill="var(--err)">±4° jitter</text>}
    </g>
  );
}
function CanFig({ t, anomaly }) {
  const nodes = [["BMS", 60], ["PDU", 105], ["INV", 150], ["DASH", 195]];
  return (
    <g>
      <line x1="30" y1="120" x2="225" y2="120" stroke="var(--bd)" strokeWidth="2"></line>
      {nodes.map(([n, x]) => {
        const bad = anomaly && n === "INV";
        return (
          <g key={n}>
            <line x1={x} y1="120" x2={x} y2="96" stroke="var(--bd)"></line>
            <rect x={x - 22} y="66" width="44" height="30" rx="3" fill="var(--sur2)" stroke={bad ? "var(--err)" : "color-mix(in srgb, var(--rt) 40%, var(--bd))"} className={bad ? "gm-orb" : ""}></rect>
            <text x={x} y="82" textAnchor="middle" fontFamily="var(--mono)" fontSize="8.5" fill={bad ? "var(--err)" : "var(--tx)"}>{n}</text>
            <text x={x} y="92" textAnchor="middle" fontFamily="var(--mono)" fontSize="7" fill="var(--mut)">{bad ? "FAULT 0x0A2" : Math.floor(t * 37 + x) % 1000 + " fr/s"}</text>
          </g>
        );
      })}
    </g>
  );
}

function BenchScreen2({ world, anomalyLive, scope, setScope, openChat, telemSpeed, extraLeft, extraBottom, header }) {
  const [running, setRunning] = useStateB2(true);
  const [scene, setScene] = useStateB2(world.sim.defaultScene);
  const [spawnOpen, setSpawnOpen] = useStateB2(false);
  const [renames, setRenames] = useStateB2({});
  const [, force] = useStateB2(0);
  const tRef = useRefB2(0);
  const bufs = useRefB2({});
  useEffectB2(() => { setScene(world.sim.defaultScene); bufs.current = {}; tRef.current = 0; }, [world.id]);

  window.__v2world = world;
  world.signals.forEach((s) => { if (!bufs.current[s.id]) bufs.current[s.id] = Array.from({ length: B2_BUF }, (_, i) => v2sample(s, i * 0.14, false)); });

  useInterval(() => {
    tRef.current += 0.14;
    world.signals.forEach((s) => {
      let b = bufs.current[s.id];
      if (!b) b = bufs.current[s.id] = Array.from({ length: B2_BUF }, (_, i) => v2sample(s, i * 0.14, false));
      b.push(v2sample(s, tRef.current, anomalyLive && s.hot));
      if (b.length > B2_BUF) b.shift();
    });
    force((n) => n + 1);
  }, Math.max(40, 130 / (telemSpeed || 1)), running);

  const isLog = world.id === "priya";
  const nothing = world.signals.length === 0;

  return (
    <div style={{ flex: 1, overflowY: "auto", minWidth: 0 }} data-screen-label="Live Bench">
      <div style={{ maxWidth: 1180, margin: "0 auto", padding: "16px 22px 40px" }}>
        {header}
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <Btn kind="soft" size="sm" onClick={() => setRunning(!running)}>{running ? <>{SI.pause({ size: 12 })} Pause</> : <>{SI.play({ size: 12 })} Run</>}</Btn>
          <Mono size={10} color={running ? "var(--ok)" : "var(--mut)"}>{running ? (isLog ? "● PLAYING SATURDAY'S LOG" : "● STREAMING") : "○ PAUSED"}</Mono>
          {isLog && <Mono size={9}>PCAN IDLE — NO LIVE BUS. THIS IS RECORDED DATA, LABELLED AS SUCH.</Mono>}
          <div style={{ flex: 1 }}></div>
          {anomalyLive && <Btn kind="primary" size="sm" onClick={() => openChat(world.id === "sam" ? "jitter" : world.id === "priya" ? "cutout" : "diagnose")}>{SI.sol({ size: 12 })} Ask SOL about the red</Btn>}
        </div>

        {nothing ? (
          <Card pad={0} style={{ marginTop: 16 }}>
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", padding: "70px 24px", gap: 12, textAlign: "center" }}>
              <span style={{ color: "var(--mut)", opacity: 0.7 }}>{SI.bench({ size: 28 })}</span>
              <div style={{ fontSize: 14, fontWeight: 600 }}>Nothing is streaming</div>
              <div style={{ fontSize: 12, color: "var(--mut)", maxWidth: 380, lineHeight: 1.6 }}>The bench builds itself from what it hears. Connect a robot, start the simulator, or plug in a CAN interface — widgets appear on their own.</div>
            </div>
          </Card>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "300px minmax(0,1fr)", gap: 14, marginTop: 14, alignItems: "start" }}>
            {/* scene + video */}
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Card pad={0}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 13px", borderBottom: "1px solid var(--bd)" }}>
                  <Mono size={9}>{isLog ? "CAN TOPOLOGY" : "SCENE"}</Mono>
                  <div style={{ position: "relative" }}>
                    <Btn kind="bare" size="sm" onClick={() => setSpawnOpen(!spawnOpen)}>{SI.plus({ size: 11 })} Spawn</Btn>
                    {spawnOpen && (
                      <div style={{ position: "absolute", right: 0, top: 26, zIndex: 30, width: 230, background: "var(--sur)", border: "1px solid var(--bd)", borderRadius: 4, boxShadow: "0 14px 40px rgba(0,0,0,0.5)", padding: 5 }}>
                        <div style={{ padding: "3px 8px 6px" }}><Mono size={8}>ONLY WHAT'S CONNECTED</Mono></div>
                        {world.sim.spawnable.map((sp) => (
                          <div key={sp.id} onClick={() => { setScene((s) => s.includes(sp.id) ? s : [...s, sp.id]); setSpawnOpen(false); }}
                            style={{ padding: "7px 8px", borderRadius: 3, fontSize: 12, cursor: "pointer", color: scene.includes(sp.id) ? "var(--mut)" : "var(--tx)" }}
                            onMouseEnter={(e) => e.currentTarget.style.background = "var(--sur2)"} onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}>
                            {sp.label}{scene.includes(sp.id) && " ✓"}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
                <svg viewBox="0 0 260 175" style={{ display: "block", width: "100%" }}>
                  <defs><pattern id="b2grid" width="20" height="20" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="0.8" fill="var(--bd)"></circle></pattern></defs>
                  <rect width="260" height="175" fill="url(#b2grid)"></rect>
                  {world.sim.kind === "arm" && scene.map((id, i) => id === "cube"
                    ? <rect key={id} x={170} y={140} width="16" height="16" rx="2" fill="var(--acc)" opacity="0.7"></rect>
                    : <ArmFig key={id} t={tRef.current} anomaly={anomalyLive && id === "so101f"} ghost={id === "so101l"} x={i * 26 - 10} />)}
                  {world.sim.kind === "servo" && <ServoFig t={tRef.current} anomaly={anomalyLive} />}
                  {world.sim.kind === "can" && <CanFig t={tRef.current} anomaly={anomalyLive} />}
                </svg>
                <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 13px", borderTop: "1px solid var(--bd)" }}>
                  <Mono size={8.5}>{world.sim.kind === "arm" ? (scene.includes("so101l") ? "FOLLOWER LIVE · LEADER IDLE (GHOST)" : "MIRRORING REAL MOTION") : isLog ? "FROM LOG · 14:42:07" : "LIVE"}</Mono>
                  <Mono size={8.5} color={anomalyLive ? "var(--err)" : "var(--ok)"}>{anomalyLive ? "1 FAULT" : "NOMINAL"}</Mono>
                </div>
              </Card>

              {world.camera ? (
                <Card pad={0}>
                  <div style={{ display: "flex", justifyContent: "space-between", padding: "9px 13px", borderBottom: "1px solid var(--bd)" }}>
                    <Mono size={9}>{world.id === "priya" ? "TRACKSIDE · CAM 2" : "WRIST CAMERA"}</Mono>
                    <span style={{ display: "inline-flex", gap: 5, alignItems: "center" }}><span style={{ width: 6, height: 6, borderRadius: 99, background: "var(--err)" }} className="gm-orb"></span><Mono size={8}>{isLog ? "LOG" : "REC"}</Mono></span>
                  </div>
                  <div style={{ height: 92, background: "repeating-linear-gradient(45deg, var(--sur2), var(--sur2) 8px, var(--bg) 8px, var(--bg) 16px)", position: "relative" }}>
                    <span style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "var(--mono)", fontSize: 9, color: "var(--mut)" }}>video · time-aligned with telemetry</span>
                    <span style={{ position: "absolute", left: `${(tRef.current * 7) % 100}%`, top: 0, bottom: 0, width: 1.5, background: "var(--acc)" }}></span>
                  </div>
                </Card>
              ) : (
                <Card pad={12}><div style={{ fontSize: 11, color: "var(--mut)", lineHeight: 1.6 }}>No camera connected — video appears here, time-aligned, when one is.</div></Card>
              )}
              {extraLeft}
            </div>

            {/* signal widgets */}
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 9, gap: 10, minWidth: 0 }}>
                <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}><Mono size={9}>{world.signals.length} SIGNALS · CLICK TO SCOPE · CLICK NAME TO RENAME</Mono></span>
                <span style={{ flexShrink: 0 }}><Mono size={8.5}>WINDOW 8 S</Mono></span>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(190px, 1fr))", gap: 10 }}>
                {world.signals.map((s) => (
                  <SignalWidget key={s.id} sig={s} buf={bufs.current[s.id]} bad={anomalyLive && s.hot}
                    cmdGhost={anomalyLive && world.id === "maya" && s.id === "j2" ? world.anomaly.j2.cmd : null}
                    scoped={scope && scope.id === s.id} onScope={() => setScope({ id: s.id, label: renames[s.id] || s.name, kind: "signal" })}
                    renamed={renames[s.id]} onRename={(n) => setRenames((r) => ({ ...r, [s.id]: n }))} />
                ))}
              </div>
              {world.id === "sam" && (
                <Card pad={12} style={{ marginTop: 12, borderColor: "color-mix(in srgb, var(--warn) 30%, var(--bd))" }}>
                  <div style={{ display: "flex", gap: 9 }}>
                    <span style={{ color: "var(--warn)", flexShrink: 0, marginTop: 1 }}>{SI.warn({ size: 13 })}</span>
                    <div style={{ fontSize: 11.5, color: "var(--tx)", lineHeight: 1.6 }}>
                      Names and units are placeholders — the board hasn't told me what these pins drive, and I won't guess. Rename them inline, or <span onClick={() => openChat("hello")} style={{ color: "var(--acc)", cursor: "pointer" }}>confirm the board identity</span> to get real names.
                    </div>
                  </div>
                </Card>
              )}
              {extraBottom}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

Object.assign(window, { BenchScreen2, Spark2, ArmFig });
