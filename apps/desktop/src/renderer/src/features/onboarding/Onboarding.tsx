// Onboarding container — orchestrates About → Connect → Build (API.md §5
// /onboarding, FND-08). The step state machine is persisted server-side via
// the settings endpoint: a reload or a login on another machine resumes at the
// saved step, and a user the server marks done goes straight to the workspace.
// Connections are always skippable — they never gate reaching the homepage.
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Mono } from '../../components/ui/Mono'
import { Spinner } from '../../components/ui/Spinner'
import { Wordmark } from '../../components/ui/Wordmark'
import { StepDots } from './StepDots'
import { AboutStep } from './AboutStep'
import { ConnectStep } from './ConnectStep'
import { BuildStep } from './BuildStep'
import { useOnboardingStore } from './onboardingStore'
import { ensureWorkspace } from './provisioning'
import { hydrateOnboarding, persistOnboardingStep } from './onboardingSync'
import { useSettingsStore } from '../../store/settingsStore'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceStore } from '../../store/workspaceStore'

/** Upper bound on waiting for the terminal 'done' write before navigating. */
const DONE_PERSIST_TIMEOUT_MS = 2000

export function Onboarding(): React.JSX.Element {
  const navigate = useNavigate()
  const store = useOnboardingStore()
  const solMode = useSettingsStore((s) => s.solMode)
  const setSolMode = useSettingsStore((s) => s.setSolMode)
  const userEmail = useAuthStore((s) => s.user?.email)
  const completeOnboarding = useAuthStore((s) => s.completeOnboarding)
  const workspace = useWorkspaceStore()
  const [hydrated, setHydrated] = useState(false)

  // Resume from the server-persisted step (FND-08). Someone the server already
  // marks done (e.g. onboarded on another machine) skips straight to the
  // workspace; an unreachable API falls back to the local step so the flow
  // still completes in dev bypass.
  // No once-only ref here: under StrictMode the first run's result is
  // cancelled by cleanup, so EVERY effect run must start its own hydrate or
  // the splash never resolves in dev (a duplicate GET is harmless).
  useEffect(() => {
    let cancelled = false
    void hydrateOnboarding().then((result) => {
      if (cancelled) return
      if (result.status === 'done') {
        completeOnboarding()
        navigate('/', { replace: true })
        return
      }
      if (result.status === 'resume' && result.step !== store.step) {
        store.setStep(result.step)
      }
      setHydrated(true)
    })
    return () => {
      cancelled = true
    }
    // Run once on mount; store actions are stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Ensure the workspace when the build begins. Reuses the project already
  // created on the Connect step (no double-create). Runs alongside the
  // simulated build animation; best-effort, so a missing/unreachable API never
  // blocks the flow (the UI just stays in its simulated state).
  const beginBuild = (): void => {
    store.setStep(2)
    void persistOnboardingStep('build')
    void ensureWorkspace({
      description: store.description,
      solMode,
      existing: { teamId: workspace.teamId, project: workspace.project }
    }).then((result) => {
      workspace.setLinked(result.linked)
      if (result.teamId) workspace.setTeamId(result.teamId)
      if (result.project) workspace.setProject(result.project)
    })
  }

  const handleContinue = (): void => {
    if (store.path === 'template') {
      // Template path pre-connects simulated sources, then builds.
      store.connectAll()
      beginBuild()
    } else {
      store.setStep(1)
      void persistOnboardingStep('connect')
    }
  }

  const handleComplete = async (): Promise<void> => {
    // The terminal transition is the one write where server durability matters
    // (it's what stops other machines re-showing onboarding), so await it — but
    // bounded, so a hung network can never hold the user away from their
    // workspace. On failure the user still completes locally; another device
    // would resume from the last saved step (explicit tradeoff, FND-08).
    await Promise.race([
      persistOnboardingStep('done'),
      new Promise((resolve) => setTimeout(resolve, DONE_PERSIST_TIMEOUT_MS))
    ])
    completeOnboarding()
    navigate('/')
  }

  if (!hydrated) {
    return (
      <div
        style={{
          minHeight: '100vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'var(--bg)'
        }}
      >
        <Spinner size={22} />
      </div>
    )
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
      <OnboardingHeader step={store.step} userEmail={userEmail} />

      <div style={{ flex: 1, display: 'flex', justifyContent: 'center', padding: '52px 24px' }}>
        {store.step === 0 && (
          <AboutStep
            description={store.description}
            onDescription={store.setDescription}
            path={store.path}
            onPath={store.setPath}
            templateId={store.templateId}
            onTemplate={store.setTemplate}
            solMode={solMode}
            onSolMode={setSolMode}
            onContinue={handleContinue}
          />
        )}
        {store.step === 1 && <ConnectStep onBuild={beginBuild} />}
        {store.step === 2 && <BuildStep onComplete={() => void handleComplete()} />}
      </div>
    </div>
  )
}

function OnboardingHeader({
  step,
  userEmail
}: {
  step: number
  userEmail?: string
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
      <StepDots step={step} />
      <Mono size={9.5}>{(userEmail ?? 'you@solus.dev').toUpperCase()}</Mono>
    </div>
  )
}
