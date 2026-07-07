// Live Bench — ported from BenchScreen in TestDesign/app/bench.jsx: Sim/Real
// telemetry with synthesized joint torques + system vitals, the top-down
// quadruped schematic, and the τ_FL_knee anomaly flow that hands off to SOL.
// Anomaly state lives in the shell store; telemetry speed is fixed at 1.
import { useEffect, useRef, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { KV } from '../../components/ui/KV'
import { Mono } from '../../components/ui/Mono'
import { Segmented } from '../../components/ui/Segmented'
import { Spark } from '../../components/ui/Spark'
import { Spinner } from '../../components/ui/Spinner'
import { Icons } from '../../components/ui/icons.constants'
import { useInterval } from '../../lib/useInterval'
import { useShellStore } from '../workspace/shellStore'
import {
  TELEM_JOINTS,
  TELEM_SYSTEM,
  type TelemetryChannel
} from '../workspace/workspaceData.constants'

const BENCH_BUF = 64
/** Tick cadence at the fixed telemetry speed of 1 (prototype: max(40, 120/speed)). */
const TICK_MS = 120
const TICK_DT = 0.12
const AUTO_ANOMALY_MS = 8000
const PAIR_SCAN_MS = 1800
const ANOMALY_SIGNAL_ID = 'FL_knee'
const ANOMALY_FREQ_HZ = 4.2
const ANOMALY_RAMP_S = 2.5
const ANOMALY_AMP = 1.1
const NOISE_FRACTION = 0.18

const BENCH_MODES = ['Sim', 'Real'] as const
type BenchMode = (typeof BENCH_MODES)[number]
type PairState = 'none' | 'searching' | 'found' | 'paired'
type Buffers = Record<string, number[]>

const ALL_CHANNELS: readonly TelemetryChannel[] = [...TELEM_JOINTS, ...TELEM_SYSTEM]

/**
 * Ring buffers of synthesized telemetry, ticked while streaming. Exactly the
 * prototype signal model: base + amp·sin(t/period + phase) + small noise, with
 * a growing 4.2 Hz oscillation on τ_FL_knee while the anomaly is active.
 */
function useTelemetryBuffers(anomalyActive: boolean, streaming: boolean): Buffers {
  const [, force] = useState(0)
  const tRef = useRef(0)
  const t0Ref = useRef<number | null>(null)
  const bufsRef = useRef<Buffers | null>(null)

  const sample = (s: TelemetryChannel, t: number, anomalyOn: boolean): number => {
    let v =
      s.base +
      s.amp * Math.sin((2 * Math.PI * t) / s.period + (s.phase ?? 0)) +
      (Math.random() - 0.5) * s.amp * NOISE_FRACTION
    if (anomalyOn && s.id === ANOMALY_SIGNAL_ID) {
      if (t0Ref.current == null) t0Ref.current = t
      const grow = Math.min(1, (t - t0Ref.current) / ANOMALY_RAMP_S)
      v += ANOMALY_AMP * grow * Math.sin(2 * Math.PI * ANOMALY_FREQ_HZ * t)
    }
    return v
  }

  if (bufsRef.current === null) {
    const init: Buffers = {}
    for (const s of ALL_CHANNELS) {
      init[s.id] = Array.from({ length: BENCH_BUF }, (_, i) => sample(s, i * TICK_DT, false))
    }
    bufsRef.current = init
  }
  const bufs = bufsRef.current

  useInterval(
    () => {
      tRef.current += TICK_DT
      for (const s of ALL_CHANNELS) {
        const b = bufs[s.id]
        if (!b) continue
        b.push(sample(s, tRef.current, anomalyActive))
        if (b.length > BENCH_BUF) b.shift()
      }
      force((n) => n + 1)
    },
    TICK_MS,
    streaming
  )

  return bufs
}

interface BenchScreenProps {
  onAskSol: (key: string) => void
}

export function BenchScreen({ onAskSol }: BenchScreenProps): React.JSX.Element {
  const anomaly = useShellStore((s) => s.anomaly)
  const setAnomaly = useShellStore((s) => s.setAnomaly)
  const [mode, setMode] = useState<BenchMode>('Sim')
  const [running, setRunning] = useState(true)
  const [pair, setPair] = useState<PairState>('none')
  const [dismissed, setDismissed] = useState(false)

  const live = mode === 'Sim' || pair === 'paired'
  const streaming = live && running
  const bufs = useTelemetryBuffers(anomaly === 'active', streaming)

  // Auto-anomaly ~8 s after entering, once (prototype behavior).
  useEffect(() => {
    if (anomaly !== 'none') return
    const t = setTimeout(() => setAnomaly('active'), AUTO_ANOMALY_MS)
    return () => clearTimeout(t)
  }, [anomaly, setAnomaly])

  const startPair = (): void => {
    setPair('searching')
    setTimeout(() => setPair('found'), PAIR_SCAN_MS)
  }
  const injectAnomaly = (): void => {
    setDismissed(false)
    setAnomaly('active')
  }

  const showBanner = anomaly === 'active' && !dismissed

  return (
    <div style={{ flex: 1, overflowY: 'auto', minWidth: 0 }}>
      <div style={{ maxWidth: 1160, margin: '0 auto', padding: '18px 24px 40px' }}>
        <BenchToolbar
          mode={mode}
          onMode={setMode}
          running={running}
          onToggleRunning={() => setRunning(!running)}
          live={live}
          streaming={streaming}
          pair={pair}
          onInject={injectAnomaly}
        />
        <BenchNotices
          banner={showBanner}
          resolvedNotice={anomaly === 'resolved'}
          onAskSol={() => onAskSol('anomaly')}
          onDismiss={() => setDismissed(true)}
        />
        {mode === 'Real' && pair !== 'paired' && (
          <PairEmptyState pair={pair} onStartPair={startPair} onConnect={() => setPair('paired')} />
        )}
        {live && (
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '248px minmax(0,1fr)',
              gap: 14,
              marginTop: 16,
              alignItems: 'start'
            }}
          >
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <RobotCard active={anomaly === 'active'} real={mode === 'Real'} />
              <SystemVitals bufs={bufs} />
            </div>
            <JointGrid bufs={bufs} anomalyActive={anomaly === 'active'} />
          </div>
        )}
      </div>
    </div>
  )
}

