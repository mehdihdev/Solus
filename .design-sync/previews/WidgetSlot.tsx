import { useEffect } from 'react'
import { KV, Mono, WidgetSlot } from '@solus/desktop'

const noop = (): void => {}

/** The real canvas grid: `.widget-slot` spans columns, so a slot only reads
 *  correctly inside `.widget-canvas-grid`. */
const canvas = { width: 560 } as const

function TelemetryBody({ onStateChange }: { onStateChange?: (s: string) => void }) {
  useEffect(() => {
    onStateChange?.('ready')
  }, [onStateChange])
  return (
    <div>
      <Mono size={9}>ARI-02 · REAL MODE · 200 HZ</Mono>
      <div style={{ marginTop: 10 }}>
        <KV k="knee_motor current" v="6.4 A" vColor="var(--ok)" />
        <KV k="bus voltage" v="23.8 V" />
        <KV k="IMU drift" v="0.4 deg/s" vColor="var(--warn)" />
      </div>
    </div>
  )
}

function NeighbourListBody({ onStateChange }: { onStateChange?: (s: string) => void }) {
  useEffect(() => {
    onStateChange?.('ready')
  }, [onStateChange])
  return (
    <div style={{ display: 'grid', gap: 6, fontSize: 11.5 }}>
      <Mono size={9}>4 NEIGHBOURS</Mono>
      <span>DRV8301 (U4)</span>
      <span>knee_motor</span>
      <span>CAN_BUS_1</span>
      <span>motor_control.cpp</span>
    </div>
  )
}

function UnreachableTargetBody({ onStateChange }: { onStateChange?: (s: string) => void }) {
  useEffect(() => {
    onStateChange?.('error')
  }, [onStateChange])
  return (
    <div style={{ fontSize: 11.5, color: 'var(--mut)', lineHeight: 1.5 }}>
      Could not reach the Jetson at <code>ari-02.local</code>. Last telemetry 14 minutes ago.
    </div>
  )
}

const builtin = (id: string, title: string, component: unknown, preferred: string) => ({
  kind: 'builtin' as const,
  entry: {
    ref: `builtin:${id}`,
    id,
    title,
    domains: ['runtime'],
    size: { preferred, minimum: 'compact' },
    component
  }
})

const FOCUS = {
  entity: { projectId: 'p-ari-02', entityId: 'e-knee-motor' },
  domain: 'mechanical',
  label: 'knee_motor',
  path: []
}

export function StandardSlot() {
  return (
    <div className="widget-canvas-grid" style={canvas}>
      <WidgetSlot
        projectId="p-ari-02"
        slot={{ ref: 'builtin:livebench', size: 'standard' }}
        target={builtin('livebench', 'Live Bench', TelemetryBody, 'wide')}
        focus={FOCUS}
        onFocusChange={noop}
        onRemove={noop}
        canMoveLeft={false}
        canMoveRight
        onResize={noop}
        onMove={noop}
      />
    </div>
  )
}

export function CompactSlot() {
  return (
    <div className="widget-canvas-grid" style={canvas}>
      <WidgetSlot
        projectId="p-ari-02"
        slot={{ ref: 'builtin:neighbours', size: 'compact' }}
        target={builtin('neighbours', 'Neighbours', NeighbourListBody, 'standard')}
        focus={FOCUS}
        onFocusChange={noop}
        onRemove={noop}
        canMoveLeft
        canMoveRight
        onResize={noop}
        onMove={noop}
      />
    </div>
  )
}

export function SlotInError() {
  return (
    <div className="widget-canvas-grid" style={canvas}>
      <WidgetSlot
        projectId="p-ari-02"
        slot={{ ref: 'builtin:deploy-target', size: 'standard' }}
        target={builtin('deploy-target', 'Deploy target', UnreachableTargetBody, 'standard')}
        focus={FOCUS}
        onFocusChange={noop}
        onRemove={noop}
        canMoveLeft
        canMoveRight={false}
        onResize={noop}
        onMove={noop}
      />
    </div>
  )
}
