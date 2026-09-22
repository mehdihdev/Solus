import { useEffect, useState, useSyncExternalStore } from 'react'
import type { SelectableItem } from '../../lib/api/resources'
import { useSettingsStore } from '../../store/settingsStore'
import type { DocumentTreeItem } from '../../lib/api/resources.documentTree'
import type { DocumentTreeCatalog, TreeListing } from './documentTreeCatalog'
interface Props {
  catalog: DocumentTreeCatalog
  connectionId: string
  busy: boolean
  added: (item: SelectableItem) => boolean
  select: (item: SelectableItem) => void
}
export function ServiceDocumentTree(props: Props): React.JSX.Element {
  return <TreeBranch {...props} node="root" ancestors={[]} />
}
interface BranchProps extends Props {
  node: string
  ancestors: string[]
}
function TreeBranch(props: BranchProps): React.JSX.Element {
  const { catalog, connectionId, node, ancestors } = props
  const state = useSyncExternalStore(catalog.subscribe, catalog.snapshot)
  const listing = state[`${connectionId}:${node}`]
  useEffect(() => {
    void catalog.load(connectionId, node)
  }, [catalog, connectionId, node])
  return (
    <div className="workspace-service-documents" style={{ paddingLeft: ancestors.length ? 12 : 0 }}>
      <TreeStatus listing={listing} />
      {listing?.items.map((item) => (
        <TreeRow key={`${item.kind}:${item.id}`} {...props} item={item} />
      ))}
      {listing?.nextOffset != null && (
        <button
          type="button"
          disabled={listing.status === 'loading'}
          onClick={() => void catalog.more(connectionId, node)}
        >
          Load more
        </button>
      )}
      <button
        type="button"
        disabled={listing?.status === 'loading'}
        onClick={() => void catalog.load(connectionId, node, true)}
      >
        {listing?.items.length ? 'Refresh documents' : 'Load documents'}
      </button>
    </div>
  )
}

function TreeRow(props: BranchProps & { item: DocumentTreeItem }): React.JSX.Element {
  const { item, busy, select, added } = props
  if (item.kind === 'folder') return <FolderRow {...props} />
  return (
    <button type="button" disabled={busy} onClick={() => select(item)}>
      {item.name}
      {added(item) ? ' · Added' : ''}
    </button>
  )
}

function FolderRow(props: BranchProps & { item: DocumentTreeItem }): React.JSX.Element {
  const { item, node, ancestors } = props
  const [expanded, setExpanded] = useState(false)
  const child = item.node
  const blocked =
    child === null || ancestors.includes(child) || child === node || ancestors.length >= 20
  return (
    <div>
      <button
        type="button"
        aria-expanded={expanded}
        disabled={blocked}
        title={blocked ? 'This folder cannot be expanded further.' : undefined}
        onClick={() => setExpanded(!expanded)}
      >
        {item.name}
      </button>
      {child !== null && !blocked && expanded && (
        <TreeBranch {...props} node={child} ancestors={[...ancestors, node]} />
      )}
    </div>
  )
}

function TreeStatus({ listing }: { listing?: TreeListing }): React.ReactNode {
  const mode = useSettingsStore((settings) => settings.solMode)
  switch (listing?.status) {
    case 'loading':
      return <p role="status">Loading documents…</p>
    case 'missing':
      return (
        <p>
          {mode === 'Guide'
            ? 'Load your documents once, then expand a folder to choose a document.'
            : 'No cached documents.'}
        </p>
      )
    case 'error':
      return <p role="alert">{listing.error}</p>
    case 'ready':
      return listing.items.length === 0 ? <p>No documents here.</p> : null
    default:
      return null
  }
}
