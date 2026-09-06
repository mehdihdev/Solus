// Solus v4 — Live Bench: fed by Physical Robot nodes. Sensor panes, live reasoning, live test. Wraps BenchScreen2.
const { useState: useB4, useEffect: useEB4, useRef: useRB4 } = React;

function LidarPane({ anomaly }) {
  const [, f] = useB4(0); const t = useRB4(0);
  useInterval(() => { t.current += 0.1; f((n) => n + 1); }, 160, true);
  const pts = Array.from({ length: 90 }, (_, i) => { const a = (i / 90) * Math.PI * 2 + t.current * 0.2; const r = 60 + 22 * Math.sin(a * 3 + t.current) + (i % 7 === 0 ? -25 : 0); return [130 + r * Math.cos(a), 78 + r * 0.55 * Math.sin(a)]; });
  return (
    <Card pad={0}>
      <div style={{ display: "flex", justifyContent: "space-between", padding: "9px 13px", borderBottom: "1px solid var(--bd)" }}><Mono size={9}>LIDAR · 2D · 10 HZ</Mono><Mono size={8} color="var(--ok)">SYNCED</Mono></div>
      <svg viewBox="0 0 260 156" style={{ display: "block", width: "100%" }}>
        {[30, 60, 90].map((r) => <ellipse key={r} cx="130" cy="78" rx={r} ry={r * 0.55} fill="none" stroke="var(--bd)"></ellipse>)}
        {pts.map((p, i) => <circle key={i} cx={p[0]} cy={p[1]} r="1.4" fill={anomaly && i % 11 === 0 ? "var(--err)" : "var(--rt)"} opacity="0.85"></circle>)}
        <circle cx="130" cy="78" r="3" fill="var(--acc)"></circle>
      </svg>
    </Card>);
}

function LiveTest({ d, onRun, run, openSol }) {
  const prev = d.runs[0];
  return (
    <Card pad={0} style={{ marginBottom: 14 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 14px", borderBottom: run ? "1px solid var(--bd)" : "none", flexWrap: "wrap" }}>
        <Mono size={9}>LIVE TEST</Mono>
        <span style={{ fontSize: 12, color: "var(--mut)" }}>{run ? (run.done ? `Captured · ${run.eps} episodes · compared against ${prev ? "run " + prev.id : "expected"}` : `Running · episode ${run.progress} / ${run.eps} · capturing everything`) : prev ? `Last capture: run ${prev.id} — ${prev.bad.length ? prev.bad.length + "/" + prev.eps + " anomalous" : "clean"}` : "No previous run — the first capture becomes the baseline."}</span>
        <div style={{ flex: 1 }}></div>
        {run && !run.done && <span style={{ display: "inline-flex", gap: 3 }}>{Array.from({ length: run.eps }, (_, i) => <span key={i} style={{ width: 9, height: 9, borderRadius: 2, background: i < run.progress ? "color-mix(in srgb, var(--ok) 70%, transparent)" : "var(--sur2)", border: "1px solid var(--bd)" }}></span>)}</span>}
        {run && run.done && <Btn kind="ghost" size="sm" onClick={() => openSol(null, "Compare this run against " + (prev ? "run " + prev.id : "expected") + " — where do they diverge?")}>Explain divergence</Btn>}
        <Btn kind="primary" size="sm" disabled={run && !run.done} onClick={onRun}>{SI.play({ size: 12 })} {run ? "Run again" : "Run & capture"}</Btn>
      </div>
      {run && run.done && (
        <div style={{ padding: "12px 14px" }}>
          <CurveChart world={d} sigId={d.signals.find((s) => s.hot) ? d.signals.find((s) => s.hot).id : d.signals[0].id} dur={8} variantA={prev && prev.bad.length ? "bad" : "good"} variantB="good" labelA={prev ? "run " + prev.id + " (previous)" : "expected"} labelB="this run" divergeAt={prev && prev.bad.length ? 3.5 : null} h={100} />
          <div style={{ fontSize: 11.5, color: "var(--mut)", marginTop: 8, lineHeight: 1.55 }}>{d.compare.runRun || "Both traces agree within tolerance — nothing to explain."}</div>
        </div>)}
    </Card>);
}

function LiveReasoning({ d, anomaly, openSol }) {
  const items = [
    ...(anomaly && d.finding ? [{ h: d.finding.title, e: d.finding.what, chain: d.finding.chain, key: d.findings[0].key }] : []),
    ...(d.signals.length && !anomaly ? [{ h: "Nothing out of range", e: `Watching ${d.signals.length} signals across ${d.robots.filter((r) => !r.idle).length} robot${d.robots.filter((r) => !r.idle).length === 1 ? "" : "s"}. Findings appear here as headline → explanation → detail when a cause spans domains.`, quiet: true }] : []),
  ];
  if (!items.length) return null;
  return (
    <div style={{ marginTop: 12 }}>
      <Mono size={9}>LIVE REASONING · SOL WATCHES THE RUN</Mono>
      {items.map((it, i) => (
        <Card key={i} pad={0} style={{ marginTop: 8, borderColor: it.quiet ? "var(--bd)" : "color-mix(in srgb, var(--err) 45%, var(--bd))" }}>
          <div style={{ display: "flex", gap: 10, padding: "11px 14px", alignItems: "flex-start" }}>
            <span style={{ color: it.quiet ? "var(--ok)" : "var(--err)", marginTop: 1 }} className={it.quiet ? "" : "gm-orb"}>{it.quiet ? SI.check({ size: 14 }) : SI.warn({ size: 14 })}</span>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 12.5, fontWeight: 600 }}>{it.h}</div>
              <div style={{ fontSize: 11.5, color: "var(--mut)", marginTop: 3, lineHeight: 1.55 }}>{it.e}</div>
              {it.chain && <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 }}>{it.chain.map((c, j) => <span key={j} style={{ fontFamily: "var(--mono)", fontSize: 9.5, border: `1px solid color-mix(in srgb, ${dcol(c.d)} 40%, transparent)`, borderRadius: 99, padding: "2px 8px" }}><span style={{ display: "inline-block", width: 5, height: 5, borderRadius: 99, background: dcol(c.d), marginRight: 5 }}></span>{c.l}</span>)}</div>}
            </div>
            {!it.quiet && <Btn kind="primary" size="sm" onClick={() => openSol(it.key)}>Detail & fix</Btn>}
          </div>
        </Card>))}
    </div>);
}

