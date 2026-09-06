// Solus — Settings layout (sub-nav) + Profile, Preferences, Model Config, Integrations, Members
const { useState: useStateS2, useEffect: useEffectS2 } = React;

/* ---------- shared bits ---------- */
function Toggle({ on, onChange }) {
  return (
    <span onClick={() => onChange(!on)} style={{ width: 36, height: 20, borderRadius: 99, background: on ? "var(--acc)" : "var(--sur2)", border: "1px solid var(--bd)", position: "relative", cursor: "pointer", flexShrink: 0, transition: "background 0.15s" }}>
      <span style={{ position: "absolute", top: 2, left: on ? 17 : 2, width: 14, height: 14, borderRadius: 99, background: on ? "var(--acc-ink)" : "var(--mut)", transition: "left 0.15s" }}></span>
    </span>
  );
}
function SettSection({ icon, title, sub, children, right }) {
  return (
    <Card pad={20} style={{ marginBottom: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div style={{ display: "flex", gap: 11, alignItems: "flex-start" }}>
          {icon && <span style={{ color: "var(--mut)", marginTop: 1 }}>{icon}</span>}
          <div>
            <div style={{ fontSize: 14, fontWeight: 600 }}>{title}</div>
            {sub && <div style={{ fontSize: 11.5, color: "var(--mut)", marginTop: 3, lineHeight: 1.5, maxWidth: 440 }}>{sub}</div>}
          </div>
        </div>
        {right}
      </div>
      <div style={{ marginTop: 16 }}>{children}</div>
    </Card>
  );
}
function SettRow({ label, sub, children, top }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: top ? "flex-start" : "center", gap: 18, padding: "11px 0", borderBottom: "1px solid var(--bd)" }}>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 12.5 }}>{label}</div>
        {sub && <div style={{ fontSize: 11, color: "var(--mut)", marginTop: 3, lineHeight: 1.45, maxWidth: 360 }}>{sub}</div>}
      </div>
      <div style={{ flexShrink: 0 }}>{children}</div>
    </div>
  );
}
function SettInput({ value, onChange, placeholder, textarea, mono, width }) {
  const st = { width: width || "100%", boxSizing: "border-box", background: "var(--bg)", color: "var(--tx)", border: "1px solid var(--bd)", borderRadius: 3, padding: "9px 11px", fontSize: 13, fontFamily: mono ? "var(--mono)" : "var(--ui)", outline: "none", resize: "none", lineHeight: 1.5 };
  return textarea
    ? <textarea value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} style={{ ...st, height: 70 }} />
    : <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} style={st} />;
}
function Selectbox({ value, onChange, options, width }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} style={{ background: "var(--bg)", color: "var(--tx)", border: "1px solid var(--bd)", borderRadius: 3, padding: "7px 10px", fontSize: 12.5, fontFamily: "var(--ui)", outline: "none", width }}>
      {options.map((o) => typeof o === "string" ? <option key={o} value={o}>{o}</option> : <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
}
function SaveBar({ show, onSave, onDiscard, saving, saved }) {
  if (!show && !saved) return null;
  return (
    <div className="toast-in" style={{ position: "sticky", bottom: 16, marginTop: 8, zIndex: 5 }}>
      <Card pad={0} style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 14px", boxShadow: "0 12px 36px rgba(0,0,0,0.45)", borderColor: saved ? "color-mix(in srgb, var(--ok) 45%, var(--bd))" : "color-mix(in srgb, var(--acc) 45%, var(--bd))" }}>
        <span style={{ fontSize: 12.5, flex: 1, color: saved ? "var(--ok)" : "var(--tx)" }}>
          {saved ? "✓ Changes saved" : "You have unsaved changes"}
        </span>
        {!saved && <Btn kind="ghost" size="sm" onClick={onDiscard}>Discard</Btn>}
        {!saved && <Btn kind="primary" size="sm" onClick={onSave}>{saving ? <><Spinner size={11} color="var(--acc-ink)" /> Saving…</> : "Save changes"}</Btn>}
      </Card>
    </div>
  );
}

/* ---------- Profile ---------- */
function ProfilePage() {
  const init = { name: "Maya Krishnan", handle: "maya-builds", role: "Firmware", domain: "sw", bio: "Firmware + controls. I keep the legs from falling over. Previously embedded at a drone startup.", tz: "America/Los_Angeles" };
  const [f, setF] = useStateS2(init);
  const [dirty, setDirty] = useStateS2(false);
  const [saving, setSaving] = useStateS2(false);
  const [saved, setSaved] = useStateS2(false);
  const set = (k, v) => { setF((s) => ({ ...s, [k]: v })); setDirty(true); setSaved(false); };
  const save = () => { setSaving(true); setTimeout(() => { setSaving(false); setDirty(false); setSaved(true); setTimeout(() => setSaved(false), 2200); }, 900); };
  const discard = () => { setF(init); setDirty(false); };
  return (
    <div>
      <SettSection icon={SI.user({ size: 15 })} title="Profile" sub="How you appear to teammates across the workspace.">
        <div style={{ display: "flex", gap: 18, alignItems: "center", paddingBottom: 14, borderBottom: "1px solid var(--bd)" }}>
          <Avatar name={f.name} size={56} />
          <div>
            <Btn kind="ghost" size="sm">Upload photo</Btn>
            <div style={{ fontSize: 10.5, color: "var(--mut)", marginTop: 7 }}>PNG or JPG, up to 2 MB. Falls back to your initials.</div>
          </div>
        </div>
        <SettRow label="Display name"><SettInput value={f.name} onChange={(v) => set("name", v)} width={240} /></SettRow>
        <SettRow label="Handle"><SettInput value={f.handle} onChange={(v) => set("handle", v)} width={240} mono /></SettRow>
        <SettRow label="Role"><SettInput value={f.role} onChange={(v) => set("role", v)} width={240} /></SettRow>
        <SettRow label="Primary domain">
          <div style={{ display: "flex", gap: 6 }}>
            {["sw", "ee", "me", "rt"].map((d) => <DomainChip key={d} d={d} small on={f.domain === d} onClick={() => set("domain", d)} />)}
          </div>
        </SettRow>
        <SettRow label="Bio" top><div style={{ width: 320 }}><SettInput value={f.bio} onChange={(v) => set("bio", v)} textarea /></div></SettRow>
        <SettRow label="Timezone"><Selectbox value={f.tz} onChange={(v) => set("tz", v)} options={["America/Los_Angeles", "America/New_York", "Europe/Berlin", "Asia/Tokyo"]} /></SettRow>
      </SettSection>

      <SettSection icon={SI.link({ size: 15 })} title="Linked accounts" sub="Used for sign-in and to attribute commits across domains.">
        <SettRow label={<span style={{ display: "inline-flex", gap: 9, alignItems: "center" }}>{SI.github({ size: 15 })} GitHub <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--mut)" }}>@maya-builds</span></span>}>
          <Mono size={9} color="var(--ok)">● CONNECTED</Mono>
        </SettRow>
        <SettRow label={<span style={{ display: "inline-flex", gap: 9, alignItems: "center" }}><span style={{ width: 15, height: 15, borderRadius: 99, border: "1px solid var(--bd)", display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: 9, fontFamily: "var(--mono)" }}>G</span> Google</span>}>
          <Btn kind="ghost" size="sm">Connect</Btn>
        </SettRow>
      </SettSection>

      <SettSection icon={SI.file({ size: 15 })} title="Account">
        <SettRow label="Email"><span style={{ fontFamily: "var(--mono)", fontSize: 12 }}>maya@strider.dev</span></SettRow>
        <SettRow label="Member since"><span style={{ fontSize: 12.5, color: "var(--mut)" }}>February 2026</span></SettRow>
        <SettRow label="Password"><Btn kind="ghost" size="sm">Change password</Btn></SettRow>
      </SettSection>

      <SaveBar show={dirty} saved={saved} saving={saving} onSave={save} onDiscard={discard} />
    </div>
  );
}

/* ---------- Preferences ---------- */
function PreferencesPage({ tw, setTweak }) {
  const [units, setUnits] = useStateS2("SI");
  const [editorSync, setEditorSync] = useStateS2(false);
  const [startup, setStartup] = useStateS2("Last viewed");
  const [notif, setNotif] = useStateS2({ crossdomain: true, mychanges: true, bench: true, mentions: true, weekly: false });
  return (
    <div>
      <SettSection icon={SI.monitor({ size: 15 })} title="Appearance" sub="Theme presets include editor schemes — set Solus to match your IDE.">
        <SettRow label="Theme">
          <Selectbox value={tw.theme} onChange={(v) => setTweak("theme", v)} options={Object.keys(SolusThemes).map((k) => ({ value: k, label: SolusThemes[k].name }))} />
        </SettRow>
        <SettRow label="Sync with editor theme" sub="Match Solus to your VS Code color theme automatically.">
          <Toggle on={editorSync} onChange={setEditorSync} />
        </SettRow>
        <SettRow label="Accent">
          <div style={{ display: "flex", gap: 8 }}>
            {Object.keys(SolusAccents).map((k) => (
              <span key={k} onClick={() => setTweak("accent", k)} style={{ width: 22, height: 22, borderRadius: 99, background: SolusAccents[k].c, cursor: "pointer", border: tw.accent === k ? "2px solid var(--tx)" : "2px solid transparent", boxSizing: "border-box" }}></span>
            ))}
          </div>
        </SettRow>
        <SettRow label="Density"><Seg size="sm" options={["compact", "regular"]} value={tw.density} onChange={(v) => setTweak("density", v)} /></SettRow>
      </SettSection>

      <SettSection icon={SI.sol({ size: 15 })} title="SOL defaults" sub="Starting behavior for the agent. You can still flip these per-conversation.">
        <SettRow label="Answer mode" sub="Guide explains and teaches; Expert is terse and direct."><Seg size="sm" options={["Guide", "Expert"]} value={tw.solMode} onChange={(v) => setTweak("solMode", v)} /></SettRow>
        <SettRow label="SOL companion" sub="Guide mode rides your cursor; corner mode docks it bottom-right. Press Ctrl to toggle anytime."><Seg size="sm" options={["corner", "follow"]} value={tw.orbMode} onChange={(v) => setTweak("orbMode", v)} /></SettRow>
        <SettRow label="Core energy"><input type="range" min="10" max="100" value={tw.orbEnergy} onChange={(e) => setTweak("orbEnergy", +e.target.value)} style={{ accentColor: "var(--acc)", width: 150 }} /></SettRow>
      </SettSection>

      <SettSection icon={SI.sliders({ size: 15 })} title="Workspace" sub="Units and where Solus opens.">
        <SettRow label="Units" sub="Telemetry, torque, and dimensions display."><Seg size="sm" options={["SI", "Imperial"]} value={units} onChange={setUnits} /></SettRow>
        <SettRow label="Startup screen"><Selectbox value={startup} onChange={setStartup} options={["Last viewed", "Context Model", "Live Bench", "SOL"]} /></SettRow>
        <SettRow label="Default telemetry speed"><input type="range" min="0.5" max="4" step="0.5" value={tw.telemSpeed} onChange={(e) => setTweak("telemSpeed", +e.target.value)} style={{ accentColor: "var(--acc)", width: 150 }} /></SettRow>
      </SettSection>

      <SettSection icon={SI.bell({ size: 15 })} title="Notifications" sub="What pings you. Cross-domain alerts are always on for criticals.">
        {[["crossdomain", "Cross-domain alerts", "When a change in another domain affects your work"], ["mychanges", "Effects of my changes", "When something I edit affects a teammate"], ["bench", "Bench anomalies", "When live telemetry goes out of range"], ["mentions", "Mentions & replies", "When a teammate @s you"], ["weekly", "Weekly digest", "A Monday summary of cross-domain activity"]].map(([k, l, s]) => (
          <SettRow key={k} label={l} sub={s}><Toggle on={notif[k]} onChange={(v) => setNotif((n) => ({ ...n, [k]: v }))} /></SettRow>
        ))}
      </SettSection>
    </div>
  );
}

/* ---------- Model Configuration ---------- */
function ModelConfigPage() {
  const [providerId, setProviderId] = useStateS2("solus");
  const [keys, setKeys] = useStateS2({});
  const [testing, setTesting] = useStateS2(null); // null | 'busy' | 'ok'
  const [effort, setEffort] = useStateS2(2); // 0..3
  const [ctx, setCtx] = useStateS2("200k");
  const [routing, setRouting] = useStateS2(() => { const r = {}; SOL_TASKS.forEach((t) => (r[t.id] = t.def)); return r; });
  const provider = SOL_PROVIDERS.find((p) => p.id === providerId);
  const byo = !provider.hosted;
  const allModels = [].concat(...SOL_PROVIDERS.map((p) => p.models));
  const effortLabels = ["Instant", "Fast", "Balanced", "Deep"];

  const testKey = () => { setTesting("busy"); setTimeout(() => setTesting("ok"), 1400); };

  return (
    <div>
      <SettSection icon={SI.bolt({ size: 15 })} title="SOL engine" sub="Choose who runs SOL's reasoning. Hosted is metered by credit; bring your own key to use a provider directly.">
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))", gap: 10, marginTop: 4 }}>
          {SOL_PROVIDERS.map((p) => {
            const on = providerId === p.id;
            return (
              <Card key={p.id} pad={13} onClick={() => { setProviderId(p.id); setTesting(null); }} style={{ cursor: "pointer", borderColor: on ? "var(--acc)" : "var(--bd)", position: "relative" }}>
                {on && <span style={{ position: "absolute", top: 10, right: 10, color: "var(--acc)" }}>{SI.check({ size: 14 })}</span>}
                <span style={{ width: 30, height: 30, borderRadius: 5, background: "var(--sur2)", border: "1px solid var(--bd)", display: "inline-flex", alignItems: "center", justifyContent: "center", fontFamily: "var(--mono)", fontSize: 13, fontWeight: 500 }}>{p.mark}</span>
                <div style={{ fontSize: 13, fontWeight: 600, marginTop: 9 }}>{p.name}</div>
                {p.note && <Mono size={8.5} color={p.hosted ? "var(--ok)" : "var(--acc)"} style={{ marginTop: 3, display: "block" }}>{p.note}</Mono>}
              </Card>
            );
          })}
        </div>
        <div style={{ fontSize: 11.5, color: "var(--mut)", marginTop: 12, lineHeight: 1.5 }}>{provider.desc}</div>
      </SettSection>

      {byo && (
        <SettSection icon={SI.key({ size: 15 })} title={`${provider.name} API key`} sub="Stored locally in this workspace and sent directly to the provider — never to Solus servers.">
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input type="password" value={keys[providerId] || ""} onChange={(e) => { setKeys((k) => ({ ...k, [providerId]: e.target.value })); setTesting(null); }}
              placeholder={provider.id === "local" ? "http://localhost:11434" : "sk-…"}
              style={{ flex: 1, background: "var(--bg)", color: "var(--tx)", border: "1px solid var(--bd)", borderRadius: 3, padding: "9px 11px", fontSize: 12.5, fontFamily: "var(--mono)", outline: "none" }} />
            <Btn kind="ghost" size="sm" onClick={testKey} disabled={!(keys[providerId] || "").length}>
              {testing === "busy" ? <><Spinner size={11} /> Testing…</> : testing === "ok" ? <><span style={{ color: "var(--ok)" }}>{SI.check({ size: 13 })}</span> Connected</> : "Test connection"}
            </Btn>
          </div>
          <div style={{ display: "flex", gap: 7, alignItems: "center", marginTop: 10, fontSize: 11, color: "var(--mut)" }}>
            {SI.key({ size: 12 })} {provider.id === "local" ? "Point at your Ollama or llama.cpp server." : "Generate a key in your provider dashboard with inference scope."}
          </div>
        </SettSection>
      )}

      <SettSection icon={SI.sliders({ size: 15 })} title="Reasoning" sub="How hard SOL thinks by default. Deeper reasoning costs more credits / tokens.">
        <SettRow label="Effort" sub={effortLabels[effort] + (effort >= 2 ? " — traces more of the graph" : " — quicker, shallower")}>
          <input type="range" min="0" max="3" value={effort} onChange={(e) => setEffort(+e.target.value)} style={{ accentColor: "var(--acc)", width: 170 }} />
        </SettRow>
        <SettRow label="Context window"><Selectbox value={ctx} onChange={setCtx} options={["32k", "128k", "200k", "1M"]} /></SettRow>
      </SettSection>

      <SettSection icon={SI.cmd({ size: 15 })} title="Per-task routing" sub="Send different jobs to different models. Defaults use the engine above.">
        {SOL_TASKS.map((t) => (
          <SettRow key={t.id} label={t.label} sub={t.sub}>
            <Selectbox value={routing[t.id]} onChange={(v) => setRouting((r) => ({ ...r, [t.id]: v }))} options={allModels} width={190} />
          </SettRow>
        ))}
      </SettSection>
    </div>
  );
}

