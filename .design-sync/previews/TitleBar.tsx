import { Mono, SolusLogo, TitleBar } from '@solus/desktop'

const pill = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 9,
  padding: '5px 10px',
  border: '1px solid var(--bd)',
  borderRadius: 4,
  background: 'var(--sur)',
  fontSize: 12.5
} as const

const frame = { width: 620, border: '1px solid var(--bd)', borderRadius: 4, overflow: 'hidden' } as const

export function ProjectPill() {
  return (
    <div style={frame}>
      <TitleBar>
        <span style={pill}>
          <SolusLogo size={15} />
          Ari-02 · Perception stack
          <Mono size={9}>SWITCH</Mono>
        </span>
      </TitleBar>
    </div>
  )
}

export function SyncingProject() {
  return (
    <div style={frame}>
      <TitleBar>
        <span style={pill}>
          <SolusLogo size={15} />
          Ari-02 · Perception stack
        </span>
        <Mono size={9.5} color="var(--warn)" style={{ marginLeft: 12 }}>
          SYNCING KICAD · 148 ENTITIES
        </Mono>
      </TitleBar>
    </div>
  )
}

export function NoProject() {
  return (
    <div style={frame}>
      <TitleBar>
        <span style={{ ...pill, color: 'var(--mut)' }}>
          <SolusLogo size={15} />
          No project open
        </span>
      </TitleBar>
    </div>
  )
}
