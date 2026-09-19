import { Card, Mono, Row, Section, Segmented } from '@solus/desktop'

const noop = (): void => {}

export function SolMode() {
  return (
    <Segmented
      options={['Guide', 'Expert'] as const}
      value="Expert"
      onChange={noop}
      ariaLabel="Answer mode"
    />
  )
}

export function Sizes() {
  return (
    <div style={{ display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap' }}>
      <Segmented
        options={['Compact', 'Regular'] as const}
        value="Compact"
        onChange={noop}
        size="sm"
        ariaLabel="Density"
      />
      <Segmented
        options={['Sim', 'Real'] as const}
        value="Real"
        onChange={noop}
        size="md"
        ariaLabel="Live Bench mode"
      />
    </div>
  )
}

export function DomainFilter() {
  return (
    <Segmented
      options={['All', 'Software', 'Electrical', 'Mechanical', 'Runtime'] as const}
      value="Electrical"
      onChange={noop}
      size="sm"
      ariaLabel="Filter graph by domain"
    />
  )
}

export function InSettings() {
  return (
    <div style={{ width: 460 }}>
      <Section title="SOL" sub="How the agent talks to you across the workspace.">
        <Row label="Answer mode">
          <Segmented
            options={['Guide', 'Expert'] as const}
            value="Guide"
            onChange={noop}
            size="sm"
            ariaLabel="Answer mode"
          />
        </Row>
        <Row label="Action mode">
          <Segmented
            options={['Guide', 'Build'] as const}
            value="Build"
            onChange={noop}
            size="sm"
            ariaLabel="Action mode"
          />
        </Row>
        <Row label="Density">
          <Segmented
            options={['Compact', 'Regular'] as const}
            value="Regular"
            onChange={noop}
            size="sm"
            ariaLabel="Density"
          />
        </Row>
      </Section>
    </div>
  )
}

export function OnCardHeader() {
  return (
    <Card style={{ width: 400 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Mono>LIVE BENCH · ARI-02</Mono>
        <Segmented
          options={['Sim', 'Real'] as const}
          value="Sim"
          onChange={noop}
          size="sm"
          ariaLabel="Live Bench mode"
        />
      </div>
      <div style={{ fontSize: 12.5, color: 'var(--mut)', marginTop: 12, lineHeight: 1.5 }}>
        MuJoCo scene rebuilt from Onshape 12 minutes ago. 17 telemetry signals mapped.
      </div>
    </Card>
  )
}
