// Solus — auth screens: Landing, Signup, Login (light fidelity doorway)
const { useState: useStateA } = React;

function AuthChrome({ children, wide }) {
  return (
    <div style={{ minHeight: "100vh", background: "var(--bg)", color: "var(--tx)", fontFamily: "var(--ui)", display: "flex", flexDirection: "column" }}>
      <div style={{ fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.14em", color: "var(--mut)", borderBottom: "1px solid var(--bd)", padding: "7px 28px", display: "flex", justifyContent: "space-between" }}>
        <span>SOLUS // CROSS-DOMAIN INTEGRITY FOR ROBOTICS TEAMS</span>
        <span>v0.9</span>
      </div>
      {children}
    </div>
  );
}

function SolusWordmark({ go, size = 16 }) {
  return (
    <div onClick={() => go && go("landing")} style={{ display: "flex", alignItems: "center", gap: 10, cursor: go ? "pointer" : "default" }}>
      <div style={{ width: size + 2, height: size + 2, borderRadius: "50%", background: "radial-gradient(circle at 35% 32%, var(--acc), transparent 72%)", boxShadow: "0 0 14px color-mix(in srgb, var(--acc) 40%, transparent)" }}></div>
      <span style={{ fontWeight: 700, fontSize: size, letterSpacing: "0.12em" }}>SOLUS</span>
    </div>
  );
}

function LandingPage({ go }) {
  const chain = [
    { l: "motor_driver.c", d: "sw" }, { l: "M3_PWM", d: "ee" },
    { l: "DRV8316C · U4", d: "ee" }, { l: "knee gearbox 9:1", d: "me" }, { l: "τ3 torque", d: "rt" },
  ];
  return (
    <AuthChrome>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "20px 48px" }}>
        <SolusWordmark />
        <div style={{ display: "flex", gap: 28, fontSize: 13.5, color: "var(--mut)" }}>
          <span style={{ cursor: "pointer" }}>Product</span><span style={{ cursor: "pointer" }}>Docs</span><span style={{ cursor: "pointer" }}>Pricing</span>
        </div>
        <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
          <span onClick={() => go("login")} style={{ fontSize: 13.5, color: "var(--mut)", cursor: "pointer" }}>Sign in</span>
          <Btn kind="primary" size="sm" onClick={() => go("signup")}>Get started</Btn>
        </div>
      </div>
      <div style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "center", padding: "48px 96px 24px" }}>
        <Mono color="var(--acc)" size={11} style={{ letterSpacing: "0.16em", marginBottom: 18 }}>CODE · PCB · CAD · HARDWARE — ONE GRAPH</Mono>
        <h1 style={{ margin: 0, fontWeight: 600, fontSize: "clamp(40px, 5vw, 64px)", lineHeight: 1.04, letterSpacing: "-0.025em", maxWidth: 880 }}>
          Your robot is one system.<br /><span style={{ color: "var(--acc)" }}>Your tools aren't.</span>
        </h1>
        <p style={{ fontSize: 17, lineHeight: 1.6, color: "var(--mut)", maxWidth: 560, marginTop: 22 }}>
          Solus connects firmware, schematics, CAD, and live telemetry into one
          context model — and catches the integration bugs that only exist
          between them, before they break the robot.
        </p>
        <div style={{ display: "flex", gap: 12, marginTop: 32 }}>
          <Btn kind="primary" size="lg" onClick={() => go("signup")}>Create account</Btn>
          <Btn kind="ghost" size="lg" onClick={() => go("signup")}>See it catch a bug {SI.arrowR({ size: 14 })}</Btn>
        </div>
        <div style={{ display: "flex", alignItems: "center", marginTop: 60, flexWrap: "wrap", rowGap: 10 }}>
          {chain.map((c, i) => (
            <React.Fragment key={c.l}>
              {i > 0 && <div style={{ width: 34, height: 1, background: "var(--bd)" }}></div>}
              <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--tx)", background: "var(--sur)", border: `1px solid color-mix(in srgb, ${dcol(c.d)} 38%, transparent)`, borderRadius: 3, padding: "6px 11px", display: "inline-flex", alignItems: "center", gap: 7, whiteSpace: "nowrap" }}>
                <span style={{ width: 6, height: 6, borderRadius: 99, background: dcol(c.d), display: "inline-block" }}></span>
                {c.l}
              </span>
            </React.Fragment>
          ))}
        </div>
        <Mono size={10.5} style={{ marginTop: 14, letterSpacing: "0.06em", textTransform: "none" }}>one broken assumption, traced across four domains — in 90 ms</Mono>
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", padding: "18px 48px", borderTop: "1px solid var(--bd)" }}>
        <Mono size={10}>WORKS WITH GITHUB · KICAD · ONSHAPE · ROS 2</Mono>
        <Mono size={10}>SOC 2 · SELF-HOST AVAILABLE</Mono>
      </div>
    </AuthChrome>
  );
}

function AuthField({ label, type, value, onChange, placeholder, err }) {
  return (
    <label style={{ display: "block", marginBottom: 14 }}>
      <Mono size={9.5} style={{ display: "block", marginBottom: 6 }}>{label}</Mono>
      <input type={type} value={value} placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        style={{
          width: "100%", boxSizing: "border-box", background: "var(--bg)", color: "var(--tx)",
          border: `1px solid ${err ? "var(--err)" : "var(--bd)"}`, borderRadius: 3,
          padding: "10px 12px", fontSize: 13.5, fontFamily: "var(--ui)", outline: "none",
        }} />
      {err && <span style={{ fontSize: 11, color: "var(--err)", marginTop: 4, display: "block" }}>{err}</span>}
    </label>
  );
}

