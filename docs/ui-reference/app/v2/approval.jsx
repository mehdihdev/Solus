// Solus v2 — approval surface: one card for every action type (code / cad / flash / motion / cmd)
const { useState: useStateAp } = React;

function RiskChip({ risk }) {
  const c = risk === "high" ? "var(--err)" : risk === "medium" ? "var(--warn)" : "var(--ok)";
  return <span style={{ fontFamily: "var(--mono)", fontSize: 8.5, letterSpacing: "0.08em", color: c, border: `1px solid color-mix(in srgb, ${c} 45%, transparent)`, borderRadius: 99, padding: "2px 8px", textTransform: "uppercase" }}>{risk} risk</span>;
}

function DiffBlock({ diff }) {
  return (
    <div style={{ background: "var(--bg)", border: "1px solid var(--bd)", borderRadius: 3, overflow: "auto", fontFamily: "var(--mono)", fontSize: 11, lineHeight: 1.75 }}>
      {diff.map((d, i) => (
        <div key={i} style={{ padding: "0 12px", whiteSpace: "pre", background: d.t === "del" ? "color-mix(in srgb, var(--err) 11%, transparent)" : d.t === "add" ? "color-mix(in srgb, var(--ok) 11%, transparent)" : "transparent", color: d.t === "del" ? "color-mix(in srgb, var(--err) 70%, var(--tx))" : d.t === "add" ? "color-mix(in srgb, var(--ok) 70%, var(--tx))" : "var(--mut)" }}>
          <span style={{ display: "inline-block", width: 14, opacity: 0.7 }}>{d.t === "del" ? "−" : d.t === "add" ? "+" : " "}</span>{d.s}
        </div>
      ))}
    </div>
  );
}

function ParamDiff({ params }) {
  return (
    <div style={{ background: "var(--bg)", border: "1px solid var(--bd)", borderRadius: 3, padding: "4px 12px" }}>
      {params.map(([k, from, to]) => (
        <div key={k} style={{ display: "flex", alignItems: "baseline", gap: 10, padding: "6px 0", borderBottom: "1px solid var(--bd)", fontSize: 12 }}>
          <span style={{ color: "var(--mut)", width: 110, flexShrink: 0, fontSize: 11.5 }}>{k}</span>
          <span style={{ fontFamily: "var(--mono)", fontSize: 11.5, color: "color-mix(in srgb, var(--err) 70%, var(--tx))", textDecoration: "line-through", textDecorationColor: "color-mix(in srgb, var(--err) 55%, transparent)" }}>{from}</span>
          <span style={{ color: "var(--acc)" }}>{SI.arrowR({ size: 12 })}</span>
          <span style={{ fontFamily: "var(--mono)", fontSize: 11.5, color: "color-mix(in srgb, var(--ok) 75%, var(--tx))" }}>{to}</span>
        </div>
      ))}
    </div>
  );
}

function Manifest({ manifest }) {
  return (
    <div style={{ background: "var(--bg)", border: "1px solid var(--bd)", borderRadius: 3, padding: "4px 12px" }}>
      {manifest.map(([k, v]) => (
        <div key={k} style={{ display: "flex", justifyContent: "space-between", gap: 12, padding: "6px 0", borderBottom: "1px solid var(--bd)" }}>
          <span style={{ fontSize: 11.5, color: "var(--mut)", flexShrink: 0 }}>{k}</span>
          <span style={{ fontFamily: "var(--mono)", fontSize: 11, textAlign: "right" }}>{v}</span>
        </div>
      ))}
    </div>
  );
}

const AP_TYPE_LABEL = { code: "CODE EDIT", cad: "CAD EDIT", flash: "FIRMWARE FLASH", motion: "ROBOT MOTION", cmd: "SHELL COMMAND" };

