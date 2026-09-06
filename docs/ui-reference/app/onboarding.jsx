// Solus — onboarding: project setup → connect tools → build context model
const { useState: useStateO, useEffect: useEffectO, useRef: useRefO } = React;

const OB_TEMPLATES = [
  { id: "quad", name: "Quadruped", sub: "12 actuators · IMU · CAN FD", body: "M12" },
  { id: "rover", name: "Diff-drive rover", sub: "2 motors · lidar · IMU", body: "M2" },
  { id: "arm", name: "Robot arm", sub: "6 DOF · servo bus · gripper", body: "M6" },
  { id: "drone", name: "Quadcopter", sub: "4 ESCs · GPS · baro", body: "M4" },
];

function ObStepDots({ step }) {
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
      {["About", "Connect", "Build"].map((s, i) => (
        <React.Fragment key={s}>
          {i > 0 && <div style={{ width: 26, height: 1, background: i <= step ? "var(--acc)" : "var(--bd)" }}></div>}
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            <span style={{ width: 7, height: 7, borderRadius: 99, background: i <= step ? "var(--acc)" : "var(--bd)" }}></span>
            <Mono size={9.5} color={i <= step ? "var(--tx)" : "var(--mut)"}>{s}</Mono>
          </span>
        </React.Fragment>
      ))}
    </div>
  );
}

function ConnectTile({ integ, st, onConnect }) {
  // st: undefined | {phase:'busy', stepIdx} | {phase:'done'}
  const busy = st && st.phase === "busy";
  const done = st && st.phase === "done";
  return (
    <Card pad={0} onClick={!st ? onConnect : undefined}
      style={{ cursor: !st ? "pointer" : "default", overflow: "hidden", borderColor: done ? "color-mix(in srgb, var(--ok) 45%, var(--bd))" : busy ? "var(--acc)" : "var(--bd)", transition: "border-color 0.2s" }}>
      <div style={{ padding: "16px 16px 14px", display: "flex", gap: 12, alignItems: "center" }}>
        <span style={{ width: 38, height: 38, borderRadius: 3, background: "var(--sur2)", border: "1px solid var(--bd)", display: "inline-flex", alignItems: "center", justifyContent: "center", fontFamily: "var(--mono)", fontSize: 13, fontWeight: 500, color: "var(--tx)", flexShrink: 0 }}>{integ.mark}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13.5, fontWeight: 600 }}>{integ.name}</div>
          <div style={{ fontSize: 11, color: "var(--mut)" }}>{integ.kind}</div>
        </div>
        {!st && <span style={{ color: "var(--acc)", fontSize: 12, fontWeight: 500 }}>Connect</span>}
        {busy && <Spinner />}
        {done && <span style={{ color: "var(--ok)" }}>{SI.check({ size: 15 })}</span>}
      </div>
      <div style={{ borderTop: "1px solid var(--bd)", padding: "9px 16px", minHeight: 16, background: "var(--bg)" }}>
        {!st && <span style={{ fontSize: 11, color: "var(--mut)" }}>Not connected</span>}
        {busy && <span style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--acc)" }}>{integ.steps[st.stepIdx]}</span>}
        {done && <span style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--ok)" }}>{integ.result}</span>}
      </div>
    </Card>
  );
}