function AuthCard({ title, sub, children, footer }) {
  return (
    <AuthChrome>
      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}>
        <div style={{ width: 380 }}>
          <div style={{ display: "flex", justifyContent: "center", marginBottom: 28 }}><SolusWordmark /></div>
          <Card pad={28}>
            <div style={{ fontSize: 18, fontWeight: 600, letterSpacing: "-0.01em" }}>{title}</div>
            <div style={{ fontSize: 12.5, color: "var(--mut)", marginTop: 4, marginBottom: 22, lineHeight: 1.5 }}>{sub}</div>
            {children}
          </Card>
          <div style={{ textAlign: "center", marginTop: 16, fontSize: 12.5, color: "var(--mut)" }}>{footer}</div>
        </div>
      </div>
    </AuthChrome>
  );
}

function GithubBtn({ label, onDone }) {
  const [st, setSt] = useStateA("idle");
  const click = () => {
    if (st !== "idle") return;
    setSt("auth");
    setTimeout(() => setSt("ok"), 1400);
    setTimeout(onDone, 2100);
  };
  return (
    <Btn kind="soft" onClick={click} style={{ width: "100%", padding: "10px 0", fontSize: 13 }}>
      {st === "idle" && <>{SI.github({ size: 15 })} {label}</>}
      {st === "auth" && <><Spinner /> Authorizing with GitHub…</>}
      {st === "ok" && <><span style={{ color: "var(--ok)" }}>{SI.check({ size: 14 })}</span> Authorized as maya-builds</>}
    </Btn>
  );
}

function SignupPage({ go, onAuth }) {
  const [email, setEmail] = useStateA("");
  const [pw, setPw] = useStateA("");
  const [errs, setErrs] = useStateA({});
  const [busy, setBusy] = useStateA(false);
  const submit = () => {
    const e = {};
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) e.email = "Enter a valid email address";
    if (pw.length < 8) e.pw = "At least 8 characters";
    setErrs(e);
    if (Object.keys(e).length) return;
    setBusy(true);
    setTimeout(() => onAuth(email), 1300);
  };
  return (
    <AuthCard title="Create your workspace" sub="Free for solo builders. No credit card."
      footer={<span>Already have an account? <span onClick={() => go("login")} style={{ color: "var(--acc)", cursor: "pointer" }}>Sign in</span></span>}>
      <GithubBtn label="Continue with GitHub" onDone={() => onAuth("maya@strider.dev")} />
      <div style={{ display: "flex", alignItems: "center", gap: 10, margin: "18px 0" }}>
        <div style={{ flex: 1, height: 1, background: "var(--bd)" }}></div>
        <Mono size={9}>OR</Mono>
        <div style={{ flex: 1, height: 1, background: "var(--bd)" }}></div>
      </div>
      <AuthField label="WORK EMAIL" type="email" value={email} onChange={setEmail} placeholder="you@team.dev" err={errs.email} />
      <AuthField label="PASSWORD" type="password" value={pw} onChange={setPw} placeholder="8+ characters" err={errs.pw} />
      <Btn kind="primary" onClick={submit} style={{ width: "100%", padding: "11px 0", marginTop: 6 }}>
        {busy ? <><Spinner color="var(--acc-ink)" /> Creating workspace…</> : "Create account"}
      </Btn>
    </AuthCard>
  );
}

function LoginPage({ go, onAuth }) {
  const [email, setEmail] = useStateA("maya@strider.dev");
  const [pw, setPw] = useStateA("");
  const [err, setErr] = useStateA(null);
  const [busy, setBusy] = useStateA(false);
  const submit = () => {
    if (!pw) { setErr("Enter your password"); return; }
    setErr(null);
    setBusy(true);
    setTimeout(() => onAuth(email, true), 1100);
  };
  return (
    <AuthCard title="Welcome back" sub="Sign in to strider-qd12"
      footer={<span>New to Solus? <span onClick={() => go("signup")} style={{ color: "var(--acc)", cursor: "pointer" }}>Create account</span></span>}>
      <GithubBtn label="Sign in with GitHub" onDone={() => onAuth("maya@strider.dev", true)} />
      <div style={{ display: "flex", alignItems: "center", gap: 10, margin: "18px 0" }}>
        <div style={{ flex: 1, height: 1, background: "var(--bd)" }}></div>
        <Mono size={9}>OR</Mono>
        <div style={{ flex: 1, height: 1, background: "var(--bd)" }}></div>
      </div>
      <AuthField label="EMAIL" type="email" value={email} onChange={setEmail} />
      <AuthField label="PASSWORD" type="password" value={pw} onChange={setPw} placeholder="••••••••" err={err} />
      <Btn kind="primary" onClick={submit} style={{ width: "100%", padding: "11px 0", marginTop: 6 }}>
        {busy ? <><Spinner color="var(--acc-ink)" /> Signing in…</> : "Sign in"}
      </Btn>
    </AuthCard>
  );
}

Object.assign(window, { LandingPage, SignupPage, LoginPage, AuthChrome, SolusWordmark });
