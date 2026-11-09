// Onboarding container — SOL walks you in (SOLUSDEV-323,
// docs/wireflows/onboarding.md): Meet → Project → Voice → Access → Connect →
// Build, then Land. The step is persisted server-side (FND-08): a reload or a
// login elsewhere resumes, a user the server marks done goes straight to the
// workspace, an unreachable API runs the flow locally. Connections never gate
// reaching the homepage; Skip setup is always one click away after Meet.
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button } from '../../components/ui/Button'
import { Mono } from '../../components/ui/Mono'
import { Spinner } from '../../components/ui/Spinner'
import { useAuthStore } from '../../store/authStore'
import { useSettingsStore, type SolMode } from '../../store/settingsStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { switchWorkspaceProject } from '../workspace/projectSwitch'
import { AboutStep } from './AboutStep'
import { AccessStep } from './AccessStep'
import { BuildStep } from './BuildStep'
import { ConnectStep } from './ConnectStep'
import { MeetStep } from './MeetStep'
import { OnboardingOrb, type OrbState } from './OnboardingOrb'
import {
  hydrateOnboarding,
  persistOnboardingStep,
  persistSolMode,
  stepIndexToName
} from './onboardingSync'
import {
  toOnboardingStep,
  useOnboardingStore,
  type OnboardingState,
  type OnboardingStep
} from './onboardingStore'
import { endOnboardingReplay, isOnboardingReplay } from './onboardingReplay'
import { getDesktopPlatform, setDesktopWindowChrome } from '../../lib/desktopBridge'
import { MAC_TRAFFIC_LIGHT_INSET } from '../workspace/TitleBar'
import { ensureWorkspace } from './provisioning'
import { SolLines } from './SolLines'
import { StepDots } from './StepDots'
import { VoiceStep } from './VoiceStep'
import './onboarding.css'

/** Upper bound on waiting for the terminal 'done' write before navigating. */
const DONE_PERSIST_TIMEOUT_MS = 2000
const BUILD_STEP: OnboardingStep = 5

/** Centre the macOS lights in this 64 px header; the workspace's 44 px row gets them back. */
function useOnboardingWindowChrome(): void {
  useEffect(() => {
    setDesktopWindowChrome('onboarding')
    return () => setDesktopWindowChrome('title')
  }, [])
}

function useHydrate(): boolean {
  const navigate = useNavigate()
  const completeOnboarding = useAuthStore((s) => s.completeOnboarding)
  // `pnpm dev:onboarding` replays from Meet without asking the server.
  const [hydrated, setHydrated] = useState(isOnboardingReplay)
  // No once-only ref: under StrictMode the first run is cancelled by cleanup,
  // so EVERY effect run starts its own hydrate (a duplicate GET is harmless).
  useEffect(() => {
    if (isOnboardingReplay()) {
      useOnboardingStore.getState().reset()
      return
    }
    let cancelled = false
    void hydrateOnboarding().then((result) => {
      if (cancelled) return
      if (result.status === 'done') {
        completeOnboarding()
        navigate('/', { replace: true })
        return
      }
      if (result.status === 'resume') useOnboardingStore.getState().setStep(result.step)
      setHydrated(true)
    })
    return () => {
      cancelled = true
    }
  }, [completeOnboarding, navigate])
  return hydrated
}

interface OnboardingFlow {
  store: OnboardingState
  goTo: (step: number) => void
  beginBuild: () => void
  finish: () => Promise<void>
}

function useOnboardingFlow(): OnboardingFlow {
  const navigate = useNavigate()
  const store = useOnboardingStore()
  const solMode = useSettingsStore((s) => s.solMode)
  const completeOnboarding = useAuthStore((s) => s.completeOnboarding)
  const workspace = useWorkspaceStore()

  const goTo = (step: number): void => {
    const next = toOnboardingStep(step)
    store.setStep(next)
    void persistOnboardingStep(stepIndexToName(next))
  }

  // Ensure the workspace as the build begins, reusing the Connect step's
  // project (no double-create). Best-effort: never blocks the flow.
  const beginBuild = (): void => {
    goTo(BUILD_STEP)
    void ensureWorkspace({
      description: store.description,
      solMode,
      existing: { teamId: workspace.teamId, project: workspace.project }
    }).then((result) => {
      workspace.setLinked(result.linked)
      if (result.teamId) workspace.setTeamId(result.teamId)
      if (result.project)
        switchWorkspaceProject(
          { ...result.project, ...(result.teamId ? { teamId: result.teamId } : {}) },
          'onboarding'
        )
    })
  }

  // The terminal write is the one where durability matters (it stops other
  // machines re-showing onboarding), so await it — bounded, so a hung network
  // never holds the user away from their workspace (FND-08 tradeoff).
  const finish = async (): Promise<void> => {
    await Promise.race([
      persistOnboardingStep('done'),
      new Promise((resolve) => setTimeout(resolve, DONE_PERSIST_TIMEOUT_MS))
    ])
    endOnboardingReplay()
    completeOnboarding()
    store.setLandingHint(true)
    navigate('/')
  }

  return { store, goTo, beginBuild, finish }
}

function orbStateFor(step: OnboardingStep, hasDescription: boolean, buildDone: boolean): OrbState {
  if (step === 0) return 'big'
  if (step === 1) return hasDescription ? 'listening' : 'idle'
  if (step === BUILD_STEP && !buildDone) return 'working'
  return step >= 3 ? 'small' : 'idle'
}

