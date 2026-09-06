// Solus v2 — Experiments: define, run live, playback (scrub), compare with explained divergence
const { useState: useStateE2, useEffect: useEffectE2, useRef: useRefE2 } = React;

function StatusChip({ status }) {
  const map = { failed: ["var(--err)", "FAILED"], passed: ["var(--ok)", "PASSED"], running: ["var(--acc)", "RUNNING"], defined: ["var(--mut)", "DEFINED"] };
  const [c, l] = map[status] || map.defined;
  return <span style={{ fontFamily: "var(--mono)", fontSize: 8.5, letterSpacing: "0.08em", color: c, border: `1px solid color-mix(in srgb, ${c} 45%, transparent)`, borderRadius: 99, padding: "2px 8px" }}>{l}</span>;
}

function EpGrid({ eps, bad, progress, small }) {
  const cells = Array.from({ length: eps }, (_, i) => i + 1);
  return (
    <div style={{ display: "grid", gridTemplateColumns: `repeat(${Math.min(eps, 20)}, 1fr)`, gap: 3 }}>
      {cells.map((i) => {
        const done = progress == null || i <= progress;
        const isBad = bad.includes(i);
        return <span key={i} title={`episode ${i}${isBad ? " — anomaly" : ""}`} style={{ height: small ? 8 : 14, borderRadius: 2, background: !done ? "var(--sur2)" : isBad ? "var(--err)" : "color-mix(in srgb, var(--ok) 70%, transparent)", border: "1px solid var(--bd)" }}></span>;
      })}
    </div>
  );
}

/* curve generator for playback/compare (pure fn of t) */
function curve(world, sigId, t, variant) {
  const s = world.signals.find((x) => x.id === sigId) || world.signals[0];
  const base = s.base + s.amp * Math.sin((2 * Math.PI * t) / s.period + (s.phase || 0));
  if (variant === "bad" && s.hot) {
    const an = world.anomaly[s.id];
    if (an && t > 3.5) return an.pin != null ? an.pin : an.dip != null ? an.dip : base;
  }
  if (variant === "sim" && s.hot && t > 3.5) return Math.min(base, 90);
  return base;
}
function CurveChart({ world, sigId, dur, variantA, variantB, labelA, labelB, cursor, divergeAt, h = 120 }) {
  const N = 90, w = 560;
  const pts = (variant) => Array.from({ length: N }, (_, i) => curve(world, sigId, (i / (N - 1)) * dur, variant));
  const A = pts(variantA), B = variantB ? pts(variantB) : null;
  const all = B ? A.concat(B) : A;
  const mn = Math.min(...all), mx = Math.max(...all), rg = mx - mn || 1;
  const px = (i) => (i / (N - 1)) * w, py = (v) => h - 6 - ((v - mn) / rg) * (h - 12);
  const path = (arr) => arr.map((v, i) => `${px(i)},${py(v)}`).join(" ");
  const divX = divergeAt != null ? (divergeAt / dur) * w : null;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} style={{ display: "block", width: "100%", background: "var(--bg)", border: "1px solid var(--bd)", borderRadius: 3 }}>
      {divX != null && <rect x={divX} y="0" width={w - divX} height={h} fill="var(--err)" opacity="0.06"></rect>}
      {divX != null && <line x1={divX} y1="0" x2={divX} y2={h} stroke="var(--err)" strokeWidth="1" strokeDasharray="3 3" opacity="0.7"></line>}
      <polyline points={path(A)} fill="none" stroke="var(--acc)" strokeWidth="1.6"></polyline>
      {B && <polyline points={path(B)} fill="none" stroke="var(--ok)" strokeWidth="1.6" strokeDasharray="5 3"></polyline>}
      {cursor != null && <line x1={(cursor / dur) * w} y1="0" x2={(cursor / dur) * w} y2={h} stroke="var(--tx)" strokeWidth="1" opacity="0.6"></line>}
      <text x="8" y="14" fontFamily="var(--mono)" fontSize="9" fill="var(--acc)">— {labelA}</text>
      {B && <text x="8" y="26" fontFamily="var(--mono)" fontSize="9" fill="var(--ok)">-- {labelB}</text>}
      {divX != null && <text x={divX + 6} y={h - 8} fontFamily="var(--mono)" fontSize="8.5" fill="var(--err)">diverges here</text>}
    </svg>
  );
}

