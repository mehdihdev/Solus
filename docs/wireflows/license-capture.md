# BYO-License Capture — Wireflow (SOLUSDEV-102 / MCP-05, ALT-9)

Customer-side capture of a bring-your-own license for a `byo_paid` MCP server
(worked example: `altium`, key name `altium_license`). Documents the flow
**exactly as implemented**. Cloud contract: `docs/contracts/bridge-protocol.md`
Addendum B (`status` / `license_state`) and Addendum C (`credential_submit` /
`credential_ack`).

## States (per server row in the Bridge popover)

`license_state` arrives on `GET /api/v1/projects/{id}/bridge` for every
connected server (`bridge.py::_license_states`):

| `license_state`      | meaning                                       | popover affordance                        |
| -------------------- | --------------------------------------------- | ----------------------------------------- |
| `ready`              | free tier, uncataloged, or fully licensed     | none (name + state + detail only)         |
| `bring_your_license` | byo_paid, plan-entitled, license keys missing | **Add license** button → capture modal    |
| `upgrade_required`   | byo_paid, plan not entitled                   | non-interactive **Upgrade required** note |

## Flow

1. **Bridge pill → popover** (`BridgePill.tsx`). Each connected server renders
   one row. A `bring_your_license` row shows the "Add license" button; clicking
   it closes the popover and opens the modal (modal state is held by the pill,
   so it outlives the popover).
2. **LicenseCaptureModal** (`LicenseCaptureModal.tsx`). One **masked**
   (`type="password"`) input per `license_secrets` key NAME. Key names are a
   client-side mirror of `MCP_SERVER_CATALOG` (`mcp_servers.py`) — the status
   endpoint does not send them; an unknown byo server degrades to an "update
   Solus" note with no submit. Values exist only in the modal's local React
   state: cleared on close, never in any Zustand store, never logged.
3. **Submit** → `window.solus.bridge.submitLicense(server, secrets)`
   (preload) → IPC `bridge:license` (main, own-renderer-gated) →
   `writeCredential` validates (string server; flat, non-empty
   string→string secrets; static error strings only) → one newline-terminated
   line on the companion's stdin:

   ```json
   {
     "type": "credential",
     "server": "altium",
     "secrets": { "altium_license": "<value>" }
   }
   ```

   Failure modes surfaced in the modal: `invalid server name` /
   `invalid secrets` / `companion not running` / `companion write failed`,
   or the desktop-app-required note outside Electron. Success shows the
   submitted key NAMES ("License submitted (altium_license)…").

4. **Companion relay** (`solus_companion/credentials.py`, wired via
   `config.apply_token_line` + `channel.py`). The stdin line is validated —
   known server from the DISCOVERED set, flat str→str secrets, exact field
   set, oversize refused before parsing (32 KiB raw-line guard) and against
   the Addendum C **16 KiB** control cap on the built frame — then queued
   (bounded, 8) and sent as **exactly one** frame per accepted line:

   ```json
   {
     "type": "credential_submit",
     "data": { "server": "altium", "secrets": { "altium_license": "<value>" } }
   }
   ```

   Malformed / oversize / unknown-server / backlog lines are dropped and
   counted (`CredentialRelay.dropped`), never raised on, never echoed.
   At-most-once: a frame lost to a dying socket is not re-queued.

5. **Cloud ack** (Addendum C). Exactly one per submit, key NAMES only:

   ```json
   {
     "type": "credential_ack",
     "data": {
       "server": "altium",
       "ok": true,
       "stored": ["altium_license"],
       "error": null
     }
   }
   ```

   The companion surfaces it on the server's existing status entry
   (`Supervisor.note_license_ack` → detail "license stored (altium_license)"
   or "license not stored: <reason>"), which rides the next `status` frame to
   the cloud and appears as the row's detail text in the popover.

6. **Confirmation loop**. The pill polls the bridge status every 10 s; once
   the cloud has stored the keys, `license_state` flips to `ready` and the
   affordance disappears. The renderer never receives the ack directly —
   stdin is one-way (renderer → … → companion), by design.

## Hygiene invariants (CLAUDE.md §7, tested with sentinel values)

- Secret VALUES appear in NO log record, console output, Zustand store,
  crash report, or persisted state, on any path — key NAMES only.
- The desktop main process never remembers or replays credentials (unlike
  the access token); the flow is renderer → preload → main → child stdin only.
- The ack and every status detail carry key NAMES only; values are
  write-only over the wire (no read-back).

## Windows launcher note (same ticket)

Catalog specs keep pointing at `bin/launch`; on win32 the companion resolves
the sibling `bin/launch.cmd` (the altium fork ships both) and fails closed
with a REFUSED log when it is absent. Executability is checked per-platform:
extension allowlist on Windows (`.cmd`/`.bat`/`.exe`/`.com` — `os.access
X_OK` is meaningless there), execute bit on POSIX. ADR-031 root confinement
applies to the resolved launcher unchanged.
