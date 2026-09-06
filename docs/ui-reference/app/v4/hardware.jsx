// Solus v4 — Hardware onboarding: five paths as cards, each a click-through with propose/confirm
const { useState: useH4 } = React;

function StateChip({ state, small }) {
  const c = state === "live" ? "var(--ok)" : state === "installed" ? "var(--rt)" : state === "received" ? "var(--tx)" : state === "ordered" ? "var(--warn)" : "var(--mut)";
  return <span style={{ fontFamily: "var(--mono)", fontSize: small ? 7.5 : 8.5, letterSpacing: "0.08em", color: c, border: `1px solid color-mix(in srgb, ${c} 45%, transparent)`, borderRadius: 99, padding: small ? "1px 6px" : "2px 8px", textTransform: "uppercase", whiteSpace: "nowrap", background: state === "planned" ? "transparent" : `color-mix(in srgb, ${c} 6%, transparent)` }}>{state}</span>;
}
function Conf({ v }) { return v == null ? <Mono size={8.5} color="var(--warn)">UNKNOWN — NOT GUESSING</Mono> : <span style={{ fontFamily: "var(--mono)", fontSize: 9.5, color: v >= 0.85 ? "var(--ok)" : "var(--warn)" }}>{Math.round(v * 100)}%</span>; }
function RobotPick({ robots, value, onChange, allowNew }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} style={{ background: "var(--bg)", color: "var(--tx)", border: "1px solid var(--bd)", borderRadius: 3, padding: "6px 9px", fontSize: 12, fontFamily: "var(--ui)", outline: "none" }}>
      {allowNew && <option value="__new">＋ new Physical Robot</option>}
      {robots.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
    </select>);
}

