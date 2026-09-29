// SOLUSDEV-311: one bad component must never blank the whole app. A render
// error below this boundary is reported once and replaced by ErrorFallback;
// everything outside it keeps working. Scopes: `panel` (one shell screen —
// Reload panel remounts it), `app` (a window root), `silent` (the click-through
// guide overlay: report, draw nothing). Render errors only — event-handler and
// async errors reach the reporter through lib/errors/globalHandlers.
import { Component, type ErrorInfo, type ReactNode } from 'react'
import { ErrorFallback } from './ErrorFallback'
import { appErrorReporter } from '../../lib/errors/appErrorReporter'
import type { BoundaryScope } from './errorCopy'
import type { ErrorReporter } from '../../lib/errors/errorReporter'
import type { ErrorSurface } from '../../../../main/diagnostics/diagnostics.constants'

export interface ErrorBoundaryProps {
  surface: ErrorSurface
  scope: BoundaryScope
  children: ReactNode
  reporter?: Pick<ErrorReporter, 'report'>
}

interface ErrorBoundaryState {
  caught: { error: unknown; componentStack?: string } | null
}

function summary(error: unknown): { name: string; message: string; stack?: string } {
  if (error instanceof Error)
    return { name: error.name, message: error.message, stack: error.stack }
  return {
    name: 'Error',
    message: typeof error === 'string' ? error : 'A non-Error value was thrown'
  }
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { caught: null }

  static getDerivedStateFromError(error: unknown): ErrorBoundaryState {
    return { caught: { error } }
  }

  componentDidCatch(error: unknown, info: ErrorInfo): void {
    const componentStack = info.componentStack ?? undefined
    this.setState({ caught: { error, componentStack } })
    const reporter = this.props.reporter ?? appErrorReporter
    reporter.report(error, { origin: 'render', surface: this.props.surface, componentStack })
  }

  private readonly reset = (): void => this.setState({ caught: null })

  render(): ReactNode {
    const { caught } = this.state
    if (!caught) return this.props.children
    if (this.props.scope === 'silent') return null
    return (
      <ErrorFallback
        surface={this.props.surface}
        scope={this.props.scope}
        error={summary(caught.error)}
        componentStack={caught.componentStack}
        onReloadPanel={this.reset}
      />
    )
  }
}