function deviceLabel(mode: BenchMode, pair: PairState): string {
  if (mode === 'Sim') return 'SIM · GAZEBO HEADLESS'
  return pair === 'paired' ? 'REAL · STRIDER-QD12 #A3 · USB-C' : 'REAL · NO DEVICE'
}

function BenchToolbar({
  mode,
  onMode,
  running,
  onToggleRunning,
  live,
  streaming,
  pair,
  onInject
}: {
  mode: BenchMode
  onMode: (mode: BenchMode) => void
  running: boolean
  onToggleRunning: () => void
  live: boolean
  streaming: boolean
  pair: PairState
  onInject: () => void
}): React.JSX.Element {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap' }}>
      <Segmented options={BENCH_MODES} value={mode} onChange={onMode} ariaLabel="Bench mode" />
      <Button kind="soft" size="sm" onClick={onToggleRunning} disabled={!live}>
        {running ? (
          <>
            <Icons.pause size={12} /> Pause
          </>
        ) : (
          <>
            <Icons.play size={12} /> Run
          </>
        )}
      </Button>
      <Mono size={10}>{deviceLabel(mode, pair)}</Mono>
      <div style={{ flex: 1 }} />
      <Mono size={10} color={streaming ? 'var(--ok)' : 'var(--mut)'}>
        {streaming ? '● STREAMING · 500 HZ' : '○ PAUSED'}
      </Mono>
      <Button kind="bare" size="sm" onClick={onInject} style={{ fontSize: 11 }}>
        <Icons.warn size={12} /> Inject anomaly
      </Button>
    </div>
  )
}

function BenchNotices({
  banner,
  resolvedNotice,
  onAskSol,
  onDismiss
}: {
  banner: boolean
  resolvedNotice: boolean
  onAskSol: () => void
  onDismiss: () => void
}): React.JSX.Element {
  return (
    <>
      {banner && <AnomalyBanner onAskSol={onAskSol} onDismiss={onDismiss} />}
      {resolvedNotice && <ResolvedNotice />}
    </>
  )
}

function AnomalyBanner({
  onAskSol,
  onDismiss
}: {
  onAskSol: () => void
  onDismiss: () => void
}): React.JSX.Element {
  return (
    <div
      className="bench-banner"
      style={{
        marginTop: 14,
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        background: 'color-mix(in srgb, var(--err) 9%, var(--sur))',
        border: '1px solid color-mix(in srgb, var(--err) 55%, transparent)',
        borderRadius: 3,
        padding: '12px 16px'
      }}
    >
      <span style={{ color: 'var(--err)' }} className="gm-orb">
        <Icons.warn size={17} />
      </span>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 13, fontWeight: 600 }}>
          Anomaly detected — τ_FL_knee oscillating at 4.2 Hz
        </div>
        <div style={{ fontSize: 11.5, color: 'var(--mut)', marginTop: 2 }}>
          Amplitude rising · locked to 2× stride frequency · started 6 s ago
        </div>
      </div>
      <Button id="btn-ask-sol-anomaly" kind="primary" size="sm" onClick={onAskSol}>
        <Icons.sol size={13} /> Ask SOL
      </Button>
      <span
        role="button"
        aria-label="Dismiss anomaly banner"
        onClick={onDismiss}
        style={{ color: 'var(--mut)', cursor: 'pointer', padding: 4 }}
      >
        <Icons.x size={12} />
      </span>
    </div>
  )
}

