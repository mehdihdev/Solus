import { Mono, PageIconTile } from '@solus/desktop'

const BOARD_ICON =
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6" rx="1"/><line x1="9" y1="2" x2="9" y2="4"/><line x1="15" y1="2" x2="15" y2="4"/><line x1="9" y1="20" x2="9" y2="22"/><line x1="15" y1="20" x2="15" y2="22"/><line x1="2" y1="9" x2="4" y2="9"/><line x1="2" y1="15" x2="4" y2="15"/><line x1="20" y1="9" x2="22" y2="9"/><line x1="20" y1="15" x2="22" y2="15"/></svg>'

function Sample({ label, children }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
      {children}
      <Mono size={9}>{label}</Mono>
    </div>
  )
}

export function WithManifestIcon() {
  return (
    <div style={{ display: 'flex', gap: 18, alignItems: 'flex-end' }}>
      <Sample label="20px">
        <PageIconTile svg={BOARD_ICON} size={20} />
      </Sample>
      <Sample label="24px">
        <PageIconTile svg={BOARD_ICON} size={24} />
      </Sample>
      <Sample label="32px">
        <PageIconTile svg={BOARD_ICON} size={32} />
      </Sample>
      <Sample label="44px">
        <PageIconTile svg={BOARD_ICON} size={44} />
      </Sample>
    </div>
  )
}

export function FallbackGlyph() {
  return (
    <div style={{ display: 'flex', gap: 18, alignItems: 'flex-end' }}>
      <Sample label="no icon · 24px">
        <PageIconTile svg={null} size={24} />
      </Sample>
      <Sample label="no icon · 32px">
        <PageIconTile svg={null} size={32} />
      </Sample>
      <Sample label="no icon · 44px">
        <PageIconTile svg={null} size={44} />
      </Sample>
    </div>
  )
}

export function InHeaderRow() {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, width: 340 }}>
      <PageIconTile svg={BOARD_ICON} />
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 14.5, fontWeight: 600 }}>KiCad Viewer</div>
        <Mono size={9.5} style={{ textTransform: 'none' }}>
          by Solus · v2.1.0
        </Mono>
      </div>
    </div>
  )
}
