import { FrameSkeleton, PageHeader } from '@solus/desktop'

const frame = {
  width: 440,
  height: 200,
  display: 'flex',
  flexDirection: 'column',
  border: '1px solid var(--bd)',
  borderRadius: 4,
  overflow: 'hidden'
} as const

export function Downloading() {
  return (
    <div style={frame}>
      <FrameSkeleton text="Downloading BOM 1.2.0…" />
    </div>
  )
}

export function Handshake() {
  return (
    <div style={frame}>
      <FrameSkeleton text="Starting KiCad Viewer…" />
    </div>
  )
}

export function InPageChrome() {
  return (
    <div style={frame}>
      <PageHeader
        name="Telemetry Dashboard"
        iconSvg={null}
        isDev={false}
        version="2.1.0"
        publisher={{ displayName: 'Solus', verified: true }}
      />
      <FrameSkeleton text="Connecting to Ari-02 telemetry…" />
    </div>
  )
}

export function WidgetSlotSize() {
  return (
    <div style={{ ...frame, width: 260, height: 140 }}>
      <FrameSkeleton text="Loading widget…" />
    </div>
  )
}