function DefineModal({ world, onClose, onCreate }) {
  const [name, setName] = useStateE2("");
  const [expect, setExpect] = useStateE2("");
  const [target, setTarget] = useStateE2("sim + hardware");
  const [eps, setEps] = useStateE2(20);
  const f = { width: "100%", boxSizing: "border-box", background: "var(--bg)", color: "var(--tx)", border: "1px solid var(--bd)", borderRadius: 3, padding: "9px 11px", fontSize: 12.5, fontFamily: "var(--ui)", outline: "none" };
  return (
    <ChromeModal title="Define experiment" onClose={onClose} width={430}>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div><Mono size={8.5} style={{ display: "block", marginBottom: 5 }}>WHAT ARE YOU TESTING?</Mono><input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. ACT eval after clamp fix" style={f} /></div>
        <div><Mono size={8.5} style={{ display: "block", marginBottom: 5 }}>WHAT DO YOU EXPECT?</Mono><input value={expect} onChange={(e) => setExpect(e.target.value)} placeholder="e.g. ≥ 18/20 grasps, no joint past ±90°" style={f} /></div>
        <div style={{ display: "flex", gap: 10 }}>
          <div style={{ flex: 1 }}><Mono size={8.5} style={{ display: "block", marginBottom: 5 }}>RUNS ON</Mono>
            <select value={target} onChange={(e) => setTarget(e.target.value)} style={{ ...f, padding: "8px 10px" }}>{["sim", "hardware", "sim + hardware"].map((o) => <option key={o}>{o}</option>)}</select></div>
          <div style={{ width: 110 }}><Mono size={8.5} style={{ display: "block", marginBottom: 5 }}>EPISODES</Mono><input type="number" value={eps} onChange={(e) => setEps(+e.target.value)} style={f} /></div>
        </div>
        <Btn kind="primary" disabled={!name} onClick={() => onCreate({ name, expect, target, eps })} style={{ marginTop: 4 }}>Create — runs after approval</Btn>
      </div>
    </ChromeModal>
  );
}

