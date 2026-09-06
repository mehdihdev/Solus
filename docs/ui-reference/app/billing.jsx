// Solus — Billing & plan page + Stripe-style payment modal
const { useState: useStateB2 } = React;

function fmtCardNum(v) {
  const d = v.replace(/\D/g, "").slice(0, 16);
  return d.replace(/(.{4})/g, "$1 ").trim();
}
function fmtExp(v) {
  const d = v.replace(/\D/g, "").slice(0, 4);
  return d.length > 2 ? d.slice(0, 2) + " / " + d.slice(2) : d;
}

function StripeModal({ onClose, onSaved }) {
  const [num, setNum] = useStateB2("");
  const [exp, setExp] = useStateB2("");
  const [cvc, setCvc] = useStateB2("");
  const [name, setName] = useStateB2("Maya Krishnan");
  const [state, setState] = useStateB2("idle"); // idle | busy | done
  const ready = num.replace(/\s/g, "").length >= 15 && exp.length >= 7 && cvc.length >= 3 && name;
  const brand = num.trim().startsWith("4") ? "Visa" : num.trim().startsWith("5") ? "Mastercard" : "Card";
  const pay = () => {
    setState("busy");
    setTimeout(() => {
      setState("done");
      setTimeout(() => { onSaved({ brand, last4: num.replace(/\s/g, "").slice(-4) || "4242", exp: exp || "08 / 28", name }); }, 900);
    }, 1700);
  };
  const fieldStyle = { width: "100%", boxSizing: "border-box", background: "var(--bg)", color: "var(--tx)", border: "1px solid var(--bd)", borderRadius: 4, padding: "10px 12px", fontSize: 13, fontFamily: "var(--mono)", outline: "none" };
  return (
    <ChromeModal title="Add payment method" onClose={state === "busy" ? () => {} : onClose} width={420}>
      {state === "done" ? (
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 12, padding: "16px 0" }}>
          <span style={{ width: 44, height: 44, borderRadius: 99, background: "color-mix(in srgb, var(--ok) 16%, transparent)", color: "var(--ok)", display: "inline-flex", alignItems: "center", justifyContent: "center" }}>{SI.check({ size: 22 })}</span>
          <div style={{ fontSize: 14, fontWeight: 600 }}>Card added</div>
          <div style={{ fontSize: 12, color: "var(--mut)" }}>{brand} ending {num.replace(/\s/g, "").slice(-4) || "4242"}</div>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div>
            <Mono size={8.5} style={{ display: "block", marginBottom: 6 }}>CARD NUMBER</Mono>
            <div style={{ position: "relative" }}>
              <input value={num} onChange={(e) => setNum(fmtCardNum(e.target.value))} placeholder="4242 4242 4242 4242" style={fieldStyle} />
              <span style={{ position: "absolute", right: 12, top: 9, color: "var(--mut)" }}>{SI.card({ size: 16 })}</span>
            </div>
          </div>
          <div style={{ display: "flex", gap: 10 }}>
            <div style={{ flex: 1 }}>
              <Mono size={8.5} style={{ display: "block", marginBottom: 6 }}>EXPIRY</Mono>
              <input value={exp} onChange={(e) => setExp(fmtExp(e.target.value))} placeholder="MM / YY" style={fieldStyle} />
            </div>
            <div style={{ flex: 1 }}>
              <Mono size={8.5} style={{ display: "block", marginBottom: 6 }}>CVC</Mono>
              <input value={cvc} onChange={(e) => setCvc(e.target.value.replace(/\D/g, "").slice(0, 4))} placeholder="123" style={fieldStyle} />
            </div>
          </div>
          <div>
            <Mono size={8.5} style={{ display: "block", marginBottom: 6 }}>NAME ON CARD</Mono>
            <input value={name} onChange={(e) => setName(e.target.value)} style={{ ...fieldStyle, fontFamily: "var(--ui)" }} />
          </div>
          <Btn kind="primary" onClick={pay} disabled={!ready || state === "busy"} style={{ width: "100%", padding: "11px 0", marginTop: 4 }}>
            {state === "busy" ? <><Spinner color="var(--acc-ink)" /> Processing…</> : "Add card"}
          </Btn>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 6, fontSize: 10.5, color: "var(--mut)" }}>
            {SI.key({ size: 11 })} Secured by <span style={{ fontWeight: 600 }}>Stripe</span> · test mode — no real charge
          </div>
        </div>
      )}
    </ChromeModal>
  );
}

