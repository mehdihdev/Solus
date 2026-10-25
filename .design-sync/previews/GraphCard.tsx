import { GraphCard, Mono } from '@solus/desktop'

const noop = (): void => {}

/** `.graph-node` is absolutely positioned; `point - offset` places it in here. */
const stage = { position: 'relative', width: 248, height: 188 } as const
const POINT = { x: 124, y: 94 }
const ORIGIN = { x: 0, y: 0 }

const DRIVER = {
  id: 'e-u4-drv8301',
  type: 'motor_driver',
  domain: 'electrical',
  name: 'DRV8301 (U4)',
  source_key: 'kicad:main-board:U4'
}

const KNEE_MOTOR = {
  id: 'e-knee-motor',
  type: 'motor',
  domain: 'mechanical',
  name: 'knee_motor',
  source_key: 'onshape:ari-02:knee'
}

const CAMERA_NODE = {
  id: 'e-camera-node',
  type: 'ros_node',
  domain: 'runtime',
  name: 'camera_node',
  source_key: 'ros:/camera_node'
}

export function FocusedNode() {
  return (
    <div style={stage}>
      <GraphCard
        entity={DRIVER}
        point={POINT}
        offset={ORIGIN}
        focused
        childCount={6}
        onSelect={noop}
        onEnter={noop}
        onBack={noop}
        onPreview={noop}
        onMove={noop}
      />
    </div>
  )
}

export function LeafNode() {
  return (
    <div style={stage}>
      <GraphCard
        entity={KNEE_MOTOR}
        point={POINT}
        offset={ORIGIN}
        focused={false}
        childCount={0}
        onSelect={noop}
        onEnter={noop}
        onBack={noop}
        onPreview={noop}
        onMove={noop}
      />
    </div>
  )
}

export function WithEmbeddedContent() {
  return (
    <div style={stage}>
      <GraphCard
        entity={CAMERA_NODE}
        point={POINT}
        offset={ORIGIN}
        focused={false}
        childCount={2}
        onSelect={noop}
        onEnter={noop}
        onBack={noop}
        onPreview={noop}
        onMove={noop}
        renderContent={(entity) => (
          <div style={{ display: 'grid', gap: 2 }}>
            <Mono size={8}>{entity.source_key}</Mono>
            <Mono size={8} color="var(--ok)">
              30 FPS · /image_raw
            </Mono>
          </div>
        )}
      />
    </div>
  )
}

/** SOLUSDEV-320: a focused node previews up to four children and carries its open-findings badge. */
export function WithChildrenAndFinding() {
  return (
    <div style={{ ...stage, height: 260 }}>
      <GraphCard
        entity={{ ...DRIVER, name: 'main-board', type: 'pcb', source_key: 'kicad:main-board' }}
        point={{ x: 124, y: 130 }}
        offset={ORIGIN}
        focused
        childCount={14}
        finding={{ severity: 'warning', count: 2 }}
        childPreviews={[
          { entity: DRIVER, childCount: 6 },
          { entity: { ...DRIVER, id: 'e-u2-imu', name: 'BMI088 (U2)', type: 'imu' }, childCount: 0 },
          { entity: { ...DRIVER, id: 'e-j4', name: 'J4 USB-C', type: 'connector' }, childCount: 0 }
        ]}
        onSelect={noop}
        onEnter={noop}
        onBack={noop}
        onPreview={noop}
        onMove={noop}
        onRevealChild={noop}
      />
    </div>
  )
}
