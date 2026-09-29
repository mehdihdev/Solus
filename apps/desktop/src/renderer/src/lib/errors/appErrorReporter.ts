// SOLUSDEV-311: the app's reporter instance, bound to the real bridge, the
// typed events client and the open project. Tests build their own with
// createErrorReporter; this module only wires.
import { postDataEvents } from '../api/resources.extensions'
import { getSettings } from '../api/resources'
import { createConsentSync } from './errorConsent'
import { getDesktopDiagnosticsBridge } from '../desktopBridge'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useAuthStore } from '../../store/authStore'
import { useShellStore } from '../../features/workspace/shellStore'
import { surfaceForHash } from '../../components/errors/errorCopy'
import type { ErrorSurface } from '../../../../main/diagnostics/diagnostics.constants'
import { createErrorReporter } from './errorReporter'

export const appErrorReporter = createErrorReporter({
  bridge: getDesktopDiagnosticsBridge,
  emitEvents: (events) => postDataEvents(events),
  projectId: () => useWorkspaceStore.getState().project?.id ?? undefined,
  isDev: import.meta.env.DEV,
  // Dev only (errorReporter gates it): never swallow an error while developing.
  consoleError: (...args) => console.error(...args)
})

/** Where a global (non-render) error happened: the window, and in the main
 *  window the last shell screen once signed in — never a guessed panel. */
export function currentErrorSurface(): ErrorSurface {
  const windowSurface = surfaceForHash(window.location.hash)
  if (windowSurface !== 'root') return windowSurface
  return useAuthStore.getState().status === 'authenticated'
    ? useShellStore.getState().lastMain
    : 'root'
}

/** Main's Sentry gate, kept in step with the user's data-collection consent. */
export const errorConsent = createConsentSync({
  bridge: getDesktopDiagnosticsBridge,
  fetchConsent: () => getSettings().then((s) => s.data_collection_consent)
})