export function Onboarding(): React.JSX.Element {
  useOnboardingWindowChrome()
  const hydrated = useHydrate()
  const { store, goTo, beginBuild, finish } = useOnboardingFlow()
  const userEmail = useAuthStore((s) => s.user?.email)
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
  const { step } = store
  const next = (): void => goTo(step + 1)
  const back = (): void => goTo(step - 1)
  return (
    <div
      className="ob-root"
      style={{
        height: '100vh',
        background: 'var(--bg)',
        color: 'var(--tx)',
        fontFamily: 'var(--font-ui)',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden'
      }}
    >
      <OnboardingHeader
        step={step}
        userEmail={userEmail}
        onSkip={step > 0 ? () => void finish() : undefined}
      />
      <main style={{ flex: 1, display: 'flex', minHeight: 0 }}>
        <SolColumn
          orb={orbStateFor(step, store.description.trim() !== '', store.buildDone)}
          step={step}
        />
        <Stage
          step={step}
          description={store.description}
          onDescription={store.setDescription}
          next={next}
          back={back}
          beginBuild={beginBuild}
          finish={finish}
        />
      </main>
    </div>
  )
}

interface StageProps {
  step: OnboardingStep
  description: string
  onDescription: (value: string) => void
  next: () => void
  back: () => void
  beginBuild: () => void
  finish: () => Promise<void>
}

/** The right-hand stage: the current step's controls (keyed so each step rises in fresh). */
function Stage(p: StageProps): React.JSX.Element {
  const solMode = useSettingsStore((s) => s.solMode)
  const setSolMode = useSettingsStore((s) => s.setSolMode)
  const onSolMode = (mode: SolMode): void => {
    setSolMode(mode)
    void persistSolMode(mode) // saved at once — Skip setup must not lose it
  }
  return (
    <section
      key={p.step}
      style={{
        flex: 1,
        minWidth: 0,
        padding: '64px clamp(28px, 4.5vw, 64px) 40px',
        display: 'flex',
        flexDirection: 'column',
        overflowY: 'auto'
      }}
    >
      {p.step === 0 && <MeetStep onNext={p.next} />}
      {p.step === 1 && (
        <AboutStep
          description={p.description}
          onDescription={p.onDescription}
          onNext={p.next}
          onBack={p.back}
        />
      )}
      {p.step === 2 && (
        <VoiceStep solMode={solMode} onSolMode={onSolMode} onNext={p.next} onBack={p.back} />
      )}
      {p.step === 3 && <AccessStep onNext={p.next} onBack={p.back} />}
      {p.step === 4 && <ConnectStep onBuild={p.beginBuild} onBack={p.back} />}
      {p.step === BUILD_STEP && <BuildStep onComplete={() => void p.finish()} />}
    </section>
  )
}

function SolColumn({ orb, step }: { orb: OrbState; step: OnboardingStep }): React.JSX.Element {
  return (
    <section
      style={{
        width: 'clamp(300px, 32vw, 440px)',
        flex: 'none',
        boxSizing: 'border-box',
        padding: '64px clamp(28px, 3.5vw, 48px) 48px clamp(28px, 4vw, 56px)',
        display: 'flex',
        flexDirection: 'column',
        gap: 32,
        borderRight: '1px solid var(--bd)',
        background:
          'radial-gradient(600px 420px at 20% 18%, color-mix(in srgb, var(--acc) 7%, transparent), transparent 70%)'
      }}
    >
      <div
        style={{
          height: 176,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'flex-start',
          justifyContent: 'center',
          gap: 14
        }}
      >
        <OnboardingOrb state={orb} />
        <span
          data-testid="ob-brand"
          style={{
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: '0.24em',
            color: 'var(--mut)'
          }}
        >
          SOLUS
        </span>
      </div>
      <SolLines step={step} />
    </section>
  )
}

function OnboardingHeader({
  step,
  userEmail,
  onSkip
}: {
  step: number
  userEmail?: string
  onSkip?: () => void
}): React.JSX.Element {
  // The window has no native title bar (hiddenInset): this row clears the
  // macOS traffic lights and drags the window, like the workspace TitleBar.
  const inset = getDesktopPlatform() === 'darwin' ? 'mac' : 'none'
  return (
    <header
      data-testid="ob-header"
      data-inset={inset}
      className="app-drag"
      style={{
        height: 64,
        flex: 'none',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 32px',
        paddingLeft: inset === 'mac' ? MAC_TRAFFIC_LIGHT_INSET : 32,
        borderBottom: '1px solid var(--bd)'
      }}
    >
      {/* Left of the rail: the macOS lights on their own (SOL's orb is the brand). */}
      <div style={{ flex: '1 1 0', minWidth: 0 }} />
      <StepDots step={step} />
      <div
        style={{
          flex: '1 1 0',
          minWidth: 0,
          display: 'flex',
          justifyContent: 'flex-end',
          alignItems: 'center',
          gap: 14
        }}
        className="app-no-drag"
      >
        {userEmail && <Mono size={9.5}>{userEmail.toUpperCase()}</Mono>}
        {onSkip && (
          <Button kind="bare" size="sm" onClick={onSkip}>
            Skip setup
          </Button>
        )}
      </div>
    </header>
  )
}
