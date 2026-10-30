// SOLUSDEV-320 P5-T3d: the environment/divergences view — one plain table,
// a row per (machine, cause, item), from GET /environment/divergences.
import { useEffect, useState } from 'react'
import {
  getEnvironmentDivergences,
  type EnvironmentDivergencesDoc
} from '../../lib/api/environment'

const COLUMNS = ['Machine', 'Cause', 'Item', 'Expected', 'Actual'] as const
const NONE = '—'

export interface DivergenceRow {
  machine: string
  cause: string
  item: string
  expected: string
  actual: string
}

/** Flatten machine → cause → item; empty when every machine matches. */
export function divergenceRows(doc: EnvironmentDivergencesDoc): DivergenceRow[] {
  return doc.machines.flatMap((machine) =>
    machine.causes.flatMap((cause) =>
      cause.items.map((item) => ({
        machine: machine.hostname,
        cause: cause.cause.replace(/_/gu, ' '),
        item: item.name,
        expected: item.expected ?? NONE,
        actual: item.actual ?? NONE
      }))
    )
  )
}

interface Props {
  projectId: string
  load?: (projectId: string) => Promise<EnvironmentDivergencesDoc>
}

export function EnvironmentDivergences({
  projectId,
  load = getEnvironmentDivergences
}: Props): React.JSX.Element {
  const [doc, setDoc] = useState<EnvironmentDivergencesDoc | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let active = true
    setDoc(null)
    setFailed(false)
    load(projectId).then(
      (next) => active && setDoc(next),
      () => active && setFailed(true)
    )
    return () => {
      active = false
    }
  }, [projectId, load])
  if (failed) return <p role="status">Could not load divergences.</p>
  if (doc === null) return <p role="status">Loading…</p>
  const rows = divergenceRows(doc)
  if (rows.length === 0)
    return (
      <p role="status">
        {doc.machines.length === 0
          ? 'No machine has reported yet.'
          : 'Every machine matches the spec.'}
      </p>
    )
  return (
    <table className="solus-divergences" aria-label="Environment divergences">
      <thead>
        <tr>
          {COLUMNS.map((column) => (
            <th key={column}>{column}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, index) => (
          <tr key={`${row.machine}|${row.cause}|${row.item}|${index}`}>
            <td>{row.machine}</td>
            <td>{row.cause}</td>
            <td>{row.item}</td>
            <td>{row.expected}</td>
            <td>{row.actual}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