function Onboarding({ onComplete }) {
  const [step, setStep] = useStateO(0);
  const [desc, setDesc] = useStateO("");
  const [tpl, setTpl] = useStateO(null);
  const [path, setPath] = useStateO("connect"); // connect | template
  const [conn, setConn] = useStateO({});
  const [buildLog, setBuildLog] = useStateO([]);
  const [buildDone, setBuildDone] = useStateO(false);

  const nConnected = Object.values(conn).filter((s) => s.phase === "done").length;

  const connect = (integ) => {
    setConn((c) => ({ ...c, [integ.id]: { phase: "busy", stepIdx: 0 } }));
    integ.steps.forEach((_, i) => {
      if (i > 0) setTimeout(() => setConn((c) => ({ ...c, [integ.id]: { phase: "busy", stepIdx: i } })), i * 650);
    });
    setTimeout(() => setConn((c) => ({ ...c, [integ.id]: { phase: "done" } })), integ.steps.length * 650 + 350);
  };

  const startBuild = () => {
    setStep(2);
    const lines = [
      ["Parsing strider_main.kicad_sch", "47 components · 16 nets"],
      ["Indexing strider-fw", "214 files · 31k LOC"],
      ["Reading Onshape assemblies", "12 assemblies · 84 parts"],
      ["Mapping ROS 2 node graph", "9 nodes · 23 topics"],
      ["Resolving cross-domain links", "31 links found"],
      ["Checking integration contracts", "2 issues flagged"],
    ];
    lines.forEach((l, i) => setTimeout(() => setBuildLog((b) => [...b, l]), 500 + i * 750));
    setTimeout(() => setBuildDone(true), 500 + lines.length * 750 + 400);
  };

  const tplPick = path === "template";

  return (
    <div style={{ height: "100%", minHeight: 0, background: "var(--bg)", color: "var(--tx)", fontFamily: "var(--ui)", display: "flex", flexDirection: "column" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "18px 32px", borderBottom: "1px solid var(--bd)", flexShrink: 0 }}>
        <SolusWordmark size={14} />
        <ObStepDots step={step} />
        <Mono size={9.5}>MAYA@STRIDER.DEV</Mono>
      </div>

      <div style={{ flex: 1, display: "flex", justifyContent: "center", padding: "52px 24px", overflowY: "auto" }}>
        {step === 0 && (
          <div style={{ width: 660 }}>
            <h2 style={{ margin: 0, fontSize: 28, fontWeight: 600, letterSpacing: "-0.02em" }}>What are you building?</h2>
            <p style={{ color: "var(--mut)", fontSize: 13.5, marginTop: 8, lineHeight: 1.55 }}>
              Solus uses this to name your project and tune what it looks for.
            </p>
            <textarea value={desc} onChange={(e) => setDesc(e.target.value)}
              placeholder="A 12-DOF quadruped for outdoor inspection. STM32 firmware, custom BLDC drivers, ROS 2 on a Jetson…"
              style={{ width: "100%", boxSizing: "border-box", height: 84, marginTop: 18, background: "var(--sur)", color: "var(--tx)", border: "1px solid var(--bd)", borderRadius: 3, padding: "12px 14px", fontSize: 13.5, fontFamily: "var(--ui)", resize: "none", outline: "none", lineHeight: 1.5 }}></textarea>

            <div style={{ display: "flex", gap: 8, marginTop: 26, alignItems: "center" }}>
              <Mono size={9.5}>STARTING POINT</Mono>
              <div style={{ flex: 1, height: 1, background: "var(--bd)" }}></div>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginTop: 14 }}>
              <Card pad={16} onClick={() => setPath("connect")} style={{ cursor: "pointer", borderColor: path === "connect" ? "var(--acc)" : "var(--bd)" }}>
                <div style={{ fontSize: 13.5, fontWeight: 600 }}>Connect my existing tools</div>
                <div style={{ fontSize: 12, color: "var(--mut)", marginTop: 4, lineHeight: 1.5 }}>GitHub, KiCad, Onshape, ROS 2 — Solus builds the graph from your real sources.</div>
              </Card>
              <Card pad={16} onClick={() => setPath("template")} style={{ cursor: "pointer", borderColor: path === "template" ? "var(--acc)" : "var(--bd)" }}>
                <div style={{ fontSize: 13.5, fontWeight: 600 }}>Start from a template robot</div>
                <div style={{ fontSize: 12, color: "var(--mut)", marginTop: 4, lineHeight: 1.5 }}>No project yet? Explore with a fully-wired reference robot and simulated bench.</div>
              </Card>
            </div>

            {tplPick && (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10, marginTop: 14 }}>
                {OB_TEMPLATES.map((t) => (
                  <Card key={t.id} pad={14} onClick={() => setTpl(t.id)} style={{ cursor: "pointer", textAlign: "center", borderColor: tpl === t.id ? "var(--acc)" : "var(--bd)" }}>
                    <div style={{ fontFamily: "var(--mono)", fontSize: 17, color: tpl === t.id ? "var(--acc)" : "var(--mut)" }}>{t.body}</div>
                    <div style={{ fontSize: 12.5, fontWeight: 600, marginTop: 6 }}>{t.name}</div>
                    <div style={{ fontSize: 10, color: "var(--mut)", marginTop: 3 }}>{t.sub}</div>
                  </Card>
                ))}
              </div>
            )}

            <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 28 }}>
              <Btn kind="primary" size="lg" disabled={tplPick && !tpl}
                onClick={() => {
                  if (tplPick) {
                    // template path pre-connects simulated sources
                    const all = {};
                    INTEGRATIONS.forEach((i) => (all[i.id] = { phase: "done" }));
                    setConn(all);
                    startBuild();
                  } else setStep(1);
                }}>
                Continue {SI.arrowR({ size: 14 })}
              </Btn>
            </div>
          </div>
        )}

        {step === 1 && (
          <div style={{ width: 660 }}>
            <h2 style={{ margin: 0, fontSize: 28, fontWeight: 600, letterSpacing: "-0.02em" }}>Connect your tools</h2>
            <p style={{ color: "var(--mut)", fontSize: 13.5, marginTop: 8, lineHeight: 1.55 }}>
              Each source becomes a domain in your context model. Connect at least two —
              cross-domain checks need something to cross.
            </p>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginTop: 24 }}>
              {INTEGRATIONS.map((integ) => (
                <ConnectTile key={integ.id} integ={integ} st={conn[integ.id]} onConnect={() => connect(integ)} />
              ))}
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 28 }}>
              <Mono size={10} color={nConnected >= 2 ? "var(--ok)" : "var(--mut)"}>
                {nConnected} OF 4 CONNECTED {nConnected >= 2 ? "— READY" : "(NEED 2+)"}
              </Mono>
              <Btn kind="primary" size="lg" disabled={nConnected < 2} onClick={startBuild}>
                Build context model {SI.arrowR({ size: 14 })}
              </Btn>
            </div>
          </div>
        )}

        {step === 2 && (
          <div style={{ width: 560 }}>
            <h2 style={{ margin: 0, fontSize: 28, fontWeight: 600, letterSpacing: "-0.02em" }}>
              {buildDone ? "Context model ready" : "Building your context model"}
            </h2>
            <p style={{ color: "var(--mut)", fontSize: 13.5, marginTop: 8 }}>
              {buildDone ? "247 nodes · 31 cross-domain links · 2 issues already flagged" : "Linking everything your robot is made of…"}
            </p>
            <Card pad={0} style={{ marginTop: 24, fontFamily: "var(--mono)" }}>
              {buildLog.map(([l, r], i) => (
                <div key={i} className="ob-logline" style={{ display: "flex", justifyContent: "space-between", padding: "9px 16px", borderBottom: "1px solid var(--bd)", fontSize: 11 }}>
                  <span style={{ color: "var(--tx)" }}><span style={{ color: "var(--ok)", marginRight: 10 }}>✓</span>{l}</span>
                  <span style={{ color: "var(--mut)" }}>{r}</span>
                </div>
              ))}
              {!buildDone && (
                <div style={{ display: "flex", gap: 10, padding: "9px 16px", fontSize: 11, color: "var(--acc)", alignItems: "center" }}>
                  <Spinner size={11} /> working…
                </div>
              )}
            </Card>
            {buildDone && (
              <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 24 }}>
                <Btn kind="primary" size="lg" onClick={() => onComplete(Object.keys(conn))}>
                  Open workspace {SI.arrowR({ size: 14 })}
                </Btn>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

Object.assign(window, { Onboarding });
