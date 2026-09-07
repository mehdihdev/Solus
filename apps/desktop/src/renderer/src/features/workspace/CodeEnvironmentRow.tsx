// Home › Connected accounts › Software › "Code environment" (SOLUSDEV-250 /
// INTEGRATIONS I3): the linked folder on THIS machine plus the interpreter and
// venv that run it, in the same row language as every other tool. Rendered
// only when the project's local source lives on this machine; the status line
// says what is actually known (companion offline, code server down, not
// probed) before it summarises; conflicts get their own red line. Details
// opens the modal; the modal's footer hands the setup off to SOL.
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import type { Source } from '../../lib/api/resources'
import { codeEnvironmentStatus, conflictLine } from '../project/codeEnvironment.constants'
import { toolMark } from '../project/localFolder.constants'
import { useCodeEnvironment } from '../project/useCodeEnvironment'
import { CodeEnvironmentModal } from './CodeEnvironmentModal'
import { handOffToSol } from './codeEnvironmentSol'
import type { MainScreen } from './shellStore'
import './codeEnvironment.css'

export const CODE_ENVIRONMENT_TITLE = 'Code environment'

/** The square the row leads with — the scan's python mark, tinted software,
 *  so the row reads as kin to the detected `python` projects beneath the
 *  LOCAL FOLDER card. A local mark rather than ProviderMark: importing the
 *  card here would make the card and its row a module cycle. */
function PythonMark(): React.JSX.Element {
  const { mark, color } = toolMark('python')
  return (
    <span
      aria-hidden
      style={{
        width: 28,
        height: 28,
        borderRadius: 6,
        background: 'var(--sur2)',
        border: '1px solid var(--bd)',
        color,
        fontFamily: 'var(--font-mono)',
        fontSize: 11,
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexShrink: 0
      }}
    >
      {mark}
    </span>
  )
}

export interface CodeEnvironmentRowProps {
  projectId: string | null
  /** The project's sources; the row finds its own `local` one for this machine. */
  sources: readonly Source[]
  /** The shell navigator, so "Ask SOL to set it up" can open the SOL screen. */
  onNavigate?: (screen: MainScreen) => void
}

export function CodeEnvironmentRow({
  projectId,
  sources,
  onNavigate
}: CodeEnvironmentRowProps): React.JSX.Element | null {
  const env = useCodeEnvironment(projectId, sources)
  const [open, setOpen] = useState(false)
  if (!env.source) return null
  const conflicts = conflictLine(env.view)
  const askSol = (): void => {
    setOpen(false)
    void handOffToSol({ navigate: onNavigate })
  }
  return (
    <div className="code-env-in" style={{ borderTop: '1px solid var(--bd)' }}>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', padding: '13px 16px' }}>
        <PythonMark />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 12.5, fontWeight: 600 }}>{CODE_ENVIRONMENT_TITLE}</div>
          <div style={{ fontSize: 10.5, color: 'var(--mut)' }}>
            {codeEnvironmentStatus(env.view, env.status)}
          </div>
          {conflicts && (
            <div
              data-testid="code-env-conflicts"
              style={{ fontSize: 10.5, color: 'var(--err)', marginTop: 2 }}
            >
              {conflicts}
            </div>
          )}
        </div>
        <Button
          kind="ghost"
          size="sm"
          aria-label={`Details for ${CODE_ENVIRONMENT_TITLE}`}
          disabled={env.view === null}
          onClick={() => setOpen(true)}
        >
          Details
        </Button>
      </div>
      {open && env.view && (
        <CodeEnvironmentModal view={env.view} onClose={() => setOpen(false)} onAskSol={askSol} />
      )}
    </div>
  )
}
