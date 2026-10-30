// Teleoperation confirmation (wireflow live-bench-teleop.md §Start). Nothing
// moves until the user presses Start with the table on screen.
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { ApiError } from '../../lib/api/envelope.types'
import {
  startTeleop,
  type Teleop,
  type TeleopPair,
  type TeleopPreview
} from '../../lib/api/resources'
import { ModalShell } from '../workspace/modals'
import type { RobotPanelInfo } from './robotGrouping'
import { useTeleopPreview } from './useTeleopPreview'

const CELL: React.CSSProperties = { padding: '4px 8px', textAlign: 'left' }

function fmt(value: number | null, unit?: string): string {
  if (value === null) return '—'
  return unit ? `${value.toFixed(1)} ${unit}` : value.toFixed(1)
}

function isPreview(value: unknown): value is TeleopPreview {
  return (
    typeof value === 'object' && value !== null && Array.isArray((value as TeleopPreview).pairs)
  )
}

function PairRow({ pair }: { pair: TeleopPair }): React.JSX.Element {
  return (
    <tr>
      <td style={CELL}>{pair.leader_signal}</td>
      <td style={CELL}>{fmt(pair.leader_value, pair.unit)}</td>
      <td style={CELL}>{fmt(pair.follower_value, pair.unit)}</td>
      <td style={CELL}>{fmt(pair.delta)}</td>
      <td style={CELL}>
        {pair.within_tolerance ? (
          <span aria-label="within tolerance">✓</span>
        ) : (
          <span aria-label="outside tolerance" style={{ color: 'var(--err)' }}>
            ✗
          </span>
        )}
      </td>
    </tr>
  )
}

function PreviewBody({ preview }: { preview: TeleopPreview }): React.JSX.Element {
  const outOfTolerance =
    preview.blockers.length === 0 && preview.pairs.some((p) => !p.within_tolerance)
  return (
    <>
      {preview.blockers.length > 0 && (
        <ul style={{ margin: '10px 0', paddingLeft: 18, color: 'var(--err)', fontSize: 12.5 }}>
          {preview.blockers.map((b) => (
            <li key={`${b.code}:${b.message}`}>{b.message}</li>
          ))}
        </ul>
      )}
      {preview.pairs.length > 0 && (
        <table style={{ width: '100%', fontSize: 12, marginTop: 10, borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ color: 'var(--mut)' }}>
              <th style={CELL}>Joint</th>
              <th style={CELL}>Leader</th>
              <th style={CELL}>Follower</th>
              <th style={CELL}>Difference</th>
              <th style={CELL}>Within tolerance</th>
            </tr>
          </thead>
          <tbody>
            {preview.pairs.map((pair) => (
              <PairRow key={pair.address} pair={pair} />
            ))}
          </tbody>
        </table>
      )}
      {outOfTolerance && (
        <p style={{ fontSize: 12.5, marginTop: 10 }}>
          Move the leader closer to the follower&apos;s pose.
        </p>
      )}
    </>
  )
}

function startFailure(error: unknown): { message: string; fresh?: TeleopPreview } {
  if (!(error instanceof ApiError)) return { message: 'Teleoperation could not be started.' }
  if (error.code === 'teleop_not_ready') {
    return {
      message: 'Not ready — the pairing changed. Check the table below.',
      fresh: error.details?.find(isPreview)
    }
  }
  if (error.code === 'preview_expired') {
    return { message: 'The preview expired and was refreshed. Review it and start again.' }
  }
  if (error.code === 'teleop_running') return { message: 'Teleoperation is already running.' }
  return { message: 'Teleoperation could not be started.' }
}

export function TeleopDialog({
  projectId,
  leader,
  follower,
  onStarted,
  onClose
}: {
  projectId: string
  leader: RobotPanelInfo
  follower: RobotPanelInfo
  onStarted: (teleop: Teleop) => void
  onClose: () => void
}): React.JSX.Element {
  const [starting, setStarting] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)
  const { preview, error, adopt, refresh } = useTeleopPreview(
    projectId,
    leader.sessionId,
    follower.sessionId,
    starting
  )
  async function start(): Promise<void> {
    if (!preview?.ready || starting) return
    setStarting(true)
    setFailure(null)
    try {
      onStarted(await startTeleop(projectId, preview.preview_id))
    } catch (caught) {
      const { message, fresh } = startFailure(caught)
      setFailure(message)
      if (fresh) adopt(fresh)
      setStarting(false)
      if (!fresh) void refresh()
    }
  }
  const message = failure ?? error
  return (
    <ModalShell onClose={onClose} width={560}>
      <div role="dialog" aria-modal="true" aria-label="Teleoperate">
        <div style={{ fontSize: 16, fontWeight: 600 }}>Teleoperate</div>
        <p style={{ fontSize: 12.5, color: 'var(--mut)', lineHeight: 1.5 }}>
          <strong>{follower.name}</strong> will turn its torque on, hold its pose, then mirror{' '}
          <strong>{leader.name}</strong>, which you move by hand.
        </p>
        {preview ? <PreviewBody preview={preview} /> : <p role="status">Reading both arms…</p>}
        {message && (
          <p role="alert" style={{ color: 'var(--err)', fontSize: 12.5 }}>
            {message}
          </p>
        )}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 16 }}>
          <Button kind="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            kind="primary"
            disabled={!preview?.ready || starting}
            onClick={() => void start()}
          >
            Start teleoperation
          </Button>
        </div>
      </div>
    </ModalShell>
  )
}
