// SOLUSDEV-321 P1-T6: "answered from the graph". The first tier answers from the graph with no
// model call; this badge says so and names the fact sources it read — the line the dropped
// synthetic tool call used to put in the trace. It shows only what the server said: a source it
// does not know renders nothing, never a guess. Text nodes only.
import type { AnswerSourceInfo } from './solStream'

const BADGE: React.CSSProperties = {
  display: 'flex',
  width: 'fit-content',
  alignItems: 'center',
  gap: 6,
  marginTop: 6,
  fontFamily: 'var(--font-mono)',
  fontSize: 10.5,
  color: 'var(--mut)',
  background: 'var(--sur2)',
  border: '1px solid var(--bd)',
  borderRadius: 999,
  padding: '2px 8px'
}

export function AnswerSourceBadge({
  answer
}: {
  answer: AnswerSourceInfo | undefined
}): React.JSX.Element | null {
  if (answer?.source !== 'graph') return null
  return (
    <span data-testid="answer-source" style={BADGE}>
      <span>answered from the graph</span>
      {answer.sources.length > 0 && (
        <>
          <span aria-hidden="true">·</span>
          <span>{`sources: ${answer.sources.join(', ')}`}</span>
        </>
      )}
    </span>
  )
}
