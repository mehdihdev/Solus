// The sidebar for a Physical Robot or one of its categories (SOLUSDEV-250 P4,
// docs/wireflows/workspace.md). Rename, delete, unassigned parts, suggestions and the
// connection line live here — the card carries none of them. Propose, never assert:
// counts come from the snapshot, everything else from a read that says so when it failed.
import { useEffect, useState, type ReactNode } from 'react'
import { Button } from '../../../components/ui/Button'
import {
  acceptHardwareSuggestion,
  attachParts,
  rejectHardwareSuggestion,
  type HardwareSuggestion,
  type RobotCategory
} from '../../../lib/api/hardware'
import type { Entity, Relation } from '../../../lib/api/resources'
import type { SolMode } from '../../../store/settingsStore'
import { hardwareErrorText } from '../hardware/detected'
import { RobotOrphans } from '../robots/RobotOrphans'
import { editableRobot, type RobotSession, type RobotView } from '../robots/robotSession'
import { RobotRenameEditor } from './RobotRenameEditor'
import { TwoStepDelete } from './TwoStepDelete'
import {
  childrenOf,
  robotCategories,
  useRobotReads,
  type Connection,
  type RobotReads
} from './useRobotSidebar'

export interface RobotSidebarProps {
  entity: Entity
  session: RobotSession
  state: RobotView
  online: boolean
  mode: SolMode
  entities: readonly Entity[]
  relations: readonly Relation[]
  onChanged: () => void
  onReveal: (entityId: string) => void
}

const ORPHANS_READ = new WeakSet<readonly Entity[]>()
const CONNECTION: Record<Connection, string> = {
  streaming: 'Connected · session open',
  none: 'Not connected',
  unknown: 'Unknown (offline)'
}
function managedConnection(entity: Entity): string | null {
  const connection = entity.properties?.connection
  if (typeof connection !== 'object' || connection === null) return null
  const value = connection as Record<string, unknown>
  if (value.managed_by !== 'local_runtime') return null
  switch (value.status) {
    case 'connecting':
      return 'Connecting…'
    case 'connected':
      return 'Connected'
    case 'failed':
      return typeof value.error === 'string'
        ? `Connection failed. ${value.error}`
        : 'Connection failed. Retry from the saved hardware.'
    case 'disconnected':
      return 'Disconnected'
    default:
      return null
  }
}
function ConnectionStatus({
  entity,
  reads
}: {
  entity: Entity
  reads: RobotReads | null
}): React.JSX.Element {
  return (
    <section aria-label="Connection">
      <h3>Connection</h3>
      {reads?.identityNote && <p>{reads.identityNote}</p>}
      <p role="status">{managedConnection(entity) ?? CONNECTION[reads?.connection ?? 'unknown']}</p>
    </section>
  )
}
const COPY = {
  category: {
    Guide: 'Parts assigned to this category appear inside.',
    Expert: 'Assigned parts inside.'
  },
  empty: { Guide: 'none yet — assign hardware from Add', Expert: 'none yet' },
  noSuggestions: {
    Guide: 'No pending suggestions. Devices that look like this robot are proposed here.',
    Expert: 'No pending suggestions.'
  }
} as const

function PartList({
  parts,
  tags = {},
  onReveal
}: {
  parts: readonly Entity[]
  tags?: Record<string, string>
  onReveal: (entityId: string) => void
}): React.JSX.Element {
  return (
    <ul>
      {parts.map((part) => (
        <li key={part.id} aria-label={part.name}>
          <button
            type="button"
            className="node-sidebar-link"
            aria-label={`Reveal ${part.name}`}
            onClick={() => onReveal(part.id)}
          >
            {part.name}
          </button>
          {tags[part.id] && <code className="node-sidebar-mono">{tags[part.id]}</code>}
        </li>
      ))}
    </ul>
  )
}

function Suggestions({
  reads,
  mode,
  projectId,
  onChanged
}: {
  reads: RobotReads | null
  mode: SolMode
  projectId: string
  onChanged: () => void
}): React.JSX.Element {
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const decide = async (suggestion: HardwareSuggestion, accept: boolean): Promise<void> => {
    setBusy(suggestion.id)
    setError(null)
    try {
      if (accept) await acceptHardwareSuggestion(projectId, suggestion.id)
      else await rejectHardwareSuggestion(projectId, suggestion.id)
      onChanged()
    } catch (failure) {
      setError(hardwareErrorText(failure))
    } finally {
      setBusy(null)
    }
  }
  return (
    <section aria-label="Pending suggestions">
      <h3>Pending suggestions</h3>
      {reads && reads.suggestions.length === 0 && <p>{COPY.noSuggestions[mode]}</p>}
      <ul>
        {reads?.suggestions.map((suggestion) => (
          <li key={suggestion.id} aria-label={suggestion.subject_ref}>
            <span>{suggestion.subject_ref}</span>
            <code className="node-sidebar-mono">{suggestion.tier}</code>
            {suggestion.reason && <p>{suggestion.reason}</p>}
            <div className="node-sidebar-actions">
              <Button
                kind="primary"
                size="sm"
                disabled={busy !== null}
                onClick={() => void decide(suggestion, true)}
              >
                Accept
              </Button>
              <Button
                size="sm"
                disabled={busy !== null}
                onClick={() => void decide(suggestion, false)}
              >
                Reject
              </Button>
            </div>
          </li>
        ))}
      </ul>
      {error && <p role="alert">{error}</p>}
    </section>
  )
}