/* ---- Detected ---- */
function PathDetected({ d, act, done }) {
  const [dev, setDev] = useH4(null);
  const [target, setTarget] = useH4("__new");
  const [rows, setRows] = useH4({});
  const [name, setName] = useH4("");
  const added = new Set(d.robots.map((r) => r.device));
  if (!dev) return (
    <div>
      <Mono size={9}>PLUGGED IN RIGHT NOW · IDENTITY IS HONEST</Mono>
      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 10 }}>
        {V4.DETECTED.map((x) => (
          <Card key={x.id} pad={0} onClick={() => !added.has(x.id) && setDev(x)} style={{ cursor: added.has(x.id) ? "default" : "pointer", opacity: added.has(x.id) ? 0.55 : 1 }}>
            <div style={{ display: "flex", gap: 12, alignItems: "center", padding: "11px 14px" }}>
              <span style={{ width: 34, height: 34, borderRadius: 4, background: "var(--sur2)", border: `1px solid ${x.honest ? "color-mix(in srgb, var(--warn) 45%, var(--bd))" : "var(--bd)"}`, display: "inline-flex", alignItems: "center", justifyContent: "center", color: x.honest ? "var(--warn)" : "var(--tx)" }}>{SI.chip2({ size: 15 })}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 12.5, fontWeight: 600 }}>{x.name} <Mono size={8} style={{ marginLeft: 6 }}>SN {x.serial}</Mono></div>
                <div style={{ fontSize: 11, color: x.honest ? "var(--warn)" : "var(--mut)", marginTop: 2, lineHeight: 1.5 }}>{x.identity}</div>
              </div>
              {added.has(x.id) ? <Mono size={8.5} color="var(--ok)">● IN PROJECT</Mono> : <Btn kind="ghost" size="sm">Add</Btn>}
            </div>
          </Card>))}
      </div>
    </div>);
  const acc = (i, v) => setRows((r) => ({ ...r, [i]: v }));
  const finish = () => {
    const rid = target === "__new" ? act.addRobot(name || d.project.name, dev) : target;
    const parts = dev.mapping.map((m, i) => rows[i] === false ? null : ({ name: m[1] && rows[i] !== "raw" ? m[1] : `Motor-${i + 1}`, cat: /grip/.test(m[1] || "") ? "end effectors" : "actuators", state: "live", src: "detected", ev: m[3], conf: m[2], ch: m[0], honest: !m[1] })).filter(Boolean);
    act.addParts(rid, parts, dev.mapping.every((m, i) => m[1] && rows[i] !== false));
    if (dev.mapping.length === 0) act.addParts(rid, [{ name: dev.name, cat: dev.id === "cam0" ? "sensors" : "controllers", state: "live", src: "detected", honest: dev.honest }], false);
    done(`Hardware config written — ${dev.name} → ${target === "__new" ? name || d.project.name : d.robots.find((r) => r.id === target).name}`);
  };
  return (
    <div>
      <span onClick={() => setDev(null)} style={{ fontSize: 12, color: "var(--mut)", cursor: "pointer", display: "inline-flex", gap: 6, alignItems: "center" }}>{SI.arrowL({ size: 12 })} devices</span>
      <div style={{ fontSize: 14, fontWeight: 600, marginTop: 10 }}>{dev.name} <Mono size={8.5} style={{ marginLeft: 6 }}>SN {dev.serial}</Mono></div>
      <div style={{ fontSize: 11.5, color: dev.honest ? "var(--warn)" : "var(--mut)", marginTop: 3, lineHeight: 1.5 }}>{dev.identity}</div>
      <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 14, flexWrap: "wrap" }}>
        <Mono size={9}>ADD TO</Mono>
        <RobotPick robots={d.robots} value={target} onChange={setTarget} allowNew />
        {target === "__new" && <input value={name} onChange={(e) => setName(e.target.value)} placeholder={d.project.name + " (default)"} style={{ background: "var(--bg)", color: "var(--tx)", border: "1px solid var(--bd)", borderRadius: 3, padding: "6px 9px", fontSize: 12, fontFamily: "var(--ui)", outline: "none", width: 200 }} />}
      </div>
      {dev.mapping.length > 0 ? (
        <Card pad={0} style={{ marginTop: 14 }}>
          <div style={{ display: "grid", gridTemplateColumns: "70px 1fr 70px 1fr 120px", gap: 10, padding: "8px 14px", borderBottom: "1px solid var(--bd)" }}>{["CHANNEL", "PROPOSED FUNCTION", "CONF", "EVIDENCE", ""].map((h, i) => <Mono key={i} size={8}>{h}</Mono>)}</div>
          {dev.mapping.map((m, i) => (
            <div key={i} style={{ display: "grid", gridTemplateColumns: "70px 1fr 70px 1fr 120px", gap: 10, alignItems: "center", padding: "8px 14px", borderBottom: "1px solid var(--bd)", opacity: rows[i] === false ? 0.45 : 1 }}>
              <span style={{ fontFamily: "var(--mono)", fontSize: 11 }}>{m[0]}</span>
              <span style={{ fontFamily: "var(--mono)", fontSize: 11.5, color: m[1] ? "var(--tx)" : "var(--warn)" }}>{m[1] || `Motor-${i + 1} (default name)`}</span>
              <Conf v={m[2]} />
              <span style={{ fontSize: 10.5, color: "var(--mut)" }}>{m[3]}</span>
              <div style={{ display: "flex", gap: 5, justifyContent: "flex-end" }}>
                {rows[i] === true ? <Mono size={8.5} color="var(--ok)">✓ ACCEPTED</Mono> : rows[i] === false ? <Mono size={8.5}>REJECTED</Mono> : <><Btn kind="primary" size="sm" onClick={() => acc(i, true)}>Accept</Btn><Btn kind="bare" size="sm" onClick={() => acc(i, false)}>✕</Btn></>}
              </div>
            </div>))}
          <div style={{ display: "flex", gap: 8, padding: "10px 14px", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ fontSize: 10.5, color: "var(--mut)" }}>Proposals, not facts — nothing is written until you confirm.</span>
            <div style={{ display: "flex", gap: 8 }}>
              <Btn kind="ghost" size="sm" onClick={() => { const r = {}; dev.mapping.forEach((_, i) => (r[i] = true)); setRows(r); }}>Accept all</Btn>
              <Btn kind="primary" size="sm" disabled={!dev.mapping.every((_, i) => rows[i] !== undefined)} onClick={finish}>Done — write config</Btn>
            </div>
          </div>
        </Card>
      ) : (
        <Card pad={14} style={{ marginTop: 14 }}>
          <div style={{ fontSize: 12, color: "var(--mut)", lineHeight: 1.6 }}>No channels to map — this device reports nothing enumerable. It'll be added as a {dev.id === "cam0" ? "sensor" : "controller"} with its honest identity.</div>
          <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 10 }}><Btn kind="primary" size="sm" onClick={finish}>Add it</Btn></div>
        </Card>)}
    </div>);
}

