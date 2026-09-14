// Topbar bridge pill (SOLUSDEV-154 / BRG-03): a dot + label reflecting the
// local companion's state for the linked project, with a click popover listing
// each vendored MCP server. Design tokens only — no new colors.
import { useState } from 'react'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import type { BridgeServer, BridgeStatus } from '../../lib/api/resources'
import { isPlatformUnavailableDetail } from '../project/localconnections/presentation'
import { LicenseCaptureModal } from './LicenseCaptureModal'
import { useBridgeStatus, pillState, type BridgePillState } from './useBridgeStatus'

const PILL_LABELS: Readonly<Record<BridgePillState, string>> = {
  offline: 'Bridge offline',
  ready: 'Bridge',
  busy: 'Bridge busy',
  attention: 'Bridge attention'
}

const PILL_COLORS: Readonly<Record<BridgePillState, string>> = {
  offline: 'var(--mut)',
  ready: 'var(--ok)',
  busy: 'var(--acc)',
  attention: 'var(--warn)'
}

export function BridgePill({ projectId }: { projectId: string | null }): React.JSX.Element {
  const status = useBridgeStatus(projectId)
  const state = pillState(status)
  const [open, setOpen] = useState(false)
  // MCP-05: the license modal outlives the popover (held here, not inside it).
  const [licenseServer, setLicenseServer] = useState<string | null>(null)
  return (
    <div style={{ position: 'relative' }}>
      <div
        data-testid="bridge-pill"
        title="Local bridge"
        onClick={(e) => {
          e.stopPropagation()
          setOpen((o) => !o)
        }}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 7,
          padding: '4px 10px',
          background: 'var(--sur)',
          border: '1px solid var(--bd)',
          borderRadius: 99,
          cursor: 'pointer'
        }}
      >
        <span style={{ width: 7, height: 7, borderRadius: 99, background: PILL_COLORS[state] }} />
        <span style={{ fontSize: 11, color: 'var(--mut)' }}>{PILL_LABELS[state]}</span>
      </div>
      {open && (
        <BridgePopover
          status={status}
          onClose={() => setOpen(false)}
          onAddLicense={(server) => {
            setOpen(false)
            setLicenseServer(server)
          }}
        />
      )}
      {licenseServer !== null && (
        <LicenseCaptureModal server={licenseServer} onClose={() => setLicenseServer(null)} />
      )}
    </div>
  )
}

function BridgePopover({
  status,
  onClose,
  onAddLicense
}: {
  status: BridgeStatus | null
  onClose: () => void
  onAddLicense: (server: string) => void
}): React.JSX.Element {
  return (
    <div
      style={{ position: 'absolute', top: 34, right: 0, width: 300, zIndex: 50 }}
      onClick={(e) => e.stopPropagation()}
    >
      <Card pad={0} style={{ boxShadow: '0 16px 50px rgba(0,0,0,0.5)' }}>
        <div
          style={{
            padding: '11px 14px',
            borderBottom: '1px solid var(--bd)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center'
          }}
        >
          <Mono size={9.5}>LOCAL BRIDGE</Mono>
          {status?.companion_version && (
            <Mono size={9.5} style={{ textTransform: 'none' }}>
              v{status.companion_version}
            </Mono>
          )}
        </div>
        {!status?.connected && (
          <div style={{ padding: '16px 14px', fontSize: 11, color: 'var(--mut)', lineHeight: 1.5 }}>
            The local companion isn&apos;t connected. Local tools (KiCad, files, serial) are
            unavailable until it comes back.
          </div>
        )}
        {status?.connected && status.servers.length === 0 && (
          <div style={{ padding: '16px 14px', fontSize: 11, color: 'var(--mut)' }}>
            Connected — no local servers reported yet.
          </div>
        )}
        {status?.connected &&
          status.servers.map((s) => (
            <div
              key={s.name}
              onClick={onClose}
              style={{
                display: 'flex',
                gap: 10,
                alignItems: 'baseline',
                padding: '10px 14px',
                borderBottom: '1px solid var(--bd)',
                fontSize: 11.5
              }}
            >
              <span style={{ fontWeight: 600 }}>{s.name}</span>
              <Mono size={9}>{s.state}</Mono>
              {s.detail && (
                <span style={{ color: 'var(--mut)', flex: 1, minWidth: 0 }}>{s.detail}</span>
              )}
              {!(s.state === 'not_launched' && isPlatformUnavailableDetail(s.detail)) && (
                <LicenseAffordance state={s.license_state} onAdd={() => onAddLicense(s.name)} />
              )}
            </div>
          ))}
      </Card>
    </div>
  )
}

/** MCP-05 BYO-license surface per row: an "Add license" button when the user
 *  should bring their own license, a non-interactive upgrade note when the
 *  plan does not cover byo tools, nothing when ready. */
function LicenseAffordance({
  state,
  onAdd
}: {
  state: BridgeServer['license_state']
  onAdd: () => void
}): React.JSX.Element | null {
  if (state === 'upgrade_required') {
    return (
      <span style={{ marginLeft: 'auto', color: 'var(--warn)', fontSize: 10.5 }}>
        Upgrade required
      </span>
    )
  }
  if (state !== 'bring_your_license') return null
  return (
    <button
      onClick={(e) => {
        e.stopPropagation()
        onAdd()
      }}
      style={{
        marginLeft: 'auto',
        background: 'transparent',
        color: 'var(--acc)',
        border: '1px solid var(--bd)',
        borderRadius: 3,
        padding: '2px 8px',
        fontSize: 10.5,
        cursor: 'pointer'
      }}
    >
      Add license
    </button>
  )
}