function useAttach(
  projectId: string,
  robotId: string,
  onChanged: () => void
): { attach: (part: Entity, category: RobotCategory) => void; error: string | null } {
  const [error, setError] = useState<string | null>(null)
  const attach = async (part: Entity, category: RobotCategory): Promise<void> => {
    setError(null)
    try {
      await attachParts(projectId, robotId, { entity_ids: [part.id], category })
      onChanged()
    } catch (failure) {
      setError(hardwareErrorText(failure))
    }
  }
  return { attach: (part, category) => void attach(part, category), error }
}

function Heading({
  entity,
  session,
  state,
  canEdit
}: Pick<RobotSidebarProps, 'entity' | 'session' | 'state'> & {
  canEdit: boolean
}): React.JSX.Element {
  const [editing, setEditing] = useState(false)
  return (
    <header>
      <h2>{entity.name}</h2>
      {canEdit &&
        (editing ? (
          <RobotRenameEditor
            entity={entity}
            session={session}
            state={state}
            onClose={() => setEditing(false)}
          />
        ) : (
          <Button
            kind="bare"
            size="sm"
            disabled={state.busy !== null}
            onClick={() => setEditing(true)}
          >
            Rename
          </Button>
        ))}
    </header>
  )
}

function Parts({
  entity,
  mode,
  entities,
  relations,
  reads,
  onReveal
}: Pick<RobotSidebarProps, 'entity' | 'mode' | 'entities' | 'relations' | 'onReveal'> & {
  reads: RobotReads | null
}): React.JSX.Element {
  return (
    <section aria-label="Parts">
      {robotCategories(entity, entities, relations).map((row) => (
        <div key={row.key}>
          <h3>
            {row.label} · {row.parts.length}
          </h3>
          {row.parts.length === 0 ? (
            <p>{COPY.empty[mode]}</p>
          ) : (
            <PartList parts={row.parts} tags={reads?.provenance} onReveal={onReveal} />
          )}
        </div>
      ))}
    </section>
  )
}

function RobotRail(props: RobotSidebarProps): React.JSX.Element {
  const { entity, session, state, online, mode, entities, relations, onChanged } = props
  const [armed, setArmed] = useState(false)
  const reads = useRobotReads(session.projectId, entity, online, entities, relations)
  const { attach, error: attachError } = useAttach(session.projectId, entity.id, onChanged)
  const canEdit = online && editableRobot(entity, session.projectId)
  const error = state.error?.key === entity.id ? state.error.message : null
  // Unassigned parts: one read per snapshot, shared by every robot's sidebar. Deferred a
  // microtask because this child effect runs before the hook's `session.activate()` effect.
  useEffect(() => {
    if (!online || ORPHANS_READ.has(entities)) return
    ORPHANS_READ.add(entities)
    void Promise.resolve().then(() => session.load())
  }, [session, online, entities])
  return (
    <>
      <Heading entity={entity} session={session} state={state} canEdit={canEdit} />
      <Parts {...props} reads={reads} />
      <ConnectionStatus entity={entity} reads={reads} />
      <Suggestions reads={reads} mode={mode} projectId={session.projectId} onChanged={onChanged} />
      <RobotOrphans
        session={session}
        state={state}
        mode={mode}
        onAttach={canEdit ? { robotName: entity.name, attach } : undefined}
      />
      {attachError && <p role="alert">{attachError}</p>}
      {canEdit && (
        <TwoStepDelete
          label="Delete robot"
          detail={`Delete ${entity.name}? Its parts and other links are retained.`}
          armed={armed}
          busy={state.busy !== null}
          error={armed ? error : null}
          onArm={() => setArmed(true)}
          onDisarm={() => setArmed(false)}
          onConfirm={() => session.remove(entity)}
        />
      )}
    </>
  )
}

export function RobotSidebar(props: RobotSidebarProps): ReactNode {
  const { entity, mode, entities, relations, onReveal } = props
  if (entity.type !== 'robot_category') return <RobotRail {...props} />
  return (
    <>
      <h2>{entity.name}</h2>
      <p>{COPY.category[mode]}</p>
      <PartList parts={childrenOf(entity.id, entities, relations)} onReveal={onReveal} />
    </>
  )
}