/* ---- From a file ---- */
function PathFromFile({ d, act, done }) {
  const [selm, setSel] = useH4({});
  const [target, setTarget] = useH4(d.robots[0] ? d.robots[0].id : "__new");
  const have = new Set(d.project.parts.map((p) => p.name.toLowerCase()));
  const cands = [];
  d.docs.forEach((doc) => (doc.tree || []).forEach((a) => (a.kids || []).forEach((k) => { if (!/\.cu$|\.py|\.c$|\.h$|\.md|\.json|\.xml|sheet|physics|model|body|joint/i.test(k.l) && !have.has(k.l.toLowerCase())) cands.push({ ...k, doc, asm: a.l }); })));
  if (cands.length === 0) return <Card pad={16}><div style={{ fontSize: 12, color: "var(--mut)", lineHeight: 1.6 }}>{d.docs.length ? "Every part found in connected CAD, schematics and BOMs is already assigned. Add another document in From a service and new parts appear here." : "No CAD, schematic or BOM documents in this project yet — nothing to parse. Add one from a service first."}</div></Card>;
  const n = Object.values(selm).filter(Boolean).length;
  return (
    <div>
      <Mono size={9}>PARSED FROM WHAT'S ALREADY HERE · NOT YET ASSIGNED TO A ROBOT</Mono>
      <Card pad={0} style={{ marginTop: 10 }}>
        {cands.map((c, i) => (
          <div key={i} onClick={() => setSel((s) => ({ ...s, [i]: !s[i] }))} style={{ display: "flex", gap: 12, alignItems: "center", padding: "9px 14px", borderBottom: "1px solid var(--bd)", cursor: "pointer", background: selm[i] ? "color-mix(in srgb, var(--acc) 5%, transparent)" : "transparent" }}>
            <span style={{ width: 14, height: 14, borderRadius: 3, border: `1px solid ${selm[i] ? "var(--acc)" : "var(--bd)"}`, background: selm[i] ? "var(--acc)" : "transparent", display: "inline-flex", alignItems: "center", justifyContent: "center", color: "var(--acc-ink)" }}>{selm[i] && SI.check({ size: 10 })}</span>
            <span style={{ width: 7, height: 7, borderRadius: 99, background: dcol(c.d) }}></span>
            <span style={{ fontFamily: "var(--mono)", fontSize: 11.5, flex: 1 }}>{c.l}</span>
            <Mono size={8.5}>{V4.guessCat(c.l)}</Mono>
            <span style={{ fontSize: 10.5, color: "var(--mut)" }}>{c.doc.serviceName} · {c.doc.name} › {c.asm}</span>
          </div>))}
      </Card>
      <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 12, justifyContent: "flex-end" }}>
        <Mono size={9}>ADD {n} TO</Mono><RobotPick robots={d.robots} value={target} onChange={setTarget} allowNew />
        <Btn kind="primary" size="sm" disabled={!n} onClick={() => { const rid = target === "__new" ? act.addRobot(d.project.name) : target; act.addParts(rid, cands.filter((_, i) => selm[i]).map((c) => ({ name: c.l, cat: V4.guessCat(c.l), state: "installed", src: "file", doc: c.doc.id }))); done(`${n} part${n > 1 ? "s" : ""} added from ${[...new Set(cands.filter((_, i) => selm[i]).map((c) => c.doc.serviceName))].join(", ")}`); }}>Add to robot</Btn>
      </div>
    </div>);
}

