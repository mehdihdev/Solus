import { Card, Field, Mono } from '@solus/desktop'

const noop = (): void => {}
const box = { width: 380 } as const

export function SignIn() {
  return (
    <div style={box}>
      <Field
        label="EMAIL"
        type="email"
        value="priya@ari-robotics.dev"
        onChange={noop}
        placeholder="you@team.dev"
        autoComplete="email"
      />
      <Field
        label="PASSWORD"
        type="password"
        value="hunter-not-a-real-password"
        onChange={noop}
        placeholder="••••••••"
        autoComplete="current-password"
        onSubmit={noop}
      />
    </div>
  )
}

export function Empty() {
  return (
    <div style={box}>
      <Field
        label="ROBOT NAME"
        value=""
        onChange={noop}
        placeholder="Ari-02"
      />
      <Field
        label="ONSHAPE DOCUMENT URL"
        value=""
        onChange={noop}
        placeholder="https://cad.onshape.com/documents/…"
      />
    </div>
  )
}

export function WithError() {
  return (
    <div style={box}>
      <Field
        label="EMAIL"
        type="email"
        value="priya@ari-robotics"
        onChange={noop}
        error="That doesn't look like an email address."
      />
      <Field
        label="TEAM INVITE CODE"
        value="ARI-9F2X"
        onChange={noop}
        error="This invite expired on 12 May. Ask an admin for a new one."
      />
    </div>
  )
}

export function InCard() {
  return (
    <Card style={box}>
      <div style={{ marginBottom: 12 }}>
        <Mono>CONNECT A KICAD SOURCE</Mono>
      </div>
      <Field label="PROJECT LABEL" value="Ari main board" onChange={noop} />
      <Field
        label="BOARD FILE"
        value="hardware/main-board.kicad_pcb"
        onChange={noop}
        placeholder="path/to/board.kicad_pcb"
      />
      <Field
        label="NETLIST"
        value=""
        onChange={noop}
        placeholder="hardware/main-board.net"
      />
    </Card>
  )
}
