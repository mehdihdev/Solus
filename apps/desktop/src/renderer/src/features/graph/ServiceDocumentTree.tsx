// A tree-shaped provider's documents in the Add modal (design template rows): folders expand
// in place with a chevron, documents are the same checkbox rows the flat listing uses. With
// `onToggle`, a document joins the pick set (an attached one still focuses its node on click);
// without it, a click selects at once. Loading is cache-only; refresh is explicit at the root.
import { useEffect, useState, useSyncExternalStore } from 'react'
import { Mono } from '../../components/ui/Mono'
import type { SelectableItem } from '../../lib/api/resources'
import type { DocumentTreeItem } from '../../lib/api/resources.documentTree'
import { useSettingsStore } from '../../store/settingsStore'
import { AddDocumentRow } from './AddDocumentRow'
import type { DocumentTreeCatalog, TreeListing } from './documentTreeCatalog'

interface Props {
  catalog: DocumentTreeCatalog
  connectionId: string
  busy: boolean
  added: (item: SelectableItem) => boolean
  select: (item: SelectableItem) => void
  /** Pick-set support (the Add modal): a document not yet in the graph toggles instead of selecting. */
  picked?: (item: SelectableItem) => boolean
  onToggle?: (item: SelectableItem) => void
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
  const root = ancestors.length === 0
  return (
    <div className={root ? 'add-tree' : 'add-tree add-tree-branch'}>
      <TreeStatus listing={listing} />
      {listing?.items.map((item) => (
        <TreeRow key={`${item.kind}:${item.id}`} {...props} item={item} />
      ))}
      <BranchLinks
        listing={listing}
        root={root}
        onMore={() => void catalog.more(connectionId, node)}
        onReload={() => void catalog.load(connectionId, node, true)}
      />
    </div>
  )
}

/** "Load more" when the page continues; the explicit load/refresh at the root (or after a miss). */
function BranchLinks({
  listing,
  root,
  onMore,
  onReload
}: {
  listing?: TreeListing
  root: boolean
  onMore: () => void
  onReload: () => void
}): React.JSX.Element {
  const status = listing?.status
  const loading = status === 'loading'
  const offerReload = root || status === 'missing' || status === 'error'
  return (
    <>
      <MoreLink listing={listing} loading={loading} onMore={onMore} />
      {offerReload && (
        <button type="button" className="workspace-refresh" disabled={loading} onClick={onReload}>
          {listing?.items.length ? 'Refresh documents' : 'Load documents'}
        </button>
      )}
    </>
  )
}

function MoreLink({
  listing,
  loading,
  onMore
}: {
  listing?: TreeListing
  loading: boolean
  onMore: () => void
}): React.JSX.Element | null {
  if (listing?.nextOffset == null) return null
  return (
    <button type="button" className="workspace-refresh" disabled={loading} onClick={onMore}>
      Load more
    </button>
  )
}

function TreeRow(props: BranchProps & { item: DocumentTreeItem }): React.JSX.Element {
  const { item, busy, select, added, picked, onToggle } = props
  if (item.kind === 'folder') return <FolderRow {...props} />
  const inGraph = added(item)
  return (
    <AddDocumentRow
      item={item}
      added={inGraph}
      picked={picked?.(item) ?? false}
      busy={busy}
      onClick={() => (onToggle && !inGraph ? onToggle(item) : select(item))}
    />
  )
}

function FolderRow(props: BranchProps & { item: DocumentTreeItem }): React.JSX.Element {
  const { item, node, ancestors } = props
  const [expanded, setExpanded] = useState(false)
  const child = item.node
  const blocked =
    child === null || ancestors.includes(child) || child === node || ancestors.length >= 20
  return (
    <div className="add-tree-folder">
      <button
        type="button"
        className="add-tree-folder-row"
        aria-expanded={expanded}
        aria-label={item.name}
        disabled={blocked}
        title={blocked ? 'This folder cannot be expanded further.' : `${item.name} (folder)`}
        onClick={() => setExpanded(!expanded)}
      >
        <span className="add-tree-chevron" aria-hidden="true">
          {expanded ? '▾' : '▸'}
        </span>
        <strong>{item.name}</strong>
        <Mono size={10}>folder</Mono>
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
