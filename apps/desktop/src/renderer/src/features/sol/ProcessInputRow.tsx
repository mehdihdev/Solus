// SOLUSDEV-317 §11.3 waiting row: an interactive process is asking. Shows what
// it printed (untrusted machine text, plain text in the shared CodeBlock) and
// lets the person answer — Send writes the text plus Enter, Enter writes a bare
// Enter — through the owner-scoped user input route. A direct user action: no
// card. The input carries the composer marker, so a Cmd/Ctrl+Enter typed here
// with a draft never approves a command card.
import { useCallback, useState } from 'react'
import { MAX_PROCESS_INPUT_CHARS, type CodeProcess } from '../../lib/api/resources.commands'
import { CodeBlock } from './CodeBlock'
import { COMPOSER_ATTR } from './commandHotkey'
import { INPUT_ERROR, inputErrorText, programName } from './processStrip.constants'

export type SendProcessInput = (text: string) => Promise<{ readonly ok: boolean }>

interface Sender {
  readonly busy: boolean
  readonly error: string | null
  readonly send: (text: string) => Promise<boolean>
}

function useSender(sendInput: SendProcessInput, onSent: () => Promise<void>): Sender {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const send = useCallback(
    async (text: string): Promise<boolean> => {
      setBusy(true)
      setError(null)
      try {
        const answer = await sendInput(text)
        if (!answer.ok) throw new Error(INPUT_ERROR)
        await onSent()
        return true
      } catch (thrown) {
        setError(inputErrorText(thrown))
        return false
      } finally {
        setBusy(false)
      }
    },
    [sendInput, onSent]
  )
  return { busy, error, send }
}

/** Cmd/Ctrl+Enter belongs to the surface's approve shortcut — never a submit. */
function keepShortcut(event: React.KeyboardEvent<HTMLInputElement>): void {
  if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) event.preventDefault()
}

export interface ProcessInputRowProps {
  readonly process: CodeProcess
  /** The draft lives with the row, so a poll that re-renders keeps it. */
  readonly draft: string
  readonly onDraft: (text: string) => void
  readonly sendInput: SendProcessInput
  readonly onSent: () => Promise<void>
}

export function ProcessInputRow({
  process,
  draft,
  onDraft,
  sendInput,
  onSent
}: ProcessInputRowProps): React.JSX.Element {
  const { busy, error, send } = useSender(sendInput, onSent)
  const submit = (event: React.FormEvent): void => {
    event.preventDefault()
    if (busy || draft === '') return
    void send(draft).then((sent) => sent && onDraft(''))
  }
  const name = programName(process)
  return (
    <div className="process-strip__waiting" role="group" aria-label={`${name} is waiting`}>
      <span className="process-strip__badge">Waiting for input</span>
      {process.prompt_tail !== '' && <CodeBlock text={process.prompt_tail} kind="output" />}
      <form className="process-strip__answer" onSubmit={submit}>
        <input
          type="text"
          aria-label={`Input for ${name}`}
          value={draft}
          maxLength={MAX_PROCESS_INPUT_CHARS}
          autoComplete="off"
          spellCheck={false}
          disabled={busy}
          onChange={(event) => onDraft(event.target.value)}
          onKeyDown={keepShortcut}
          {...{ [COMPOSER_ATTR]: '' }}
        />
        <button type="submit" disabled={busy || draft === ''}>
          {busy ? 'Sending…' : 'Send'}
        </button>
        <button type="button" disabled={busy} onClick={() => void send('')}>
          Enter
        </button>
      </form>
      {error !== null && (
        <p role="alert" className="process-strip__error">
          {error}
        </p>
      )}
    </div>
  )
}
