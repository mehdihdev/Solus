// Solus — cross-domain alert detail (the magic moment)
const { useState: useStateAl } = React;

function SevBadge({ sev, state }) {
  const c = state === "resolved" ? "var(--ok)" : sev === "critical" ? "var(--err)" : "var(--warn)";
  const label = state === "resolved" ? "RESOLVED" : sev.toUpperCase();
  return (
    <span style={{ fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.1em", color: c, border: `1px solid color-mix(in srgb, ${c} 45%, transparent)`, background: `color-mix(in srgb, ${c} 9%, transparent)`, borderRadius: 99, padding: "4px 10px" }}>{label}</span>
  );
}

function CodeBlock({ lines, hot, diff }) {
  return (
    <div style={{ background: "var(--bg)", border: "1px solid var(--bd)", borderRadius: 3, overflow: "hidden", fontFamily: "var(--mono)", fontSize: 11, lineHeight: 1.75 }}>
      {diff
        ? lines.map((d, i) => (
          <div key={i} style={{
            padding: "0 12px", whiteSpace: "pre",
            background: d.t === "del" ? "color-mix(in srgb, var(--err) 11%, transparent)" : d.t === "add" ? "color-mix(in srgb, var(--ok) 11%, transparent)" : "transparent",
            color: d.t === "del" ? "color-mix(in srgb, var(--err) 70%, var(--tx))" : d.t === "add" ? "color-mix(in srgb, var(--ok) 70%, var(--tx))" : "var(--mut)",
          }}>
            <span style={{ display: "inline-block", width: 14, opacity: 0.7 }}>{d.t === "del" ? "−" : d.t === "add" ? "+" : " "}</span>{d.s}
          </div>
        ))
        : lines.map((s, i) => (
          <div key={i} style={{ padding: "0 12px", whiteSpace: "pre", background: hot && hot.includes(i) ? "color-mix(in srgb, var(--warn) 10%, transparent)" : "transparent", color: hot && hot.includes(i) ? "var(--tx)" : "var(--mut)", borderLeft: hot && hot.includes(i) ? "2px solid var(--warn)" : "2px solid transparent" }}>
            {s || " "}
          </div>
        ))}
    </div>
  );
}

function BeforeAfter({ change }) {
  const col = (title, rows, accent) => (
    <div style={{ flex: 1 }}>
      <Mono size={9} color={accent ? "var(--acc)" : "var(--mut)"}>{title}</Mono>
      <div style={{ marginTop: 8 }}>
        {rows.map(([k, v]) => (
          <div key={k} style={{ display: "flex", justifyContent: "space-between", gap: 8, padding: "5px 0", borderBottom: "1px solid var(--bd)" }}>
            <span style={{ fontSize: 11, color: "var(--mut)" }}>{k}</span>
            <span style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: accent ? "var(--tx)" : "var(--mut)", textAlign: "right" }}>{v}</span>
          </div>
        ))}
      </div>
    </div>
  );
  return (
    <div style={{ display: "flex", gap: 18, alignItems: "stretch" }}>
      {col("BEFORE · REV 41", change.before, false)}
      <div style={{ display: "flex", alignItems: "center", color: "var(--acc)" }}>{SI.arrowR({ size: 16 })}</div>
      {col("AFTER · REV 42", change.after, true)}
    </div>
  );
}

