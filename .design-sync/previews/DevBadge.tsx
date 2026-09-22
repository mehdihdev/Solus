import { Card, DevBadge, Mono, PageIconTile } from '@solus/desktop'

export function Badge() {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <span style={{ fontSize: 14.5, fontWeight: 600 }}>Harness Router</span>
      <DevBadge />
    </div>
  )
}

export function InRailRow() {
  return (
    <Card style={{ width: 320, display: 'flex', flexDirection: 'column', gap: 12 }}>
      <Mono size={9.5} ls="0.18em">
        Registered extensions
      </Mono>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <PageIconTile svg={null} size={22} />
        <span style={{ fontSize: 13, flex: 1 }}>BOM</span>
        <Mono size={9}>v1.2.0</Mono>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <PageIconTile svg={null} size={22} />
        <span style={{ fontSize: 13, flex: 1 }}>Harness Router</span>
        <DevBadge />
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <PageIconTile svg={null} size={22} />
        <span style={{ fontSize: 13, flex: 1 }}>URDF Inspector</span>
        <DevBadge />
      </div>
    </Card>
  )
}

export function BesideVersion() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 14.5, fontWeight: 600 }}>URDF Inspector</span>
        <DevBadge />
      </div>
      <Mono size={9.5} style={{ textTransform: 'none' }}>
        by Ari Robotics · dev
      </Mono>
    </div>
  )
}
