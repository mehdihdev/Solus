import { Card, Mono, NeighborsWidget } from '@solus/desktop'

const noop = (): void => {}

const ACTIONS = { refocus: noop, requestSolAction: noop }

const DRIVER = {
  id: 'e-u4-drv8301',
  type: 'motor_driver',
  domain: 'electrical',
  name: 'DRV8301 (U4)',
  source_key: 'kicad:main-board:U4'
}

const NEIGHBOURS = [
  DRIVER,
  {
    id: 'e-knee-motor',
    type: 'motor',
    domain: 'mechanical',
    name: 'knee_motor',
    source_key: 'onshape:ari-02:knee'
  },
  {
    id: 'e-can-bus',
    type: 'bus',
    domain: 'electrical',
    name: 'CAN_BUS_1',
    source_key: 'kicad:main-board:net-can'
  },
  {
    id: 'e-motor-control',
    type: 'code_module',
    domain: 'code',
    name: 'motor_control.cpp',
    source_key: 'github:ari-firmware:src/motor_control.cpp'
  }
]

const edge = (to: string, type: string) => ({
  id: `edge-${to}`,
  type,
  from_entity_id: DRIVER.id,
  to_entity_id: to
})

function Slot({ children }: { children: React.ReactNode }) {
  return (
    <Card style={{ width: 300 }}>
      <Mono>NEIGHBOURS OF DRV8301 (U4)</Mono>
      <div style={{ marginTop: 10 }}>{children}</div>
    </Card>
  )
}

export function Neighbours() {
  return (
    <Slot>
      <NeighborsWidget
        focus={{
          status: 'ready',
          focusedEntity: DRIVER,
          neighborhood: {
            entities: NEIGHBOURS,
            edges: [edge('e-knee-motor', 'drives'), edge('e-can-bus', 'connected_to')],
            truncated: false
          },
          error: null
        }}
        actions={ACTIONS}
      />
    </Slot>
  )
}

export function Truncated() {
  return (
    <Slot>
      <NeighborsWidget
        focus={{
          status: 'ready',
          focusedEntity: DRIVER,
          neighborhood: {
            entities: NEIGHBOURS,
            edges: [edge('e-knee-motor', 'drives')],
            truncated: true
          },
          error: null
        }}
        actions={ACTIONS}
      />
    </Slot>
  )
}

export function EmptyNeighbourhood() {
  return (
    <Slot>
      <NeighborsWidget
        focus={{ status: 'ready', focusedEntity: null, neighborhood: null, error: null }}
        actions={ACTIONS}
      />
    </Slot>
  )
}

export function NeighbourhoodFailed() {
  return (
    <Slot>
      <NeighborsWidget
        focus={{
          status: 'error',
          focusedEntity: DRIVER,
          neighborhood: null,
          error: 'KiCad source sync failed — reconnect main-board.kicad_pcb.'
        }}
        actions={ACTIONS}
      />
    </Slot>
  )
}
