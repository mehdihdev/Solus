// Solus v4 — Store (extensions) + BOM widget
const { useState: useSt4 } = React;

function StoreScreen4({ d, pinned, onInstall, onPin, onToast }) {
  const [detail, setDetail] = useSt4(null);
  const inst = (w) => d.project.installed.includes(w.id);
  const met = (w) => w.id === "bom" ? d.project.parts.length > 0 : w.id === "compliance" ? d.rules > 0 : w.id === "canview" ? d.robots.some((r) => r.platform === "fsae") : w.id === "datasheets" ? d.docs.some((x) => x.domain === "ee") : true;
  const row = (w) => (
    <Card key={w.id} pad={0} onClick={() => setDetail(w)} style={{ cursor: "pointer" }}>
      <div style={{ display: "flex", gap: 12, alignItems: "center", padding: "12px 15px" }}>
        <span style={{ width: 34, height: 34, borderRadius: 5, background: "var(--sur2)", border: "1px solid var(--bd)", display: "inline-flex", alignItems: "center", justifyContent: "center", color: met(w) ? "var(--acc)" : "var(--mut)" }}>{(SI[w.icon] || SI.box)({ size: 15 })}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}><span style={{ fontSize: 13, fontWeight: 600 }}>{w.name}</span><Mono size={7.5} color={w.fp ? "var(--ok)" : "var(--warn)"} style={{ border: `1px solid ${w.fp ? "color-mix(in srgb, var(--ok) 35%, transparent)" : "color-mix(in srgb, var(--warn) 35%, transparent)"}`, borderRadius: 99, padding: "1px 7px" }}>{w.fp ? "FIRST-PARTY" : "COMMUNITY"}</Mono>{pinned.includes(w.id) && <Mono size={7.5} color="var(--acc)">📌 ALL PROJECTS</Mono>}</div>
          <div style={{ fontSize: 11, color: "var(--mut)", marginTop: 3, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{w.does}</div>
        </div>
        {inst(w) ? <Mono size={8.5} color="var(--ok)">● INSTALLED</Mono> : met(w) ? <Btn kind="primary" size="sm" onClick={(e) => { e.stopPropagation(); onInstall(w.id, true); }}>Install</Btn> : <Mono size={8.5}>NEEDS {w.req.toUpperCase()}</Mono>}
      </div>
    </Card>);
  const sug = V4.WIDGETS.filter((w) => !inst(w) && met(w)), ins = V4.WIDGETS.filter(inst), rest = V4.WIDGETS.filter((w) => !inst(w) && !met(w));
  return (
    <div style={{ flex: 1, overflowY: "auto", minWidth: 0 }} data-screen-label="Store">
      <div style={{ maxWidth: 720, margin: "0 auto", padding: "24px 28px 48px" }}>
        <h1 style={{ margin: 0, fontSize: 21, fontWeight: 600 }}>Store</h1>
        <p style={{ fontSize: 12.5, color: "var(--mut)", margin: "6px 0 0", lineHeight: 1.6 }}>Capabilities are extensions. Each adds a tab after the separator, a node in the graph, and abilities for SOL. Suggested because of what's connected — never because it sells.</p>
        {[["SUGGESTED — THIS PROJECT HAS WHAT THESE NEED", sug], ["INSTALLED", ins], ["EVERYTHING ELSE", rest]].map(([t, list]) => list.length > 0 && <div key={t} style={{ marginTop: 20 }}><Mono size={9}>{t}</Mono><div style={{ display: "flex", flexDirection: "column", gap: 9, marginTop: 9 }}>{list.map(row)}</div></div>)}
      </div>
      {detail && (
        <ChromeModal title={detail.name} onClose={() => setDetail(null)} width={440}>
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <span style={{ width: 38, height: 38, borderRadius: 6, background: "var(--sur2)", border: "1px solid var(--bd)", display: "inline-flex", alignItems: "center", justifyContent: "center", color: "var(--acc)" }}>{(SI[detail.icon] || SI.box)({ size: 17 })}</span>
            <div><Mono size={8.5} color={detail.fp ? "var(--ok)" : "var(--warn)"}>{detail.fp ? "FIRST-PARTY · SOLUS" : detail.by.toUpperCase()}</Mono><div style={{ fontSize: 11.5, color: "var(--mut)", marginTop: 2 }}>needs: {detail.req}</div></div>
          </div>
          <p style={{ fontSize: 12.5, lineHeight: 1.65, margin: "14px 0 0" }}>{detail.does}</p>
          <Mono size={8.5} style={{ display: "block", marginTop: 14 }}>INSTALLING ADDS</Mono>
          <div style={{ marginTop: 6 }}>{detail.adds.map((a) => <div key={a} style={{ display: "flex", gap: 8, fontSize: 12, padding: "5px 0", borderBottom: "1px solid var(--bd)" }}><span style={{ color: "var(--ok)" }}>{SI.check({ size: 12 })}</span>{a}</div>)}</div>
          {!met(detail) && <div style={{ marginTop: 12, background: "color-mix(in srgb, var(--warn) 6%, transparent)", border: "1px solid color-mix(in srgb, var(--warn) 35%, transparent)", borderRadius: 3, padding: "9px 11px", fontSize: 11.5, lineHeight: 1.55 }}>Won't do anything in this project yet — it needs <b>{detail.req}</b>. It installs fine and stays dormant.</div>}
          <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
            {inst(detail) ? <><Btn kind="ghost" style={{ flex: 1 }} onClick={() => { onInstall(detail.id, false); setDetail(null); }}>Uninstall</Btn><Btn kind={pinned.includes(detail.id) ? "soft" : "ghost"} style={{ flex: 1 }} onClick={() => onPin(detail.id)}>{pinned.includes(detail.id) ? "Unpin from all projects" : "Pin for all projects"}</Btn></>
              : <Btn kind="primary" style={{ flex: 1 }} onClick={() => { onInstall(detail.id, true); setDetail(null); }}>Install{met(detail) ? "" : " anyway"}</Btn>}
          </div>
        </ChromeModal>)}
    </div>);
}

/* ---- BOM widget ---- */
function BomScreen({ d, act, openSol, onToast }) {
  const [sel, setSel] = useSt4(null);
  const [compat, setCompat] = useSt4(null);
  const rows = d.bom;
  const selRow = rows.find((r) => r.id === sel);
  const find = () => { setCompat("busy"); setTimeout(() => setCompat([
    { name: selRow.name.replace(/30 A/, "35 A").replace(/16 AWG/, "12 AWG"), why: "meets the finding's requirement", ok: true, rule: d.rules ? "EV.7.3 ✓" : null },
    { name: "Littelfuse MIDI 40 A", why: "fits footprint; exceeds harness rating", ok: d.rules === 0, rule: d.rules ? "EV.7.3 ✗ — exceeds W-12 gauge" : null },
    { name: "Generic ATO 30 A", why: "same rating as today — doesn't fix anything", ok: false, rule: d.rules ? "EV.7.3 ✓ (but no change)" : null },
  ]), 1400); };
  if (rows.length === 0) return (
    <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }} data-screen-label="BOM">
      <div style={{ textAlign: "center", maxWidth: 380 }}><span style={{ color: "var(--mut)", opacity: 0.6 }}>{SI.file({ size: 28 })}</span><div style={{ fontSize: 15, fontWeight: 600, marginTop: 12 }}>No parts yet</div><div style={{ fontSize: 12.5, color: "var(--mut)", marginTop: 8, lineHeight: 1.65 }}>The BOM has one row per canonical part. Rows appear as hardware enters through any of the five paths — nothing is listed that isn't real.</div></div>
    </div>);
  return (
    <div style={{ flex: 1, display: "flex", minWidth: 0, minHeight: 0 }} data-screen-label="BOM">
      <div style={{ flex: 1, overflowY: "auto", minWidth: 0 }}>
        <div style={{ maxWidth: 980, margin: "0 auto", padding: "22px 26px 44px" }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 14 }}><h1 style={{ margin: 0, fontSize: 21, fontWeight: 600 }}>BOM</h1><Mono size={9}>{rows.length} CANONICAL PARTS · ONE ROW EVEN WHEN A PART IS IN CAD + SCHEMATIC + BOM</Mono><div style={{ flex: 1 }}></div><Mono size={8.5} color={d.rules ? "var(--ok)" : "var(--mut)"}>{d.rules ? `${d.rules} COMPLIANCE RULES ACTIVE` : "NO RULES IN .SOLUS › PROJECT DETAILS"}</Mono></div>
          <Card pad={0} style={{ marginTop: 16 }}>
            <div style={{ display: "grid", gridTemplateColumns: "1.6fr 0.8fr 0.9fr 1fr 0.7fr", gap: 10, padding: "8px 14px", borderBottom: "1px solid var(--bd)" }}>{["PART", "CATEGORY", "ROBOT", "SEEN IN", "STATE"].map((h) => <Mono key={h} size={8}>{h}</Mono>)}</div>
            {rows.map((r) => (
              <div key={r.id} onClick={() => { setSel(r.id); setCompat(null); }} style={{ display: "grid", gridTemplateColumns: "1.6fr 0.8fr 0.9fr 1fr 0.7fr", gap: 10, alignItems: "center", padding: "9px 14px", borderBottom: "1px solid var(--bd)", cursor: "pointer", background: sel === r.id ? "color-mix(in srgb, var(--acc) 5%, transparent)" : "transparent" }}>
                <span style={{ fontFamily: "var(--mono)", fontSize: 11.5, color: r.honest ? "var(--warn)" : r.hot ? "var(--acc)" : "var(--tx)" }}>{r.name}{r.hot ? " ●" : ""}</span>
                <span style={{ fontSize: 11, color: "var(--mut)" }}>{r.cat}</span>
                <span style={{ fontFamily: "var(--mono)", fontSize: 10.5 }}>{(d.robots.find((x) => x.id === r.robotId) || {}).name || "—"}</span>
                <span style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>{r.sources.map((s) => <Mono key={s} size={7.5} style={{ border: "1px solid var(--bd)", borderRadius: 99, padding: "1px 6px" }}>{s}</Mono>)}</span>
                <StateChip state={r.state} small />
              </div>))}
          </Card>
        </div>
      </div>
      <div style={{ width: 300, borderLeft: "1px solid var(--bd)", background: "var(--sur)", flexShrink: 0, overflowY: "auto", padding: 16 }}>
        {!selRow ? <div style={{ color: "var(--mut)", fontSize: 12, lineHeight: 1.65, textAlign: "center", paddingTop: 30 }}>Select a row — lifecycle, evidence, and Find compatible parts.</div> : (
          <div>
            <Mono size={9}>{selRow.cat.toUpperCase()}</Mono>
            <div style={{ fontFamily: "var(--mono)", fontSize: 14, marginTop: 6, lineHeight: 1.4 }}>{selRow.name}</div>
            <div style={{ display: "flex", gap: 5, marginTop: 10, flexWrap: "wrap" }}>{V4.STATES.map((s) => <span key={s} onClick={() => act.setState(selRow.id, s)} style={{ cursor: "pointer", opacity: s === selRow.state ? 1 : 0.45 }}><StateChip state={s} small /></span>)}</div>
            <div style={{ marginTop: 12 }}>{[["Source", selRow.src], ["Evidence", selRow.ev || (selRow.doc ? "parsed from " + V4.DOC(selRow.doc).name : "—")], ["Replaces", selRow.replaces ? (rows.find((x) => x.id === selRow.replaces) || {}).name : "—"]].map(([k, v]) => <KV key={k} k={k} v={v} />)}</div>
            <div style={{ display: "flex", gap: 8, marginTop: 14 }}><Btn kind="primary" size="sm" style={{ flex: 1 }} onClick={find}>Find compatible parts</Btn><Btn kind="ghost" size="sm" onClick={() => openSol(null, `Tell me about ${selRow.name} in this robot`)}>Ask SOL</Btn></div>
            {compat === "busy" && <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 12, fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--mut)" }}><Spinner size={11} /> checking {d.rules || "no"} rules…</div>}
            {Array.isArray(compat) && <div style={{ marginTop: 12 }}><Mono size={8.5}>COMPATIBLE · {d.rules ? "RULE-CHECKED" : "UNCHECKED — NO RULES"}</Mono>{compat.map((c) => <div key={c.name} style={{ padding: "8px 0", borderBottom: "1px solid var(--bd)", opacity: c.ok ? 1 : 0.55 }}><div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}><span style={{ fontFamily: "var(--mono)", fontSize: 11 }}>{c.name}</span>{c.ok && <Btn kind="ghost" size="sm" onClick={() => { act.addParts(selRow.robotId, [{ name: c.name, cat: selRow.cat, state: "planned", src: "sourced", replaces: selRow.id }]); onToast("Added as planned", c.name); }}>Select</Btn>}</div><div style={{ fontSize: 10.5, color: "var(--mut)", marginTop: 2 }}>{c.why}{c.rule ? " · " + c.rule : ""}</div></div>)}</div>}
          </div>)}
      </div>
    </div>);
}
Object.assign(window, { StoreScreen4, BomScreen });
