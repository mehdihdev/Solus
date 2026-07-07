// Workspace home (API.md §5 "/"): the signed-in user's projects across their
// teams, plus a recent cross-team activity feed and create-project / create-team
// actions. Falls back to a friendly single-project card when offline (dev
// bypass) so the demo still lands somewhere useful.
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import { Spinner } from '../../components/ui/Spinner'
import { Icons } from '../../components/ui/icons.constants'
import { relativeTime } from '../../lib/relativeTime'
import type { Project } from '../../lib/api/resources'
import { activityText } from '../team/activityText'
import { FALLBACK_PROJECT_NAME } from './workspaceData.constants'
import { displayName, useMe } from './useMe'
import { useHomeData, type HomeData } from './useHomeData'

export interface HomeScreenProps {
  onOpenProject: (project: { id: string; name: string }) => void
}

export function HomeScreen({ onOpenProject }: HomeScreenProps): React.JSX.Element {
  const me = useMe()
  const home = useHomeData()
  const greeting = `Welcome back, ${displayName(me.name, me.email)}`

  if (home.status === 'loading') {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Spinner size={20} />
      </div>
    )
  }

  return (
    <div style={{ flex: 1, overflowY: 'auto', minWidth: 0 }}>
      <div style={{ maxWidth: 980, margin: '0 auto', padding: '26px 24px 48px' }}>
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 600, letterSpacing: '-0.015em' }}>
          {greeting}
        </h1>
        <div style={{ fontSize: 12.5, color: 'var(--mut)', marginTop: 4 }}>
          Your robots across every team.
        </div>
        {home.status === 'offline' ? (
          <OfflineHome onOpenProject={onOpenProject} />
        ) : (
          <LiveHome home={home} onOpenProject={onOpenProject} />
        )}
      </div>
    </div>
  )
}

function LiveHome({
  home,
  onOpenProject
}: {
  home: HomeData
  onOpenProject: HomeScreenProps['onOpenProject']
}): React.JSX.Element {
  const [creatingFor, setCreatingFor] = useState<string | null>(null)
  const [creatingTeam, setCreatingTeam] = useState(false)
  const totalProjects = home.groups.reduce((n, g) => n + g.projects.length, 0)

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 16 }}>
        <Button kind="ghost" size="sm" onClick={() => setCreatingTeam(true)}>
          <Icons.team size={13} /> New team
        </Button>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(0,1fr) 340px',
          gap: 16,
          marginTop: 12,
          alignItems: 'start'
        }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {home.groups.map((group) => (
            <Card key={group.team.team_id} pad={0}>
              <div
                style={{
                  padding: '12px 16px',
                  borderBottom: '1px solid var(--bd)',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center'
                }}
              >
                <span style={{ fontSize: 13, fontWeight: 600 }}>
                  {group.team.name}
                  {group.team.is_personal && (
                    <Mono size={8.5} color="var(--mut)" style={{ marginLeft: 8 }}>
                      PERSONAL
                    </Mono>
                  )}
                </span>
                <Button kind="ghost" size="sm" onClick={() => setCreatingFor(group.team.team_id)}>
                  <Icons.plus size={12} /> New project
                </Button>
              </div>
              {group.projects.length === 0 ? (
                <div style={{ padding: '16px', fontSize: 12, color: 'var(--mut)' }}>
                  No projects yet. Create one to start building the graph.
                </div>
              ) : (
                group.projects.map((p) => (
                  <ProjectRow key={p.id} project={p} onOpen={onOpenProject} />
                ))
              )}
            </Card>
          ))}
          {totalProjects === 0 && home.groups.length === 0 && (
            <Card pad={20}>
              <div style={{ fontSize: 12.5, color: 'var(--mut)' }}>
                You&apos;re not on any teams yet.
              </div>
            </Card>
          )}
        </div>

        <RecentActivity activity={home.activity} />
      </div>

      {creatingFor && (
        <NameModal
          title="New project"
          label="Project name"
          onClose={() => setCreatingFor(null)}
          onSubmit={async (name) => {
            const created = await home.actions.createProject(creatingFor, name)
            setCreatingFor(null)
            if (created) onOpenProject({ id: created.id, name: created.name })
          }}
        />
      )}
      {creatingTeam && (
        <NameModal
          title="New team"
          label="Team name"
          onClose={() => setCreatingTeam(false)}
          onSubmit={async (name) => {
            await home.actions.createTeam(name)
            setCreatingTeam(false)
          }}
        />
      )}
    </>
  )
}

