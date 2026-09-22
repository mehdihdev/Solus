import { ExtensionIconTile, Mono, PublisherBadge } from '@solus/desktop'

export function Sizes() {
  return (
    <div style={{ display: 'flex', gap: 16, alignItems: 'flex-end' }}>
      {[24, 32, 36, 48].map((size) => (
        <div
          key={size}
          style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}
        >
          <ExtensionIconTile size={size} />
          <Mono size={9}>{`${size}px`}</Mono>
        </div>
      ))}
    </div>
  )
}

export function ListRowSize() {
  return (
    <div style={{ display: 'flex', gap: 12, alignItems: 'center', width: 360 }}>
      <ExtensionIconTile size={32} />
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600 }}>KiCad Viewer</div>
        <div style={{ fontSize: 12, color: 'var(--mut)', marginTop: 2 }}>
          Open the board beside the graph.
        </div>
      </div>
    </div>
  )
}

export function CardRowSize() {
  return (
    <div style={{ display: 'flex', gap: 14, alignItems: 'flex-start', width: 360 }}>
      <ExtensionIconTile size={36} />
      <div style={{ minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 14, fontWeight: 600 }}>BOM</span>
          <PublisherBadge publisher="Solus" verified />
        </div>
        <div style={{ fontSize: 12, color: 'var(--mut)', marginTop: 4, lineHeight: 1.5 }}>
          Bill of materials from your EDA project, priced against Octopart.
        </div>
      </div>
    </div>
  )
}
