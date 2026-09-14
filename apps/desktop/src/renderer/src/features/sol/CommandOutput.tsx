import { useEffect, useState } from 'react'
import { api } from '../../lib/api/client'

interface Progress {
  chunks: { sequence: number; stream: 'stdout' | 'stderr'; text: string }[]
  cursor: number
  complete: boolean
  truncated: boolean
}

/** Mounted only during the already-approved command; progress grants no authority. */
export function CommandOutput({
  projectId,
  confirmationId
}: {
  projectId: string
  confirmationId: string
}): React.JSX.Element {
  const [text, setText] = useState('')
  const [unavailable, setUnavailable] = useState(false)
  const [truncated, setTruncated] = useState(false)
  useEffect(() => {
    let stopped = false
    let cursor = 0
    let timer: ReturnType<typeof setTimeout> | undefined
    async function poll(): Promise<void> {
      try {
        const result = await api.request<Progress>(
          `/projects/${projectId}/sol/confirmations/${confirmationId}/output?cursor=${cursor}`
        )
        if (stopped) return
        const next = result.chunks
          .filter((chunk) => chunk.sequence > cursor)
          .slice(0, 256)
          .map((chunk) => chunk.text.slice(0, 2048))
          .join('')
        setText((previous) => (previous + next).slice(0, 262144))
        setTruncated(result.truncated)
        setUnavailable(false)
        cursor = Math.min(256, Math.max(cursor, result.cursor))
        if (result.complete) return
      } catch {
        if (stopped) return
        setUnavailable(true)
      }
      if (!stopped) timer = setTimeout(() => void poll(), 750)
    }
    void poll()
    return () => {
      stopped = true
      if (timer !== undefined) clearTimeout(timer)
    }
  }, [projectId, confirmationId])
  return (
    <div className="confirmation-card__output" aria-label="Command output">
      {unavailable && <p>Progress unavailable. Waiting for the command result.</p>}
      <pre tabIndex={0}>{text || 'Waiting for command output…'}</pre>
      {truncated && <p>Output display limit reached. The final result includes output tails.</p>}
    </div>
  )
}
