import { Card, Mono, Wordmark } from '@solus/desktop'

const noop = (): void => {}
const cap = { fontSize: 11, color: 'var(--mut)', marginTop: 8 } as const

export function Sizes() {
  return (
    <div style={{ display: 'grid', gap: 20, justifyItems: 'start' }}>
      <div>
        <Wordmark size={14} />
        <div style={cap}>14 · onboarding header</div>
      </div>
      <div>
        <Wordmark size={16} />
        <div style={cap}>16 · default, auth layout</div>
      </div>
      <div>
        <Wordmark size={24} />
        <div style={cap}>24 · landing hero</div>
      </div>
    </div>
  )
}

export function Clickable() {
  return (
    <div>
      <Wordmark size={18} onClick={noop} />
      <div style={cap}>Clicking the wordmark returns to the workspace home.</div>
    </div>
  )
}

export function AuthHeader() {
  return (
    <Card pad={24} style={{ width: 360 }}>
      <Wordmark size={16} onClick={noop} />
      <div style={{ marginTop: 22 }}>
        <Mono size={9.5}>SIGN IN TO YOUR TEAM</Mono>
      </div>
      <div style={{ fontSize: 12.5, color: 'var(--mut)', marginTop: 8, lineHeight: 1.5 }}>
        Solus keeps your robot&apos;s code, schematics, CAD and runtime in one graph.
      </div>
    </Card>
  )
}

export function OnSurface() {
  return (
    <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
      <Card pad={18} style={{ background: 'var(--bg)' }}>
        <Wordmark size={16} />
      </Card>
      <Card pad={18}>
        <Wordmark size={16} />
      </Card>
      <Card pad={18} style={{ background: 'var(--sur2)' }}>
        <Wordmark size={16} />
      </Card>
    </div>
  )
}
