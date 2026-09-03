// App routing + auth guards (API.md §5 frontend routes; hash history in Electron).
import type { ReactNode } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { LandingPage } from '../features/auth/LandingPage'
import { LoginPage } from '../features/auth/LoginPage'
import { SignupPage } from '../features/auth/SignupPage'
import { ResetPasswordPage } from '../features/auth/ResetPasswordPage'
import { Onboarding } from '../features/onboarding/Onboarding'
import { OverlayWindow } from '../features/overlay/OverlayWindow'
import { OrbWindow } from '../features/sol/OrbWindow'
import { ExtensionWindowRoot } from '../features/extensions/pageview/ExtensionWindowRoot'
import { WorkspaceShell } from '../features/workspace/WorkspaceShell'
import { Spinner } from '../components/ui/Spinner'
import { useAuthStore } from '../store/authStore'

function Splash(): React.JSX.Element {
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

/** Root: route by auth + onboarding status. */
function RootRoute(): React.JSX.Element {
  const status = useAuthStore((s) => s.status)
  const onboarded = useAuthStore((s) => s.onboarded)
  if (status === 'loading') return <Splash />
  if (status === 'unauthenticated') return <LandingPage />
  if (!onboarded) return <Navigate to="/onboarding" replace />
  return <WorkspaceShell />
}

/** Guard for the post-login onboarding flow: must be authed and not yet onboarded. */
function RequireOnboarding({ children }: { children: ReactNode }): React.JSX.Element {
  const status = useAuthStore((s) => s.status)
  const onboarded = useAuthStore((s) => s.onboarded)
  if (status === 'loading') return <Splash />
  if (status === 'unauthenticated') return <Navigate to="/login" replace />
  if (onboarded) return <Navigate to="/" replace />
  return <>{children}</>
}

/** Auth screens redirect away once the user is signed in. */
function PublicOnly({ children }: { children: ReactNode }): React.JSX.Element {
  const status = useAuthStore((s) => s.status)
  if (status === 'authenticated') return <Navigate to="/" replace />
  return <>{children}</>
}

export function AppRoutes(): React.JSX.Element {
  return (
    <Routes>
      <Route path="/" element={<RootRoute />} />
      <Route
        path="/login"
        element={
          <PublicOnly>
            <LoginPage />
          </PublicOnly>
        }
      />
      <Route
        path="/signup"
        element={
          <PublicOnly>
            <SignupPage />
          </PublicOnly>
        }
      />
      <Route
        path="/reset-password"
        element={
          <PublicOnly>
            <ResetPasswordPage />
          </PublicOnly>
        }
      />
      <Route
        path="/onboarding"
        element={
          <RequireOnboarding>
            <Onboarding />
          </RequireOnboarding>
        }
      />
      {/* SOLX-02: the detached always-on-top orb window (guards its own auth). */}
      <Route path="/orb" element={<OrbWindow />} />
      {/* SOLX-03/TU-10: the click-through guide overlay window. No auth guard —
          it renders only what the orb hands it over CTR-06, never fetched data. */}
      <Route path="/overlay" element={<OverlayWindow />} />
      {/* SOLUSDEV-235 / EXT-13: an extension's window view — the second
          BrowserWindow main opens (guards its own auth, like the orb). */}
      <Route path="/ext-window/:extensionId" element={<ExtensionWindowRoot />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
