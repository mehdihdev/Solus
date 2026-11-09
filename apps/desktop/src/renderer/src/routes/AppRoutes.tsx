// App routing + auth guards (API.md §5 frontend routes; hash history in Electron).
import type { ReactNode } from 'react'
import { useEffect } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { AuthShell } from '../features/auth/AuthShell'
import { StarterPage } from '../features/auth/StarterPage'
import { rememberedLaunchSize, requestWindowSize } from '../features/auth/starterWindow'
import { LoginPage } from '../features/auth/LoginPage'
import { SignupPage } from '../features/auth/SignupPage'
import { ResetPasswordPage } from '../features/auth/ResetPasswordPage'
import { Onboarding } from '../features/onboarding/Onboarding'
import { OverlayWindow } from '../features/overlay/OverlayWindow'
import { SolWindow } from '../features/sol/SolWindow'
import { ExtensionWindowRoot } from '../features/extensions/pageview/ExtensionWindowRoot'
import { WorkspaceShell } from '../features/workspace/WorkspaceShell'
import { SolLandingHint } from '../features/onboarding/SolLandingHint'
import { isOnboardingReplay } from '../features/onboarding/onboardingReplay'
import { Spinner } from '../components/ui/Spinner'
import { useAuthStore } from '../store/authStore'

function Splash(): React.JSX.Element {
  // SOLUSDEV-323: while the session loads, take the size the window last had,
  // so a signed-out launch opens compact instead of shrinking after a flash.
  useEffect(() => {
    void requestWindowSize(rememberedLaunchSize())
  }, [])
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

/** SOLUSDEV-323: signed-in screens fill the window (a no-op when it already does). */
function useFullWindow(active: boolean): void {
  useEffect(() => {
    if (active) void requestWindowSize('full')
  }, [active])
}

/** Root: route by auth + onboarding status. */
function RootRoute(): React.JSX.Element {
  const status = useAuthStore((s) => s.status)
  const onboarded = useAuthStore((s) => s.onboarded)
  useFullWindow(status === 'authenticated')
  if (status === 'loading') return <Splash />
  if (status === 'unauthenticated') return <Navigate to="/welcome" replace />
  if (!onboarded || isOnboardingReplay()) return <Navigate to="/onboarding" replace />
  return (
    <>
      <WorkspaceShell />
      {/* SOLUSDEV-323 Land: the one-time SOL hint right after onboarding. */}
      <SolLandingHint />
    </>
  )
}

/** Guard for the post-login onboarding flow: must be authed and not yet onboarded. */
function RequireOnboarding({ children }: { children: ReactNode }): React.JSX.Element {
  const status = useAuthStore((s) => s.status)
  const onboarded = useAuthStore((s) => s.onboarded)
  useFullWindow(status === 'authenticated')
  if (status === 'loading') return <Splash />
  if (status === 'unauthenticated') return <Navigate to="/login" replace />
  if (onboarded && !isOnboardingReplay()) return <Navigate to="/" replace />
  return <>{children}</>
}

export function AppRoutes(): React.JSX.Element {
  return (
    <Routes>
      <Route path="/" element={<RootRoute />} />
      {/* SOLUSDEV-323: the compact signed-out window. One shell across these
          screens, so SOL's orb and the window ease between them; it grows the
          window and moves on once the user is signed in. */}
      <Route element={<AuthShell />}>
        <Route path="/welcome" element={<StarterPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/signup" element={<SignupPage />} />
        <Route path="/reset-password" element={<ResetPasswordPage />} />
      </Route>
      <Route
        path="/onboarding"
        element={
          <RequireOnboarding>
            <Onboarding />
          </RequireOnboarding>
        }
      />
      {/* SOLUSDEV-252 S3: the SOL window, summoned by double-tap Ctrl or the
          circle gesture — guards its own auth like the extension window. */}
      <Route path="/sol-window" element={<SolWindow />} />
      {/* SOLX-03/TU-10: the click-through guide overlay window. No auth guard —
          it renders only what the SOL window hands it over CTR-06, never fetched data. */}
      <Route path="/overlay" element={<OverlayWindow />} />
      {/* SOLUSDEV-235 / EXT-13: an extension's window view — the second
          BrowserWindow main opens (guards its own auth, like the SOL window). */}
      <Route path="/ext-window/:extensionId" element={<ExtensionWindowRoot />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
