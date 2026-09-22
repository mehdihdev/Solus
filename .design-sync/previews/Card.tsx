import { Button, Card, DomainChip, KV, Mono, Spark } from '@solus/desktop'

const noop = (): void => {}
const title = { fontSize: 14, fontWeight: 600, color: 'var(--tx)' } as const
const body = { fontSize: 12.5, color: 'var(--mut)', lineHeight: 1.5 } as const

export function SourceCard() {
  return (
    <Card style={{ width: 340 }}>
      <Mono>GITHUB SOURCE</Mono>
      <div style={{ ...title, marginTop: 8 }}>ari-robotics/ari-firmware</div>
      <div style={{ ...body, marginTop: 6 }}>
        Synced 4 minutes ago · 212 entities, 388 relations.
      </div>
      <div style={{ marginTop: 12 }}>
        <KV k="Branch" v="main" />
        <KV k="Last commit" v="a91f3c2 — bump IMU driver" />
        <KV k="Checks" v="3 open warnings" vColor="var(--warn)" />
      </div>
    </Card>
  )
}

export function Clickable() {
  return (
    <Card style={{ width: 300 }} onClick={noop}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <DomainChip d="ee" small />
        <DomainChip d="rt" small />
      </div>
      <div style={{ ...title, marginTop: 10 }}>I²C address conflict</div>
      <div style={{ ...body, marginTop: 6 }}>
        IMU_BNO085 and the OV9281 EEPROM both answer at 0x28 on bus i2c-1.
      </div>
    </Card>
  )
}

export function Padding() {
  return (
    <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start', flexWrap: 'wrap' }}>
      <Card pad={8} style={{ width: 150 }}>
        <Mono size={9}>PAD 8</Mono>
        <div style={{ ...body, marginTop: 6 }}>Telemetry tile</div>
      </Card>
      <Card pad={16} style={{ width: 150 }}>
        <Mono size={9}>PAD 16</Mono>
        <div style={{ ...body, marginTop: 6 }}>Default surface</div>
      </Card>
      <Card pad={24} style={{ width: 170 }}>
        <Mono size={9}>PAD 24</Mono>
        <div style={{ ...body, marginTop: 6 }}>Settings panel</div>
      </Card>
    </div>
  )
}

export function WithActions() {
  return (
    <Card style={{ width: 360 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Mono>ONSHAPE · ARI CHASSIS V4</Mono>
        <Spark values={[3.1, 3.4, 3.2, 3.9, 4.4, 4.1, 4.8, 5.2]} w={90} h={22} />
      </div>
      <div style={{ ...body, marginTop: 10 }}>
        Mass properties last read 12 minutes ago. 41 parts mapped to graph entities.
      </div>
      <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
        <Button kind="primary" size="sm">Sync now</Button>
        <Button kind="ghost" size="sm">Open in Onshape</Button>
      </div>
    </Card>
  )
}

export function Nested() {
  return (
    <Card style={{ width: 360 }} pad={16}>
      <Mono>SYSTEM PROVING · ARI-02</Mono>
      <div style={{ display: 'grid', gap: 10, marginTop: 12 }}>
        <Card pad={12} style={{ background: 'var(--sur2)' }}>
          <KV k="Power budget" v="8.4 W of 12 W" vColor="var(--ok)" />
        </Card>
        <Card pad={12} style={{ background: 'var(--sur2)' }}>
          <KV k="Pin assignments" v="2 collisions" vColor="var(--err)" />
        </Card>
        <Card pad={12} style={{ background: 'var(--sur2)' }}>
          <KV k="CUDA runtime" v="11.8 — needs 12" vColor="var(--warn)" />
        </Card>
      </div>
    </Card>
  )
}
