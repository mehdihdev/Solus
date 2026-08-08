# Runbook — Altium customer-side validation (SOLUSDEV-102)

This runbook is for a **customer** (or design partner) validating the Solus Altium
integration on their own machine. Solus does not hold an Altium license, so everything that
needs a live Altium Designer session is validated here, by you, and not in Solus' own QA
(`integrations/mcp/README.md`, byo_paid QA scope). Working through this document end-to-end
and reporting the checklist results IS the acceptance test for the live Altium path.

What Solus already validated in-house (you do not need to re-prove it): launch confinement,
the trimmed 11-tool surface, credential hygiene, and the graceful degraded behavior when
Altium is absent. What only you can validate: the real DelphiScript bridge round trip, real
project reads, the confirmation-gated writes, and pointer/workspace confinement against a
live Altium session.

## 1. Prerequisites

- **Windows 10/11.** Altium Designer runs only on Windows.
- **Altium Designer** (recent version; AD20+ preferred per upstream guidance) with **your own
  valid license**, and a real project you can open (ideally a copy — see the write-tool step).
- **Back up any design you use.** The underlying bridge is experimental upstream software;
  Solus trims it to a read-mostly surface, but upstream itself warns some operations can crash
  Altium's scripting engine.
- **Solus desktop app** installed and signed in, with your team on a plan that includes
  BYO-paid tools (PRO — a BASIC team will see "Upgrade required" instead of a license prompt).
- **Solus companion** running (bundled with the desktop app), connected to the project you
  will validate against.

## 2. Install

1. **Fork runtime.** The companion's install/update step materializes the Altium server's
   private Python environment from the committed, hash-pinned lockfile
   (`integrations/mcp/altium/requirements.lock.txt` → `.venv\Scripts\python.exe` inside the
   fork directory). Nothing is downloaded at launch time; if install succeeded, the Bridge
   popover in the Solus desktop app lists an `altium` row.
2. **Altium-side script project.** The DelphiScript bridge ships inside the fork at
   `integrations\mcp\altium\upstream\scripts\altium\Altium_API.PrjScr` (under the companion's
   install root). Unlike upstream's `eda-agent install-scripts` command, the Solus fork does
   NOT install a console entrypoint or copy scripts around — point Altium directly at the
   shipped script project. Register it once:
   1. In Altium: **DXP → Preferences → Scripting System → Global Projects → Install from
      file**, and select the `Altium_API.PrjScr` above.
      (Alternative, no global registration: **File → Open…** the `.PrjScr`, then use the Run
      Script dialog the same way.)
3. **Start the bridge** (after every Altium start, when you want Solus connected):
   1. **File → Run Script…**
   2. Expand `Altium_API` → `Dispatcher.pas`, select **StartMCPServer**, click **Run**.
   3. The in-Altium floating status window appears and the polling loop is live.

## 3. Enter your license (the Add-license modal)

1. In the Solus desktop app TopBar, open the **Bridge** pill popover. The `altium` row shows
   an **Add license** button (state: bring your license).
2. Click it. A modal opens with one masked input, labeled `altium_license`. Enter your Altium
   license value and submit.
3. Expected: "License submitted (altium_license)…", then the row's detail reads
   "license stored (altium_license)", and within ~10 seconds the row flips to **ready** and
   the button disappears.
4. Your license value is stored per-team in Solus' secret store and is never shown, logged,
   or sent back — every message you will ever see names only the KEY (`altium_license`),
   never the value. Re-submitting later simply overwrites.

## 4. Validation checklist

This mirrors Section B of `docs/qa/COWORK_QA_altium-mcp.md`. Mark each ✅ / ❌ (with notes)
/ ➖.

### B1 — Bridge round trip

1. [ ] With `StartMCPServer` running and a project open, the `altium` row is **ready**.
2. [ ] Ask SOL something that reads Altium status (e.g. "is Altium reachable? what version?"
       — `app_get_status`): the answer matches your real Altium version and active document,
       and the in-Altium status window logs the request.

### B2 — Real project reads

1. [ ] Ask SOL for the focused project's path, documents, and stats (`proj_get_path`,
       `proj_list_documents`, `proj_get_stats`): values match the open project.
2. [ ] Ask for the BOM (`proj_get_bom`) and one component's detail
       (`proj_get_component_info`): designators, footprints, and values match.
3. [ ] **No hidden saves:** make a small edit WITHOUT saving (document shows dirty), ask for
       the nets (`proj_get_nets`), then confirm the document is STILL dirty. If the tool
       saved your document, that is a ❌ — report it immediately.

### B3 — Netlist export + live sync