/* ---- Library ---- */
function PathLibrary({ d, act, done }) {
  const [q, setQ] = useH4(""); const [pick, setPick] = useH4(null);
  const list = V4.LIBRARY.filter((l) => (l.name + l.by + l.sub).toLowerCase().includes(q.toLowerCase()));
  if (pick) return (
    <div>
      <span onClick={() => setPick(null)} style={{ fontSize: 12, color: "var(--mut)", cursor: "pointer", display: "inline-flex", gap: 6, alignItems: "center" }}>{SI.arrowL({ size: 12 })} library</span>
      <div style={{ fontSize: 16, fontWeight: 600, marginTop: 10 }}>{pick.name} <span style={{ fontSize: 11.5, color: "var(--mut)", fontWeight: 400 }}>by {pick.by}</span></div>
      <div style={{ marginTop: 10 }}>{[["Actuators", pick.actuators], ["Kinematics", pick.kinematics], ["Protocol", pick.protocol]].map(([k, v]) => <KV key={k} k={k} v={v} />)}</div>
      <Mono size={9} style={{ display: "block", marginTop: 14 }}>IMPORTS {pick.parts.length} PARTS AS PLANNED — THEY GO LIVE WHEN HARDWARE ANSWERS</Mono>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8 }}>{pick.parts.map(([n, c]) => <span key={n} style={{ fontFamily: "var(--mono)", fontSize: 10.5, border: "1px solid var(--bd)", borderRadius: 99, padding: "3px 9px" }}><span style={{ display: "inline-block", width: 6, height: 6, borderRadius: 99, background: dcol(V4.CAT_D[c]), marginRight: 6 }}></span>{n}</span>)}</div>
      <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 16 }}><Btn kind="primary" onClick={() => { const rid = act.addRobot(pick.name.toLowerCase().replace(/\s+/g, "-"), null, pick.id); act.addParts(rid, pick.parts.map(([n, c]) => ({ name: n, cat: c, state: "planned", src: "library" })), true); done(`${pick.name} imported — Physical Robot created, config written`); }}>Import</Btn></div>
    </div>);
  return (
    <div>
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search known platforms — SO-101, G1, UR5, PX4…" style={{ width: "100%", boxSizing: "border-box", background: "var(--bg)", color: "var(--tx)", border: "1px solid var(--bd)", borderRadius: 3, padding: "9px 12px", fontSize: 12.5, fontFamily: "var(--ui)", outline: "none" }} />
      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 10 }}>
        {list.map((l) => <Card key={l.id} pad={0} onClick={() => setPick(l)} style={{ cursor: "pointer" }}><div style={{ display: "flex", gap: 12, alignItems: "center", padding: "11px 14px" }}><span style={{ width: 34, height: 34, borderRadius: 4, background: "var(--sur2)", border: "1px solid var(--bd)", display: "inline-flex", alignItems: "center", justifyContent: "center" }}>{SI.box({ size: 15 })}</span><div style={{ flex: 1 }}><div style={{ fontSize: 12.5, fontWeight: 600 }}>{l.name} <span style={{ fontSize: 10.5, color: "var(--mut)", fontWeight: 400 }}>· {l.by}</span></div><div style={{ fontSize: 11, color: "var(--mut)", marginTop: 2 }}>{l.sub} · {l.actuators}</div></div>{SI.arrowR({ size: 12 })}</div></Card>)}
        {list.length === 0 && <Card pad={14}><div style={{ fontSize: 12, color: "var(--mut)" }}>Not in the library. Define it under Authored, or ask SOL — it will say if it doesn't know the platform.</div></Card>}
      </div>
    </div>);
}

