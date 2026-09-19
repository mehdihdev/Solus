import { Mono, ModeBadge } from '@solus/desktop'

const noop = (): void => {}

const row = { display: 'flex', gap: 10, alignItems: 'center' } as const

export function GuideMode() {
  return (
    <div style={row}>
      <ModeBadge mode="guide" onChange={noop} />
      <Mono size={9}>SOL EXPLAINS BEFORE IT ACTS</Mono>
    </div>
  )
}

export function BuildMode() {
  return (
    <div style={row}>
      <ModeBadge mode="do" onChange={noop} />
      <Mono size={9}>SOL EDITS AND FLASHES ON CONFIRM</Mono>
    </div>
  )
}

export function InWindowHeader() {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 12,
        width: 340,
        padding: '8px 10px',
        background: 'var(--sur)',
        border: '1px solid var(--bd)',
        borderRadius: 4
      }}
    >
      <Mono size={9}>SOL · ARI-02</Mono>
      <ModeBadge mode="guide" onChange={noop} />
    </div>
  )
}