function ProjectRow({
  project,
  onOpen
}: {
  project: Project
  onOpen: HomeScreenProps['onOpenProject']
}): React.JSX.Element {
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onOpen({ id: project.id, name: project.name })}
      onKeyDown={(e) => e.key === 'Enter' && onOpen({ id: project.id, name: project.name })}
      style={{
        display: 'flex',
        gap: 12,
        alignItems: 'center',
        padding: '12px 16px',
        borderBottom: '1px solid var(--bd)',
        cursor: 'pointer'
      }}
    >
      <span style={{ color: 'var(--acc)' }}>
        <Icons.graph size={15} />
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12.5, fontWeight: 600 }}>{project.name}</div>
        {project.description && (
          <div style={{ fontSize: 11, color: 'var(--mut)' }}>{project.description}</div>
        )}
      </div>
      <span style={{ color: 'var(--mut)' }}>
        <Icons.arrowR size={12} />
      </span>
    </div>
  )
}

function RecentActivity({ activity }: { activity: HomeData['activity'] }): React.JSX.Element {
  return (
    <Card pad={0}>
      <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--bd)' }}>
        <Mono size={9.5}>RECENT ACTIVITY</Mono>
      </div>
      {activity.length === 0 ? (
        <div style={{ padding: '16px', fontSize: 12, color: 'var(--mut)' }}>Nothing yet.</div>
      ) : (
        activity.map((a) => (
          <div key={a.id} style={{ padding: '11px 16px', borderBottom: '1px solid var(--bd)' }}>
            <div style={{ fontSize: 12, lineHeight: 1.5 }}>{activityText(a)}</div>
            <div style={{ fontSize: 10, color: 'var(--mut)', marginTop: 3 }}>
              {relativeTime(a.created_at)}
            </div>
          </div>
        ))
      )}
    </Card>
  )
}

function OfflineHome({
  onOpenProject
}: {
  onOpenProject: HomeScreenProps['onOpenProject']
}): React.JSX.Element {
  return (
    <Card pad={0} style={{ marginTop: 16 }}>
      <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--bd)' }}>
        <Mono size={9.5}>YOUR PROJECT</Mono>
      </div>
      <ProjectRow
        project={{
          id: 'demo',
          name: FALLBACK_PROJECT_NAME,
          team_id: 'demo',
          description: 'Six-wheel autonomous rover',
          created_at: '',
          updated_at: ''
        }}
        onOpen={onOpenProject}
      />
      <div style={{ padding: '12px 16px', fontSize: 11, color: 'var(--mut)', lineHeight: 1.5 }}>
        Connect the workspace to your account to see every team and project here.
      </div>
    </Card>
  )
}

function NameModal({
  title,
  label,
  onClose,
  onSubmit
}: {
  title: string
  label: string
  onClose: () => void
  onSubmit: (name: string) => void | Promise<void>
}): React.JSX.Element {
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async (): Promise<void> => {
    if (!name.trim()) return
    setBusy(true)
    await onSubmit(name.trim())
  }
  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.55)',
        zIndex: 70,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center'
      }}
      onClick={onClose}
    >
      <div onClick={(e) => e.stopPropagation()}>
        <Card pad={24} style={{ width: 360, boxShadow: '0 18px 60px rgba(0,0,0,0.5)' }}>
          <div style={{ fontSize: 16, fontWeight: 600 }}>{title}</div>
          <input
            aria-label={label}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={label}
            autoFocus
            onKeyDown={(e) => e.key === 'Enter' && void submit()}
            style={{
              width: '100%',
              boxSizing: 'border-box',
              marginTop: 16,
              background: 'var(--bg)',
              color: 'var(--tx)',
              border: '1px solid var(--bd)',
              borderRadius: 3,
              padding: '10px 12px',
              fontSize: 13,
              fontFamily: 'var(--font-ui)',
              outline: 'none'
            }}
          />
          <div style={{ display: 'flex', gap: 8, marginTop: 16, justifyContent: 'flex-end' }}>
            <Button kind="ghost" size="sm" onClick={onClose}>
              Cancel
            </Button>
            <Button kind="primary" size="sm" onClick={() => void submit()}>
              {busy ? <Spinner size={11} color="var(--acc-ink)" /> : 'Create'}
            </Button>
          </div>
        </Card>
      </div>
    </div>
  )
}
