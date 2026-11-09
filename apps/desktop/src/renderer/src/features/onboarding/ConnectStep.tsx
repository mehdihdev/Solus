// Onboarding step 5 — Connect (SOLUSDEV-323 ring over the SOLUSDEV-165 connect
// plumbing; docs/wireflows/onboarding.md §5). Tiles come from the LIVE backend
// catalog and open the REAL connect flows — there is no simulated connect
// (SOLUSDEV-152). Entering the step ensures a project exists so a real connect
// has something to attach to. Connections never gate the workspace (FND-08).
import { useEffect } from 'react'
import { Button } from '../../components/ui/Button'
import { Mono } from '../../components/ui/Mono'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { switchWorkspaceProject } from '../workspace/projectSwitch'
import { useSettingsStore } from '../../store/settingsStore'
import { ConnectRing } from './ConnectRing'
import { hearDomains, suggestedIntegrations } from './domainHearing'
import { MIN_SOURCES_TO_BUILD } from './integrations.constants'
import { useOnboardingStore, connectedCount, canBuildModel } from './onboardingStore'
import { ensureWorkspace, projectNameFor } from './provisioning'
import { StepFooter } from './StepFooter'
import { useCatalogConnect } from './useCatalogConnect'

interface ConnectStepProps {
  onBuild: () => void
  onBack?: () => void
}

function useEnsureWorkspaceOnMount(): void {
  const description = useOnboardingStore((s) => s.description)
  const projectName = useOnboardingStore((s) => s.projectName)
  const solMode = useSettingsStore((s) => s.solMode)
  const workspace = useWorkspaceStore()
  useEffect(() => {
    let cancelled = false
    void ensureWorkspace({
      description,
      name: projectNameFor(description, projectName),
      solMode,
      existing: { teamId: workspace.teamId, project: workspace.project }
    }).then((result) => {
      if (cancelled) return
      workspace.setLinked(result.linked)
      if (result.teamId) workspace.setTeamId(result.teamId)
      if (result.project)
        switchWorkspaceProject(
          { ...result.project, ...(result.teamId ? { teamId: result.teamId } : {}) },
          'onboarding'
        )
    })
    return () => {
      cancelled = true
    }
    // Run once on mount; workspace setters are stable store actions.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
}

export function ConnectStep({ onBuild, onBack }: ConnectStepProps): React.JSX.Element {
  useEnsureWorkspaceOnMount()
  const description = useOnboardingStore((s) => s.description)
  const workspace = useWorkspaceStore()
  const connect = useCatalogConnect({
    projectId: workspace.linked && workspace.project ? workspace.project.id : null
  })
  const suggestedIds = suggestedIntegrations(
    connect.catalog.map((e) => e.id),
    hearDomains(description)
  )
  const suggestedNames = connect.catalog
    .filter((e) => suggestedIds.includes(e.id))
    .map((e) => e.name)
  const count = connectedCount(connect.connections)
  const ready = canBuildModel(connect.connections)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, flex: 1 }}>
      <p className="ob-rise ob-d2" style={{ margin: 0, fontSize: 13, color: 'var(--mut)' }}>
        {suggestedNames.length
          ? `From what you told me, start with ${suggestedNames.join(' and ')}.`
          : 'Pick the tools your team already lives in.'}
      </p>
      <div className="ob-rise ob-d2" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <ConnectRing connect={connect} suggested={new Set(suggestedIds)} />
      </div>
      <StepFooter onBack={onBack} className="ob-rise ob-d4">
        <Mono size={9.5} color={ready ? 'var(--ok)' : 'var(--mut)'}>
          {ready
            ? `${count} CONNECTED — READY`
            : `${count} CONNECTED · ${MIN_SOURCES_TO_BUILD}+ RECOMMENDED`}
        </Mono>
        {/* Connections never gate the workspace (FND-08). */}
        {!ready && (
          <Button kind="ghost" size="lg" onClick={onBuild}>
            Skip for now
          </Button>
        )}
        <Button kind="primary" size="lg" disabled={!ready} onClick={onBuild}>
          Build my graph
        </Button>
      </StepFooter>
      {connect.modals}
    </div>
  )
}