/* ---- Sourced ---- */
function PathSourced({ d, act, done, openSol }) {
  const [req, setReq] = useH4(""); const [derived, setDerived] = useH4(null); const [busy, setBusy] = useH4(false); const [cands, setCands] = useH4(null); const [target, setTarget] = useH4(d.robots[0] ? d.robots[0].id : "__new");
  const go = (text) => { setBusy(true); setTimeout(() => { setBusy(false); setCands(V4.SOURCED); }, 1500); };
  const deriveCad = () => { if (!d.docs.some((x) => x.domain === "me")) { setDerived({ err: "No CAD connected — I can't compute torque from geometry I don't have. Type the requirement instead." }); return; } setDerived({ text: "From CAD: 0.42 kg arm at 0.30 m + 2.0 kg payload → 7.1 N·m at the shoulder (×1.5 margin → 10.6 N·m)." }); setReq("≥ 7.1 N·m at shoulder, ≤ 200 g, serial or CAN"); };
  return (
    <div>
      <Mono size={9}>I NEED A PART</Mono>
      <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
        <input value={req} onChange={(e) => setReq(e.target.value)} placeholder="e.g. holds 2 kg at 30 cm" style={{ flex: 1, background: "var(--bg)", color: "var(--tx)", border: "1px solid var(--bd)", borderRadius: 3, padding: "9px 12px", fontSize: 12.5, fontFamily: "var(--ui)", outline: "none" }} />
        <Btn kind="ghost" size="sm" onClick={deriveCad}>Derive from CAD</Btn>
        <Btn kind="primary" size="sm" disabled={!req || busy} onClick={() => go(req)}>{busy ? <><Spinner size={10} color="var(--acc-ink)" /> asking SOL…</> : "Find candidates"}</Btn>
      </div>
      {derived && <div style={{ marginTop: 8, fontSize: 11.5, lineHeight: 1.55, color: derived.err ? "var(--warn)" : "var(--tx)", background: "var(--bg)", border: "1px solid var(--bd)", borderRadius: 3, padding: "8px 11px" }}>{derived.err || derived.text}</div>}
      {cands && (
        <Card pad={0} style={{ marginTop: 14 }}>
          <div style={{ padding: "9px 14px", borderBottom: "1px solid var(--bd)", display: "flex", justifyContent: "space-between" }}><Mono size={9}>CANDIDATES · SIDE BY SIDE</Mono><Mono size={8.5} color={d.rules ? "var(--ok)" : "var(--mut)"}>{d.rules ? `FILTERED BY ${d.rules} COMPLIANCE RULES` : "NO COMPLIANCE RULES IN THIS PROJECT — UNFILTERED"}</Mono></div>
          <div style={{ display: "grid", gridTemplateColumns: "1.4fr 0.8fr 0.6fr 0.7fr 0.7fr 1.2fr 80px", gap: 8, padding: "7px 14px", borderBottom: "1px solid var(--bd)" }}>{["PART", "TORQUE", "COST", "WEIGHT", "PROTOCOL", "TRADE-OFF", ""].map((h, i) => <Mono key={i} size={8}>{h}</Mono>)}</div>
          {cands.map((c) => (
            <div key={c.name} style={{ display: "grid", gridTemplateColumns: "1.4fr 0.8fr 0.6fr 0.7fr 0.7fr 1.2fr 80px", gap: 8, alignItems: "center", padding: "9px 14px", borderBottom: "1px solid var(--bd)", opacity: c.weak ? 0.5 : 1 }}>
              <span style={{ fontFamily: "var(--mono)", fontSize: 11.5 }}>{c.name}</span><span style={{ fontFamily: "var(--mono)", fontSize: 11, color: c.weak ? "var(--err)" : "var(--ok)" }}>{c.torque}</span><span style={{ fontFamily: "var(--mono)", fontSize: 11 }}>{c.cost}</span><span style={{ fontFamily: "var(--mono)", fontSize: 11 }}>{c.weight}</span><span style={{ fontFamily: "var(--mono)", fontSize: 11 }}>{c.proto}</span><span style={{ fontSize: 10.5, color: "var(--mut)" }}>{c.note}</span>
              <Btn kind={c.weak ? "ghost" : "primary"} size="sm" disabled={c.weak} onClick={() => { const rid = target === "__new" ? act.addRobot(d.project.name) : target; act.addParts(rid, [{ name: c.name, cat: "actuators", state: "planned", src: "sourced", ev: req }]); done(`${c.name} added as planned — drop its vendor CAD into the assembly when ready`); }}>Select</Btn>
            </div>))}
          <div style={{ display: "flex", gap: 10, alignItems: "center", padding: "9px 14px", justifyContent: "flex-end" }}><Mono size={9}>ENTERS AS PLANNED IN</Mono><RobotPick robots={d.robots} value={target} onChange={setTarget} allowNew /></div>
        </Card>)}
    </div>);
}

/* ---- Authored ---- */
function PathAuthored({ d, act, done }) {
  const [f, setF] = useH4({ name: "", cat: "structure", specs: "", target: d.robots[0] ? d.robots[0].id : "__new" });
  const inp = (k, ph, w) => <input value={f[k]} onChange={(e) => setF((s) => ({ ...s, [k]: e.target.value }))} placeholder={ph} style={{ width: w || "100%", boxSizing: "border-box", background: "var(--bg)", color: "var(--tx)", border: "1px solid var(--bd)", borderRadius: 3, padding: "9px 11px", fontSize: 12.5, fontFamily: "var(--ui)", outline: "none" }} />;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 520 }}>
      <Mono size={9}>DEFINE A CUSTOM PART</Mono>
      <div><Mono size={8.5} style={{ display: "block", marginBottom: 5 }}>NAME</Mono>{inp("name", "e.g. carbon wrist plate v2")}</div>
      <div style={{ display: "flex", gap: 10 }}>
        <div style={{ flex: 1 }}><Mono size={8.5} style={{ display: "block", marginBottom: 5 }}>CATEGORY</Mono><select value={f.cat} onChange={(e) => setF((s) => ({ ...s, cat: e.target.value }))} style={{ width: "100%", background: "var(--bg)", color: "var(--tx)", border: "1px solid var(--bd)", borderRadius: 3, padding: "8px 10px", fontSize: 12.5, fontFamily: "var(--ui)", outline: "none" }}>{V4.CATS.map((c) => <option key={c}>{c}</option>)}</select></div>
        <div style={{ flex: 1 }}><Mono size={8.5} style={{ display: "block", marginBottom: 5 }}>ROBOT</Mono><RobotPick robots={d.robots} value={f.target} onChange={(v) => setF((s) => ({ ...s, target: v }))} allowNew /></div>
      </div>
      <div><Mono size={8.5} style={{ display: "block", marginBottom: 5 }}>KEY SPECS</Mono>{inp("specs", "e.g. 2 mm CF, 38 g, M3 pattern 20×20")}</div>
      <div style={{ display: "flex", justifyContent: "flex-end" }}><Btn kind="primary" disabled={!f.name} onClick={() => { const rid = f.target === "__new" ? act.addRobot(d.project.name) : f.target; act.addParts(rid, [{ name: f.name, cat: f.cat, state: "planned", src: "authored", specs: f.specs }]); done(`${f.name} created as planned`); }}>Create</Btn></div>
    </div>);
}

