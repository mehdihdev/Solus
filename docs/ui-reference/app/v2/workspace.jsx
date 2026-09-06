// Solus v2 — Workspace canvas: derived widgets, shared selection, task layouts
const { useState: useStateW2, useEffect: useEffectW2, useRef: useRefW2 } = React;

function WidgetShell({ w, scoped, children, onDragStart, onDragOver, onDrop, footer }) {
  return (
    <Card pad={0} draggable onDragStart={onDragStart} onDragOver={onDragOver} onDrop={onDrop}
      style={{ borderColor: scoped ? "color-mix(in srgb, var(--acc) 55%, var(--bd))" : "var(--bd)", display: "flex", flexDirection: "column", minHeight: 150 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "9px 13px", borderBottom: "1px solid var(--bd)", cursor: "grab" }} title="Drag to rearrange">
        <span style={{ fontSize: 12, fontWeight: 600 }}>{w.title}</span>
        {scoped && <Mono size={7.5} color="var(--acc)">IN SCOPE</Mono>}
      </div>
      <div style={{ flex: 1, padding: 13 }}>{children}</div>
      <div style={{ padding: "7px 13px", borderTop: "1px solid var(--bd)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <Mono size={7.5}>HERE BECAUSE: {w.because.toUpperCase()}</Mono>
        {footer}
      </div>
    </Card>
  );
}

function MiniSpark({ world, sigId, anomaly }) {
  const [, force] = useStateW2(0);
  const tRef = useRefW2(0);
  const buf = useRefW2(Array.from({ length: 36 }, (_, i) => v2sample(world.signals.find((s) => s.id === sigId) || world.signals[0], i * 0.16, false)));
  useInterval(() => {
    tRef.current += 0.16;
    const s = world.signals.find((x) => x.id === sigId) || world.signals[0];
    buf.current.push(v2sample(s, tRef.current, anomaly && s.hot));
    if (buf.current.length > 36) buf.current.shift();
    force((n) => n + 1);
  }, 150, true);
  return <Spark2 values={buf.current} h={30} color={anomaly ? "var(--err)" : "var(--rt)"} />;
}

function WidgetBody({ w, world, go, openChat, fixes, run42, anomalyLive, requestProbe }) {
  const t = w.type;
  if (t === "exp") {
    const r41 = world.runs[0];
    const fixed = fixes["ap-clamp"] === "approved" && fixes["ap-flash"] === "approved";
    return (
      <div>
        {r41 ? (
          <div>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <span style={{ fontFamily: "var(--mono)", fontSize: 8.5, color: "var(--err)", border: "1px solid color-mix(in srgb, var(--err) 45%, transparent)", borderRadius: 99, padding: "2px 7px" }}>FAILED</span>
              <span style={{ fontSize: 12, fontWeight: 600 }}>Run {r41.id} — {r41.name}</span>
            </div>
            <div style={{ fontSize: 11, color: "var(--mut)", margin: "6px 0 8px" }}>{r41.bad.length} of {r41.eps} episodes anomalous · {r41.when}</div>
            <EpGrid eps={r41.eps} bad={r41.bad} small />
            {run42 && run42.status === "running" && <div style={{ marginTop: 8, fontFamily: "var(--mono)", fontSize: 10, color: "var(--acc)" }}>run 42 live — episode {run42.progress}/20</div>}
            {run42 && run42.status === "done" && <div style={{ marginTop: 8, fontFamily: "var(--mono)", fontSize: 10, color: "var(--ok)" }}>✓ run 42 passed — 0/20 anomalous</div>}
          </div>
        ) : <div style={{ fontSize: 11.5, color: "var(--mut)", lineHeight: 1.6 }}>{world.runsEmpty}</div>}
      </div>
    );
  }
  if (t === "finding") return <FindingCard f={world.finding} compact onOpen={() => openChat(world.id === "priya" ? "cutout" : world.id === "sam" ? "jitter" : "diagnose")} />;
  if (t === "bench") {
    const hots = world.signals.filter((s) => s.hot).slice(0, 2);
    const show = hots.length ? hots : world.signals.slice(0, 2);
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {show.map((s) => (
          <div key={s.id}>
            <div style={{ display: "flex", justifyContent: "space-between" }}><Mono size={8.5}>{s.name}</Mono><Mono size={8.5} color={anomalyLive && s.hot ? "var(--err)" : "var(--mut)"}>{anomalyLive && s.hot ? "ANOMALY" : "OK"}</Mono></div>
            <MiniSpark world={world} sigId={s.id} anomaly={anomalyLive} />
          </div>
        ))}
      </div>
    );
  }
  if (t === "repo") return (
    <div>
      {[["clamp action head to URDF limits", fixes["ap-clamp"] === "approved" ? "just now · SOL (approved by you)" : null], ["eval: log per-episode current", "2 d ago"], ["train: bump chunk size 100", "3 d ago"]].filter((r) => r[1]).map(([m, when]) => (
        <div key={m} style={{ padding: "6px 0", borderBottom: "1px solid var(--bd)" }}>
          <div style={{ fontFamily: "var(--mono)", fontSize: 10.5, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{m}</div>
          <div style={{ fontSize: 9.5, color: "var(--mut)", marginTop: 2 }}>{when}</div>
        </div>
      ))}
    </div>
  );
  if (t === "sim") return <div style={{ fontSize: 11.5, color: "var(--mut)", lineHeight: 1.7 }}>MuJoCo · so101_cube.xml<br />RT ×1.0 · joint clipping ON<br /><span style={{ color: "var(--warn)" }}>Sim clips at limits silently — hardware doesn't. That gap caused run 41.</span></div>;
  if (t === "guide") {
    const g = world.guide;
    return (
      <div>
        <div style={{ fontSize: 12, fontWeight: 600 }}>{g.task}</div>
        <div style={{ fontSize: 10.5, color: "var(--mut)", margin: "4px 0 8px" }}>{g.tool} · {g.steps.length} steps · 1 honest gap</div>
        <div style={{ display: "flex", gap: 3 }}>{g.steps.map((s, i) => <span key={i} style={{ flex: 1, height: 5, borderRadius: 2, background: s.gap ? "var(--warn)" : "var(--sur2)", border: "1px solid var(--bd)" }} title={s.t}></span>)}</div>
      </div>
    );
  }
  if (t === "board") return (
    <div>
      <div style={{ height: 64, borderRadius: 3, background: "repeating-linear-gradient(45deg, color-mix(in srgb, var(--ee) 12%, var(--bg)), color-mix(in srgb, var(--ee) 12%, var(--bg)) 6px, var(--bg) 6px, var(--bg) 12px)", border: "1px solid var(--bd)", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <Mono size={8.5}>{world.id === "priya" ? "PDU REV C · SHEET PREVIEW" : "SERVO-SHIELD.KICAD_PCB"}</Mono>
      </div>
      <div style={{ fontSize: 10.5, color: "var(--mut)", marginTop: 7, lineHeight: 1.5 }}>{world.id === "priya" ? "F3 (30 A) flagged by Saturday's finding." : "2 layers · no ground pour yet — the guide task fixes that."}</div>
    </div>
  );
  if (t === "identify") return (
    <div>
      <div style={{ fontSize: 11.5, lineHeight: 1.6 }}>I can see a <span style={{ fontFamily: "var(--mono)" }}>CH340</span> USB bridge. What's behind it is <span style={{ color: "var(--warn)" }}>unknown</span> — I won't guess.</div>
      <div style={{ display: "flex", gap: 6, marginTop: 9 }}>
        <Btn kind="primary" size="sm" onClick={requestProbe}>Probe (approval)</Btn>
        <Btn kind="bare" size="sm">It's an Uno</Btn>
      </div>
    </div>
  );
  if (t === "log") return (
    <div>
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <Btn kind="soft" size="sm" onClick={() => go("bench")}>{SI.play({ size: 11 })} Play in bench</Btn>
        <Mono size={8.5}>42 MIN · 1.2M FRAMES</Mono>
      </div>
      <div style={{ fontSize: 10.5, color: "var(--mut)", marginTop: 8, lineHeight: 1.55 }}>Lap 7 fault marked at 14:42:07. No live car — this is Saturday, labelled as such.</div>
    </div>
  );
  if (t === "can") return (
    <div>
      {[["bus load", "46%", "var(--ok)"], ["error frames", "0.02%", "var(--ok)"], ["inverter 0x0A2", "1 fault (log)", "var(--err)"]].map(([k, v, c]) => (
        <div key={k} style={{ display: "flex", justifyContent: "space-between", padding: "5px 0", borderBottom: "1px solid var(--bd)" }}>
          <span style={{ fontSize: 11, color: "var(--mut)" }}>{k}</span><span style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: c }}>{v}</span>
        </div>
      ))}
    </div>
  );
  if (t === "knowledge") return (
    <div>
      <div onClick={() => openChat("harness")} style={{ background: "var(--bg)", border: "1px solid var(--bd)", borderRadius: 3, padding: "8px 11px", fontSize: 11.5, color: "var(--mut)", cursor: "text" }}>who designed the accumulator harness?</div>
      <div style={{ fontSize: 10, color: "var(--mut)", marginTop: 7, lineHeight: 1.5 }}>Answers come with provenance — PDM, git, and the old team drive. Knowledge survives graduation.</div>
    </div>
  );
  if (t === "team") return (
    <div>
      {[["J. Park", "loom re-route merged", "me"], ["D. Chen", "vcu-fw: fault telemetry", "sw"], ["A. Osei", "PDU rev C sheet 4", "ee"]].map(([who, what, d]) => (
        <div key={who} style={{ display: "flex", gap: 8, alignItems: "center", padding: "5px 0", borderBottom: "1px solid var(--bd)" }}>
          <span style={{ width: 6, height: 6, borderRadius: 99, background: dcol(d), flexShrink: 0 }}></span>
          <span style={{ fontSize: 11 }}><strong>{who}</strong> · {what}</span>
        </div>
      ))}
    </div>
  );
  return null;
}

function WorkspaceScreen({ world, scope, go, openChat, fixes, run42, anomalyLive, requestProbe, onToast }) {
  const [task, setTask] = useStateW2(world.taskTabs[0]);
  const [order, setOrder] = useStateW2(null);
  const [trayOpen, setTrayOpen] = useStateW2(false);
  const dragIdx = useRefW2(null);
  useEffectW2(() => { setTask(world.taskTabs[0]); setOrder(null); }, [world.id]);

  const widgets = order || world.widgets[task] || [];
  const scopedIn = (w) => scope && ((w.type === "bench" && scope.kind === "signal") || (w.type === "finding") || (scope.kind === "node" && (w.type === "board" || w.type === "repo")));

  return (
    <div style={{ flex: 1, overflowY: "auto", minWidth: 0 }} data-screen-label="Workspace">
      <div style={{ maxWidth: 1080, margin: "0 auto", padding: "20px 26px 44px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 21, fontWeight: 600 }}>{world.wsName}</h1>
            <div style={{ fontSize: 11.5, color: "var(--mut)", marginTop: 3 }}>{world.tagline} — widgets derived from connections, nothing configured.</div>
          </div>
          <div style={{ flex: 1 }}></div>
          <Seg size="sm" options={world.taskTabs} value={task} onChange={(v) => { setTask(v); setOrder(null); }} />
          <Btn kind="ghost" size="sm" onClick={() => setTrayOpen(!trayOpen)}>{SI.plus({ size: 12 })} Add widget</Btn>
        </div>

        {trayOpen && (
          <Card pad={0} style={{ marginTop: 12 }}>
            <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--bd)" }}><Mono size={9}>NOT HERE YET — AND WHY</Mono></div>
            {world.unlocks.map((u) => (
              <div key={u.n} style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", padding: "10px 14px", borderBottom: "1px solid var(--bd)" }}>
                <div style={{ fontSize: 12 }}>{u.n} <span style={{ color: "var(--mut)" }}>→ unlocks {u.u}</span></div>
                <Btn kind="ghost" size="sm" onClick={() => go("connections")}>Connections</Btn>
              </div>
            ))}
            <div style={{ padding: "9px 14px", fontSize: 10.5, color: "var(--mut)" }}>Nothing here is configured by hand — widgets appear when their source exists.</div>
          </Card>
        )}

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 12, marginTop: 14 }}>
          {widgets.map((w, i) => (
            <WidgetShell key={w.id} w={w} scoped={scopedIn(w)}
              onDragStart={() => (dragIdx.current = i)}
              onDragOver={(e) => e.preventDefault()}
              onDrop={() => { const from = dragIdx.current; if (from == null || from === i) return; const n = [...widgets]; const [m] = n.splice(from, 1); n.splice(i, 0, m); setOrder(n); onToast("Layout saved for “" + task + "”", "Each task remembers its own arrangement."); }}
              footer={w.type === "exp" ? <Btn kind="bare" size="sm" onClick={() => go("experiments")}>Open →</Btn> : w.type === "bench" ? <Btn kind="bare" size="sm" onClick={() => go("bench")}>Open →</Btn> : w.type === "guide" ? <Btn kind="bare" size="sm" onClick={() => openChat("pour")}>Continue →</Btn> : null}>
              <WidgetBody w={w} world={world} go={go} openChat={openChat} fixes={fixes} run42={run42} anomalyLive={anomalyLive} requestProbe={requestProbe} />
            </WidgetShell>
          ))}
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { WorkspaceScreen, WidgetShell, WidgetBody });
