import type { ReactNode } from 'react'
import type { SolMode } from '../../../store/settingsStore'
import type { RobotSession, RobotView } from './robotSession'

interface OrphanProps {
  session: RobotSession
  state: RobotView
  mode: SolMode
}
export function RobotOrphans({ session, state, mode }: OrphanProps): ReactNode {
  if (!state.loading && !state.readError && state.parts.length === 0) return null
  return (
    <section className="robot-orphans" aria-label="Unassigned robot parts">
      <strong>Unassigned parts</strong>
      {state.parts.length > 0 && (
        <p>
          {mode === 'Guide'
            ? 'These parts were retained when their robot was deleted. Attach them to another robot when assigning hardware. Select a part below to reveal its existing graph node.'
            : 'Parts retained. Attach them to another robot when assigning hardware; select to reveal.'}
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
