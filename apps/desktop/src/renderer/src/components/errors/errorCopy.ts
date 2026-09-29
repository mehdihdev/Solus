// SOLUSDEV-311: what the error fallback says, per SOL mode (ADR-016), and the
// "Copy details" text. Pure. SPEC Principles: explain, don't just display;
// empty beats invented — the log is only mentioned when there is one.
import { scrubText } from '../../../../main/diagnostics/scrub'
import type { ErrorSurface } from '../../../../main/diagnostics/diagnostics.constants'
import type { ShellRoute } from '../../features/workspace/shellStore'
import type { SolMode } from '../../store/settingsStore'

export type BoundaryScope = 'panel' | 'app' | 'silent'

export const SURFACE_LABELS: Readonly<Record<ErrorSurface, string>> = {
  root: 'Solus',
  home: 'Home',
  workspace: 'Workspace',
  bench: 'Live Bench',
  sol: 'SOL',
  store: 'Store',
  billing: 'Billing',
  settings: 'Settings',
  alert: 'This alert',
  extension: 'this extension',
  sol_window: 'The SOL window',
  overlay: 'The guide overlay',
  ext_window: 'This extension window',
  main: 'Solus'
}

export function surfaceForRoute(route: ShellRoute): ErrorSurface {
  return route.name === 'ext-page' ? 'extension' : route.name
}

export function surfaceForHash(hash: string): ErrorSurface {
  if (hash.startsWith('#/sol-window')) return 'sol_window'
  if (hash.startsWith('#/overlay')) return 'overlay'
  if (hash.startsWith('#/ext-window')) return 'ext_window'
  return 'root'
}

interface ErrorSummary {
  name: string
  message: string
  stack?: string
}

export interface FallbackCopy {
  title: string
  body: string
  /** The error itself, shown in mono (Expert only; Guide keeps it in Copy details). */
  detail?: string
}

const capitalise = (s: string): string => s.charAt(0).toUpperCase() + s.slice(1)

export function fallbackCopy(input: {
  mode: SolMode
  scope: Exclude<BoundaryScope, 'silent'>
  surface: ErrorSurface
  error: ErrorSummary
  logged: boolean
}): FallbackCopy {
  const label = capitalise(SURFACE_LABELS[input.surface])
  const detail = `${input.error.name}: ${input.error.message}`
  const logLine = input.logged ? " The error has been saved to Solus's error log." : ''
  if (input.mode === 'Expert') {
    return input.scope === 'panel'
      ? {
          title: `${label} crashed`,
          body: 'Render error. Panel isolated; the rest of the app is live.',
          detail
        }
      : { title: 'Renderer crashed', body: 'Render error at the window root.', detail }
  }
  if (input.scope === 'panel') {
    return {
      title: `${label} hit a problem`,
      body:
        `Something inside ${label} failed while it was drawing, so Solus stopped just this panel — ` +
        'the rest of Solus still works, and you can keep going from the navigation. ' +
        `Reload panel tries ${label} again. If it keeps happening, use Copy details and send them to the Solus team.` +
        logLine
    }
  }
  return {
    title: 'Solus hit a problem',
    body:
      'Something failed while this window was drawing, so Solus stopped it — ' +
      'nothing in your projects or connected tools was changed. ' +
      'Reload app starts this window fresh. If it keeps happening, use Copy details and send them to the Solus team.' +
      logLine
  }
}

/** Plain-text details for the clipboard — scrubbed like every other report. */
export function detailsText(input: {
  surface: ErrorSurface
  error: ErrorSummary
  componentStack?: string
  at: Date
}): string {
  const lines = [
    'Solus error report',
    `Where: ${capitalise(SURFACE_LABELS[input.surface])} (${input.surface})`,
    `When: ${input.at.toISOString()}`,
    `Error: ${input.error.name}: ${input.error.message}`,
    ...(input.error.stack ? ['', 'Stack:', input.error.stack] : []),
    ...(input.componentStack ? ['', 'Component stack:', input.componentStack.trim()] : [])
  ]
  return scrubText(lines.join('\n'), '')
}