const HW_PATHS = [
  { id: "detected", title: "Detected", sub: "Plugged in right now.", icon: "chip2" },
  { id: "file", title: "From a file", sub: "Parsed from what's already here.", icon: "file" },
  { id: "library", title: "Library", sub: "A known platform.", icon: "box" },
  { id: "sourced", title: "Sourced", sub: "I need a part.", icon: "search" },
  { id: "authored", title: "Authored", sub: "Define a custom part.", icon: "plus" },
];
function HardwarePanel({ d, act, onDone, openSol }) {
  const [path, setPath] = useH4(null);
  const [msg, setMsg] = useH4(null);
  const done = (m) => { setMsg(m); setPath(null); onDone && onDone(m); };
  if (!path) return (
    <div>
      {msg && <div style={{ display: "flex", gap: 9, alignItems: "center", background: "color-mix(in srgb, var(--ok) 7%, transparent)", border: "1px solid color-mix(in srgb, var(--ok) 40%, transparent)", borderRadius: 3, padding: "9px 12px", fontSize: 12, marginBottom: 12 }}><span style={{ color: "var(--ok)" }}>{SI.check({ size: 13 })}</span>{msg}</div>}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(170px, 1fr))", gap: 10 }}>
        {HW_PATHS.map((p) => (
          <Card key={p.id} pad={14} onClick={() => setPath(p.id)} style={{ cursor: "pointer" }}>
            <span style={{ color: "var(--acc)" }}>{SI[p.icon]({ size: 17 })}</span>
            <div style={{ fontSize: 13.5, fontWeight: 600, marginTop: 10 }}>{p.title}</div>
            <div style={{ fontSize: 11.5, color: "var(--mut)", marginTop: 3 }}>“{p.sub}”</div>
          </Card>))}
      </div>
      <div style={{ marginTop: 14, fontSize: 11, color: "var(--mut)", lineHeight: 1.6 }}>Every part gets a lifecycle — <StateChip state="planned" small /> <StateChip state="ordered" small /> <StateChip state="received" small /> <StateChip state="installed" small /> <StateChip state="live" small /> — shown the same way in Workspace, Live Bench and BOM. A planned part is visibly not yet wired.</div>
    </div>);
  const P = HW_PATHS.find((p) => p.id === path);
  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
        <span onClick={() => setPath(null)} style={{ fontSize: 12, color: "var(--mut)", cursor: "pointer", display: "inline-flex", gap: 6, alignItems: "center" }}>{SI.arrowL({ size: 12 })} five paths</span>
        <span style={{ color: "var(--mut)" }}>/</span><span style={{ fontSize: 13, fontWeight: 600 }}>{P.title}</span>
      </div>
      {path === "detected" && <PathDetected d={d} act={act} done={done} />}
      {path === "file" && <PathFromFile d={d} act={act} done={done} />}
      {path === "library" && <PathLibrary d={d} act={act} done={done} />}
      {path === "sourced" && <PathSourced d={d} act={act} done={done} openSol={openSol} />}
      {path === "authored" && <PathAuthored d={d} act={act} done={done} />}
    </div>);
}
Object.assign(window, { HardwarePanel, StateChip });
