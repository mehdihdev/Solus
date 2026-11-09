// SOLUSDEV-323: the compact signed-out window (docs/wireflows/onboarding.md
// §Before onboarding). One shell persists across the starter, sign-in, create
// account and reset, so SOL's orb never remounts: it eases between big and
// small while each screen's content rises in and the window resizes around it.
// Signing in fades the content, grows the window to full, then hands over.
import { useEffect, useLayoutEffect, useRef } from 'react'
import { Navigate, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { Mono } from '../../components/ui/Mono'
import { useAuthStore } from '../../store/authStore'
import { OnboardingOrb, type OrbState } from '../onboarding/OnboardingOrb'
import { requestWindowSize, sizeForPath } from './starterWindow'
import '../onboarding/onboarding.css'
import './authShell.css'

const APP_VERSION = 'v0.9'
/** Matches .auth-leave in authShell.css: the content fades before the window grows. */
const LEAVE_FADE_MS = 220

const wait = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

/** Grow to full, then go on to `/`, once the user signs in while this shell is up. */
function useHandOffOnSignIn(signedInAtMount: boolean): boolean {
  const status = useAuthStore((s) => s.status)
  const navigate = useNavigate()
  const leaving = status === 'authenticated' && !signedInAtMount
  useEffect(() => {
    if (!leaving) return
    let cancelled = false
    void (async () => {
      await wait(LEAVE_FADE_MS)
      await requestWindowSize('full')
      if (!cancelled) navigate('/', { replace: true })
    })()
    return () => {
      cancelled = true
    }
  }, [leaving, navigate])
  return leaving
}

function orbState(pathname: string, leaving: boolean): OrbState {
  if (leaving) return 'listening'
  return pathname === '/welcome' ? 'big' : 'small'
}

export function AuthShell(): React.JSX.Element {
  const { pathname } = useLocation()
  const signedInAtMount = useRef(useAuthStore.getState().status === 'authenticated').current
  const leaving = useHandOffOnSignIn(signedInAtMount)

  // Before paint, so the resize starts with the new screen's first frame.
  useLayoutEffect(() => {
    if (!signedInAtMount && !leaving) void requestWindowSize(sizeForPath(pathname))
  }, [pathname, leaving, signedInAtMount])

  if (signedInAtMount) return <Navigate to="/" replace />
  const orb = orbState(pathname, leaving)
  return (
    <div
      className="ob-root auth-shell"
      data-testid="auth-shell"
      data-leaving={leaving}
      style={{
        height: '100vh',
        color: 'var(--tx)',
        fontFamily: 'var(--font-ui)',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden'
      }}
    >
      {/* The window has no native title bar: this row holds the macOS lights and drags it. */}
      <header className="app-drag auth-shell-header">
        <Mono size={9}>{APP_VERSION}</Mono>
      </header>
      <main className="auth-shell-main">
        <div className="auth-shell-column">
          <div className="auth-shell-orb" data-testid="auth-orb" data-state={orb}>
            <OnboardingOrb state={orb} size="compact" />
            <span className="auth-shell-brand">SOLUS</span>
          </div>
          <div key={pathname} className={leaving ? 'auth-leave' : 'ob-rise ob-d1'}>
            <Outlet />
          </div>
        </div>
      </main>
      <footer className="auth-shell-footer">
        <Mono size={9}>WORKS WITH GITHUB · KICAD · ONSHAPE · ROS 2</Mono>
      </footer>
    </div>
  )
}
