import { Button, Card, Mono, Spinner } from '@solus/desktop'

const row = { display: 'flex', gap: 10, alignItems: 'flex-end', flexWrap: 'wrap' } as const
const buttons = { display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' } as const
const cap = { fontSize: 11, color: 'var(--mut)', marginTop: 8 } as const
const col = {
  width: 70,
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
  justifyContent: 'flex-end',
  height: 46
} as const
const line = { display: 'flex', gap: 10, alignItems: 'center', padding: '7px 0' } as const
const text = { fontSize: 12.5, color: 'var(--tx)' } as const

export function Sizes() {
  return (
    <div style={row}>
      <div style={col}>
        <Spinner size={11} />
        <div style={cap}>11</div>
      </div>
      <div style={col}>
        <Spinner size={14} />
        <div style={cap}>14 · default</div>
      </div>
      <div style={col}>
        <Spinner size={20} />
        <div style={cap}>20</div>
      </div>
      <div style={col}>
        <Spinner size={32} />
        <div style={cap}>32</div>
      </div>
    </div>
  )
}

export function Colors() {
  return (
    <div style={row}>
      <div style={col}>
        <Spinner size={22} color="var(--acc)" />
        <div style={cap}>accent</div>
      </div>
      <div style={col}>
        <Spinner size={22} color="var(--ok)" />
        <div style={cap}>ok</div>
      </div>
      <div style={col}>
        <Spinner size={22} color="var(--warn)" />
        <div style={cap}>warn</div>
      </div>
      <div style={col}>
        <Spinner size={22} color="var(--err)" />
        <div style={cap}>err</div>
      </div>
      <div style={col}>
        <Spinner size={22} color="var(--mut)" />
        <div style={cap}>muted</div>
      </div>
    </div>
  )
}

export function SyncingSources() {
  return (
    <Card style={{ width: 360 }}>
      <Mono>SYNCING ARI-02</Mono>
      <div style={{ marginTop: 10 }}>
        <div style={line}>
          <Spinner size={13} />
          <span style={text}>KiCad — parsing main-board.kicad_pcb</span>
        </div>
        <div style={line}>
          <Spinner size={13} />
          <span style={text}>Onshape — reading mass properties</span>
        </div>
        <div style={line}>
          <Spinner size={13} color="var(--mut)" />
          <span style={{ ...text, color: 'var(--mut)' }}>ROS — queued</span>
        </div>
      </div>
    </Card>
  )
}

export function InButtons() {
  return (
    <div style={buttons}>
      <Button kind="primary" disabled>
        <span style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
          <Spinner size={11} color="var(--acc-ink)" /> Flashing…
        </span>
      </Button>
      <Button kind="ghost" disabled>
        <span style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
          <Spinner size={11} /> Proving system…
        </span>
      </Button>
    </div>
  )
}
