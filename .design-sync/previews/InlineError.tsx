import { Button, Card, Field, InlineError, Mono, Row, Section, Switch } from '@solus/desktop'

const noop = (): void => {}

export function SyncFailure() {
  return (
    <div style={{ width: 460 }}>
      <Section title="GitHub" sub="solus-robotics/ari-firmware · branch main">
        <Row label="Sync on every push">
          <Switch checked onChange={noop} ariaLabel="Sync on every push" />
        </Row>
        <InlineError message="Sync failed: the GitHub token no longer has access to solus-robotics/ari-firmware. Reconnect the source." />
      </Section>
    </div>
  )
}

export function FormError() {
  return (
    <Card pad={20} style={{ width: 400 }}>
      <Mono>INVITE A TEAMMATE</Mono>
      <div style={{ marginTop: 12 }}>
        <Field label="Email" value="nav@solus" onChange={noop} placeholder="name@team.dev" />
      </div>
      <InlineError message="Enter a valid email address." />
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 14 }}>
        <Button kind="primary" size="sm">
          Send invite
        </Button>
      </div>
    </Card>
  )
}

export function EnvelopeMessages() {
  return (
    <Card pad={20} style={{ width: 460 }}>
      <Mono>ERROR ENVELOPES FROM THE API</Mono>
      <InlineError message="You do not have permission to disconnect this source — ask a team owner." />
      <InlineError message="Onshape rejected the request: document Ari chassis v4 is checked out by another user." />
      <InlineError message="Flash aborted: /dev/ttyACM0 is busy. Close the serial monitor and retry." />
    </Card>
  )
}

export function Resolved() {
  return (
    <Card pad={20} style={{ width: 460 }}>
      <Mono>ONSHAPE · ARI CHASSIS V4</Mono>
      <div style={{ marginTop: 12 }}>
        <Row label="Last sync">just now</Row>
        <Row label="Parts ingested">148</Row>
      </div>
      <InlineError message={null} />
      <div style={{ marginTop: 12 }}>
        <Mono color="var(--ok)">NO ERRORS</Mono>
      </div>
    </Card>
  )
}
