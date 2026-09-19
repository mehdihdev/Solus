import { Button, ScreenEmptyState } from '@solus/desktop'

const screen = {
  display: 'flex',
  flexDirection: 'column',
  height: 420,
  width: 620,
  border: '1px solid var(--bd)',
  borderRadius: 4,
  background: 'var(--sur)'
} as const

export function BenchNoDevice() {
  return (
    <div style={screen}>
      <ScreenEmptyState
        title="Live Bench watches the focused part"
        body="Select an entity in the Workspace — its telemetry signals, anomaly flags, and observer events stream here from the robot or from the MuJoCo sim."
        status="NO DEVICE CONNECTED"
      />
    </div>
  )
}

export function WithActions() {
  return (
    <div style={screen}>
      <ScreenEmptyState
        title="Nothing in the graph yet"
        body="Connect GitHub, KiCad, Onshape, or a ROS workspace and Solus builds Ari-02's entities and relations from what is already in your tools."
        status="0 ENTITIES · 0 RELATIONS"
      >
        <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
          <Button kind="primary" size="sm">
            Connect a source
          </Button>
          <Button kind="ghost" size="sm">
            Browse the Store
          </Button>
        </div>
      </ScreenEmptyState>
    </div>
  )
}

export function NoProject() {
  return (
    <div style={screen}>
      <ScreenEmptyState
        title="Open a project to see the graph"
        body="Every entity, relation, and check belongs to a project. Open Ari-02 or create a new one to begin."
      />
    </div>
  )
}