function BenchScreen4({ d, anomalyLive, setAnomalyLive, scope, setScope, openSol, telemSpeed, run, onRun }) {
  if (d.robots.length === 0) return (
    <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }} data-screen-label="Live Bench">
      <div style={{ textAlign: "center", maxWidth: 400 }}>
        <span style={{ color: "var(--mut)", opacity: 0.6 }}>{SI.bench({ size: 30 })}</span>
        <div style={{ fontSize: 15, fontWeight: 600, marginTop: 12 }}>No Physical Robot yet</div>
        <div style={{ fontSize: 12.5, color: "var(--mut)", marginTop: 8, lineHeight: 1.65 }}>Live Bench is fed by Physical Robot nodes — nothing is configured here. Add hardware in Workspace → Add → Hardware and this fills itself in.</div>
      </div>
    </div>);
  const live = d.robots.filter((r) => !r.idle);
  const world = { id: d.affinity || "custom", signals: d.signals, anomaly: d.anomaly, camera: d.camera,
    sim: { kind: d.simKind, spawnable: [...d.robots.map((r) => ({ id: r.platform === "so101" && r.idle ? "so101l" : r.platform === "so101" ? "so101f" : r.platform === "uno" ? "horn" : "pdu", label: r.name + (r.idle ? " (idle · ghost)" : " (live mirror)") })), ...(d.docs.some((x) => x.id === "mj-so101") ? [{ id: "cube", label: "Cube prop (sim only)" }] : [])], defaultScene: live[0] ? [live[0].platform === "so101" ? "so101f" : live[0].platform === "uno" ? "horn" : "pdu"] : [] } };
  window.__v2world = world;
  if (d.signals.length === 0) return (
    <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }} data-screen-label="Live Bench">
      <div style={{ textAlign: "center", maxWidth: 420 }}>
        <span style={{ color: "var(--mut)", opacity: 0.6 }}>{SI.bench({ size: 30 })}</span>
        <div style={{ fontSize: 15, fontWeight: 600, marginTop: 12 }}>{d.robots.map((r) => r.name).join(", ")} — nothing live yet</div>
        <div style={{ fontSize: 12.5, color: "var(--mut)", marginTop: 8, lineHeight: 1.65 }}>Every part is <StateChip state="planned" small /> or <StateChip state="installed" small /> — no signal has arrived, so no widget is drawn. When a detected device answers, its channels appear here one widget each.</div>
      </div>
    </div>);
  const cadNote = d.docs.some((x) => x.domain === "me") ? "SCENE LINKED TO CAD — UPDATES WHEN THE CAD CHANGES" : "NO CAD LINKED — SCENE USES DEFAULT GEOMETRY";
  return (
    <BenchScreen2 world={world} anomalyLive={anomalyLive} scope={scope} setScope={setScope} openChat={(k) => openSol(k)} telemSpeed={telemSpeed}
      header={<LiveTest d={d} run={run} onRun={onRun} openSol={openSol} />}
      extraLeft={<>{d.lidar ? <LidarPane anomaly={anomalyLive} /> : <Card pad={12}><div style={{ fontSize: 11, color: "var(--mut)", lineHeight: 1.6 }}>No LiDAR or depth sensor — point cloud pane appears when one is detected.</div></Card>}<div style={{ fontSize: 9.5, fontFamily: "var(--mono)", color: "var(--mut)", letterSpacing: "0.06em" }}>{cadNote}</div></>}
      extraBottom={<LiveReasoning d={d} anomaly={anomalyLive} openSol={openSol} />} />);
}
Object.assign(window, { BenchScreen4 });
