import { useState, type ReactNode } from 'react'
import {
  ROBOT_CATEGORIES,
  ROBOT_CATEGORY_LABELS,
  type RobotCategory
} from '../../../lib/api/hardware'
import type { Entity } from '../../../lib/api/resources'
import type { SolMode } from '../../../store/settingsStore'
import { LabeledSelect } from '../hardware/LabeledSelect'
import type { RobotSession, RobotView } from './robotSession'

export interface OrphanAttach {
  robotName: string
  attach: (part: Entity, category: RobotCategory) => void
}
interface OrphanProps {
  session: RobotSession
  state: RobotView
  mode: SolMode
  /** When set, every part gets "Attach to <robot>" under the category it last had. */
  onAttach?: OrphanAttach
}
const CATEGORY_OPTIONS = ROBOT_CATEGORIES.map((value) => ({
  value,
  label: ROBOT_CATEGORY_LABELS[value]
}))
function lastCategory(part: Entity): RobotCategory {
  const category = part.properties?.category
  // ponytail: structure is the honest default for CAD/schematic parts; the user picks otherwise.
  return ROBOT_CATEGORIES.find((key) => key === category) ?? 'structure'
}
function AttachRow({
  part,
  onAttach
}: {
  part: Entity
  onAttach: OrphanAttach
}): React.JSX.Element {
  const [category, setCategory] = useState(() => lastCategory(part))
  return (
    <span className="robot-orphan-attach">
      <LabeledSelect
        label="Category"
        value={category}
        onChange={setCategory}
        options={CATEGORY_OPTIONS}
      />
      <button type="button" onClick={() => onAttach.attach(part, category)}>
        Attach to {onAttach.robotName}
      </button>
    </span>
  )
}
export function RobotOrphans({ session, state, mode, onAttach }: OrphanProps): ReactNode {
  if (!state.loading && !state.readError && state.parts.length === 0) return null
  return (
    <section className="robot-orphans" aria-label="Unassigned robot parts">
      <strong>Unassigned parts</strong>
      {state.parts.length > 0 && (
        <p>
          {mode === 'Guide'
            ? 'These parts have no robot owner. Attach them when assigning hardware. Select a part below to reveal its existing graph node.'
            : 'Unassigned parts. Attach them when assigning hardware; select to reveal.'}
        </p>
      )}
      {state.readError && (
        <p role="alert">
          {state.readError}{' '}
          <button type="button" onClick={session.retry} disabled={state.loading}>
            Retry unassigned parts
          </button>
        </p>
      )}
      {state.loading && <p role="status">Loading unassigned parts…</p>}
      <ul>
        {state.parts.map((part) => (
          <li key={part.id}>
            <button
              type="button"
              aria-label={`Reveal ${part.name}`}
              onClick={() => session.reveal(part.id)}
            >
              {part.name}
            </button>
            {onAttach && <AttachRow part={part} onAttach={onAttach} />}
          </li>
        ))}
      </ul>
      <OrphanPagination state={state} session={session} />
    </section>
  )
}
function OrphanPagination({ state, session }: Pick<OrphanProps, 'state' | 'session'>): ReactNode {
  return (
    (state.cursors.length > 1 || state.next) && (
      <div className="robot-orphan-pages">
        <button
          type="button"
          aria-label="Previous unassigned parts"
          disabled={state.loading || state.cursors.length === 1}
          onClick={session.previous}
        >
          Previous
        </button>
        <span>Page {state.cursors.length}</span>
        <button
          type="button"
          aria-label="Next unassigned parts"
          disabled={state.loading || !state.next}
          onClick={session.next}
        >
          Next
        </button>
      </div>
    )
  )
}