function ApprovalCard({ spec, state, onApprove, onReject, busyLines }) {
  const done = state === "approved", rejected = state === "rejected", busy = state === "busy";
  return (
    <Card pad={0} style={{ borderColor: done ? "color-mix(in srgb, var(--ok) 40%, var(--bd))" : rejected ? "var(--bd)" : "color-mix(in srgb, var(--acc) 50%, var(--bd))", opacity: rejected ? 0.6 : 1 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, padding: "10px 14px", borderBottom: "1px solid var(--bd)" }}>
        <Mono size={9} color="var(--acc)">{AP_TYPE_LABEL[spec.type] || "ACTION"}</Mono>
        <RiskChip risk={spec.risk} />
      </div>
      <div style={{ padding: "12px 14px" }}>
        <div style={{ fontSize: 13, fontWeight: 600, lineHeight: 1.45 }}>{spec.title}</div>
        {spec.target && <div style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--mut)", marginTop: 3 }}>{spec.target}</div>}
        <div style={{ marginTop: 10 }}>
          {spec.diff && <DiffBlock diff={spec.diff} />}
          {spec.params && <ParamDiff params={spec.params} />}
          {spec.cmd && <div style={{ background: "var(--bg)", border: "1px solid var(--bd)", borderRadius: 3, padding: "9px 12px", fontFamily: "var(--mono)", fontSize: 11, color: "var(--tx)", overflowX: "auto", whiteSpace: "nowrap" }}>$ {spec.cmd}</div>}
          {spec.manifest && <div style={{ marginTop: spec.cmd || spec.diff ? 8 : 0 }}><Manifest manifest={spec.manifest} /></div>}
        </div>
        {spec.note && <div style={{ fontSize: 11.5, color: "var(--mut)", lineHeight: 1.55, marginTop: 10 }}>{spec.note}</div>}

        {busy && busyLines && (
          <div style={{ marginTop: 10, fontFamily: "var(--mono)", fontSize: 10.5 }}>
            {busyLines.map((l, i) => (
              <div key={i} style={{ display: "flex", gap: 8, alignItems: "center", padding: "3px 0", color: l.done ? "var(--ok)" : "var(--acc)" }}>
                {l.done ? <span>✓</span> : <Spinner size={10} />}{l.s}
              </div>
            ))}
          </div>
        )}
        {!done && !rejected && !busy && (
          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <Btn kind="primary" size="sm" style={{ flex: 1 }} onClick={onApprove}>Approve & run</Btn>
            <Btn kind="ghost" size="sm" style={{ flex: 1 }} onClick={onReject}>Reject</Btn>
          </div>
        )}
        {done && <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 12, fontSize: 12, color: "var(--ok)" }}>{SI.check({ size: 14 })} {spec.doneMsg || "Applied"} · nothing ran before your click</div>}
        {rejected && <div style={{ marginTop: 12, fontSize: 12, color: "var(--mut)" }}>Rejected — no action taken. SOL keeps the proposal in history.</div>}
      </div>
    </Card>
  );
}

function ApprovalsPopover({ items, onClose, onJump }) {
  return (
    <div style={{ position: "fixed", top: 58, right: 120, width: 330, zIndex: 130 }} onClick={(e) => e.stopPropagation()}>
      <Card pad={0} style={{ boxShadow: "0 16px 50px rgba(0,0,0,0.5)" }}>
        <div style={{ padding: "11px 14px", borderBottom: "1px solid var(--bd)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <Mono size={9.5}>APPROVALS</Mono>
          <span onClick={onClose} style={{ color: "var(--mut)", cursor: "pointer" }}>{SI.x({ size: 12 })}</span>
        </div>
        {items.length === 0 && <div style={{ padding: "20px 14px", fontSize: 12, color: "var(--mut)", lineHeight: 1.55 }}>Nothing waiting. When SOL proposes a destructive action — a CAD edit, a flash, a motion — it queues here and never runs on its own.</div>}
        {items.map(({ spec, state }) => (
          <div key={spec.id} onClick={() => onJump(spec.id)} style={{ display: "flex", gap: 10, padding: "11px 14px", borderBottom: "1px solid var(--bd)", cursor: "pointer", opacity: state === "pending" ? 1 : 0.55 }}>
            <span style={{ color: state === "approved" ? "var(--ok)" : state === "rejected" ? "var(--mut)" : "var(--acc)", marginTop: 1 }}>
              {state === "approved" ? SI.check({ size: 13 }) : SI.warn({ size: 13 })}
            </span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 12, fontWeight: 600, lineHeight: 1.4 }}>{spec.title}</div>
              <Mono size={8.5} style={{ marginTop: 3 }}>{AP_TYPE_LABEL[spec.type]} · {state.toUpperCase()}</Mono>
            </div>
          </div>
        ))}
      </Card>
    </div>
  );
}

Object.assign(window, { ApprovalCard, ApprovalsPopover, RiskChip, DiffBlock, ParamDiff });
