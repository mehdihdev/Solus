// SOLUSDEV-311: what a broken panel (or window) shows instead of a blank
// screen. Wording follows the SOL mode; actions: Reload panel (panel scope),
// Reload app, Copy details.
import { useState } from 'react'
import { Button } from '../ui/Button'
import { useSettingsStore } from '../../store/settingsStore'
import { getDesktopDiagnosticsBridge } from '../../lib/desktopBridge'
import { detailsText, fallbackCopy, type BoundaryScope } from './errorCopy'
import type { ErrorSurface } from '../../../../main/diagnostics/diagnostics.constants'

export interface ErrorFallbackProps {
  surface: ErrorSurface
  scope: Exclude<BoundaryScope, 'silent'>
  error: { name: string; message: string; stack?: string }
  componentStack?: string
  onReloadPanel: () => void
}

type CopyState = 'idle' | 'copied' | 'failed'
const COPY_LABEL: Record<CopyState, string> = {
  idle: 'Copy details',
  copied: 'Copied',
  failed: 'Copy failed'
}

export function ErrorFallback(props: ErrorFallbackProps): React.JSX.Element {
  const mode = useSettingsStore((s) => s.solMode)
  const [copy, setCopy] = useState<CopyState>('idle')
  const text = fallbackCopy({
    mode,
    scope: props.scope,
    surface: props.surface,
    error: props.error,
    logged: getDesktopDiagnosticsBridge() !== null
  })
  const copyDetails = (): void => {
    const details = detailsText({ ...props, at: new Date() })
    // Written inside the click itself: the clipboard needs the user gesture.
    try {
      navigator.clipboard.writeText(details).then(
        () => setCopy('copied'),
        () => setCopy('failed')
      )
    } catch {
      setCopy('failed')
    }
  }
  return (
    <div
      role="alert"
      style={{
        flex: 1,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 32,
        background: 'var(--bg)',
        minHeight: props.scope === 'app' ? '100vh' : undefined
      }}
    >
      <div style={{ maxWidth: 520, display: 'flex', flexDirection: 'column', gap: 12 }}>
        <h2 style={{ margin: 0, fontSize: 17, fontWeight: 600, color: 'var(--tx)' }}>
          {text.title}
        </h2>
        <p style={{ margin: 0, fontSize: 13.5, lineHeight: 1.55, color: 'var(--mut)' }}>
          {text.body}
        </p>
        {text.detail && (
          <pre
            className="font-mono"
            style={{ margin: 0, fontSize: 12, color: 'var(--err)', whiteSpace: 'pre-wrap' }}
          >
            {text.detail}
          </pre>
        )}
        <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
          {props.scope === 'panel' && (
            <Button kind="primary" size="sm" onClick={props.onReloadPanel}>
              Reload panel
            </Button>
          )}
          <Button
            kind={props.scope === 'panel' ? 'ghost' : 'primary'}
            size="sm"
            onClick={() => window.location.reload()}
          >
            Reload app
          </Button>
          <Button kind="bare" size="sm" onClick={copyDetails}>
            {COPY_LABEL[copy]}
          </Button>
        </div>
      </div>
    </div>
  )
}