function ResolvedNotice(): React.JSX.Element {
  return (
    <div
      style={{
        marginTop: 14,
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        background: 'color-mix(in srgb, var(--ok) 7%, var(--sur))',
        border: '1px solid color-mix(in srgb, var(--ok) 40%, transparent)',
        borderRadius: 3,
        padding: '10px 16px',
        fontSize: 12.5
      }}
    >
      <span style={{ color: 'var(--ok)' }}>
        <Icons.check size={14} />
      </span>
      Fix flashed — τ_FL_knee stable for 30 s. SOL is still watching this signal.
    </div>
  )
}

function PairEmptyState({
  pair,
  onStartPair,
  onConnect
}: {
  pair: PairState
  onStartPair: () => void
  onConnect: () => void
}): React.JSX.Element {
  return (
    <Card pad={0} style={{ marginTop: 16 }}>
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '64px 24px',
          gap: 14,
          textAlign: 'center'
        }}
      >
        <span style={{ color: 'var(--mut)', opacity: 0.7 }}>
          <Icons.chip2 size={30} />
        </span>
        {pair === 'none' && (
          <>
            <div style={{ fontSize: 15, fontWeight: 600 }}>No hardware detected</div>
            <div style={{ fontSize: 12.5, color: 'var(--mut)', maxWidth: 380, lineHeight: 1.6 }}>
              Connect your robot over USB-C or CAN, or pair a device on the local network. Telemetry
              starts streaming the moment a device answers.
            </div>
            <Button kind="primary" onClick={onStartPair}>
              Pair device
            </Button>
          </>
        )}
        {pair === 'searching' && (
          <>
            <div
              style={{
                fontSize: 14,
                fontWeight: 600,
                display: 'flex',
                gap: 10,
                alignItems: 'center'
              }}
            >
              <Spinner /> Scanning USB + mDNS…
            </div>
            <Mono size={10}>LISTENING FOR STRIDER BOOTLOADER BEACON</Mono>
          </>
        )}
        {pair === 'found' && <FoundDeviceCard onConnect={onConnect} />}
      </div>
    </Card>
  )
}

function FoundDeviceCard({ onConnect }: { onConnect: () => void }): React.JSX.Element {
  return (
    <>
      <div style={{ fontSize: 14, fontWeight: 600 }}>Found 1 device</div>
      <Card
        pad={14}
        style={{ width: 340, textAlign: 'left', display: 'flex', alignItems: 'center', gap: 12 }}
      >
        <span style={{ color: 'var(--ok)' }}>
          <Icons.chip2 size={20} />
        </span>
        <div style={{ flex: 1 }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>STRIDER-QD12 #A3</div>
          <div style={{ fontSize: 10.5, color: 'var(--mut)' }}>
            USB-C · fw 0.9.2 · 12 joints reporting
          </div>
        </div>
        <Button kind="primary" size="sm" onClick={onConnect}>
          Connect
        </Button>
      </Card>
    </>
  )
}

function RobotCard({ active, real }: { active: boolean; real: boolean }): React.JSX.Element {
  return (
    <Card pad={14}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 8
        }}
      >
        <Mono size={9.5}>ROBOT · TOP VIEW</Mono>
        {real && (
          <Mono size={9} color="var(--ok)">
            REAL
          </Mono>
        )}
      </div>
      <QuadSchematic anomaly={active} />
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6 }}>
        <Mono size={9} color="var(--mut)">
          GAIT: STANDING · 2.1 HZ
        </Mono>
        <Mono size={9} color={active ? 'var(--err)' : 'var(--ok)'}>
          {active ? '1 FAULT' : 'NOMINAL'}
        </Mono>
      </div>
    </Card>
  )
}

function SystemVitals({ bufs }: { bufs: Buffers }): React.JSX.Element {
  return (
    <Card pad={14}>
      <Mono size={9.5}>SYSTEM</Mono>
      <div style={{ marginTop: 6 }}>
        {TELEM_SYSTEM.map((s) => {
          const b = bufs[s.id]
          const v = b?.[b.length - 1] ?? s.base
          return <KV key={s.id} k={s.l} v={`${v.toFixed(s.base > 100 ? 0 : 1)} ${s.unit}`} />
        })}
      </div>
    </Card>
  )
}

