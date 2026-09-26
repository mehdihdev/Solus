import { useEffect, useRef, useState } from 'react'
import {
  acceptHardwareSuggestion,
  listHardwareSuggestions,
  rejectHardwareSuggestion,
  type HardwareSuggestion
} from '../../../lib/api/hardware'
import type { Entity } from '../../../lib/api/resources'
import type { Point } from '../../../lib/api/workspace'
import { useSettingsStore } from '../../../store/settingsStore'
import { workspaceSessionGeneration } from '../workspaceSession'
import { CARD_HEIGHT, CARD_WIDTH } from './layout'

interface Props {
  projectId: string
  visible: readonly Entity[]
  points: Record<string, Point>
  offset: Point
  onChanged?: () => void
}

/** Suggestions are server records, never inferred from screen proximity or provider names. */
export function GraphSuggestions({
  projectId,
  visible,
  points,
  offset,
  onChanged
}: Props): React.JSX.Element {
  const [rows, setRows] = useState<HardwareSuggestion[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [retry, setRetry] = useState(0)
  const pending = useRef(false)
  const mounted = useRef(true)
  const generation = useRef(workspaceSessionGeneration()).current
  const mode = useSettingsStore((state) => state.solMode)
  const robots = visible.filter(
    (entity) => entity.type === 'physical_robot' && points[entity.id] !== undefined
  )
  const robotKey = robots
    .map((robot) => robot.id)
    .sort()
    .join(',')
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])
  useEffect(() => {
    let active = true
    if (!robotKey) return
    void listHardwareSuggestions(projectId)
      .then((result) => {
        if (active && workspaceSessionGeneration() === generation) {
          setRows(result.filter((row) => row.status === 'pending'))
          setError(null)
        }
      })
      .catch(() => {
        if (active && workspaceSessionGeneration() === generation)
          setError('Link suggestions unavailable.')
      })
    return () => {
      active = false
    }
  }, [projectId, robotKey, generation, retry, visible])
  const isCurrent = (): boolean => mounted.current && workspaceSessionGeneration() === generation
  async function decide(row: HardwareSuggestion, accept: boolean): Promise<void> {
    if (pending.current || workspaceSessionGeneration() !== generation) return
    pending.current = true
    setBusy(row.id)
    setError(null)
    try {
      if (accept) await acceptHardwareSuggestion(projectId, row.id)
      else await rejectHardwareSuggestion(projectId, row.id)
      if (isCurrent()) {
        setRows((current) => current.filter((item) => item.id !== row.id))
        onChanged?.()
      }
    } catch {
      if (isCurrent()) setError('Could not save the link decision. Retry.')
    } finally {
      pending.current = false
      if (isCurrent()) setBusy(null)
    }
  }
  return (
    <>
      {robots.flatMap((robot) =>
        rows
          .filter((row) => row.candidate_robot_id === robot.id)
          .map((row, index) => (
            <aside
              key={row.id}
              className="graph-suggestion"
              aria-label={`Suggested link to ${robot.name}`}
              style={{
                left: points[robot.id].x - offset.x + CARD_WIDTH / 2 + 24,
                top: points[robot.id].y - offset.y - CARD_HEIGHT / 2 + index * 270
              }}
            >
              <small>Pending link · {row.tier}</small>
              <strong>{row.subject_ref}</strong>
              <span>→ {robot.name}</span>
              {Number.isFinite(row.confidence) && row.confidence >= 0 && row.confidence <= 1 && (
                <span>{Math.round(row.confidence * 100)}% confidence</span>
              )}
              {row.reason && <p>{row.reason}</p>}
              <details>
                <summary>{mode === 'Guide' ? 'Why this link was suggested' : 'Evidence'}</summary>
                <pre>{JSON.stringify(row.evidence, null, 2)}</pre>
              </details>
              <div>
                <button
                  type="button"
                  disabled={busy !== null}
                  onClick={() => void decide(row, true)}
                >
                  Accept link
                </button>
                <button
                  type="button"
                  disabled={busy !== null}
                  onClick={() => void decide(row, false)}
                >
                  Decline link
                </button>
              </div>
            </aside>
          ))
      )}
      {error && robotKey && (
        <div className="graph-suggestion-error" role="alert">
          {error}{' '}
          <button type="button" onClick={() => setRetry((value) => value + 1)}>
            Reload suggestions
          </button>
        </div>
      )}
    </>
  )
}