1. [ ] Ask SOL to export the netlist (`export_netlist`): a Protel-format netlist matching
       your project, not a "degraded" answer.
2. [ ] If your Solus source is configured with the project's path, a sync acquires the live
       export and the Solus graph reflects the real project.

### B4 — Writes with confirmation (use a COPY of a project)

1. [ ] Ask SOL to set a project parameter: Solus shows an explicit confirmation describing
       exactly what will be written BEFORE anything happens. **Decline** → verify nothing
       changed in Altium.
2. [ ] Repeat and **accept** → the parameter is set; re-read confirms it.
3. [ ] Bulk component-parameter write (`sch_set_components_parameters`) on a few components:
       same confirmation gate, effect visible in the schematic.

### B5 — Confinement

1. [ ] During calls, request/response files appear only under
       `<your project workspace>\.eda-agent-ipc\` — nowhere else.
2. [ ] Record whether `C:\ProgramData\eda-agent\workspace-path.txt` existed BEFORE this
       validation (e.g. from a prior upstream eda-agent install) and confirm the Solus launch
       did not create or modify it. Report both facts.
3. [ ] See "bridge not responding" below — the workspace handshake between the confined
       Python side and the Altium-side script is itself a validation point on this first run.

### B6 — Failure tolerance

1. [ ] Close Altium while connected: Solus reports the tool as unavailable/degraded, nothing
       crashes; reopening Altium and re-running **StartMCPServer** restores service.
2. [ ] If any call crashes Altium's scripting engine, note the tool and your Altium version;
       Solus itself must survive and show a structured error.

## 5. Troubleshooting

**Bridge not responding (ready row, but Altium reads hang or degrade).**

- Confirm the polling loop is actually running: the in-Altium status window must be open and
  counting. It stops when you close Altium or click Detach; re-run **StartMCPServer**.
- Check `<workspace>\.eda-agent-ipc\` while a call is in flight. `request_*.json` files that
  appear and **accumulate unanswered** mean the Python side is writing but the Altium-side
  script is polling a DIFFERENT directory. **Known validation point on first run:** the
  Solus launch confines its IPC exchange and pointer file to `<workspace>\.eda-agent-ipc\`
  and deliberately never writes upstream's machine-global pointer
  (`C:\ProgramData\eda-agent\workspace-path.txt`) — while the shipped Altium-side script
  resolves its workspace from that machine-global pointer (falling back to
  `C:\EDA Agent\workspace\` when it is absent). If you observe exactly this split
  (requests in the confined directory, Altium polling elsewhere — check for activity in
  `C:\EDA Agent\workspace\`), STOP and report it to Solus support with what you saw; do not
  hand-edit pointer files unless support asks you to. This handshake is precisely what
  in-house QA could not exercise.
- Version mismatch or a script compile error shows in Altium's Messages panel when the
  script project loads — include that text in your report.

**`license_state` stuck on "bring your license" after submitting.**

- Wait one poll cycle (~10 s) with the popover closed, then reopen.
- Check the row's detail text: "license not stored: <reason>" names the problem (unknown
  server / not a BYO tool / unknown keys). Re-submit; submits are idempotent.
- If the pill shows the bridge offline, the companion is not connected — the modal cannot
  reach the cloud without it.

**"Upgrade required" instead of a license prompt.** Your team's plan does not include
BYO-paid tools — upgrade the plan (Billing) and reopen the popover.

**Exports come back "degraded" (`altium_unreachable`).** Altium is not running, no project
is open/focused, or the bridge loop is not polling (see above). This is the designed
fallback, not a crash: Solus keeps working from the last committed/inline export
(`degraded` reason strings: `altium_unreachable`, `netlist_data_malformed`,
`artifact_write_failed`, `netlist_export_failed`).

**Altium crashed during a call.** Restart Altium, re-run **StartMCPServer**, note the tool
that triggered it (upstream's experimental-tools warning), and report it. Use design copies
for the write-tool steps.

## 6. What is safe to share with Solus support

Share freely — these never contain secret values by design:

- Companion log output and the Bridge popover's status/detail text (key NAMES only, e.g.
  "license stored (altium_license)").
- The checklist above with pass/fail notes, degraded `reason` strings, Altium version, and
  Windows version.
- Directory listings of `<workspace>\.eda-agent-ipc\` (file NAMES and timestamps).
- Altium's Messages-panel text for script compile/run errors.

Never share:

- Your license value itself, in any form — Solus support will never ask for it. If any log,
  screenshot, or message ever shows the actual value, stop and report THAT as a bug first.
- Design files or netlist contents, unless your team decides the design data itself may be
  shared for debugging.
