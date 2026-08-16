// Onboarding step 1 — "Connect your tools". Tiles are listed from the LIVE
// backend catalog (SOLUSDEV-100; curated drivable fallback offline) and open
// the connect wizard (SOLUSDEV-165), which drives the REAL flows — OAuth
// bridge or committed-export file pick. There is no simulated connect
// (SOLUSDEV-152): when a real connect can't run (workspace unlinked / no
// Electron bridge) the wizard reports an honest, retryable error. On entering
// this step we ensure a project exists so a real connect has something to
// attach a source to.
import { useEffect } from 'react'
import { Button } from '../../components/ui/Button'
import { Mono } from '../../components/ui/Mono'
import { Icons } from '../../components/ui/icons.constants'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useSettingsStore } from '../../store/settingsStore'
import { ConnectCatalog } from './ConnectCatalog'
import { MIN_SOURCES_TO_BUILD } from './integrations.constants'
import { useIntegrationCatalog } from './useIntegrationCatalog'
import { useOnboardingStore, connectedCount, canBuildModel } from './onboardingStore'
import { ensureWorkspace } from './provisioning'

interface ConnectStepProps {
  onBuild: () => void
}

export function ConnectStep({ onBuild }: ConnectStepProps): React.JSX.Element {
  const connections = useOnboardingStore((s) => s.connections)
  const description = useOnboardingStore((s) => s.description)
  const solMode = useSettingsStore((s) => s.solMode)
  const workspace = useWorkspaceStore()
  const catalog = useIntegrationCatalog()

  // Ensure a project exists as soon as we reach the connect step, reusing one
  // already created earlier in the flow. Best-effort; never blocks the UI.
  useEffect(() => {
    let cancelled = false
    void ensureWorkspace({
      description,
      solMode,
      existing: { teamId: workspace.teamId, project: workspace.project }
    }).then((result) => {
      if (cancelled) return
      workspace.setLinked(result.linked)
      if (result.teamId) workspace.setTeamId(result.teamId)
      if (result.project) workspace.setProject(result.project)
    })
    return () => {
      cancelled = true
    }
    // Run once on mount; workspace setters are stable store actions.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const count = connectedCount(connections)
  const ready = canBuildModel(connections)

  return (
    <div style={{ width: 660 }}>
      <h2 style={{ margin: 0, fontSize: 28, fontWeight: 600, letterSpacing: '-0.02em' }}>
        Connect your tools
      </h2>
      <p style={{ color: 'var(--mut)', fontSize: 13.5, marginTop: 8, lineHeight: 1.55 }}>
        Each source becomes a domain in your context model. Connect at least two — cross-domain
        checks need something to cross.
      </p>
      <ConnectCatalog
        projectId={workspace.linked && workspace.project ? workspace.project.id : null}
        gridStyle={{ marginTop: 24 }}
      />
      <StepFooter
        connectedTotal={count}
        catalogTotal={catalog.length}
        ready={ready}
        onBuild={onBuild}
      />
    </div>
  )
}

function StepFooter({
  connectedTotal,
  catalogTotal,
  ready,
  onBuild
}: {
  connectedTotal: number
  catalogTotal: number
  ready: boolean
  onBuild: () => void
}): React.JSX.Element {
  return (
    <>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginTop: 28
        }}
      >
        <Mono size={10} color={ready ? 'var(--ok)' : 'var(--mut)'}>
          {connectedTotal} OF {catalogTotal} CONNECTED{' '}
          {ready ? '— READY' : `(${MIN_SOURCES_TO_BUILD}+ RECOMMENDED)`}
        </Mono>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          {/* Connections never gate the workspace (FND-08): tools can always
              be connected later from the Sources page. */}
          {!ready && (
            <Button kind="ghost" size="lg" onClick={onBuild} aria-label="Skip for now">
              Skip for now
            </Button>
          )}
          <Button kind="primary" size="lg" disabled={!ready} onClick={onBuild}>
            Build context model <Icons.arrowR size={14} />
          </Button>
        </div>
      </div>
      <p style={{ color: 'var(--mut)', fontSize: 11.5, marginTop: 10, textAlign: 'right' }}>
        You can connect tools anytime later — skipping takes you straight to your workspace.
      </p>
    </>
  )
}
