// SOLUSDEV-311: the errors React boundaries never see — thrown in event
// handlers, timers and promises — reach the reporter through the window's own
// `error` / `unhandledrejection` events (not try/catch sprinkled everywhere).
// The events are observed, not cancelled: the browser still logs them in dev.
import type { ErrorSurface } from '../../../../main/diagnostics/diagnostics.constants'
import type { ErrorReporter } from './errorReporter'

type Target = Pick<Window, 'addEventListener' | 'removeEventListener'>

export function installGlobalErrorHandlers(
  target: Target,
  reporter: Pick<ErrorReporter, 'report'>,
  surface: () => ErrorSurface
): () => void {
  const onError = (event: Event): void => {
    const e = event as ErrorEvent
    reporter.report(e.error ?? e.message, { origin: 'window_error', surface: surface() })
  }
  const onRejection = (event: Event): void => {
    const reason = (event as PromiseRejectionEvent).reason
    reporter.report(reason, { origin: 'unhandled_rejection', surface: surface() })
  }
  target.addEventListener('error', onError)
  target.addEventListener('unhandledrejection', onRejection)
  return () => {
    target.removeEventListener('error', onError)
    target.removeEventListener('unhandledrejection', onRejection)
  }
}
