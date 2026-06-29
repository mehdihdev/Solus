import { useEffect } from 'react'
import { HashRouter } from 'react-router-dom'
import { AppRoutes } from './routes/AppRoutes'
import { applyTheme } from './theme/applyTheme'
import { useSettingsStore } from './store/settingsStore'
import { useAuthStore } from './store/authStore'

function App(): React.JSX.Element {
  const theme = useSettingsStore((s) => s.theme)
  const accent = useSettingsStore((s) => s.accent)
  const density = useSettingsStore((s) => s.density)
  const bootstrap = useAuthStore((s) => s.bootstrap)
  const teardown = useAuthStore((s) => s.teardown)

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

  return (
    <HashRouter>
      <AppRoutes />
    </HashRouter>
  )
}

export default App
