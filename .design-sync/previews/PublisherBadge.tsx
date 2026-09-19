import { ExtensionIconTile, PublisherBadge } from '@solus/desktop'

export function Verified() {
  return (
    <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
      <PublisherBadge publisher="Solus" verified />
      <PublisherBadge publisher="OmniVision Tools" verified />
      <PublisherBadge publisher="Ari Robotics" verified />
    </div>
  )
}

export function Community() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, width: 320 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 14, fontWeight: 600 }}>Telemetry Dashboard</span>
        <PublisherBadge publisher="bench-tools" verified={false} />
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 14, fontWeight: 600 }}>Harness Router</span>
        <PublisherBadge publisher="jshah" verified={false} />
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 14, fontWeight: 600 }}>Firmware Flasher</span>
        <PublisherBadge publisher="ari-lab" verified={false} />
      </div>
    </div>
  )
}

export function InCardTitle() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, width: 380 }}>
      <div style={{ display: 'flex', gap: 14, alignItems: 'flex-start' }}>
        <ExtensionIconTile size={36} />
        <div style={{ minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 14, fontWeight: 600 }}>KiCad Viewer</span>
            <PublisherBadge publisher="Solus" verified />
          </div>
          <div style={{ fontSize: 12, color: 'var(--mut)', marginTop: 4, lineHeight: 1.5 }}>
            Open the board and schematic of any EDA source beside the graph.
          </div>
        </div>
      </div>
      <div style={{ display: 'flex', gap: 14, alignItems: 'flex-start' }}>
        <ExtensionIconTile size={36} />
        <div style={{ minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 14, fontWeight: 600 }}>Telemetry Dashboard</span>
            <PublisherBadge publisher="bench-tools" verified={false} />
          </div>
          <div style={{ fontSize: 12, color: 'var(--mut)', marginTop: 4, lineHeight: 1.5 }}>
            Live signal tiles for Ari-02 — joint currents, bus voltage, ROS node health.
          </div>
        </div>
      </div>
    </div>
  )
}
