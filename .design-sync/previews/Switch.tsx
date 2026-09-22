import { Card, Mono, Row, Section, Switch } from '@solus/desktop'

const noop = (): void => {}
const row = { display: 'flex', gap: 18, alignItems: 'center', flexWrap: 'wrap' } as const
const cap = { fontSize: 11.5, color: 'var(--mut)', marginTop: 6 } as const

export function States() {
  return (
    <div style={row}>
      <div>
        <Switch checked onChange={noop} ariaLabel="Explain warnings inline" />
        <div style={cap}>On</div>
      </div>
      <div>
        <Switch checked={false} onChange={noop} ariaLabel="Auto-flash on commit" />
        <div style={cap}>Off</div>
      </div>
      <div>
        <Switch checked disabled onChange={noop} ariaLabel="Team telemetry sharing" />
        <div style={cap}>On · disabled</div>
      </div>
      <div>
        <Switch checked={false} disabled onChange={noop} ariaLabel="Self-hosted sync" />
        <div style={cap}>Off · disabled</div>
      </div>
    </div>
  )
}

export function InSettings() {
  return (
    <div style={{ width: 460 }}>
      <Section title="Robotics Autocomplete" sub="Proactive cross-domain warnings as you work.">
        <Row label="Warn on I²C address collisions">
          <Switch checked onChange={noop} ariaLabel="Warn on I2C address collisions" />
        </Row>
        <Row label="Warn on power budget overruns">
          <Switch checked onChange={noop} ariaLabel="Warn on power budget overruns" />
        </Row>
        <Row label="Warn on CAD/enclosure interference">
          <Switch checked={false} onChange={noop} ariaLabel="Warn on CAD interference" />
        </Row>
        <Row label="Warn on CUDA / JetPack mismatches">
          <Switch checked onChange={noop} ariaLabel="Warn on CUDA mismatches" />
        </Row>
      </Section>
    </div>
  )
}

export function Deployment() {
  return (
    <Card style={{ width: 400 }}>
      <Mono>DEPLOY · ARI-02</Mono>
      <div style={{ marginTop: 10 }}>
        <Row label="Confirm before flashing firmware">
          <Switch checked onChange={noop} ariaLabel="Confirm before flashing firmware" />
        </Row>
        <Row label="Run system proving before deploy">
          <Switch checked onChange={noop} ariaLabel="Run system proving before deploy" />
        </Row>
        <Row label="Deploy to Jetson over SSH">
          <Switch
            checked={false}
            disabled
            onChange={noop}
            ariaLabel="Deploy to Jetson over SSH"
          />
        </Row>
      </div>
      <div style={{ fontSize: 11.5, color: 'var(--mut)', marginTop: 10, lineHeight: 1.5 }}>
        SSH deploys need a reachable target — ari-02.local last answered 2 days ago.
      </div>
    </Card>
  )
}