/* ---------- Integrations (workspace) ---------- */
function IntegrationsPage({ connected }) {
  return (
    <SettSection icon={SI.link({ size: 15 })} title="Integrations" sub="Each connected source becomes a domain in the context model.">
      {INTEGRATIONS.map((i) => {
        const on = connected.includes(i.id);
        return (
          <SettRow key={i.id} top
            label={<span style={{ display: "inline-flex", gap: 11, alignItems: "center" }}>
              <span style={{ fontFamily: "var(--mono)", fontSize: 11, width: 30, height: 30, borderRadius: 4, background: "var(--sur2)", border: "1px solid var(--bd)", display: "inline-flex", alignItems: "center", justifyContent: "center" }}>{i.mark}</span>
              <span><span style={{ fontWeight: 600 }}>{i.name}</span><div style={{ fontSize: 10.5, color: "var(--mut)" }}>{i.kind}{on ? " · " + i.result.replace("Connected — ", "") : ""}</div></span>
            </span>}>
            {on ? <div style={{ display: "flex", gap: 8, alignItems: "center" }}><Mono size={9} color="var(--ok)">● CONNECTED</Mono><Btn kind="ghost" size="sm">Manage</Btn></div> : <Btn kind="primary" size="sm">Connect</Btn>}
          </SettRow>
        );
      })}
    </SettSection>
  );
}

