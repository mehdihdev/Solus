// Home's project pane (SOLUSDEV-317, concept B): everything Home knows about
// the CURRENT project in one place — its header (Live Bench, Open workspace)
// and four tabs. Overview is the at-a-glance row (ON THIS COMPUTER, SOURCES,
// .solus) over RECENT IN THIS PROJECT; Sources, .solus and Activity are the
// full versions. Each card keeps its own rules (docs/wireflows/home.md).
import { useId, useLayoutEffect, useRef, useState } from 'react'
import type { ActivityApi } from '../../lib/api/resources'
import type { WorkspaceProject } from '../../store/workspaceStore'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import { Icons } from '../../components/ui/icons.constants'
import { ProjectFolderCard } from '../project/ProjectFolderCard'
import { ProjectActivityFeed } from './ProjectActivityFeed'
import { ProjectSetupList } from './ProjectSetupList'
import { homeStagger } from './homeMotion'
import { relativeTime } from '../../lib/relativeTime'
import { activityText } from '../team/activityText'
import { HOME_PANE_ACTIVITY_COUNT } from './projectActivity'
import { ProjectSourcesSummary } from './ProjectSourcesSummary'
import { RepoLine } from './RepoLine'
import type { LinkedRepo } from './useProjectRepos'
import { SolusCard } from './SolusCard'

type PaneTab = 'overview' | 'sources' | 'solus' | 'activity'

const TABS: ReadonlyArray<{ id: PaneTab; label: string }> = [
  { id: 'overview', label: 'Overview' },
  { id: 'sources', label: 'Sources' },
  { id: 'solus', label: '.solus' },
  { id: 'activity', label: 'Activity' }
]

export interface HomeProjectPaneProps {
  project: WorkspaceProject
  description: string | null
  /** The project's own rows from Home's team-feed window, newest first. */
  activity: readonly ActivityApi[]
  /** The project's linked git repos, named under its title. */
  repos: readonly LinkedRepo[]
  onOpen: () => void
  onBench: () => void
  onManageSources: () => void
}

export function HomeProjectPane(props: HomeProjectPaneProps): React.JSX.Element {
  const [tab, setTab] = useState<PaneTab>('overview')
  const base = useId()
  const tabId = (id: PaneTab): string => `${base}-tab-${id}`
  const panelId = `${base}-panel`
  const indicator = useTabIndicator(tabId(tab))
  // Arrow keys move along the tabs (wrapping) and select as they go.
  const onKeyDown = (e: React.KeyboardEvent): void => {
    const step = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0
    if (step === 0) return
    e.preventDefault()
    const index = TABS.findIndex((t) => t.id === tab)
    const next = TABS[(index + step + TABS.length) % TABS.length].id
    setTab(next)
    document.getElementById(tabId(next))?.focus()
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18, minWidth: 0 }}>
      <PaneHeader {...props} />
      <div
        role="tablist"
        aria-label="Project"
        onKeyDown={onKeyDown}
        style={{
          position: 'relative',
          display: 'flex',
          gap: 22,
          borderBottom: '1px solid var(--bd)'
        }}
      >
        {TABS.map((t) => (
          <TabButton
            key={t.id}
            id={tabId(t.id)}
            controls={panelId}
            label={t.label}
            selected={tab === t.id}
            onClick={() => setTab(t.id)}
          />
        ))}
        <span
          ref={indicator}
          aria-hidden="true"
          data-testid="tab-indicator"
          className="home-tab-indicator"
          style={{
            position: 'absolute',
            left: 0,
            bottom: -1,
            height: 2,
            background: 'var(--acc)',
            borderRadius: 1
          }}
        />
      </div>
      {/* Keyed per tab, so each switch eases in. */}
      <div
        key={tab}
        role="tabpanel"
        id={panelId}
        aria-labelledby={tabId(tab)}
        tabIndex={0}
        className="home-pane-in"
      >
        <TabBody
          tab={tab}
          pane={props}
          onShowActivity={() => setTab('activity')}
          onShowSolus={() => setTab('solus')}
        />
      </div>
    </div>
  )
}

/** Moves the one indicator under the selected tab. Written straight to the
 *  bar's style (no state, no extra render); the CSS transition does the slide. */
function useTabIndicator(selectedId: string): React.RefObject<HTMLSpanElement | null> {
  const bar = useRef<HTMLSpanElement>(null)
  useLayoutEffect(() => {
    const tab = document.getElementById(selectedId)
    if (!tab || !bar.current) return
    bar.current.style.width = `${tab.offsetWidth}px`
    bar.current.style.transform = `translateX(${tab.offsetLeft}px)`
  }, [selectedId])
  return bar
}

function TabBody({
  tab,
  pane,
  onShowActivity,
  onShowSolus
}: {
  tab: PaneTab
  pane: HomeProjectPaneProps
  onShowActivity: () => void
  onShowSolus: () => void
}): React.JSX.Element {
  const { project, onManageSources } = pane
  if (tab === 'overview')
    return <Overview {...pane} onShowActivity={onShowActivity} onShowSolus={onShowSolus} />
  if (tab === 'solus') return <SolusCard projectId={project.id} projectName={project.name} />
  if (tab === 'activity')
    return project.teamId ? (
      <ProjectActivityFeed project={{ id: project.id, teamId: project.teamId }} />
    ) : (
      <Card pad={16}>
        <div style={{ fontSize: 12, color: 'var(--mut)' }}>
          This project&apos;s team isn&apos;t known yet — reopen it from the list.
        </div>
      </Card>
    )
  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <ProjectFolderCard key={project.id} projectId={project.id} heading="LOCAL FOLDER" />
      <Card pad={16}>
        <ProjectSourcesSummary project={project} onAdd={onManageSources} />
      </Card>
    </div>
  )
}