function PlanCard({ plan, onCta }) {
  const cur = plan.current;
  return (
    <Card pad={18} style={{ borderColor: cur ? "color-mix(in srgb, var(--acc) 55%, var(--bd))" : "var(--bd)", display: "flex", flexDirection: "column", position: "relative" }}>
      {cur && <span style={{ position: "absolute", top: 14, right: 14, fontFamily: "var(--mono)", fontSize: 8.5, letterSpacing: "0.08em", color: "var(--acc)", border: "1px solid color-mix(in srgb, var(--acc) 45%, transparent)", borderRadius: 99, padding: "2px 8px" }}>CURRENT</span>}
      <div style={{ fontSize: 14, fontWeight: 600 }}>{plan.name}</div>
      <div style={{ fontSize: 11.5, color: "var(--mut)", marginTop: 2 }}>{plan.tagline}</div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginTop: 14 }}>
        <span style={{ fontSize: 26, fontWeight: 700, fontFamily: "var(--mono)" }}>{plan.price === null ? "Custom" : plan.price === 0 ? "$0" : "$" + plan.price}</span>
        {plan.price !== null && <span style={{ fontSize: 11, color: "var(--mut)" }}>{plan.unit}</span>}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 7, margin: "16px 0", flex: 1 }}>
        {plan.features.map((f) => (
          <div key={f} style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: 11.5, color: "var(--tx)" }}>
            <span style={{ color: "var(--ok)", marginTop: 1, flexShrink: 0 }}>{SI.check({ size: 12 })}</span>{f}
          </div>
        ))}
      </div>
      <Btn kind={cur ? "ghost" : plan.id === "ent" ? "soft" : "primary"} size="sm" disabled={cur} onClick={() => onCta(plan)} style={{ width: "100%" }}>{plan.cta}</Btn>
    </Card>
  );
}

