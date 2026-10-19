// The project pane's SOURCES block (SOLUSDEV-317): one row per tool this
// project uses, or could use from an account already linked — its logo, what
// it holds in THIS project (a git source by its repo, anything else by name,
// with entity count or the source's own error), and the tool's project-level
// next step (Pick documents, Pick repositories, Choose file…) through the same
// wizard as Connected accounts. "Add additional sources" opens that card for
// tools not linked yet. Honest states; never an invented row.
import type { Source, SourceStatus } from '../../lib/api/resources'
import type { WorkspaceProject } from '../../store/workspaceStore'
import { Button } from '../../components/ui/Button'
import { Mono } from '../../components/ui/Mono'
import type { CatalogEntry } from '../onboarding/integrationCatalog'
import type { WizardScope } from '../onboarding/connectSteps'
import { useIntegrationCatalog } from '../onboarding/useIntegrationCatalog'
import { useProjectSources } from '../project/useProjectSources'
import { CardWizardModal, ProviderMark } from './ConnectedAccountsCard'
import { nextStep, useCardWizard } from './accountSteps'
import { LOCAL_FOLDER_MARK, LOCAL_SOURCE_TYPE } from './connectedAccounts'
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

/** One tool on the block: its catalog entry (null for a local folder) and what
 *  this project holds from it. */
interface ToolGroup {
  key: string
  entry: CatalogEntry | null
  linked: boolean
  held: Source[]
}

/** A git source is its repo; anything else (a local folder's machine) its name. */
function sourceLabel(source: Source): string {
  // The row's title already says "Local folder": its items are machines.
  if (source.type === LOCAL_SOURCE_TYPE) return source.name
  const repo = source.config['repo']
  return typeof repo === 'string' && repo.length > 0 ? repo : source.name
}

/** Tools holding something here first, then linked tools with nothing yet. */
function toolGroups(
  catalog: readonly CatalogEntry[],
  sources: readonly Source[],
  linkedProviders: ReadonlySet<string>
): ToolGroup[] {
  const groups: ToolGroup[] = catalog
    .filter((e) => e.mode !== 'local-bridge')
    .map((entry) => ({
      key: entry.id,
      entry,
      linked: linkedProviders.has(entry.id),
      held: sources.filter((s) => s.type === entry.id)
    }))
    .filter((g) => g.linked || g.held.length > 0)
  const local = sources.filter((s) => s.type === LOCAL_SOURCE_TYPE)
  const all =
    local.length > 0
      ? [...groups, { key: LOCAL_SOURCE_TYPE, entry: null, linked: false, held: local }]
      : groups
  return [...all].sort((a, b) => Number(b.held.length > 0) - Number(a.held.length > 0))
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
        <Rows status={sources.status} groups={shown} onStep={open} />
        {groups.length > shown.length && <Note>+{groups.length - shown.length} more</Note>}
      </div>
      <button type="button" className="interactive" onClick={onAdd} style={LINK_BUTTON}>
        Add additional sources
      </button>
      <CardWizardModal wizard={wizard} scope={scope} />
    </div>
  )
}

function Rows({
  status,
  groups,
  onStep
}: {
  status: 'loading' | 'ready' | 'offline'
  groups: readonly ToolGroup[]
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
      {groups.map((g) => (
        <ToolRow key={g.key} group={g} onStep={onStep} />
      ))}
    </>
  )
}

function ToolRow({
  group,
  onStep
}: {
  group: ToolGroup
  onStep: (entry: CatalogEntry, scope: WizardScope) => void
}): React.JSX.Element {
  const { entry, held } = group
  const step = entry ? nextStep(entry, group.linked) : null
  const mark = entry ?? { id: LOCAL_SOURCE_TYPE, mark: LOCAL_FOLDER_MARK }
  return (
    <div data-testid={`source-tool-${group.key}`} style={ROW}>
      <ProviderMark entry={mark} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12.5, fontWeight: 600 }}>{entry?.name ?? 'Local folder'}</div>
        {held.length === 0 ? (
          <div style={{ fontSize: 11, color: 'var(--mut)' }}>Nothing in this project yet</div>
        ) : (
          held.map((s) => <HeldItem key={s.id} source={s} />)
        )}
      </div>
      {entry && step && (
        <Button
          kind="soft"
          size="sm"
          aria-label={`${step.action} for ${entry.name}`}
          onClick={() => onStep(entry, step.scope)}
        >
          {step.action}
        </Button>
      )}
    </div>
  )
}

function HeldItem({ source }: { source: Source }): React.JSX.Element {
  const error = source.status === 'error' ? source.last_error : null
  // The item (a GitHub repo, a document) gets its own line in full — beside
  // the count and the step button it clipped to a few letters.
  return (
    <div style={{ marginTop: 3, minWidth: 0 }}>
      <div
        style={{ fontSize: 12, color: 'var(--tx)', whiteSpace: 'normal', overflowWrap: 'anywhere' }}
      >
        {sourceLabel(source)}
      </div>
      {error ? (
        <div style={{ fontSize: 11, color: 'var(--err)', overflowWrap: 'anywhere' }}>
          {error.message}
        </div>
      ) : (
        <Mono size={9} color={STATUS_TONE[source.status]} style={{ whiteSpace: 'nowrap' }}>
          {source.entity_count !== undefined
            ? `${source.entity_count.toLocaleString('en-US')} ENTITIES`
            : source.status.toUpperCase()}
        </Mono>
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
  marginTop: 10,
  background: 'transparent',
  border: 'none',
  color: 'var(--acc)',
  cursor: 'pointer',
  fontFamily: 'var(--font-ui)',
  fontSize: 12,
  padding: 0
}

const ROW: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 10,
  padding: '10px 0',
  borderBottom: '1px solid var(--bd)'
}
