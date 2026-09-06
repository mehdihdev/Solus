// Solus v2 — Connections: cloud / local apps / devices, honest identity, first-run derivation
const { useState: useStateCn, useEffect: useEffectCn } = React;

function ConnStateChip({ state, running }) {
  const map = {
    connected: ["var(--ok)", "● CONNECTED"], live: ["var(--ok)", "● LIVE"], loaded: ["var(--ok)", "● LOADED"],
    idle: ["var(--warn)", "○ IDLE"], stopped: ["var(--mut)", "○ STOPPED"],
    installed: [running ? "var(--ok)" : "var(--mut)", running ? "● RUNNING" : "○ INSTALLED, NOT RUNNING"],
    connectable: ["var(--mut)", "NOT CONNECTED"],
  };
  const [c, l] = map[state] || map.connectable;
  return <Mono size={8.5} color={c}>{l}</Mono>;
}

function ConnCard({ item, kind, onConnect, onToggle, onProbe, onSwap, busy }) {
  const isConn = ["connected", "live", "installed", "idle", "loaded", "stopped"].includes(item.state);
  return (
    <Card pad={0} style={{ borderColor: item.state === "live" ? "color-mix(in srgb, var(--ok) 30%, var(--bd))" : "var(--bd)" }}>
      <div style={{ display: "flex", gap: 12, alignItems: "center", padding: "13px 15px" }}>
        <span style={{ width: 38, height: 38, borderRadius: 4, background: "var(--sur2)", border: `1px solid ${item.honest ? "color-mix(in srgb, var(--warn) 45%, var(--bd))" : "var(--bd)"}`, display: "inline-flex", alignItems: "center", justifyContent: "center", fontFamily: "var(--mono)", fontSize: 12, fontWeight: 600, flexShrink: 0, color: item.honest ? "var(--warn)" : "var(--tx)" }}>{item.mark}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <span style={{ fontSize: 13, fontWeight: 600 }}>{item.name}</span>
            {item.role && <span style={{ fontFamily: "var(--mono)", fontSize: 8, letterSpacing: "0.08em", color: "var(--acc)", border: "1px solid color-mix(in srgb, var(--acc) 40%, transparent)", borderRadius: 3, padding: "1px 6px" }}>{item.role}</span>}
          </div>
          <div style={{ fontSize: 11, color: "var(--mut)", marginTop: 2, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{item.detail}</div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexShrink: 0 }}>
          <ConnStateChip state={item.state} running={item.running} />
          {item.state === "connectable" && <Btn kind="primary" size="sm" onClick={() => onConnect(item)} disabled={busy === item.id}>{busy === item.id ? <><Spinner size={10} color="var(--acc-ink)" /> …</> : "Connect"}</Btn>}
          {item.canStop && item.state === "live" && <Btn kind="ghost" size="sm" onClick={() => onToggle(item, false)}>Stop</Btn>}
          {(item.canStart || (item.canStop && item.state === "stopped")) && item.state === "stopped" && <Btn kind="ghost" size="sm" onClick={() => onToggle(item, true)}>Start</Btn>}
        </div>
      </div>
      {(item.identity || item.honestIdle) && (
        <div style={{ borderTop: "1px solid var(--bd)", padding: "9px 15px", background: item.honest ? "color-mix(in srgb, var(--warn) 4%, var(--bg))" : "var(--bg)", display: "flex", gap: 9, alignItems: "flex-start" }}>
          <span style={{ color: item.honest ? "var(--warn)" : "var(--mut)", marginTop: 1, flexShrink: 0 }}>{item.honest ? SI.warn({ size: 12 }) : SI.check({ size: 12 })}</span>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 11, color: "var(--tx)", lineHeight: 1.55 }}>{item.identity || item.honestIdle}</div>
            {item.honest && (
              <div style={{ display: "flex", gap: 6, marginTop: 7 }}>
                <Btn kind="ghost" size="sm" onClick={() => onProbe(item)}>Probe it (needs approval)</Btn>
                <Btn kind="bare" size="sm">Tell SOL what it is</Btn>
              </div>
            )}
            {item.swap && <div style={{ marginTop: 6 }}><Btn kind="bare" size="sm" onClick={() => onSwap(item)}>Swap leader / follower labels</Btn></div>}
          </div>
        </div>
      )}
    </Card>
  );
}

function ConnSection({ title, sub, children }) {
  return (
    <div style={{ marginBottom: 24 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 4 }}>
        <Mono size={9.5} color="var(--tx)">{title}</Mono>
        <span style={{ fontSize: 11, color: "var(--mut)" }}>{sub}</span>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 10 }}>{children}</div>
    </div>
  );
}

