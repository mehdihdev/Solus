// Solus — Live Bench: telemetry, quadruped schematic, anomaly
const { useState: useStateB, useEffect: useEffectB, useRef: useRefB } = React;

const BENCH_BUF = 64;

function JointCard({ sig, buf, val, bad }) {
  return (
    <Card pad={0} style={{ borderColor: bad ? "var(--err)" : "var(--bd)", overflow: "hidden", transition: "border-color 0.3s" }}>
      <div style={{ padding: "10px 12px 4px", display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <span style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: bad ? "var(--err)" : "var(--mut)" }}>{sig.l}</span>
        <span style={{ fontFamily: "var(--mono)", fontSize: 13.5, color: bad ? "var(--err)" : "var(--tx)" }}>
          {val.toFixed(2)}<span style={{ fontSize: 9, color: "var(--mut)", marginLeft: 3 }}>{sig.unit}</span>
        </span>
      </div>
      <Spark values={buf} w={196} h={34} color={bad ? "var(--err)" : "var(--rt)"} yMin={sig.base - sig.amp * 2.6} yMax={sig.base + sig.amp * 2.6} />
    </Card>
  );
}

function QuadSchematic({ anomaly }) {
  // top-down: body + 4 legs (hip joint at corner, knee mid, foot end)
  const legs = [
    { id: "FL", hx: 52, hy: 38, dx: -26, dy: -22 },
    { id: "FR", hx: 118, hy: 38, dx: 26, dy: -22 },
    { id: "RL", hx: 52, hy: 132, dx: -26, dy: 22 },
    { id: "RR", hx: 118, hy: 132, dx: 26, dy: 22 },
  ];
  return (
    <svg width="100%" viewBox="0 0 170 170" style={{ display: "block" }}>
      <rect x="52" y="38" width="66" height="94" rx="10" fill="var(--sur2)" stroke="var(--bd)"></rect>
      <circle cx="85" cy="62" r="5" fill="none" stroke="var(--rt)" strokeWidth="1.2" opacity="0.7"></circle>
      <text x="85" y="100" textAnchor="middle" fontFamily="var(--mono)" fontSize="8" fill="var(--mut)">QD-12</text>
      {legs.map((l) => {
        const kx = l.hx + l.dx, ky = l.hy + l.dy;
        const fx = kx + l.dx * 0.8, fy = ky + l.dy * 1.4;
        const bad = anomaly && l.id === "FL";
        const c = bad ? "var(--err)" : "var(--rt)";
        return (
          <g key={l.id}>
            <path d={`M${l.hx} ${l.hy} L${kx} ${ky} L${fx} ${fy}`} fill="none" stroke={c} strokeWidth="2" opacity="0.55" strokeLinecap="round"></path>
            <circle cx={l.hx} cy={l.hy} r="4" fill={c}></circle>
            <circle cx={kx} cy={ky} r={bad ? 5.5 : 3.5} fill={c} className={bad ? "gm-orb" : ""} style={bad ? { filter: "drop-shadow(0 0 5px var(--err))" } : {}}></circle>
            <circle cx={fx} cy={fy} r="3" fill="none" stroke={c} strokeWidth="1.5"></circle>
            <text x={l.hx + (l.dx > 0 ? 10 : -10)} y={l.hy - 8} textAnchor="middle" fontFamily="var(--mono)" fontSize="8.5" fill={bad ? "var(--err)" : "var(--mut)"}>{l.id}</text>
          </g>
        );
      })}
    </svg>
  );
}

