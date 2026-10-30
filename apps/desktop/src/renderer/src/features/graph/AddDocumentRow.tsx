// One document row in the Add modal (design template): a checkbox glyph, the name, its mono
// subtitle, when it changed, and the `In graph` pill for a document already attached. Shared by
// the flat listing and the folder tree.
import { Mono } from '../../components/ui/Mono'
import type { SelectableItem } from '../../lib/api/resources'
import { relativeTime } from '../../lib/relativeTime'

export function AddDocumentRow({
  item,
  added,
  picked,
  busy,
  onClick
}: {
  item: SelectableItem
  added: boolean
  picked: boolean
  busy: boolean
  onClick: () => void
}): React.JSX.Element {
  const state = added ? 'graph' : picked ? 'picked' : 'unpicked'
  return (
    <button
      type="button"
      className="add-doc-row"
      aria-label={added ? `${item.name} · In graph` : item.name}
      aria-pressed={added ? undefined : picked}
      disabled={busy}
      onClick={onClick}
    >
      <span className="add-doc-check" data-state={state} aria-hidden="true">
        {picked && !added ? '✓' : ''}
      </span>
      <span className="add-doc-text">
        <span>{item.name}</span>
        {item.subtitle && <Mono size={10}>{item.subtitle}</Mono>}
      </span>
      {item.modified_at && <Mono size={10}>{relativeTime(item.modified_at)}</Mono>}
      {added && <span className="add-doc-pill">In graph</span>}
    </button>
  )
}