function BillingPage({ onUpgrade }) {
  const [card, setCard] = useStateB2(BILLING.card);
  const [stripeOpen, setStripeOpen] = useStateB2(false);
  const usedPct = (BILLING.creditsUsed / BILLING.creditsTotal) * 100;
  const monthly = BILLING.seats * 20;
  return (
    <div>
      {/* current plan + usage */}
      <SettSection icon={SI.card({ size: 15 })} title="Current plan"
        right={<span style={{ fontFamily: "var(--mono)", fontSize: 8.5, letterSpacing: "0.08em", color: "var(--acc)", border: "1px solid color-mix(in srgb, var(--acc) 45%, transparent)", borderRadius: 99, padding: "3px 9px" }}>TEAM</span>}>
        <div style={{ display: "flex", gap: 24, flexWrap: "wrap", alignItems: "baseline" }}>
          <div>
            <div style={{ fontSize: 24, fontWeight: 700, fontFamily: "var(--mono)" }}>${monthly}<span style={{ fontSize: 12, color: "var(--mut)", fontFamily: "var(--ui)", fontWeight: 400 }}> / month</span></div>
            <div style={{ fontSize: 11.5, color: "var(--mut)", marginTop: 3 }}>{BILLING.seats} seats × $20 · renews {BILLING.renews}</div>
          </div>
        </div>
        <div style={{ marginTop: 18 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 8 }}>
            <Mono size={9}>POOLED SOL CREDITS</Mono>
            <span style={{ fontFamily: "var(--mono)", fontSize: 12 }}>{BILLING.creditsUsed.toLocaleString()} <span style={{ color: "var(--mut)" }}>/ {BILLING.creditsTotal.toLocaleString()}</span></span>
          </div>
          <div style={{ height: 7, background: "var(--bg)", border: "1px solid var(--bd)", borderRadius: 99, overflow: "hidden" }}>
            <div style={{ width: usedPct + "%", height: "100%", background: usedPct > 85 ? "var(--err)" : "var(--acc)" }}></div>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", marginTop: 7 }}>
            <span style={{ fontSize: 10.5, color: "var(--mut)" }}>{Math.round(usedPct)}% used · resets {BILLING.renews}</span>
            <span style={{ fontSize: 10.5, color: "var(--mut)" }}>Overage {BILLING.overageRate}</span>
          </div>
          <div style={{ marginTop: 14 }}>
            {BILLING.usageRows.map(([k, v]) => <KV key={k} k={k} v={v.toLocaleString() + " cr"} />)}
          </div>
        </div>
      </SettSection>

      {/* plans */}
      <div style={{ marginBottom: 6 }}><Mono size={9}>PLANS</Mono></div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12, marginBottom: 16 }}>
        {PLANS.map((p) => <PlanCard key={p.id} plan={p} onCta={(pl) => onUpgrade(pl)} />)}
      </div>

      {/* payment method */}
      <SettSection icon={SI.card({ size: 15 })} title="Payment method" right={<Btn kind="ghost" size="sm" onClick={() => setStripeOpen(true)}>{card ? "Update" : "Add"}</Btn>}>
        {card ? (
          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <span style={{ width: 46, height: 30, borderRadius: 5, background: "linear-gradient(135deg, var(--sur2), var(--bg))", border: "1px solid var(--bd)", display: "inline-flex", alignItems: "center", justifyContent: "center", color: "var(--mut)" }}>{SI.card({ size: 17 })}</span>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 12.5, fontWeight: 600 }}>{card.brand} ending {card.last4}</div>
              <div style={{ fontSize: 11, color: "var(--mut)" }}>Expires {card.exp} · {card.name}</div>
            </div>
            <Mono size={9} color="var(--ok)">● DEFAULT</Mono>
          </div>
        ) : (
          <div style={{ fontSize: 12, color: "var(--mut)" }}>No payment method on file.</div>
        )}
      </SettSection>

      {/* invoices */}
      <SettSection icon={SI.file({ size: 15 })} title="Billing history">
        <div>
          <div style={{ display: "grid", gridTemplateColumns: "1.3fr 1fr 1fr 0.7fr 28px", gap: 10, padding: "0 0 8px", borderBottom: "1px solid var(--bd)" }}>
            {["Invoice", "Date", "Description", "Amount", ""].map((h, i) => <Mono key={i} size={8.5}>{h}</Mono>)}
          </div>
          {INVOICES.map((inv) => (
            <div key={inv.id} style={{ display: "grid", gridTemplateColumns: "1.3fr 1fr 1fr 0.7fr 28px", gap: 10, alignItems: "center", padding: "10px 0", borderBottom: "1px solid var(--bd)" }}>
              <span style={{ fontFamily: "var(--mono)", fontSize: 11 }}>{inv.id}</span>
              <span style={{ fontSize: 11.5, color: "var(--mut)" }}>{inv.date}</span>
              <span style={{ fontSize: 11.5, color: "var(--mut)" }}>{inv.desc}</span>
              <span style={{ fontFamily: "var(--mono)", fontSize: 11.5, display: "inline-flex", alignItems: "center", gap: 7 }}>{inv.amount}<span style={{ fontFamily: "var(--ui)", fontSize: 8.5, color: "var(--ok)", border: "1px solid color-mix(in srgb, var(--ok) 40%, transparent)", borderRadius: 99, padding: "1px 6px" }}>{inv.status}</span></span>
              <span title="Download" style={{ color: "var(--mut)", cursor: "pointer", display: "inline-flex", justifyContent: "center" }}>{SI.download({ size: 14 })}</span>
            </div>
          ))}
        </div>
      </SettSection>

      {stripeOpen && <StripeModal onClose={() => setStripeOpen(false)} onSaved={(c) => { setCard(c); setStripeOpen(false); }} />}
    </div>
  );
}

Object.assign(window, { BillingPage, StripeModal });
