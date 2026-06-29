// Onboarding container — orchestrates About → Connect → Build (API.md §5
// /onboarding). Ported from the Onboarding component in
// TestDesign/app/onboarding.jsx and wired to the onboarding + settings + auth
// stores. The connect/build steps are simulated in this prototype slice.
import { useNavigate } from 'react-router-dom'
import { Mono } from '../../components/ui/Mono'
import { Wordmark } from '../../components/ui/Wordmark'
import { StepDots } from './StepDots'
import { AboutStep } from './AboutStep'
import { ConnectStep } from './ConnectStep'
import { BuildStep } from './BuildStep'
import { useOnboardingStore } from './onboardingStore'
import { provisionWorkspace } from './provisioning'
import { useSettingsStore } from '../../store/settingsStore'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceStore } from '../../store/workspaceStore'

export function Onboarding(): React.JSX.Element {
  const navigate = useNavigate()
  const store = useOnboardingStore()
  const solMode = useSettingsStore((s) => s.solMode)
  const setSolMode = useSettingsStore((s) => s.setSolMode)
  const userEmail = useAuthStore((s) => s.user?.email)
  const completeOnboarding = useAuthStore((s) => s.completeOnboarding)
  const workspace = useWorkspaceStore()

  // Kick real provisioning when the build begins. Runs alongside the simulated
  // build animation; best-effort, so a missing/unreachable API never blocks the
  // flow (the UI just stays in its simulated state).
  const beginBuild = (): void => {
    store.setStep(2)
    void provisionWorkspace({ description: store.description, solMode }).then((result) => {
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
    }
  }

  const handleComplete = (): void => {
    completeOnboarding()
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
        {store.step === 2 && <BuildStep onComplete={handleComplete} />}
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