function PaneHeader({
  project,
  description,
  repos,
  onOpen,
  onBench
}: HomeProjectPaneProps): React.JSX.Element {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-end', gap: 12 }}>
      <div style={{ flex: '1 1 240px', minWidth: 0 }}>
        <Mono size={9.5} color="var(--acc)" style={{ letterSpacing: '0.08em' }}>
          CURRENT PROJECT
        </Mono>
        <h2 style={{ margin: '6px 0 0', fontSize: 20, fontWeight: 600, letterSpacing: '-0.01em' }}>
          {project.name}
        </h2>
        <div style={{ marginTop: 4 }}>
          <RepoLine repos={repos} size="md" />
        </div>
        {description && (
          <div style={{ marginTop: 2, fontSize: 12.5, color: 'var(--mut)' }}>{description}</div>
        )}
      </div>
      <Button kind="ghost" size="md" onClick={onBench}>
        Live Bench
      </Button>
      <Button kind="primary" size="md" onClick={onOpen}>
        Open workspace
      </Button>
    </div>
  )
}

function TabButton({
  id,
  controls,
  label,
  selected,
  onClick
}: {
  id: string
  controls: string
  label: string
  selected: boolean
  onClick: () => void
}): React.JSX.Element {
  return (
    <button
      type="button"
      role="tab"
      id={id}
      aria-controls={controls}
      aria-selected={selected}
      tabIndex={selected ? 0 : -1}
      onClick={onClick}
      style={{
        background: 'transparent',
        border: 'none',
        // The accent underline is the shared sliding indicator, not each tab's border.
        borderBottom: '2px solid transparent',
        transition: 'color 0.18s ease',
        color: selected ? 'var(--tx)' : 'var(--mut)',
        cursor: 'pointer',
        fontFamily: 'var(--font-ui)',
        fontSize: 13,
        padding: '0 0 9px'
      }}
    >
      {label}
    </button>
  )
}

/** Concept 1: one PROJECT SETUP list beside a RECENT activity rail. */
function Overview({
  project,
  activity,
  onManageSources,
  onShowActivity,
  onShowSolus
}: HomeProjectPaneProps & {
  onShowActivity: () => void
  onShowSolus: () => void
}): React.JSX.Element {
  return (
    <div style={OVERVIEW_GRID}>
      <ProjectSetupList
        project={project}
        onAddSources={onManageSources}
        onAddInstructions={onShowSolus}
      />
      <RecentRail activity={activity} onShowAll={onShowActivity} />
    </div>
  )
}

/** The dot beside an activity row: connected/created ok, disconnected warn,
 *  a sync the accent, anything else muted. */
function activityTone(type: string): string {
  if (type.includes('disconnect') || type.includes('delete')) return 'var(--warn)'
  if (type.includes('connect') || type.includes('create')) return 'var(--ok)'
  if (type.includes('sync')) return 'var(--acc)'
  return 'var(--mut)'
}

function RecentRail({
  activity,
  onShowAll
}: {
  activity: readonly ActivityApi[]
  onShowAll: () => void
}): React.JSX.Element {
  const preview = activity.slice(0, HOME_PANE_ACTIVITY_COUNT)
  return (
    <Card pad={16} style={{ minWidth: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 6 }}>
        <Mono size={10} color="var(--mut)" style={{ letterSpacing: '0.08em' }}>
          RECENT
        </Mono>
        <div style={{ flex: 1 }} />
        <button type="button" className="interactive" onClick={onShowAll} style={LINK_BUTTON}>
          All activity <Icons.arrowR size={11} />
        </button>
      </div>
      {preview.length === 0 ? (
        <div style={{ fontSize: 12, color: 'var(--mut)', padding: '6px 0' }}>
          No recent activity.
        </div>
      ) : (
        preview.map((a, i) => (
          <div key={a.id} className="home-row-in" style={{ ...RAIL_ROW, ...homeStagger(i) }}>
            <span aria-hidden="true" style={{ ...RAIL_DOT, background: activityTone(a.type) }} />
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 12.5, lineHeight: 1.4 }}>{activityText(a)}</div>
              <div style={{ fontSize: 11, color: 'var(--mut)', marginTop: 2 }}>
                {relativeTime(a.created_at)}
              </div>
            </div>
          </div>
        ))
      )}
    </Card>
  )
}

const OVERVIEW_GRID: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'minmax(0, 2fr) minmax(240px, 1fr)',
  gap: 20,
  alignItems: 'start'
}

const RAIL_ROW: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: '10px minmax(0, 1fr)',
  gap: 10,
  padding: '8px 0'
}

const RAIL_DOT: React.CSSProperties = { width: 7, height: 7, marginTop: 5, borderRadius: '50%' }

const LINK_BUTTON: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 4,
  background: 'transparent',
  border: 'none',
  color: 'var(--acc)',
  cursor: 'pointer',
  fontFamily: 'var(--font-ui)',
  fontSize: 12,
  padding: 0
}
