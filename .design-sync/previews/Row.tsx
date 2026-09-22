import { Button, Card, DomainChip, Mono, Row, Section, Segmented, Switch } from '@solus/desktop'

const noop = (): void => {}

export function DeploymentRows() {
  return (
    <div style={{ width: 470 }}>
      <Section title="Deployment" sub="Where firmware goes when you press Flash.">
        <Row label="Default target">
          <Segmented options={['Arduino', 'Jetson', 'Pi'] as const} value="Jetson" onChange={noop} size="sm" />
        </Row>
        <Row label="Prove the system before flashing">
          <Switch checked onChange={noop} ariaLabel="Prove the system before flashing" />
        </Row>
        <Row label="Ari-02 · jetson-orin-nx.local">
          <Mono color="var(--ok)">REACHABLE</Mono>
        </Row>
        <Row label="CUDA on target">
          <Mono color="var(--err)">11.8 — NEEDS 12</Mono>
        </Row>
      </Section>
    </div>
  )
}

export function ValueRows() {
  return (
    <Card pad={20} style={{ width: 470 }}>
      <Mono>ARI-02 · GRAPH SUMMARY</Mono>
      <div style={{ marginTop: 14 }}>
        <Row label="Entities">1,284</Row>
        <Row label="Relations">3,061</Row>
        <Row label="Unresolved fingerprints">
          <span style={{ color: 'var(--warn)' }}>7 proposed matches</span>
        </Row>
        <Row label="Last full sync">2 minutes ago</Row>
      </div>
    </Card>
  )
}

export function ChipAndActionRows() {
  return (
    <div style={{ width: 470 }}>
      <Section title="Sources" sub="Each connector writes entities and relations into the graph.">
        <Row
          label={
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
              <DomainChip d="sw" small /> solus-robotics/ari-firmware
            </span>
          }
        >
          <Button kind="bare" size="sm">
            Sync now
          </Button>
        </Row>
        <Row
          label={
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
              <DomainChip d="ee" small /> main-board.kicad_pcb
            </span>
          }
        >
          <Button kind="bare" size="sm">
            Sync now
          </Button>
        </Row>
        <Row
          label={
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
              <DomainChip d="me" small /> Ari chassis v4
            </span>
          }
        >
          <Button kind="bare" size="sm">
            Sync now
          </Button>
        </Row>
      </Section>
    </div>
  )
}