/* ---------- Members (workspace) ---------- */
function MembersPage() {
  const roles = ["Owner", "Admin", "Member", "Viewer"];
  const memberRole = { "Maya Krishnan": "Owner", "Priya Nair": "Admin", "Jonas Weber": "Member", "Marcus Hale": "Member" };
  return (
    <SettSection icon={SI.team({ size: 15 })} title="Members" sub="Manage who can see and change this workspace." right={<Btn kind="primary" size="sm">{SI.plus({ size: 12 })} Invite</Btn>}>
      {TEAM.map((m) => (
        <SettRow key={m.name} label={<span style={{ display: "inline-flex", gap: 11, alignItems: "center" }}><Avatar name={m.name} size={28} /><span><span style={{ fontWeight: 600 }}>{m.name}{m.you && <span style={{ color: "var(--mut)", fontWeight: 400 }}> (you)</span>}</span><div style={{ fontSize: 10.5, color: "var(--mut)" }}>{m.email}</div></span></span>}>
          <Selectbox value={memberRole[m.name]} onChange={() => {}} options={roles} />
        </SettRow>
      ))}
    </SettSection>
  );
}

/* ---------- General (workspace) ---------- */
function GeneralPage() {
  return (
    <div>
      <SettSection icon={SI.building({ size: 15 })} title="Workspace" sub="Project-level settings for strider-qd12.">
        <SettRow label="Name"><SettInput value="strider-qd12" onChange={() => {}} width={220} mono /></SettRow>
        <SettRow label="Robot template"><span style={{ fontSize: 12.5, color: "var(--mut)" }}>Quadruped · 12 actuators</span></SettRow>
        <SettRow label="Context model" sub="247 nodes · 31 cross-domain links · synced 2 min ago"><Btn kind="ghost" size="sm">Re-index now</Btn></SettRow>
      </SettSection>
      <SettSection icon={SI.warn({ size: 15 })} title="Danger zone">
        <SettRow label="Archive workspace" sub="Hide from the switcher; data is retained."><Btn kind="ghost" size="sm">Archive</Btn></SettRow>
        <SettRow label="Delete workspace" sub="Permanently remove the project and its context model."><Btn kind="danger" size="sm">Delete</Btn></SettRow>
      </SettSection>
    </div>
  );
}

