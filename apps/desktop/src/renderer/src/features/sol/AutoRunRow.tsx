// SOLUSDEV-317 follow-up (code-command-execution.md §10.1/§10.3): a Build-mode
// `code.exec` that ran without a card, as a compact transcript row — program
// basename, status and an `auto` label — over the shared code-block output,
// collapsed beyond AUTO_RUN_VISIBLE_LINES. Untrusted terminal text: plain text
// only, and Copy copies the full retained output, not the collapsed view.
import { useState } from 'react'
import type { AutoRun } from '../../lib/api/solStream'
import { CodeBlock } from './CodeBlock'
import './AutoRunRow.css'

export const AUTO_RUN_VISIBLE_LINES = 12

function linesOf(output: string): string[] {
  const lines = output.split('\n')
  return lines.at(-1) === '' ? lines.slice(0, -1) : lines
}

function AutoRunOutput({ output }: { output: string }): React.JSX.Element {
  const [expanded, setExpanded] = useState(false)
  if (!output) return <p className="auto-run__empty">No output.</p>
  const lines = linesOf(output)
  const long = lines.length > AUTO_RUN_VISIBLE_LINES
  const shown = long && !expanded ? lines.slice(0, AUTO_RUN_VISIBLE_LINES).join('\n') : output
  return (
    <>
      <CodeBlock kind="output" text={output} shown={shown} scrollable />
      {long && (
        <button
          type="button"
          className="auto-run__toggle"
          aria-expanded={expanded}
          onClick={() => setExpanded((open) => !open)}
        >
          {expanded ? 'Show fewer lines' : `Show all ${lines.length} lines`}
        </button>
      )}
    </>
  )
}

export function AutoRunRow({ run }: { run: AutoRun }): React.JSX.Element {
  return (
    <div
      className="auto-run"
      role="group"
      aria-label={`Command ${run.program}, ${run.status}, ran automatically`}
    >
      <div className="auto-run__header">
        <span className="auto-run__program">{run.program}</span>
        <span className="auto-run__status">{run.status}</span>
        <span className="auto-run__badge">auto</span>
      </div>
      <AutoRunOutput output={run.output} />
    </div>
  )
}

/** Every auto-run row of one message, in call order (absent reads as none). */
export function AutoRunsView({ runs = [] }: { runs?: readonly AutoRun[] }): React.JSX.Element {
  return (
    <>
      {runs.map((run) => (
        <AutoRunRow key={run.callId} run={run} />
      ))}
    </>
  )
}
