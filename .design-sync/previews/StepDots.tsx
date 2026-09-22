import { Button, Card, Mono, StepDots, Wordmark } from '@solus/desktop'

const stack = { display: 'flex', flexDirection: 'column', gap: 18 } as const

export function Progress() {
  return (
    <div style={stack}>
      <StepDots step={0} />
      <StepDots step={1} />
      <StepDots step={2} />
    </div>
  )
}

export function OnboardingHeader() {
  return (
    <div style={{ width: 560 }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '18px 24px',
          borderBottom: '1px solid var(--bd)'
        }}
      >
        <Wordmark size={14} />
        <StepDots step={1} />
        <Mono size={9.5}>NAV@SOLUS.DEV</Mono>
      </div>
    </div>
  )
}

export function InConnectStep() {
  return (
    <Card pad={22} style={{ width: 460 }}>
      <StepDots step={1} />
      <div style={{ fontSize: 16, fontWeight: 600, marginTop: 18 }}>Connect your first source</div>
      <div style={{ fontSize: 12.5, color: 'var(--mut)', marginTop: 6, lineHeight: 1.6 }}>
        Point Solus at the GitHub repo, KiCad project, or Onshape document behind Ari-02 and it
        builds the graph from what is already there.
      </div>
      <div style={{ display: 'flex', gap: 8, marginTop: 18 }}>
        <Button kind="primary" size="sm">
          Connect GitHub
        </Button>
        <Button kind="ghost" size="sm">
          Skip for now
        </Button>
      </div>
    </Card>
  )
}
