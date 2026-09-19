import { Button } from '@solus/desktop'

const row = { display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' } as const

export function Kinds() {
  return (
    <div style={row}>
      <Button kind="primary">Connect source</Button>
      <Button kind="ghost">Open in KiCad</Button>
      <Button kind="soft">Re-run checks</Button>
      <Button kind="danger">Delete robot</Button>
      <Button kind="bare">Cancel</Button>
    </div>
  )
}

export function Sizes() {
  return (
    <div style={row}>
      <Button kind="primary" size="sm">Sync</Button>
      <Button kind="primary" size="md">Sync now</Button>
      <Button kind="primary" size="lg">Prove the system</Button>
    </div>
  )
}

export function Disabled() {
  return (
    <div style={row}>
      <Button kind="primary" disabled>Flash firmware</Button>
      <Button kind="ghost" disabled>Deploy to Jetson</Button>
      <Button kind="danger" disabled>Disconnect</Button>
    </div>
  )
}
