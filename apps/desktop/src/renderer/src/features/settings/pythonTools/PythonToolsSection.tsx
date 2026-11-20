// SOLUSDEV-329 — Settings › Python for local tools (docs/wireflows/settings.md):
// the interpreter the local MCP tools run on, and their setup state.
// States: detecting · none found (managed offer, consent first) · candidates ·
// unsupported pick · installing · partial / failed (Repair) · ready.
// Copy follows the SOL mode (ADR-016). Everything from the CLI is plain text.
import { useState } from 'react'
import { Button } from '../../../components/ui/Button'
import { useSettingsStore, type SolMode } from '../../../store/settingsStore'
import { InlineError, Section } from '../settingsUi'
import { InterpreterList } from './InterpreterList'
import { ToolRows } from './ToolRows'
import type { PythonTools } from './usePythonTools'
import {
  COPY,
  LEARN_MORE,
  MANAGED_DOWNLOAD_LABEL,
  NONE_FOUND,
  SECTION_TITLE,
  chooseErrorMessage,
  fixHint,
  stepLabel
} from './pythonToolsCopy'

const NOTE: React.CSSProperties = { fontSize: 11.5, color: 'var(--mut)', lineHeight: 1.5 }
const STACK: React.CSSProperties = { display: 'flex', flexDirection: 'column', gap: 12 }
const BUTTONS: React.CSSProperties = { display: 'flex', gap: 8, flexWrap: 'wrap' }

function Intro({ mode }: { mode: SolMode }): React.JSX.Element {
  const [open, setOpen] = useState(false)
  return (
    <div style={NOTE}>
      <span data-testid="python-intro">{COPY.intro[mode]}</span>
      {mode === 'Guide' && (
        <>
          {' '}
          <Button kind="bare" size="sm" onClick={() => setOpen((o) => !o)}>
            Learn more
          </Button>
          {open && <div style={{ marginTop: 6 }}>{LEARN_MORE}</div>}
        </>
      )}
    </div>
  )
}

function ManagedOffer({ tools, mode }: { tools: PythonTools; mode: SolMode }): React.JSX.Element {
  return (
    <div style={STACK}>
      <div style={NOTE}>{COPY.managed[mode]}</div>
      <div style={BUTTONS}>
        <Button kind="primary" size="sm" onClick={tools.actions.acceptManaged}>
          {MANAGED_DOWNLOAD_LABEL}
        </Button>
        <Button kind="ghost" size="sm" onClick={tools.actions.declineManaged}>
          Not now
        </Button>
      </div>
    </div>
  )
}

function Interpreter({ tools, mode }: { tools: PythonTools; mode: SolMode }): React.JSX.Element {
  const noneFound = tools.candidates.every((c) => !c.supported) && tools.choice?.mode !== 'managed'
  const locked = tools.running || tools.choice?.writable === false
  return (
    <div style={STACK}>
      {noneFound && (
        <div>
          <div style={{ fontSize: 12.5 }}>{NONE_FOUND}</div>
          <div style={NOTE}>{COPY.noneFound[mode]}</div>
        </div>
      )}
      {!noneFound && (
        <InterpreterList
          candidates={tools.candidates}
          choice={tools.choice}
          disabled={locked}
          onCandidate={tools.actions.chooseCandidate}
          onManaged={tools.actions.chooseManaged}
        />
      )}
      {tools.offerOpen && !tools.running && <ManagedOffer tools={tools} mode={mode} />}
      <div style={BUTTONS}>
        <Button kind="ghost" size="sm" disabled={locked} onClick={tools.actions.pick}>
          Choose…
        </Button>
      </div>
      <InlineError
        message={tools.chooseError ? chooseErrorMessage(tools.chooseError, mode) : null}
      />
    </div>
  )
}

function statusLine(tools: PythonTools, mode: SolMode): string {
  if (tools.running) return COPY.installing[mode]
  if (tools.choiceChanged) return COPY.choiceChanged[mode]
  if (tools.failed.length > 0) return COPY.partial[mode]
  if (tools.needsSetup.length > 0) return COPY.needsSetup[mode]
  return COPY.ready[mode]
}

function RunActions({ tools }: { tools: PythonTools }): React.JSX.Element | null {
  const { actions } = tools
  if (tools.running) {
    return (
      <Button kind="ghost" size="sm" onClick={actions.cancel}>
        Cancel
      </Button>
    )
  }
  if (tools.choiceChanged) {
    return (
      <Button kind="primary" size="sm" onClick={actions.setupAll}>
        Set up now
      </Button>
    )
  }
  if (tools.failed.length > 0) {
    return (
      <Button kind="primary" size="sm" onClick={actions.repair}>
        Repair
      </Button>
    )
  }
  if (tools.needsSetup.length === 0) return null
  return (
    <Button kind="primary" size="sm" onClick={actions.setupAll}>
      Install
    </Button>
  )
}

function RunNotes({ tools }: { tools: PythonTools }): React.JSX.Element {
  const { run } = tools
  const global = tools.running ? run?.global : null
  return (
    <>
      {global && <div style={NOTE}>{stepLabel(global.step, global.done, global.total)}</div>}
      {!tools.running && run?.error && (
        <div role="alert" style={{ ...NOTE, color: 'var(--err)' }}>
          {run.error.message} {fixHint(run.error.error_code)}
        </div>
      )}
      <InlineError
        message={tools.actionFailed ? "Setup couldn't start. Try again in a moment." : null}
      />
    </>
  )
}

function Tools({ tools, mode }: { tools: PythonTools; mode: SolMode }): React.JSX.Element {
  return (
    <div style={STACK}>
      <div style={NOTE}>{statusLine(tools, mode)}</div>
      <ToolRows
        forks={tools.forks}
        run={tools.run}
        running={tools.running}
        needsSetup={tools.needsSetup}
      />
      <RunNotes tools={tools} />
      <div style={BUTTONS}>
        <RunActions tools={tools} />
      </div>
    </div>
  )
}

export function PythonToolsSection({ tools }: { tools: PythonTools }): React.JSX.Element {
  const mode = useSettingsStore((s) => s.solMode)
  return (
    <Section id="python" title={SECTION_TITLE}>
      <div style={STACK}>
        <Intro mode={mode} />
        {tools.phase === 'detecting' && (
          <div data-testid="python-detecting" aria-busy="true" style={NOTE}>
            {COPY.detecting[mode]}
          </div>
        )}
        {tools.phase === 'error' && <InlineError message={COPY.unavailable[mode]} />}
        {tools.phase === 'ready' && (
          <>
            <Interpreter tools={tools} mode={mode} />
            <Tools tools={tools} mode={mode} />
          </>
        )}
      </div>
    </Section>
  )
}