/* ---------- layout ---------- */
const SETT_NAV = [
  { group: "Account", items: [["profile", "Profile", "user"], ["preferences", "Preferences", "sliders"], ["model", "Model configuration", "bolt"], ["billing", "Billing & plan", "card"]] },
  { group: "Workspace", items: [["general", "General", "building"], ["integrations", "Integrations", "link"], ["members", "Members", "team"]] },
];
const SETT_TITLES = { profile: "Profile", preferences: "Preferences", model: "Model configuration", billing: "Billing & plan", general: "General", integrations: "Integrations", members: "Members" };

function SettingsLayout({ section, setSection, tw, setTweak, connected, onUpgrade }) {
  return (
    <div style={{ flex: 1, display: "flex", minWidth: 0, minHeight: 0 }}>
      {/* sub-nav */}
      <div style={{ width: 218, borderRight: "1px solid var(--bd)", background: "var(--sur)", padding: "20px 12px", overflowY: "auto", flexShrink: 0 }}>
        <div style={{ padding: "0 8px 14px" }}><span style={{ fontSize: 15, fontWeight: 600 }}>Settings</span></div>
        {SETT_NAV.map((g) => (
          <div key={g.group} style={{ marginBottom: 16 }}>
            <div style={{ padding: "0 8px 6px" }}><Mono size={8.5}>{g.group}</Mono></div>
            {g.items.map(([id, label, icon]) => {
              const on = section === id;
              return (
                <div key={id} onClick={() => setSection(id)} style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 8px", borderRadius: 4, cursor: "pointer", fontSize: 12.5, color: on ? "var(--tx)" : "var(--mut)", background: on ? "var(--sur2)" : "transparent", fontWeight: on ? 600 : 400 }}>
                  <span style={{ color: on ? "var(--acc)" : "var(--mut)", display: "inline-flex" }}>{SI[icon]({ size: 14 })}</span>
                  {label}
                </div>
              );
            })}
          </div>
        ))}
      </div>
      {/* content */}
      <div data-screen-label={"Settings · " + (SETT_TITLES[section] || "")} style={{ flex: 1, overflowY: "auto", minWidth: 0 }}>
        <div style={{ maxWidth: 720, margin: "0 auto", padding: "24px 28px 40px" }}>
          {section === "profile" && <ProfilePage />}
          {section === "preferences" && <PreferencesPage tw={tw} setTweak={setTweak} />}
          {section === "model" && <ModelConfigPage />}
          {section === "billing" && <BillingPage onUpgrade={onUpgrade} />}
          {section === "general" && <GeneralPage />}
          {section === "integrations" && <IntegrationsPage connected={connected} />}
          {section === "members" && <MembersPage />}
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { SettingsLayout, Toggle, SettSection, SettRow });
