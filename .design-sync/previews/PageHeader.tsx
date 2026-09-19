import { Button, PageHeader } from '@solus/desktop'

const noop = (): void => {}

const BOM_ICON =
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="9" x2="9" y2="21"/></svg>'

const shell = {
  width: 520,
  border: '1px solid var(--bd)',
  borderRadius: 4,
  overflow: 'hidden'
} as const

export function VerifiedPublisher() {
  return (
    <div style={shell}>
      <PageHeader
        name="BOM"
        iconSvg={BOM_ICON}
        isDev={false}
        version="1.2.0"
        publisher={{ displayName: 'Solus', verified: true }}
      />
    </div>
  )
}

export function CommunityPublisher() {
  return (
    <div style={shell}>
      <PageHeader
        name="Telemetry Dashboard"
        iconSvg={null}
        isDev={false}
        version="0.4.2"
        publisher={{ displayName: 'bench-tools', verified: false }}
      />
    </div>
  )
}

export function DevRegistration() {
  return (
    <div style={shell}>
      <PageHeader
        name="Harness Router"
        iconSvg={null}
        isDev
        version="dev"
        publisher={{ displayName: 'Ari Robotics', verified: false }}
      />
    </div>
  )
}

export function WithBackAndActions() {
  return (
    <div style={shell}>
      <PageHeader
        name="KiCad Viewer"
        iconSvg={BOM_ICON}
        isDev={false}
        version="2.1.0"
        publisher={{ displayName: 'Solus', verified: true }}
        onBack={noop}
        actions={
          <Button size="sm" kind="ghost">
            Open in window ↗
          </Button>
        }
      />
    </div>
  )
}

export function LongName() {
  return (
    <div style={{ ...shell, width: 320 }}>
      <PageHeader
        name="Wire Harness Clearance Inspector"
        iconSvg={BOM_ICON}
        isDev
        version="dev"
        publisher={{ displayName: 'Ari Robotics', verified: false }}
        onBack={noop}
      />
    </div>
  )
}
