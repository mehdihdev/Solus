// The project pane's SOURCES block (SOLUSDEV-317): one row per tool this
// project uses, or could use from an account already linked — its logo, what
// it holds in THIS project (a git source by its repo, anything else by name,
// with entity count or the source's own error), and the tool's project-level
// next step (Pick documents, Pick repositories, Choose file…) through the same
// wizard as Connected accounts. "Add additional sources" opens that card for
// tools not linked yet. Honest states; never an invented row.
import { homeStagger } from './homeMotion'
import type { Source, SourceStatus } from '../../lib/api/resources'
import type { WorkspaceProject } from '../../store/workspaceStore'
import { getDesktopFolderBridge } from '../../lib/desktopBridge'
import { Mono } from '../../components/ui/Mono'
import type { CatalogEntry } from '../onboarding/integrationCatalog'
import type { WizardScope } from '../onboarding/connectSteps'
import { useIntegrationCatalog } from '../onboarding/useIntegrationCatalog'
import { useProjectFolderStore } from '../project/projectFolderStore'
import { useProjectSources } from '../project/useProjectSources'
import { CardWizardModal, ProviderMark } from './ConnectedAccountsCard'
import { nextStep, useCardWizard } from './accountSteps'
import { LOCAL_FOLDER_MARK, LOCAL_SOURCE_TYPE } from './connectedAccounts'
import { sourceLabel, toolGroups, type ToolGroup } from './sourceGroups'
import { linkedAccountFor, useAccountConnections } from './useAccountConnections'

/** The meta text colour per state. */
const STATUS_TONE: Readonly<Record<SourceStatus, string>> = {
  connected: 'var(--ok)',
  syncing: 'var(--acc)',
  pending: 'var(--mut)',
  error: 'var(--err)',
  disconnected: 'var(--warn)'
}

export interface ProjectSourcesSummaryProps {
  project: WorkspaceProject
  /** Opens Connected accounts, where tools not linked yet are added. */
  onAdd: () => void
  /** Show at most this many tools, then "+N more"; omit for all. */
  limit?: number
}

export function ProjectSourcesSummary({
  project,
  onAdd,
  limit
}: ProjectSourcesSummaryProps): React.JSX.Element {
  const catalog = useIntegrationCatalog()
  const accounts = useAccountConnections()
  const sources = useProjectSources()
  const { wizard, scope, open } = useCardWizard(project, accounts, sources)
  const linked = new Set(
    catalog.filter((e) => linkedAccountFor(accounts.connections, e.id)).map((e) => e.id)
  )
  const groups = toolGroups(catalog, sources.sources, linked)
  const shown = limit === undefined ? groups : groups.slice(0, limit)
  return (
    <div>
      <Mono size={9.5} color="var(--mut)" style={{ letterSpacing: '0.08em' }}>
        SOURCES
      </Mono>
      <div style={{ marginTop: 4 }}>
        <Rows status={sources.status} groups={shown} projectId={project.id} onStep={open} />
        {groups.length > shown.length && <Note>+{groups.length - shown.length} more</Note>}
      </div>
      <button
        type="button"
        className="interactive"
        onClick={onAdd}
        style={{ ...LINK_BUTTON, marginTop: 10 }}
      >
        Add additional sources
      </button>
      <CardWizardModal wizard={wizard} scope={scope} />
    </div>
  )
}

function Rows({
  status,
  groups,
  projectId,
  onStep
}: {
  status: 'loading' | 'ready' | 'offline'
  groups: readonly ToolGroup[]
  projectId: string
  onStep: (entry: CatalogEntry, scope: WizardScope) => void
}): React.JSX.Element {
  if (status === 'loading') return <Note>Loading sources…</Note>
  if (status === 'offline')
    return (
      <Note>
        Solus can&apos;t reach its API — this project&apos;s sources will appear here when it can.
      </Note>
    )
  if (groups.length === 0)
    return <Note>No sources connected yet. Add a repo, export or document to start the graph.</Note>
  return (
    <>
      {groups.map((g, i) => (
        <ToolRow key={g.key} index={i} group={g} projectId={projectId} onStep={onStep} />
      ))}
    </>
  )
}

/** One tool: mark | name and its items | entities | the next step as a link. */
function ToolRow({
  index,
  group,
  projectId,
  onStep
}: {
  index: number
  group: ToolGroup
  projectId: string
  onStep: (entry: CatalogEntry, scope: WizardScope) => void
}): React.JSX.Element {
  const { entry, held } = group
  const mark = entry ?? { id: LOCAL_SOURCE_TYPE, mark: LOCAL_FOLDER_MARK }
  return (
    <div
      data-testid={`source-tool-${group.key}`}
      data-linked={group.link}
      className="home-row-in"
      style={{
        ...ROW,
        ...homeStagger(index),
        borderBottom: group.link === 'below' ? 'none' : ROW.borderBottom
      }}
    >
      <span
        style={{
          position: 'relative',
          display: 'flex',
          alignSelf: 'stretch',
          alignItems: 'center'
        }}
      >
        <ProviderMark entry={mark} />
        {group.link && <CloneConnector side={group.link} />}
      </span>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 12.5, fontWeight: 600 }}>{entry?.name ?? 'Local folder'}</div>
        {held.length === 0 ? (
          <div style={{ fontSize: 12, color: 'var(--mut)' }}>Nothing in this project yet</div>
        ) : (
          held.map((s) => <HeldItem key={s.id} source={s} />)
        )}
        <CloneNote group={group} />
      </div>
      <Count held={held} />
      {entry ? (
        <StepLink entry={entry} linked={group.linked} onStep={onStep} />
      ) : (
        <OpenFolderLink projectId={projectId} />
      )}
    </div>
  )
}

