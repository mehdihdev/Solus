// One active bench session, inline with its source row (SOLUSDEV-72). The link
// state is the backend's honest word — a dead pump reads DISCONNECTED here.
import { Button } from '../../../components/ui/Button'
import { Mono } from '../../../components/ui/Mono'
import type { BenchLinkState, BenchSession } from '../../../lib/api/resources'

const LINK_COLOR: Record<BenchLinkState, string> = {
  streaming: 'var(--ok)',
  connected: 'var(--acc)',
  disconnected: 'var(--err)'
}

export function SessionChip({
  session,
  onStop
}: {
  session: BenchSession
  onStop: (sessionId: string) => void
}): React.JSX.Element {
  // A starting session has no honest link state yet, and the backend 409s
  // `session_starting` on stop — say STARTING and hold the button.
  const starting = session.status === 'starting'
  return (
    <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginTop: 8 }}>
      <Mono
        size={8.5}
        color={starting ? 'var(--acc)' : LINK_COLOR[session.link]}
        style={{ letterSpacing: '0.06em' }}
      >
        {starting ? 'STARTING' : session.link.toUpperCase()}
      </Mono>
      <span style={{ fontSize: 11.5, flex: 1, minWidth: 0 }}>{session.label}</span>
      <Mono size={8.5} color="var(--mut)">
        {session.counts.ingested} INGESTED
      </Mono>
      <Button
        kind="ghost"
        size="sm"
        aria-label={`Stop ${session.label}`}
        disabled={starting}
        onClick={() => onStop(session.id)}
      >
        Stop
      </Button>
    </div>
  )
}
