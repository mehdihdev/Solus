import { Button, FrameCard } from '@solus/desktop'

const noop = (): void => {}

const frame = {
  width: 460,
  height: 230,
  display: 'flex',
  flexDirection: 'column',
  border: '1px solid var(--bd)',
  borderRadius: 4,
  overflow: 'hidden'
} as const

export function LoadError() {
  return (
    <div style={frame}>
      <FrameCard
        tone="error"
        title="BOM could not be loaded"
        detail="The bundle for version 1.2.0 failed its content-hash check, so Solus refused to run it."
        onRetry={noop}
      />
    </div>
  )
}

export function Blocked() {
  return (
    <div style={frame}>
      <FrameCard
        tone="blocked"
        title="Firmware Flasher is blocked for this team"
        detail="A workspace admin blocked this extension. Ask them to allow it before it can run here."
      />
    </div>
  )
}

export function Disabled() {
  return (
    <div style={frame}>
      <FrameCard
        tone="disabled"
        title="Telemetry Dashboard is turned off"
        detail="This extension is installed on Ari-02 but disabled, so its widget and page do not run."
        actions={
          <Button size="sm" kind="primary">
            Enable
          </Button>
        }
      />
    </div>
  )
}

export function DevRequestPath() {
  return (
    <div style={frame}>
      <FrameCard
        tone="error"
        title="Dev registration did not answer"
        detail="Solus could not reach the folder this extension is loaded from on this computer."
        requestPath="http://127.0.0.1:5174/extensions/harness-router/page.html"
        onRetry={noop}
        retryLabel="Reload extension"
      />
    </div>
  )
}