function ExperimentsScreen({ world, run42, startRerun, fixes, openChat, requestApproval }) {
  const [sel, setSel] = useStateE2(null);
  const [tab, setTab] = useStateE2("Playback");
  const [t, setT] = useStateE2(4.2);
  const [defineOpen, setDefineOpen] = useStateE2(false);
  const [drafts, setDrafts] = useStateE2([]);
  useEffectE2(() => { setSel(null); }, [world.id]);

  const runs = [...(run42 && run42.status !== "none" ? [{ id: "42", name: "ACT eval · after fixes", status: run42.status === "done" ? "passed" : "running", eps: 20, bad: [], when: "just now", dur: run42.status === "done" ? "6m 12s" : "—", target: "hardware", expect: "≥ 18/20 grasps, joints within limits" }] : []), ...drafts, ...world.runs];
  const run = runs.find((r) => r.id === sel);
  const dur = 8;
  const isMaya = world.id === "maya";
  const mainSig = isMaya ? "j2" : world.id === "priya" ? "inv" : "p9";
  const bothFixed = fixes && fixes["ap-clamp"] === "approved" && fixes["ap-flash"] === "approved";

  if (world.runs.length === 0 && drafts.length === 0 && !(run42 && run42.status !== "none")) {
    return (
      <div style={{ flex: 1, overflowY: "auto" }} data-screen-label="Experiments">
        <div style={{ maxWidth: 720, margin: "0 auto", padding: "26px 28px" }}>
          <h1 style={{ margin: 0, fontSize: 21, fontWeight: 600 }}>Experiments</h1>
          <Card pad={0} style={{ marginTop: 18 }}>
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", padding: "64px 24px", gap: 12, textAlign: "center" }}>
              <span style={{ color: "var(--mut)", opacity: 0.7 }}>{SI.play({ size: 26 })}</span>
              <div style={{ fontSize: 14, fontWeight: 600 }}>Nothing runnable yet</div>
              <div style={{ fontSize: 12, color: "var(--mut)", maxWidth: 400, lineHeight: 1.65 }}>{world.runsEmpty}</div>
              <Btn kind="ghost" size="sm" onClick={() => openChat("hello")}>Ask SOL to scaffold one</Btn>
            </div>
          </Card>
        </div>
      </div>
    );
  }

  return (
    <div style={{ flex: 1, overflowY: "auto", minWidth: 0 }} data-screen-label="Experiments">
      <div style={{ maxWidth: 1080, margin: "0 auto", padding: "22px 26px 44px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h1 style={{ margin: 0, fontSize: 21, fontWeight: 600 }}>Experiments</h1>
          <div style={{ display: "flex", gap: 8 }}>
            {isMaya && bothFixed && (!run42 || run42.status === "none") && <Btn kind="primary" size="sm" onClick={startRerun}>{SI.play({ size: 12 })} Re-run after fixes (approval)</Btn>}
            <Btn kind="ghost" size="sm" onClick={() => setDefineOpen(true)}>{SI.plus({ size: 12 })} Define</Btn>
          </div>
        </div>

        {/* run list */}
        <Card pad={0} style={{ marginTop: 16 }}>
          {runs.map((r) => (
            <div key={r.id} onClick={() => { setSel(r.id); setTab(r.status === "running" ? "Live" : "Playback"); }}
              style={{ display: "flex", gap: 14, alignItems: "center", padding: "12px 16px", borderBottom: "1px solid var(--bd)", cursor: "pointer", background: sel === r.id ? "color-mix(in srgb, var(--acc) 4%, transparent)" : "transparent" }}>
              <StatusChip status={r.status} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 12.5, fontWeight: 600 }}>Run {r.id} — {r.name}</div>
                <div style={{ fontSize: 10.5, color: "var(--mut)", marginTop: 2 }}>{r.target} · {r.eps} episodes · expect: {r.expect} · {r.when}</div>
              </div>
              <div style={{ width: 180, flexShrink: 0 }}><EpGrid eps={r.eps} bad={r.bad} progress={r.status === "running" ? run42.progress : null} small /></div>
              <span style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: r.bad.length ? "var(--err)" : "var(--mut)", width: 76, textAlign: "right", flexShrink: 0 }}>{r.status === "running" ? `${run42.progress}/${r.eps}` : r.bad.length ? `${r.bad.length}/${r.eps} anomalous` : r.dur}</span>
            </div>
          ))}
        </Card>

        {/* detail */}
        {run && (
          <Card pad={0} style={{ marginTop: 14 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "11px 16px", borderBottom: "1px solid var(--bd)" }}>
              <span style={{ fontSize: 13, fontWeight: 600 }}>Run {run.id}</span>
              <Seg size="sm" options={run.status === "running" ? ["Live"] : ["Playback", "Compare"]} value={tab} onChange={setTab} />
              <div style={{ flex: 1 }}></div>
              {run.id === "41" && <Btn kind="primary" size="sm" onClick={() => openChat("diagnose")}>{SI.sol({ size: 12 })} Diagnose 14 anomalies</Btn>}
              {run.id === "sat" && <Btn kind="primary" size="sm" onClick={() => openChat("cutout")}>{SI.sol({ size: 12 })} Explain lap 7</Btn>}
            </div>
            <div style={{ padding: 16 }}>
              {tab === "Live" && run.status === "running" && (
                <div>
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}><Mono size={9} color="var(--acc)">EPISODE {run42.progress} OF 20 · LIVE</Mono><Mono size={9}>ABORT: SPACE</Mono></div>
                  <EpGrid eps={20} bad={[]} progress={run42.progress} />
                  <div style={{ marginTop: 12 }}><CurveChart world={world} sigId={mainSig} dur={dur} variantA="good" labelA="joint 2 — within limits" cursor={(run42.progress / 20) * dur} /></div>
                  <div style={{ fontSize: 11.5, color: "var(--mut)", marginTop: 10 }}>M2 peak 1.4 A · supply holding 5.0 V — the clamp and current limit are doing their jobs.</div>
                </div>
              )}
              {tab === "Playback" && run.status !== "running" && (
                <div>
                  <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                    <Btn kind="soft" size="sm" onClick={() => setT((x) => (x + 0.8) % dur)}>{SI.play({ size: 12 })}</Btn>
                    <input type="range" min="0" max={dur} step="0.05" value={t} onChange={(e) => setT(+e.target.value)} style={{ flex: 1, accentColor: "var(--acc)" }} />
                    <Mono size={9.5} style={{ width: 84, textAlign: "right" }}>t = {t.toFixed(2)} s · EP {Math.min(run.eps, Math.floor((t / dur) * run.eps) + 1)}</Mono>
                  </div>
                  <div style={{ display: "flex", gap: 2, margin: "8px 0 12px" }}>
                    {Array.from({ length: run.eps }, (_, i) => <span key={i} style={{ flex: 1, height: 5, borderRadius: 2, background: run.bad.includes(i + 1) ? "var(--err)" : "var(--sur2)" }}></span>)}
                  </div>
                  <CurveChart world={world} sigId={mainSig} dur={dur} variantA={run.bad.length ? "bad" : "good"} labelA={world.signals.find((s) => s.id === mainSig).name + (run.bad.length ? " — pinned after t≈3.5 s" : "")} cursor={t} />
                  {world.camera && (
                    <div style={{ marginTop: 10, position: "relative", height: 64, background: "repeating-linear-gradient(90deg, var(--sur2), var(--sur2) 60px, var(--bg) 60px, var(--bg) 61px)", border: "1px solid var(--bd)", borderRadius: 3 }}>
                      <span style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "var(--mono)", fontSize: 9, color: "var(--mut)" }}>video frames · aligned to scrub position</span>
                      <span style={{ position: "absolute", left: `${(t / dur) * 100}%`, top: 0, bottom: 0, width: 1.5, background: "var(--acc)" }}></span>
                    </div>
                  )}
                  {run.bad.length > 0 && <div style={{ marginTop: 10, fontSize: 11.5, lineHeight: 1.6, color: "var(--tx)", background: "color-mix(in srgb, var(--err) 6%, transparent)", border: "1px solid color-mix(in srgb, var(--err) 30%, transparent)", borderRadius: 3, padding: "9px 12px" }}>
                    {isMaya ? <>At t≈3.5 s the commanded angle passes 90° and the measured angle pins — that flat line is the servo against its stop, not a sensor dropout.</> : <>Lap 7, 14:42:07 — inverter current spikes to 40 A on corner exit; the fault frame follows 80 ms later.</>} <span onClick={() => openChat(isMaya ? "diagnose" : "cutout")} style={{ color: "var(--acc)", cursor: "pointer" }}>Full explanation →</span>
                  </div>}
                </div>
              )}
              {tab === "Compare" && (
                <div>
                  <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
                    <Seg size="sm" options={isMaya ? ["sim vs real", "run vs run"] : ["run vs run"]} value={window.__cmpMode || (isMaya ? "sim vs real" : "run vs run")} onChange={(v) => { window.__cmpMode = v; setT((x) => x); }} />
                  </div>
                  {(() => {
                    const m = window.__cmpMode || (isMaya ? "sim vs real" : "run vs run");
                    const canRunRun = isMaya ? run42 && run42.status === "done" : true;
                    if (m === "run vs run" && !canRunRun) return <div style={{ fontSize: 12, color: "var(--mut)", padding: "18px 0", lineHeight: 1.6 }}>Only one hardware run exists. Apply the fixes and re-run — the comparison appears here, divergence highlighted.</div>;
                    const A = m === "sim vs real" ? "bad" : "bad";
                    const B = m === "sim vs real" ? "sim" : "good";
                    const lA = m === "sim vs real" ? "real · run 41" : (isMaya ? "run 41 · before fixes" : "Saturday · endurance");
                    const lB = m === "sim vs real" ? "sim · run 40" : (isMaya ? "run 42 · after fixes" : "Thursday · shakedown");
                    const note = m === "sim vs real" ? world.compare.simReal : world.compare.runRun;
                    return (
                      <div>
                        <CurveChart world={world} sigId={mainSig} dur={dur} variantA={A} variantB={B} labelA={lA} labelB={lB} divergeAt={3.5} />
                        <div style={{ marginTop: 10, display: "flex", gap: 10, background: "var(--bg)", border: "1px solid var(--bd)", borderRadius: 3, padding: "10px 12px" }}>
                          <Orb2 size={18} energy={60} />
                          <div style={{ fontSize: 11.5, lineHeight: 1.65 }}>{note}</div>
                        </div>
                      </div>
                    );
                  })()}
                </div>
              )}
            </div>
          </Card>
        )}
      </div>
      {defineOpen && <DefineModal world={world} onClose={() => setDefineOpen(false)} onCreate={(d) => { setDrafts((x) => [{ id: String(43 + x.length), name: d.name, status: "defined", eps: d.eps, bad: [], when: "draft", dur: "—", target: d.target, expect: d.expect || "—" }, ...x]); setDefineOpen(false); }} />}
    </div>
  );
}

Object.assign(window, { ExperimentsScreen, CurveChart, EpGrid });
