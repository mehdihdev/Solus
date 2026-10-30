// The Add modal's right pane for a connected account (design template): who is connected,
// a search box, and the account's cached documents as checkbox rows. A document already in
// the graph shows the `In graph` pill and re-selecting it only focuses its node; the rest
// toggle into the pick set the footer confirms. Tree-shaped providers keep their tree.
import { useState } from 'react'
import { Icons } from '../../components/ui/icons.constants'
import type { Connection, SelectableItem } from '../../lib/api/resources'
import { matches } from '../onboarding/pickerModel'
import { AddDocumentRow } from './AddDocumentRow'
import type { DocumentListing, ServiceCatalog } from './serviceCatalog'
import { ServiceDocumentTree } from './ServiceDocumentTree'
import { isServiceAdded, type useServiceAttachments } from './useServiceAttachments'

export interface AddDocumentsPaneProps {
  account: Connection
  listing?: DocumentListing
  catalog: ServiceCatalog
  project: ReturnType<typeof useServiceAttachments>
  picks: readonly SelectableItem[]
  onToggle: (item: SelectableItem) => void
}

function ListingStatus({ listing }: { listing?: DocumentListing }): React.ReactNode {
  switch (listing?.status) {
    case 'loading':
      return <p role="status">Reading cached documents…</p>
    case 'missing':
      return <p>No cached documents yet. Load them once to choose what to add.</p>
    case 'error':
      return <p role="alert">{listing.error}</p>
    case 'ready':
      return listing.items.length === 0 ? <p>This account has no selectable documents.</p> : null
    default:
      return null
  }
}

interface FlatProps extends AddDocumentsPaneProps {
  q: string
  busy: boolean
  added: (item: SelectableItem) => boolean
  select: (item: SelectableItem) => void
}

/** The cached listing as rows, filtered by the search box, plus the explicit load/refresh link. */
function FlatDocuments({
  account,
  listing,
  catalog,
  picks,
  onToggle,
  q,
  busy,
  added,
  select
}: FlatProps): React.JSX.Element {
  const ready = listing?.status === 'ready'
  const items = ready ? matches(listing.items, q) : []
  return (
    <>
      <ListingStatus listing={listing} />
      {items.map((item) => {
        const inGraph = added(item)
        return (
          <AddDocumentRow
            key={item.id}
            item={item}
            added={inGraph}
            picked={picks.some((pick) => pick.id === item.id)}
            busy={busy}
            onClick={() => (inGraph ? select(item) : onToggle(item))}
          />
        )
      })}
      {ready && listing.items.length > 0 && items.length === 0 && (
        <p>No documents match “{q.trim()}”</p>
      )}
      <button
        type="button"
        className="workspace-refresh"
        disabled={busy || listing?.status === 'loading'}
        onClick={() => void catalog.loadDocuments(account.id, true)}
      >
        {ready ? 'Refresh documents' : 'Load documents'}
      </button>
    </>
  )
}

export function AddDocumentsPane(props: AddDocumentsPaneProps): React.JSX.Element {
  const { account, catalog, project } = props
  const [q, setQ] = useState('')
  const busy = project.state.busyId !== null
  const added = (item: SelectableItem): boolean =>
    isServiceAdded(project.state.sources, account, item)
  const select = (item: SelectableItem): void => void project.session.select(account, item)
  return (
    <div className="add-modal-pane" role="tabpanel">
      <div className="add-modal-pane-head">
        {account.account_login && (
          <p className="add-account-line">
            <i aria-hidden="true" />
            Connected as {account.account_login}
          </p>
        )}
        {!account.document_tree && (
          <label className="add-search">
            <Icons.search size={13} />
            <input
              type="search"
              aria-label="Search documents"
              placeholder={`Search ${account.provider} documents`}
              value={q}
              onChange={(event) => setQ(event.target.value)}
            />
          </label>
        )}
      </div>
      <div className="add-modal-pane-body">
        {account.document_tree ? (
          <ServiceDocumentTree
            catalog={catalog.tree}
            connectionId={account.id}
            busy={busy}
            added={added}
            select={select}
            picked={(item) => props.picks.some((pick) => pick.id === item.id)}
            onToggle={props.onToggle}
          />
        ) : (
          <FlatDocuments {...props} q={q} busy={busy} added={added} select={select} />
        )}
      </div>
    </div>
  )
}
