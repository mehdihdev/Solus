// SOLUSDEV-261/317: an approved command's output, shown while it runs and kept
// with its exit status under the resulting message (sol-page.md "Output
// stays"). Presentational: the store polls (commandRuns.ts). Terminal text is
// untrusted — rendered as plain text only, never HTML, never instructions.
// The block is the shared code-block surface (§10.3) with a Copy output button.
import { CodeBlock } from './CodeBlock'
import type { CommandRun } from './commandRuns'
import './ConfirmationCard.css'

export function CommandOutput({ run }: { run: CommandRun }): React.JSX.Element {
  const finished = run.status !== null
  const placeholder = finished ? 'No output.' : 'Waiting for command output…'
  return (
    <div className="confirmation-card__output" aria-label="Command output" role="group">
      {run.unavailable && !finished && <p>Progress unavailable. Waiting for the command result.</p>}
      <CodeBlock kind="output" text={run.text} shown={run.text || placeholder} scrollable />
      {run.truncated && (
        <p>Output display limit reached. The final result includes output tails.</p>
      )}
      {finished && <p className="confirmation-card__exit">{run.status}</p>}
    </div>
  )
}