function BenchScreen({ anomaly, onTriggerAnomaly, onAskSol, telemSpeed }) {
  const [mode, setMode] = useStateB("Sim");
  const [running, setRunning] = useStateB(true);
  const [pair, setPair] = useStateB("none"); // none | searching | found | paired
  const [, force] = useStateB(0);
  const tRef = useRefB(0);
  const t0Ref = useRefB(null);
  const bufs = useRefB({});
  const dismissedRef = useRefB(false);
  const [dismissed, setDismissed] = useStateB(false);

  const allSigs = [...TELEM.joints, ...TELEM.system];
  if (!bufs.current.init) {
    bufs.current.init = true;
    allSigs.forEach((s) => (bufs.current[s.id] = Array.from({ length: BENCH_BUF }, (_, i) => sample(s, i * 0.12, false))));
  }

  function sample(s, t, anomalyOn) {
    let v = s.base + s.amp * Math.sin((2 * Math.PI * t) / s.period + (s.phase || 0)) + (Math.random() - 0.5) * s.amp * 0.18;
    if (anomalyOn && s.id === "FL_knee") {
      if (t0Ref.current == null) t0Ref.current = t;
      const grow = Math.min(1, (t - t0Ref.current) / 2.5);
      v += 1.1 * grow * Math.sin(2 * Math.PI * 4.2 * t);
    }
    return v;
  }

  useInterval(() => {
    tRef.current += 0.12;
    const an = anomaly === "active";
    allSigs.forEach((s) => {
      const b = bufs.current[s.id];
      b.push(sample(s, tRef.current, an));
      if (b.length > BENCH_BUF) b.shift();
    });
    force((n) => n + 1);
  }, Math.max(40, 120 / (telemSpeed || 1)), running && (mode === "Sim" || pair === "paired"));

  // auto-anomaly ~8s after entering, once
  useEffectB(() => {
    if (anomaly !== "none") return;
    const t = setTimeout(() => onTriggerAnomaly(), 8000);
    return () => clearTimeout(t);
  }, [anomaly]);

  const startPair = () => {
    setPair("searching");
    setTimeout(() => setPair("found"), 1800);
  };

  const live = mode === "Sim" || pair === "paired";
  const showBanner = anomaly === "active" && !dismissed;

  return (
    <div style={{ flex: 1, overflowY: "auto", minWidth: 0 }}>
      <div style={{ maxWidth: 1160, margin: "0 auto", padding: "18px 24px 40px" }}>
        {/* bench header */}
        <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
          <Seg options={["Sim", "Real"]} value={mode} onChange={setMode} ids={["seg-sim", "seg-real"]} />
          <Btn kind="soft" size="sm" onClick={() => setRunning(!running)} disabled={!live}>
            {running ? <>{SI.pause({ size: 12 })} Pause</> : <>{SI.play({ size: 12 })} Run</>}
          </Btn>
          <Mono size={10}>
            {mode === "Sim" ? "SIM · GAZEBO HEADLESS" : pair === "paired" ? "REAL · STRIDER-QD12 #A3 · USB-C" : "REAL · NO DEVICE"}
          </Mono>
          <div style={{ flex: 1 }}></div>
          <Mono size={10} color={live && running ? "var(--ok)" : "var(--mut)"}>
            {live && running ? "● STREAMING · 500 HZ" : "○ PAUSED"}
          </Mono>
          <Btn kind="bare" size="sm" onClick={() => { setDismissed(false); onTriggerAnomaly(); }} style={{ fontSize: 11 }}>
            {SI.warn({ size: 12 })} Inject anomaly
          </Btn>
        </div>

        {/* anomaly banner */}
        {showBanner && (
          <div className="bench-banner" style={{ marginTop: 14, display: "flex", alignItems: "center", gap: 12, background: "color-mix(in srgb, var(--err) 9%, var(--sur))", border: "1px solid color-mix(in srgb, var(--err) 55%, transparent)", borderRadius: 3, padding: "12px 16px" }}>
            <span style={{ color: "var(--err)" }} className="gm-orb">{SI.warn({ size: 17 })}</span>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 13, fontWeight: 600 }}>Anomaly detected — τ_FL_knee oscillating at 4.2 Hz</div>
              <div style={{ fontSize: 11.5, color: "var(--mut)", marginTop: 2 }}>Amplitude rising · locked to 2× stride frequency · started 6 s ago</div>
            </div>
            <Btn id="btn-ask-sol-anomaly" kind="primary" size="sm" onClick={() => onAskSol("anomaly")}>{SI.sol({ size: 13 })} Ask SOL</Btn>
            <span onClick={() => setDismissed(true)} style={{ color: "var(--mut)", cursor: "pointer", padding: 4 }}>{SI.x({ size: 12 })}</span>
          </div>
        )}
        {anomaly === "resolved" && (
          <div style={{ marginTop: 14, display: "flex", alignItems: "center", gap: 10, background: "color-mix(in srgb, var(--ok) 7%, var(--sur))", border: "1px solid color-mix(in srgb, var(--ok) 40%, transparent)", borderRadius: 3, padding: "10px 16px", fontSize: 12.5 }}>
            <span style={{ color: "var(--ok)" }}>{SI.check({ size: 14 })}</span>
            Fix flashed — τ_FL_knee stable for 30 s. SOL is still watching this signal.
          </div>
        )}

        {/* real-mode empty state */}
        {mode === "Real" && pair !== "paired" && (
          <Card pad={0} style={{ marginTop: 16 }}>
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "64px 24px", gap: 14, textAlign: "center" }}>
              <span style={{ color: "var(--mut)", opacity: 0.7 }}>{SI.chip2({ size: 30 })}</span>
              {pair === "none" && (<>
                <div style={{ fontSize: 15, fontWeight: 600 }}>No hardware detected</div>
                <div style={{ fontSize: 12.5, color: "var(--mut)", maxWidth: 380, lineHeight: 1.6 }}>Connect your robot over USB-C or CAN, or pair a device on the local network. Telemetry starts streaming the moment a device answers.</div>
                <Btn kind="primary" onClick={startPair}>Pair device</Btn>
              </>)}
              {pair === "searching" && (<>
                <div style={{ fontSize: 14, fontWeight: 600, display: "flex", gap: 10, alignItems: "center" }}><Spinner /> Scanning USB + mDNS…</div>
                <Mono size={10}>LISTENING FOR STRIDER BOOTLOADER BEACON</Mono>
              </>)}
              {pair === "found" && (<>
                <div style={{ fontSize: 14, fontWeight: 600 }}>Found 1 device</div>
                <Card pad={14} style={{ width: 340, textAlign: "left", display: "flex", alignItems: "center", gap: 12 }}>
                  <span style={{ color: "var(--ok)" }}>{SI.chip2({ size: 20 })}</span>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontFamily: "var(--mono)", fontSize: 12 }}>STRIDER-QD12 #A3</div>
                    <div style={{ fontSize: 10.5, color: "var(--mut)" }}>USB-C · fw 0.9.2 · 12 joints reporting</div>
                  </div>
                  <Btn kind="primary" size="sm" onClick={() => setPair("paired")}>Connect</Btn>
                </Card>
              </>)}
            </div>
          </Card>
        )}

        {live && (
          <div style={{ display: "grid", gridTemplateColumns: "248px minmax(0,1fr)", gap: 14, marginTop: 16, alignItems: "start" }}>
            {/* left: robot + vitals */}
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              <Card pad={14}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                  <Mono size={9.5}>ROBOT · TOP VIEW</Mono>
                  {mode === "Real" && <Mono size={9} color="var(--ok)">REAL</Mono>}
                </div>
                <QuadSchematic anomaly={anomaly === "active"} />
                <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6 }}>
                  <Mono size={9} color="var(--mut)">GAIT: STANDING · 2.1 HZ</Mono>
                  <Mono size={9} color={anomaly === "active" ? "var(--err)" : "var(--ok)"}>{anomaly === "active" ? "1 FAULT" : "NOMINAL"}</Mono>
                </div>
              </Card>
              <Card pad={14}>
                <Mono size={9.5}>SYSTEM</Mono>
                <div style={{ marginTop: 6 }}>
                  {TELEM.system.map((s) => {
                    const b = bufs.current[s.id];
                    const v = b[b.length - 1];
                    return <KV key={s.id} k={s.l} v={`${v.toFixed(s.base > 100 ? 0 : 1)} ${s.unit}`} />;
                  })}
                </div>
              </Card>
            </div>

            {/* joint grid */}
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                <Mono size={9.5}>JOINT TORQUES · 12 ACTUATORS</Mono>
                <Mono size={9}>WINDOW: 8 S</Mono>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(196px, 1fr))", gap: 10 }}>
                {TELEM.joints.map((s) => {
                  const b = bufs.current[s.id];
                  return <JointCard key={s.id} sig={s} buf={b} val={b[b.length - 1]} bad={anomaly === "active" && s.id === "FL_knee"} />;
                })}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

Object.assign(window, { BenchScreen });