function StepLink({
  entry,
  linked,
  onStep
}: {
  entry: CatalogEntry
  linked: boolean
  onStep: (entry: CatalogEntry, scope: WizardScope) => void
}): React.JSX.Element {
  const step = nextStep(entry, linked)
  return (
    <button
      type="button"
      className="interactive"
      aria-label={`${step.action} for ${entry.name}`}
      onClick={() => onStep(entry, step.scope)}
      style={LINK_BUTTON}
    >
      {step.action} ›
    </button>
  )
}

/** The line joining a repo's row to the local folder that clones it: from
 *  the logo to the row edge, toward the paired row. */
function CloneConnector({ side }: { side: 'above' | 'below' }): React.JSX.Element {
  return (
    <span
      aria-hidden="true"
      style={{
        position: 'absolute',
        left: 13,
        width: 2,
        background: 'var(--acc)',
        opacity: 0.6,
        ...(side === 'below'
          ? { top: 'calc(50% + 14px)', bottom: -10 }
          : { top: -10, bottom: 'calc(50% + 14px)' })
      }}
    />
  )
}

/** What the pairing means, in words, on each end. */
function CloneNote({ group }: { group: ToolGroup }): React.JSX.Element | null {
  const text = group.clonedOn
    ? `Cloned on ${group.clonedOn}`
    : group.cloneOf
      ? `Clone of ${group.cloneOf}`
      : null
  if (!text) return null
  return <div style={{ fontSize: 11, color: 'var(--acc)', marginTop: 2 }}>{text}</div>
}

/** Reveals THIS machine's linked folder; nothing when it isn't linked here. */
function OpenFolderLink({ projectId }: { projectId: string }): React.JSX.Element {
  const path = useProjectFolderStore((s) => s.folders[projectId]?.path ?? null)
  const bridge = getDesktopFolderBridge()
  if (!path || !bridge) return <span />
  return (
    <button
      type="button"
      className="interactive"
      aria-label="Open folder"
      onClick={() => void bridge.reveal(path)}
      style={LINK_BUTTON}
    >
      Open folder ›
    </button>
  )
}

/** The tool's entities in this project, or a status word when none report a count. */
function Count({ held }: { held: readonly Source[] }): React.JSX.Element {
  if (held.length === 0) return <span />
  const counted = held.filter((s) => s.entity_count !== undefined)
  const first = held[0]
  const text =
    counted.length > 0
      ? `${counted.reduce((n, s) => n + (s.entity_count ?? 0), 0).toLocaleString('en-US')} ENTITIES`
      : first.status.toUpperCase()
  const tone = held.some((s) => s.status === 'error') ? 'var(--err)' : STATUS_TONE[first.status]
  return (
    <Mono size={9.5} color={tone} style={{ whiteSpace: 'nowrap', textAlign: 'right' }}>
      {text}
    </Mono>
  )
}

/** One item the tool holds here (a GitHub repo, a document): its own line in
 *  full, and the source's own error beneath it when its sync failed. */
function HeldItem({ source }: { source: Source }): React.JSX.Element {
  const error = source.status === 'error' ? source.last_error : null
  return (
    <div style={{ minWidth: 0 }}>
      <div
        style={{
          fontSize: 12,
          color: 'var(--mut)',
          whiteSpace: 'normal',
          overflowWrap: 'anywhere'
        }}
      >
        {sourceLabel(source)}
      </div>
      {error && (
        <div style={{ fontSize: 11, color: 'var(--err)', overflowWrap: 'anywhere' }}>
          {error.message}
        </div>
      )}
    </div>
  )
}

function Note({ children }: { children: React.ReactNode }): React.JSX.Element {
  return (
    <div style={{ fontSize: 12, color: 'var(--mut)', lineHeight: 1.5, padding: '6px 0' }}>
      {children}
    </div>
  )
}

const LINK_BUTTON: React.CSSProperties = {
  justifySelf: 'end',
  whiteSpace: 'nowrap',
  background: 'transparent',
  border: 'none',
  color: 'var(--acc)',
  cursor: 'pointer',
  fontFamily: 'var(--font-ui)',
  fontSize: 12,
  padding: 0
}

const ROW: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: '32px minmax(0, 1fr) 96px 132px',
  gap: 12,
  alignItems: 'center',
  padding: '10px 0',
  borderBottom: '1px solid var(--bd)'
}
