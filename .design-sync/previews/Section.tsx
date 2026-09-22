import { Button, Row, Section, Segmented, Switch } from '@solus/desktop'

const noop = (): void => {}

export function PreferencesSection() {
  return (
    <div style={{ width: 460 }}>
      <Section title="SOL" sub="How the agent talks to you across the workspace.">
        <Row label="Mode">
          <Segmented options={['Guide', 'Expert'] as const} value="Guide" onChange={noop} size="sm" />
        </Row>
        <Row label="Explain warnings inline">
          <Switch checked onChange={noop} ariaLabel="Explain warnings inline" />
        </Row>
        <Row label="Confirm before flashing">
          <Switch checked={false} onChange={noop} ariaLabel="Confirm before flashing" />
        </Row>
      </Section>
    </div>
  )
}

export function WithAction() {
  return (
    <div style={{ width: 460 }}>
      <Section title="Connected sources" sub="Solus syncs the graph from these tools.">
        <Row label="GitHub — solus-robotics/ari-firmware">
          <Button kind="bare" size="sm">Disconnect</Button>
        </Row>
        <Row label="Onshape — Ari chassis v4">
          <Button kind="bare" size="sm">Disconnect</Button>
        </Row>
        <Row label="KiCad — main-board.kicad_pcb">
          <Button kind="bare" size="sm">Disconnect</Button>
        </Row>
      </Section>
    </div>
  )
}
