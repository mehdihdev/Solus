import { Card, FocusSummaryWidget, Mono } from '@solus/desktop'

const noop = (): void => {}

const ACTIONS = { refocus: noop, requestSolAction: noop }

const KNEE_MOTOR = {
  id: 'e-knee-motor',
  type: 'motor',
  domain: 'mechanical',
  name: 'knee_motor',
  source_key: 'onshape:ari-02:knee'
}

const DRIVER = {
  id: 'e-u4-drv8301',
  type: 'motor_driver',
  domain: 'electrical',
  name: 'DRV8301 (U4)',
  source_key: 'kicad:main-board:U4'
}

const NEIGHBORHOOD = {
  entities: [KNEE_MOTOR, DRIVER],
  edges: [
    { id: 'edge-1', type: 'drives', from_entity_id: DRIVER.id, to_entity_id: KNEE_MOTOR.id },
    {
      id: 'edge-2',
      type: 'connected_to',
      from_entity_id: DRIVER.id,
      to_entity_id: 'e-can-bus'
    }
  ],
  truncated: false
}

function Slot({ children }: { children: React.ReactNode }) {
  return (
    <Card style={{ width: 300 }}>
      <Mono>FOCUS SUMMARY</Mono>
      <div style={{ marginTop: 10 }}>{children}</div>
    </Card>
  )
}

export function Focused() {
  return (
    <Slot>
      <FocusSummaryWidget
        focus={{
          status: 'ready',
          focusedEntity: KNEE_MOTOR,
          neighborhood: NEIGHBORHOOD,
          error: null
        }}
        actions={ACTIONS}
      />
    </Slot>
  )
}

export function NothingFocused() {
  return (
    <Slot>
      <FocusSummaryWidget
        focus={{ status: 'idle', focusedEntity: null, neighborhood: null, error: null }}
        actions={ACTIONS}
      />
    </Slot>
  )
}

export function NeighbourhoodFailed() {
  return (
    <Slot>
      <FocusSummaryWidget
        focus={{
          status: 'error',
          focusedEntity: KNEE_MOTOR,
          neighborhood: null,
          error: 'The Onshape source has not synced since the chassis was renamed.'
        }}
        actions={ACTIONS}
      />
    </Slot>
  )
}
