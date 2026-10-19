// SOLUSDEV-317 follow-up (code-command-execution.md §10.3): the ONE code-block
// surface SOL uses — markdown code blocks in messages and every command-output
// region share its background token, monospace font, border and padding, and
// each carries a top-right Copy button. The text is untrusted (model output,
// terminal output): it renders as a React text node only, never HTML.
import { useEffect, useRef, useState } from 'react'
import './CodeBlock.css'

/** How long the button reads "Copied" after a successful copy. */
export const COPIED_MS = 1500

export type WriteText = (text: string) => Promise<void>

function clipboardWriteText(text: string): Promise<void> {
  return navigator.clipboard.writeText(text)
}

export interface CodeBlockProps {
  /** The block's plain text: what is shown (unless `shown` overrides) and copied. */
  readonly text: string
  /** `code` for markdown blocks, `output` for command output — names the button. */
  readonly kind: 'code' | 'output'
  /** What the block shows when it differs from the copied text (a collapsed
   *  view, or a placeholder while there is no output yet). */
  readonly shown?: string
  /** Keyboard-scrollable bounded region (command output). */
  readonly scrollable?: boolean
  /** Injectable clipboard seam (tests); defaults to the browser clipboard. */
  readonly writeText?: WriteText
}

function useCopied(): [boolean, () => void] {
  const [copied, setCopied] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  useEffect(() => () => clearTimeout(timer.current), [])
  const flash = (): void => {
    clearTimeout(timer.current)
    setCopied(true)
    timer.current = setTimeout(() => setCopied(false), COPIED_MS)
  }
  return [copied, flash]
}

/** Cmd/Ctrl+Enter belongs to the surface's approve shortcut: the button lets it
 *  bubble untouched and only suppresses its own default activation. */
function keepShortcut(event: React.KeyboardEvent<HTMLButtonElement>): void {
  if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) event.preventDefault()
}

export function CodeBlock({
  text,
  kind,
  shown,
  scrollable = false,
  writeText = clipboardWriteText
}: CodeBlockProps): React.JSX.Element {
  const [copied, flash] = useCopied()
  const copy = (): void => {
    void writeText(text).then(flash, () => undefined)
  }
  const label = kind === 'code' ? 'Copy code' : 'Copy output'
  return (
    <div className="code-block" data-kind={kind}>
      <pre className="code-block__pre" tabIndex={scrollable ? 0 : undefined}>
        <code>{shown ?? text}</code>
      </pre>
      <button
        type="button"
        className="code-block__copy"
        aria-label={label}
        onClick={copy}
        onKeyDown={keepShortcut}
      >
        {copied ? 'Copied' : 'Copy'}
      </button>
      <span className="code-block__status" role="status">
        {copied ? 'Copied' : ''}
      </span>
    </div>
  )
}
