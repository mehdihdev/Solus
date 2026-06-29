// Minimal workspace home (API.md §5 "/"). Placeholder landing target after
// onboarding completes — the full workspace shell is a separate feature area.
// When onboarding linked to the API it shows the real project + live graph
// stats; otherwise it falls back to the simulated summary.
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button } from '../../components/ui/Button'
import { Mono } from '../../components/ui/Mono'
import { Card } from '../../components/ui/Card'
import { Wordmark } from '../../components/ui/Wordmark'
import { useAuthStore } from '../../store/authStore'
import { useSettingsStore, type SolMode } from '../../store/settingsStore'
import { useWorkspaceStore, type WorkspaceProject } from '../../store/workspaceStore'
import { getProject } from '../../lib/api/resources'

interface GraphStats {
  entities: number
  relations: number
}

export function WorkspaceHome(): React.JSX.Element {
  const navigate = useNavigate()
  const email = useAuthStore((s) => s.user?.email)
  const signOut = useAuthStore((s) => s.signOut)
  const solMode = useSettingsStore((s) => s.solMode)
  const linked = useWorkspaceStore((s) => s.linked)
  const project = useWorkspaceStore((s) => s.project)
  const [stats, setStats] = useState<GraphStats | null>(null)

  useEffect(() => {
    if (!linked || !project) return
    let active = true
    getProject(project.id)
      .then((detail) => {
        if (active) setStats(detail.stats)
      })
      .catch(() => undefined) // best-effort; keep the fallback summary
    return () => {
      active = false
    }
  }, [linked, project])

  const onSignOut = async (): Promise<void> => {
    await signOut()
    useWorkspaceStore.getState().reset()
    navigate('/')
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        background: 'var(--bg)',
        color: 'var(--tx)',
        fontFamily: 'var(--font-ui)',
        display: 'flex',
        flexDirection: 'column'
      }}
    >
      <WorkspaceHeader solMode={solMode} onSignOut={onSignOut} />
      <div
        style={{
          flex: 1,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: 24
        }}
      >
        <ReadyCard project={project} email={email} linked={linked} stats={stats} />
      </div>
    </div>
  )
}

function WorkspaceHeader({
  solMode,
  onSignOut
}: {
  solMode: SolMode
  onSignOut: () => void
}): React.JSX.Element {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '18px 32px',
        borderBottom: '1px solid var(--bd)'
      }}
    >
      <Wordmark size={14} />
      <div style={{ display: 'flex', gap: 14, alignItems: 'center' }}>
        <Mono size={9.5}>SOL · {solMode.toUpperCase()}</Mono>
        <Button kind="ghost" size="sm" onClick={onSignOut}>
          Sign out
        </Button>
      </div>
    </div>
  )
}

interface ReadyCardProps {
  project: WorkspaceProject | null
  email?: string
  linked: boolean
  stats: GraphStats | null
}

function ReadyCard({ project, email, linked, stats }: ReadyCardProps): React.JSX.Element {
  return (
    <Card pad={32} style={{ width: 560, textAlign: 'center' }}>
      <h2 style={{ margin: 0, fontSize: 24, fontWeight: 600, letterSpacing: '-0.02em' }}>
        Your context model is ready
      </h2>
      {project && (
        <div style={{ marginTop: 8 }}>
          <Mono size={10} color="var(--acc)">
            {project.name}
          </Mono>
        </div>
      )}
      <p style={{ color: 'var(--mut)', fontSize: 13.5, marginTop: 10, lineHeight: 1.6 }}>
        Welcome{email ? `, ${email}` : ''}. The graph explorer, Live Bench, and SOL agent land here
        next — this is the placeholder home that onboarding hands off to.
      </p>
      <div style={{ marginTop: 20 }}>
        {linked && stats ? (
          <Mono size={10} color="var(--ok)">
            LIVE · {stats.entities} ENTITIES · {stats.relations} RELATIONS · API LINKED
          </Mono>
        ) : (
          <Mono size={10}>247 NODES · 31 CROSS-DOMAIN LINKS · 2 OPEN ISSUES</Mono>
        )}
      </div>
    </Card>
  )
}
