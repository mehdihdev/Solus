// NODES IN CONTEXT (design template, SOL page right column): the chat's pinned nodes —
// they ride along with every message as mentions. ✕ unpins; "From graph →" goes to the
// Workspace, where a node's panel offers Ask SOL.
import { Mono } from '../../components/ui/Mono'
import { MAX_MENTIONS } from './mentionToken'
import { DomainDot, domainIdOf } from './domainDot'
import type { PinnedNode } from './pinnedContextStore'

export function PinnedNodesSection({
  pins,
  onUnpin,
  onFromGraph
}: {
  pins: readonly PinnedNode[]
  onUnpin: (entityId: string) => void
  onFromGraph: () => void
}): React.JSX.Element {
  return (
    <section className="sol-side-section" aria-label="Nodes in context">
      <div className="sol-side-head">
        <Mono size={10} ls="0.08em">
          NODES IN CONTEXT
        </Mono>
        <button type="button" className="sol-side-link" onClick={onFromGraph}>
          From graph →
        </button>
      </div>
      {pins.length === 0 && (
        <p className="sol-side-empty">
          Pin nodes from the graph — they ride along with every message in this chat.
        </p>
      )}
      {pins.length > 0 && (
        <ul className="sol-pin-list">
          {pins.map((node) => (
            <li key={node.id} className="sol-pin-row">
              <DomainDot d={domainIdOf(node.domain)} />
              <span className="sol-pin-name">{node.name}</span>
              <Mono size={10}>{node.type.replaceAll('_', ' ')}</Mono>
              <button
                type="button"
                className="sol-side-x"
                aria-label={`Remove ${node.name}`}
                onClick={() => onUnpin(node.id)}
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      )}
      {pins.length > MAX_MENTIONS && (
        <p className="sol-side-empty" role="note">
          Only the first {MAX_MENTIONS} nodes ride along with a message.
        </p>
      )}
    </section>
  )
}