function AlertScreen({ alert, solMode, onBack, onResolved, onIssue, onAskSol }) {
  const wasResolvedAtMount = React.useRef(alert.state === "resolved").current;
  const [applyState, setApplyState] = useStateAl(wasResolvedAtMount ? "done" : "idle"); // idle | busy | done
  const [applyStep, setApplyStep] = useStateAl(0);
  const [issueDone, setIssueDone] = useStateAl(false);
  const [whyMode, setWhyMode] = useStateAl(solMode || "Guide");

  const APPLY_STEPS = ["Creating branch fix/u4-pin-map…", "Applying patch to motor_driver.c…", "Running firmware build check…", "Opening PR #144 in strider-fw…"];

  const apply = () => {
    setApplyState("busy");
    APPLY_STEPS.forEach((_, i) => { if (i > 0) setTimeout(() => setApplyStep(i), i * 850); });
    setTimeout(() => { setApplyState("done"); onResolved && onResolved(alert.id); }, APPLY_STEPS.length * 850 + 500);
  };
  const createIssue = () => { setIssueDone(true); onIssue && onIssue(alert); };
  const resolved = applyState === "done";

  return (
    <div style={{ flex: 1, overflowY: "auto", minWidth: 0 }}>
      <div style={{ maxWidth: 1060, margin: "0 auto", padding: "22px 28px 48px" }}>
        {/* header */}
        <span onClick={onBack} style={{ display: "inline-flex", alignItems: "center", gap: 7, fontSize: 12.5, color: "var(--mut)", cursor: "pointer" }}>{SI.arrowL({ size: 13 })} Back</span>
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 18, marginTop: 14 }}>
          <div>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <SevBadge sev={alert.sev} state={resolved ? "resolved" : "open"} />
              <Mono size={9.5}>
                <span style={{ color: dcol(alert.fromD) }}>{SolusDomains[alert.fromD].label}</span>
                <span style={{ color: "var(--mut)" }}> → </span>
                <span style={{ color: dcol(alert.toD) }}>{SolusDomains[alert.toD].label}</span>
              </Mono>
            </div>
            <h1 style={{ margin: "12px 0 0", fontSize: 26, fontWeight: 600, letterSpacing: "-0.02em", lineHeight: 1.2 }}>{alert.title}</h1>
            <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 10, fontSize: 12.5, color: "var(--mut)" }}>
              <Avatar name={alert.actor} size={20} /> {alert.actor} · {alert.time} · detected by SOL in 90 ms
            </div>
          </div>
          <Btn kind="ghost" size="sm" onClick={() => onAskSol("alertq")}>{SI.sol({ size: 13 })} Ask SOL about this</Btn>
        </div>

        {resolved && (
          <div style={{ marginTop: 18, display: "flex", gap: 10, alignItems: "center", background: "color-mix(in srgb, var(--ok) 8%, transparent)", border: "1px solid color-mix(in srgb, var(--ok) 40%, transparent)", borderRadius: 3, padding: "11px 14px" }}>
            <span style={{ color: "var(--ok)" }}>{SI.check({ size: 15 })}</span>
            <span style={{ fontSize: 12.5 }}>
              {wasResolvedAtMount
                ? <>Resolved {alert.time} by {alert.resolvedBy || "Marcus Hale"} — fix merged in <span style={{ fontFamily: "var(--mono)", fontSize: 11.5 }}>{alert.issue.repo}#{alert.issue.num}</span></>
                : <>Fix applied — PR <span style={{ fontFamily: "var(--mono)", fontSize: 11.5 }}>strider-fw#144</span> opened and assigned to you. SOL will re-check on merge.</>}
            </span>
          </div>
        )}

        <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 360px", gap: 18, marginTop: 22, alignItems: "start" }}>
          {/* left: what changed + impact */}
          <div style={{ display: "flex", flexDirection: "column", gap: 14, minWidth: 0 }}>
            <Card pad={18}>
              <Mono size={9.5}>WHAT CHANGED</Mono>
              <div style={{ fontSize: 14.5, fontWeight: 600, marginTop: 8 }}>{alert.change.title}</div>
              <div style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--mut)", marginTop: 3 }}>{alert.change.source}</div>
              <div style={{ marginTop: 16 }}><BeforeAfter change={alert.change} /></div>
              <div style={{ marginTop: 14, fontSize: 11.5, color: "var(--mut)", fontStyle: "italic" }}>{alert.change.commit}</div>
            </Card>

            <Card pad={18}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <Mono size={9.5}>AFFECTED CODE · {alert.files.length} FILE{alert.files.length > 1 ? "S" : ""}</Mono>
                <Mono size={9} color={dcol("sw")}>● SOFTWARE</Mono>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 16, marginTop: 14 }}>
                {alert.files.map((f) => (
                  <div key={f.path}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 6, gap: 10 }}>
                      <span style={{ fontFamily: "var(--mono)", fontSize: 11.5, color: "var(--tx)", display: "inline-flex", gap: 7, alignItems: "center" }}>{SI.file({ size: 12 })} {f.path} <span style={{ color: "var(--mut)" }}>{f.range}</span></span>
                      <span style={{ fontSize: 11, color: "var(--warn)" }}>{f.note}</span>
                    </div>
                    <CodeBlock lines={f.code} hot={f.hot} />
                  </div>
                ))}
              </div>
            </Card>
          </div>

          {/* right: why + fix */}
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <Card pad={18}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <Mono size={9.5}>WHY IT BREAKS</Mono>
                <Seg size="sm" options={["Guide", "Expert"]} value={whyMode} onChange={setWhyMode} />
              </div>
              <p style={{ fontSize: whyMode === "Guide" ? 12.5 : 12, lineHeight: 1.65, color: "var(--tx)", margin: "12px 0 0", fontFamily: whyMode === "Expert" ? "var(--mono)" : "var(--ui)" }}>
                {whyMode === "Guide" ? alert.why.guide : alert.why.expert}
              </p>
            </Card>

            <Card pad={18} style={{ borderColor: resolved ? "var(--bd)" : "color-mix(in srgb, var(--acc) 45%, var(--bd))" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <Mono size={9.5} color="var(--acc)">SUGGESTED FIX</Mono>
                <Mono size={9}>{Math.round(alert.fix.confidence * 100)}% CONFIDENCE</Mono>
              </div>
              <div style={{ fontSize: 12.5, lineHeight: 1.55, marginTop: 10 }}>{alert.fix.summary}</div>
              <div style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--mut)", margin: "12px 0 6px" }}>{alert.fix.file}</div>
              <CodeBlock lines={alert.fix.diff} diff />

              {applyState === "idle" && (
                <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
                  <Btn id="btn-apply-fix" kind="primary" style={{ flex: 1 }} onClick={apply}>Apply fix</Btn>
                  <Btn kind="ghost" style={{ flex: 1 }} onClick={createIssue} disabled={issueDone}>
                    {issueDone ? <><span style={{ color: "var(--ok)" }}>{SI.check({ size: 13 })}</span> #144 created</> : "Create issue"}
                  </Btn>
                </div>
              )}
              {applyState === "busy" && (
                <div style={{ marginTop: 14, fontFamily: "var(--mono)", fontSize: 10.5 }}>
                  {APPLY_STEPS.map((s, i) => (
                    <div key={s} style={{ display: "flex", gap: 9, alignItems: "center", padding: "4px 0", color: i < applyStep ? "var(--ok)" : i === applyStep ? "var(--acc)" : "var(--mut)", opacity: i > applyStep ? 0.45 : 1 }}>
                      {i < applyStep ? <span>✓</span> : i === applyStep ? <Spinner size={10} /> : <span style={{ width: 10 }}></span>}
                      {s}
                    </div>
                  ))}
                </div>
              )}
              {applyState === "done" && !wasResolvedAtMount && (
                <div style={{ marginTop: 14, display: "flex", gap: 9, alignItems: "center", fontSize: 12, color: "var(--ok)" }}>
                  {SI.check({ size: 14 })} Patch applied — PR strider-fw#144 awaiting review
                </div>
              )}
            </Card>

            <Card pad={14}>
              <Mono size={9.5}>TRACE</Mono>
              <div style={{ display: "flex", flexDirection: "column", gap: 0, marginTop: 10 }}>
                {[["ee", "strider_main.sch rev 42", "change detected"], ["ee", "U4 · DRV8316C", "interface contract diff"], ["sw", "motor_driver.c +2 files", "stale references found"], ["rt", "FL knee phase", "predicted: ripple / shoot-through"]].map(([d, l, n], i, arr) => (
                  <div key={l} style={{ display: "flex", gap: 10 }}>
                    <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
                      <span style={{ width: 7, height: 7, borderRadius: 99, background: dcol(d), marginTop: 4, flexShrink: 0 }}></span>
                      {i < arr.length - 1 && <span style={{ width: 1, flex: 1, background: "var(--bd)", minHeight: 18 }}></span>}
                    </div>
                    <div style={{ paddingBottom: i < arr.length - 1 ? 10 : 0 }}>
                      <div style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--tx)" }}>{l}</div>
                      <div style={{ fontSize: 10.5, color: "var(--mut)" }}>{n}</div>
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          </div>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { AlertScreen, SevBadge, CodeBlock });
