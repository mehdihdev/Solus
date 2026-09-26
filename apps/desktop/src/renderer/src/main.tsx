import './assets/main.css'
// IBM Plex (bundled locally so it works under the renderer CSP — no CDN).
import '@fontsource/ibm-plex-sans/400.css'
import '@fontsource/ibm-plex-sans/500.css'
import '@fontsource/ibm-plex-sans/600.css'
import '@fontsource/ibm-plex-sans/700.css'
import '@fontsource/ibm-plex-mono/400.css'
import '@fontsource/ibm-plex-mono/500.css'

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { ErrorBoundary } from './components/errors/ErrorBoundary'
import { surfaceForHash } from './components/errors/errorCopy'
import { appErrorReporter, currentErrorSurface } from './lib/errors/appErrorReporter'
import { installGlobalErrorHandlers } from './lib/errors/globalHandlers'

// SOLUSDEV-311: event-handler and async errors (which no boundary sees) go to
// the reporter; render errors are caught by the boundary below. The overlay is
// a click-through window over the user's screen: it reports but draws nothing.
installGlobalErrorHandlers(window, appErrorReporter, currentErrorSurface)
const windowSurface = surfaceForHash(window.location.hash)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary surface={windowSurface} scope={windowSurface === 'overlay' ? 'silent' : 'app'}>
      <App />
    </ErrorBoundary>
  </StrictMode>
)
