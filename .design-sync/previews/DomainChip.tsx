import { Card, DomainChip, KV, Mono } from '@solus/desktop'

const noop = (): void => {}
const row = { display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' } as const

export function Domains() {
  return (
    <div style={row}>
      <DomainChip d="sw" />
      <DomainChip d="ee" />
      <DomainChip d="me" />
      <DomainChip d="rt" />
    </div>
  )
}

export function FilterBar() {
  return (
    <div style={row}>
      <DomainChip d="sw" on onClick={noop} />
      <DomainChip d="ee" on onClick={noop} />
      <DomainChip d="me" on={false} onClick={noop} />
      <DomainChip d="rt" on={false} onClick={noop} />
    </div>
  )
}

export function Small() {
  return (
    <div style={row}>
      <DomainChip d="sw" small />
      <DomainChip d="ee" small />
      <DomainChip d="me" small />
      <DomainChip d="rt" small />
      <DomainChip d="me" small on={false} />
    </div>
  )
}

export function OnEntityCard() {
  return (
    <Card style={{ width: 340 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Mono>GRAPH ENTITY</Mono>
        <div style={{ display: 'flex', gap: 6 }}>
          <DomainChip d="ee" small />
          <DomainChip d="rt" small />
        </div>
      </div>
      <div style={{ fontSize: 14, fontWeight: 600, marginTop: 8 }}>OV9281_IC</div>
      <div style={{ marginTop: 12 }}>
        <KV k="Source" v="main-board.kicad_pcb" />
        <KV k="Bus" v="i2c-1 @ 0x60" />
        <KV k="Drives" v="camera_node (ROS)" />
      </div>
    </Card>
  )
}

export function CrossDomainWarning() {
  return (
    <Card style={{ width: 380 }}>
      <div style={row}>
        <DomainChip d="me" small />
        <span style={{ fontSize: 11, color: 'var(--mut)' }}>blocks</span>
        <DomainChip d="ee" small />
      </div>
      <div style={{ fontSize: 13, color: 'var(--tx)', marginTop: 10, lineHeight: 1.5 }}>
        The rear casing sweep intersects the USB-C port on main-board.kicad_pcb by 2.4 mm.
      </div>
    </Card>
  )
}
