// Onboarding step 1 — "Connect your tools". The four connector tiles share one
// UI; GitHub drives the REAL backend connector (SOLUSDEV-103) when a project is
// linked and the Electron OAuth bridge is present, while KiCad/Onshape/ROS stay
// simulated. On entering this step we ensure a project exists so a real connect
// has something to attach a source to; if the API/auth is unavailable we fall
// back to the simulated GitHub tile so onboarding still completes (dev bypass).
import { useEffect, useRef } from 'react'
import { Button } from '../../components/ui/Button'
import { Mono } from '../../components/ui/Mono'
import { Icons } from '../../components/ui/icons.constants'
import { getDesktopOAuthBridge } from '../../lib/desktopBridge'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useSettingsStore } from '../../store/settingsStore'
import { ConnectTile } from './ConnectTile'
import { INTEGRATIONS, MIN_SOURCES_TO_BUILD, type Integration } from './integrations.constants'
import { useOnboardingStore, connectedCount, canBuildModel } from './onboardingStore'
import { ensureWorkspace } from './provisioning'
import { useGithubConnect } from './useGithubConnect'

const CONNECT_STEP_MS = 650
const COMPLETE_DELAY_MS = 350
const GITHUB_ID = 'github'

interface ConnectStepProps {
  onBuild: () => void
}

export function ConnectStep({ onBuild }: ConnectStepProps): React.JSX.Element {
  const connections = useOnboardingStore((s) => s.connections)
  const beginConnect = useOnboardingStore((s) => s.beginConnect)
  const setConnectStep = useOnboardingStore((s) => s.setConnectStep)
  const completeConnect = useOnboardingStore((s) => s.completeConnect)
  const description = useOnboardingStore((s) => s.description)
  const solMode = useSettingsStore((s) => s.solMode)
  const workspace = useWorkspaceStore()
  const github = useGithubConnect()
  const timers = useRef<ReturnType<typeof setTimeout>[]>([])

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

  useEffect(() => {
    const pending = timers.current
    return () => {
      pending.forEach(clearTimeout)
      pending.length = 0
    }
  }, [])

  const simulateConnect = (integ: Integration): void => {
    beginConnect(integ.id)
    integ.steps.forEach((_, i) => {
      if (i > 0) {
        timers.current.push(setTimeout(() => setConnectStep(integ.id, i), i * CONNECT_STEP_MS))
      }
    })
    timers.current.push(
      setTimeout(
        () => completeConnect(integ.id),
        integ.steps.length * CONNECT_STEP_MS + COMPLETE_DELAY_MS
      )
    )
  }

  const connect = (integ: Integration): void => {
    // GitHub uses the real connector when we have a linked project + bridge;
    // otherwise (dev bypass / web build) it degrades to the simulated tile.
    if (
      integ.id === GITHUB_ID &&
      workspace.linked &&
      workspace.project &&
      getDesktopOAuthBridge()
    ) {
      void github.start(workspace.project.id)
      return
    }
    simulateConnect(integ)
  }

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
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 24 }}>
        {INTEGRATIONS.map((integ) => (
          <ConnectTile
            key={integ.id}
            integration={integ}
            state={connections[integ.id]}
            onConnect={() => connect(integ)}
            onChooseRepo={github.chooseRepo}
            onRetry={() => connect(integ)}
          />
        ))}
      </div>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginTop: 28
        }}
      >
        <Mono size={10} color={ready ? 'var(--ok)' : 'var(--mut)'}>
          {count} OF {INTEGRATIONS.length} CONNECTED{' '}
          {ready ? '— READY' : `(NEED ${MIN_SOURCES_TO_BUILD}+)`}
        </Mono>
        <Button kind="primary" size="lg" disabled={!ready} onClick={onBuild}>
          Build context model <Icons.arrowR size={14} />
        </Button>
      </div>
    </div>
  )
}