function ConnectionsScreen({ world, firstRun, onDone, onToast, onProbe }) {
  const [items, setItems] = useStateCn(() => JSON.parse(JSON.stringify(world.connections)));
  const [busy, setBusy] = useStateCn(null);
  const [deriving, setDeriving] = useStateCn(false);
  const [dLines, setDLines] = useStateCn(0);

  useEffectCn(() => { setItems(JSON.parse(JSON.stringify(world.connections))); }, [world.id]);

  const connect = (item) => {
    setBusy(item.id);
    setTimeout(() => {
      setBusy(null);
      setItems((s) => {
        const n = { ...s, cloud: s.cloud.map((c) => c.id === item.id ? { ...c, state: "connected", detail: c.detail + " · just connected" } : c) };
        return n;
      });
      onToast("Connected " + item.name, "Its contents are being indexed into the graph.");
    }, 1600);
  };
  const toggle = (item, on) => {
    setItems((s) => ({ ...s, devices: s.devices.map((d) => d.id === item.id ? { ...d, state: on ? "live" : "stopped" } : d) }));
    onToast(on ? "Started " + item.name : "Stopped " + item.name, on ? "Streaming — the bench picks it up automatically." : "Its widgets grey out rather than showing stale data.");
  };
  const startDerive = () => {
    setDeriving(true); setDLines(0);
    world.derive.forEach((_, i) => setTimeout(() => setDLines(i + 1), 550 + i * 620));
  };

  const anyOn = items.devices.some((d) => d.state === "live" || d.state === "loaded") || items.cloud.some((c) => c.state === "connected");

  return (
    <div style={{ flex: 1, overflowY: "auto", minWidth: 0 }} data-screen-label="Connections">
      <div style={{ maxWidth: 760, margin: "0 auto", padding: "24px 28px 48px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 21, fontWeight: 600, letterSpacing: "-0.015em" }}>{firstRun ? "Connect what you have" : "Connections"}</h1>
            <p style={{ fontSize: 12.5, color: "var(--mut)", margin: "6px 0 0", lineHeight: 1.6, maxWidth: 520 }}>
              {firstRun ? "Solus derives your workspace from what's here — nothing to configure. Connect at least one thing and continue." : "Everything connected and connectable. Widgets appear and disappear with what's on this list."}
            </p>
          </div>
        </div>

        <div style={{ marginTop: 24 }}>
          <ConnSection title="CLOUD ACCOUNTS" sub="OAuth once · synced remotely">
            {items.cloud.map((c) => <ConnCard key={c.id} item={c} kind="cloud" onConnect={connect} busy={busy} />)}
          </ConnSection>
          <ConnSection title="LOCAL APPLICATIONS" sub="found on this machine · running or not">
            {items.local.length === 0
              ? <Card pad={14}><div style={{ fontSize: 11.5, color: "var(--mut)", lineHeight: 1.6 }}>{world.connections.localNote}</div></Card>
              : items.local.map((c) => <ConnCard key={c.id} item={c} kind="local" />)}
          </ConnSection>
          <ConnSection title="DEVICES & STREAMS" sub="live status · start and stop">
            {items.devices.map((c) => <ConnCard key={c.id} item={c} kind="device" onToggle={toggle} onProbe={onProbe} onSwap={() => onToast("Labels swapped", "Leader is now /dev/ttyACM0. The bench renames its widgets to match.")} />)}
          </ConnSection>
        </div>

        {firstRun && !deriving && (
          <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 8 }}>
            <Btn kind="primary" size="lg" disabled={!anyOn} onClick={startDerive}>Derive my workspace {SI.arrowR({ size: 14 })}</Btn>
          </div>
        )}
        {deriving && (
          <Card pad={0} style={{ marginTop: 8 }}>
            <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--bd)" }}><Mono size={9.5} color="var(--acc)">DERIVING — BECAUSE X, THEREFORE Y</Mono></div>
            {world.derive.slice(0, dLines).map(([x, y], i) => (
              <div key={i} className="ob-logline" style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 16px", borderBottom: "1px solid var(--bd)", fontSize: 12 }}>
                <span style={{ color: "var(--mut)" }}>{x}</span>
                <span style={{ color: "var(--acc)", flexShrink: 0 }}>{SI.arrowR({ size: 12 })}</span>
                <span style={{ fontWeight: 600 }}>{y}</span>
              </div>
            ))}
            {dLines < world.derive.length
              ? <div style={{ display: "flex", gap: 9, alignItems: "center", padding: "10px 16px", fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--acc)" }}><Spinner size={10} /> looking at what's connected…</div>
              : <div style={{ display: "flex", justifyContent: "flex-end", padding: "12px 16px" }}><Btn kind="primary" onClick={onDone}>Open my workspace {SI.arrowR({ size: 13 })}</Btn></div>}
          </Card>
        )}
      </div>
    </div>
  );
}

Object.assign(window, { ConnectionsScreen });
