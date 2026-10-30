import { useEffect, useRef, useState } from 'react'
import { confirmEdge, declineEdge, listEdgeCandidates } from '../../../lib/api/edges'
import {
  acceptHardwareSuggestion,
  listHardwareSuggestions,
  rejectHardwareSuggestion,
  type HardwareSuggestion
} from '../../../lib/api/hardware'
import type { Entity, Relation } from '../../../lib/api/resources'
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

const CARD_GAP = 270

/** `"commands"` → `"commands"`, `"mates_with"` → `"mates with"`: the type as words. */
function typeWords(relationType: string): string {
  return relationType.replace(/_/g, ' ')
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
  const [candidates, setCandidates] = useState<Relation[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [retry, setRetry] = useState(0)
  const pending = useRef(false)
  const mounted = useRef(true)
  const generation = useRef(workspaceSessionGeneration()).current
  const mode = useSettingsStore((state) => state.solMode)
  const anchored = visible.filter((entity) => points[entity.id] !== undefined)
  const robots = anchored.filter((entity) => entity.type === 'physical_robot')
  const robotKey = robots
    .map((robot) => robot.id)
    .sort()
    .join(',')
  const anchorKey = anchored
    .map((entity) => entity.id)
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
  useEffect(() => {
    let active = true
    if (!anchorKey) return
    void listEdgeCandidates(projectId)
      .then((result) => {
        if (active && workspaceSessionGeneration() === generation) {
          setCandidates(result)
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
  }, [projectId, anchorKey, generation, retry])
  const isCurrent = (): boolean => mounted.current && workspaceSessionGeneration() === generation
  /** One decision at a time; the row leaves the screen only once the server agreed. */
  async function settle(id: string, call: () => Promise<unknown>, drop: () => void): Promise<void> {
    if (pending.current || workspaceSessionGeneration() !== generation) return
    pending.current = true
    setBusy(id)
    setError(null)
    try {
      await call()
      if (isCurrent()) {
        drop()
        onChanged?.()
      }
    } catch {
      if (isCurrent()) setError('Could not save the link decision. Retry.')
    } finally {
      pending.current = false
      if (isCurrent()) setBusy(null)
    }
  }
  function decide(row: HardwareSuggestion, accept: boolean): Promise<void> {
    return settle(
      row.id,
      () =>
        accept
          ? acceptHardwareSuggestion(projectId, row.id)
          : rejectHardwareSuggestion(projectId, row.id),
      () => setRows((current) => current.filter((item) => item.id !== row.id))
    )
  }
  function decideEdge(edge: Relation, accept: boolean): Promise<void> {
    return settle(
      edge.id,
      () => (accept ? confirmEdge(projectId, edge.id) : declineEdge(projectId, edge.id)),
      () => setCandidates((current) => current.filter((item) => item.id !== edge.id))
    )
  }
  const names = new Map(visible.map((entity) => [entity.id, entity.name]))
  const nameOf = (id: string): string => names.get(id) ?? id.slice(0, 8)
  const place = (anchor: string, index: number): React.CSSProperties => ({
    left: points[anchor].x - offset.x + CARD_WIDTH / 2 + 24,
    top: points[anchor].y - offset.y - CARD_HEIGHT / 2 + index * CARD_GAP
  })
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
              style={place(robot.id, index)}
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
      {anchored.flatMap((entity) => {
        const stacked = rows.filter((row) => row.candidate_robot_id === entity.id).length
        return candidates
          .filter((edge) => edge.to_entity_id === entity.id)
          .map((edge, index) => (
            <aside
              key={edge.id}
              className="graph-suggestion graph-suggestion--candidate"
              aria-label={`Suggested ${typeWords(edge.type)} to ${entity.name}`}
              style={place(entity.id, stacked + index)}
            >
              <small>Candidate edge</small>
              <strong>
                {nameOf(edge.from_entity_id)} {typeWords(edge.type)} {entity.name} ·{' '}
                {Math.round((edge.confidence ?? 0) * 100)}%
              </strong>
              <details>
                <summary>{mode === 'Guide' ? 'Why this edge was suggested' : 'Evidence'}</summary>
                <pre>{JSON.stringify(edge.properties?.evidence ?? [], null, 2)}</pre>
              </details>
              <div>
                <button
                  type="button"
                  disabled={busy !== null}
                  onClick={() => void decideEdge(edge, true)}
                >
                  Accept edge
                </button>
                <button
                  type="button"
                  disabled={busy !== null}
                  onClick={() => void decideEdge(edge, false)}
                >
                  Decline edge
                </button>
              </div>
            </aside>
          ))
      })}
      {error && anchorKey && (
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
