import { Card, KV, Mono, Spark } from '@solus/desktop'

// Telemetry captured off Ari-02 over the serial bridge: one sample per 200 ms.
const MOTOR_CURRENT_A = [
  1.8, 1.9, 2.1, 2.0, 2.4, 3.1, 4.2, 5.6, 6.1, 5.4, 4.8, 4.9, 5.2, 4.6, 3.9, 3.4, 3.1, 2.8, 2.6,
  2.9, 3.6, 4.4, 4.1, 3.2, 2.7, 2.3, 2.1, 2.0, 1.9, 1.8
]
const BATTERY_V = [
  24.9, 24.9, 24.8, 24.8, 24.7, 24.6, 24.4, 24.1, 23.8, 23.9, 24.0, 23.9, 23.7, 23.5, 23.4, 23.4,
  23.2, 23.0, 22.9, 22.9, 22.8, 22.6, 22.5, 22.5, 22.4, 22.3, 22.2, 22.2, 22.1, 22.0
]
const LOOP_LATENCY_MS = [
  4.1, 4.0, 4.3, 4.2, 4.1, 4.4, 4.2, 4.0, 4.1, 4.3, 6.8, 9.2, 11.4, 8.6, 5.9, 4.6, 4.3, 4.2, 4.4,
  4.1, 4.0, 4.2, 4.5, 7.1, 9.8, 12.6, 8.3, 5.2, 4.4, 4.2
]

const tile = { display: 'flex', flexDirection: 'column', gap: 6 } as const

export function MotorCurrent() {
  return (
    <Card style={{ width: 300 }}>
      <Mono>/ari_02/left_drive/current · A</Mono>
      <div style={{ fontSize: 22, fontWeight: 600, margin: '6px 0 10px' }}>1.8 A</div>
      <Spark values={MOTOR_CURRENT_A} w={268} h={54} />
      <div style={{ marginTop: 12 }}>
        <KV k="Peak (6 s)" v="6.1 A" />
        <KV k="Stall limit" v="8.0 A" />
      </div>
    </Card>
  )
}

export function FillAndLine() {
  return (
    <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
      <div style={tile}>
        <Mono>fill</Mono>
        <Spark values={MOTOR_CURRENT_A} w={180} h={48} />
      </div>
      <div style={tile}>
        <Mono>line only</Mono>
        <Spark values={MOTOR_CURRENT_A} w={180} h={48} fill={false} />
      </div>
    </div>
  )
}

export function SignalColors() {
  return (
    <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start', flexWrap: 'wrap' }}>
      <div style={tile}>
        <Mono color="var(--ok)">battery pack · V</Mono>
        <Spark values={BATTERY_V} w={180} h={48} color="var(--ok)" />
      </div>
      <div style={tile}>
        <Mono color="var(--warn)">control loop · ms</Mono>
        <Spark values={LOOP_LATENCY_MS} w={180} h={48} color="var(--warn)" />
      </div>
      <div style={tile}>
        <Mono color="var(--err)">drive current · A</Mono>
        <Spark values={MOTOR_CURRENT_A} w={180} h={48} color="var(--err)" />
      </div>
    </div>
  )
}

export function FixedRange() {
  return (
    <Card style={{ width: 300 }}>
      <Mono>/ari_02/pack/voltage · scaled 20–26 V</Mono>
      <div style={{ marginTop: 10 }}>
        <Spark values={BATTERY_V} w={268} h={54} color="var(--ok)" yMin={20} yMax={26} />
      </div>
      <div style={{ marginTop: 12 }}>
        <KV k="Now" v="22.0 V" vColor="var(--warn)" />
        <KV k="Cutoff" v="21.0 V" />
      </div>
    </Card>
  )
}