function JointGrid({
  bufs,
  anomalyActive
}: {
  bufs: Buffers
  anomalyActive: boolean
}): React.JSX.Element {
  return (
    <div>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 10
        }}
      >
        <Mono size={9.5}>JOINT TORQUES · 12 ACTUATORS</Mono>
        <Mono size={9}>WINDOW: 8 S</Mono>
      </div>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(196px, 1fr))',
          gap: 10
        }}
      >
        {TELEM_JOINTS.map((s) => {
          const b = bufs[s.id] ?? []
          return (
            <JointCard
              key={s.id}
              sig={s}
              buf={b}
              val={b[b.length - 1] ?? s.base}
              bad={anomalyActive && s.id === ANOMALY_SIGNAL_ID}
            />
          )
        })}
      </div>
    </div>
  )
}

function JointCard({
  sig,
  buf,
  val,
  bad
}: {
  sig: TelemetryChannel
  buf: readonly number[]
  val: number
  bad: boolean
}): React.JSX.Element {
  return (
    <Card
      pad={0}
      style={{
        borderColor: bad ? 'var(--err)' : 'var(--bd)',
        overflow: 'hidden',
        transition: 'border-color 0.3s'
      }}
    >
      <div
        style={{
          padding: '10px 12px 4px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'baseline'
        }}
      >
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 10.5,
            color: bad ? 'var(--err)' : 'var(--mut)'
          }}
        >
          {sig.l}
        </span>
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 13.5,
            color: bad ? 'var(--err)' : 'var(--tx)'
          }}
        >
          {val.toFixed(2)}
          <span style={{ fontSize: 9, color: 'var(--mut)', marginLeft: 3 }}>{sig.unit}</span>
        </span>
      </div>
      <Spark
        values={buf}
        w={196}
        h={34}
        color={bad ? 'var(--err)' : 'var(--rt)'}
        yMin={sig.base - sig.amp * 2.6}
        yMax={sig.base + sig.amp * 2.6}
      />
    </Card>
  )
}

const QUAD_LEGS = [
  { id: 'FL', hx: 52, hy: 38, dx: -26, dy: -22 },
  { id: 'FR', hx: 118, hy: 38, dx: 26, dy: -22 },
  { id: 'RL', hx: 52, hy: 132, dx: -26, dy: 22 },
  { id: 'RR', hx: 118, hy: 132, dx: 26, dy: 22 }
] as const

/** Top-down quadruped: body + 4 legs (hip at corner, knee mid, foot end). */
function QuadSchematic({ anomaly }: { anomaly: boolean }): React.JSX.Element {
  return (
    <svg width="100%" viewBox="0 0 170 170" style={{ display: 'block' }}>
      <rect x="52" y="38" width="66" height="94" rx="10" fill="var(--sur2)" stroke="var(--bd)" />
      <circle
        cx="85"
        cy="62"
        r="5"
        fill="none"
        stroke="var(--rt)"
        strokeWidth="1.2"
        opacity="0.7"
      />
      <text
        x="85"
        y="100"
        textAnchor="middle"
        fontFamily="var(--font-mono)"
        fontSize="8"
        fill="var(--mut)"
      >
        QD-12
      </text>
      {QUAD_LEGS.map((l) => {
        const kx = l.hx + l.dx
        const ky = l.hy + l.dy
        const fx = kx + l.dx * 0.8
        const fy = ky + l.dy * 1.4
        const bad = anomaly && l.id === 'FL'
        const c = bad ? 'var(--err)' : 'var(--rt)'
        return (
          <g key={l.id}>
            <path
              d={`M${l.hx} ${l.hy} L${kx} ${ky} L${fx} ${fy}`}
              fill="none"
              stroke={c}
              strokeWidth="2"
              opacity="0.55"
              strokeLinecap="round"
            />
            <circle cx={l.hx} cy={l.hy} r="4" fill={c} />
            <circle
              cx={kx}
              cy={ky}
              r={bad ? 5.5 : 3.5}
              fill={c}
              className={bad ? 'gm-orb' : ''}
              style={bad ? { filter: 'drop-shadow(0 0 5px var(--err))' } : {}}
            />
            <circle cx={fx} cy={fy} r="3" fill="none" stroke={c} strokeWidth="1.5" />
            <text
              x={l.hx + (l.dx > 0 ? 10 : -10)}
              y={l.hy - 8}
              textAnchor="middle"
              fontFamily="var(--font-mono)"
              fontSize="8.5"
              fill={bad ? 'var(--err)' : 'var(--mut)'}
            >
              {l.id}
            </text>
          </g>
        )
      })}
    </svg>
  )
}
