import { useEffect } from 'react'
import { HashRouter } from 'react-router-dom'
import { AppRoutes } from './routes/AppRoutes'
import { applyTheme } from './theme/applyTheme'
import { useSettingsStore } from './store/settingsStore'
import { useAuthStore } from './store/authStore'
import { appErrorReporter } from './lib/errors/appErrorReporter'

function App(): React.JSX.Element {
  const theme = useSettingsStore((s) => s.theme)
  const accent = useSettingsStore((s) => s.accent)
  const density = useSettingsStore((s) => s.density)
  const bootstrap = useAuthStore((s) => s.bootstrap)
  const teardown = useAuthStore((s) => s.teardown)
  const status = useAuthStore((s) => s.status)

  // Re-skin whenever theme settings change (ADR-008 / prototype theme.js).
  useEffect(() => {
    applyTheme(theme, accent, density)
  }, [theme, accent, density])

  // Resolve the Supabase session (or dev bypass) on launch; detach the auth
  // listener on unmount so it never accumulates (StrictMode / HMR).
  useEffect(() => {
    void bootstrap()
    return () => teardown()
  }, [bootstrap, teardown])

  // SOLUSDEV-311: a prior session's main/renderer crash becomes one client.error
  // event once signed in (the event route needs the user's token). Main hands
  // the marker only to the main window, so the other windows get nothing.
  useEffect(() => {
    if (status === 'authenticated') void appErrorReporter.reportPendingCrash()
  }, [status])

  return (
    <HashRouter>
      <AppRoutes />
    </HashRouter>
  )
}

export default App
