// Topbar bridge pill (SOLUSDEV-154 / BRG-03): a dot + label reflecting the
// local companion's state for the linked project, with a click popover listing
// each vendored MCP server. Design tokens only — no new colors.
import { useState } from 'react'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import type { BridgeStatus } from '../../lib/api/resources'
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
      {open && <BridgePopover status={status} onClose={() => setOpen(false)} />}
    </div>
  )
}

function BridgePopover({
  status,
  onClose
}: {
  status: BridgeStatus | null
  onClose: () => void
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
            </div>
          ))}
      </Card>
    </div>
  )
}
