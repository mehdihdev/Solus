import type { Connection, SelectableItem } from '../../lib/api/resources'
import { ProviderMark } from '../workspace/ConnectedAccountsCard'
import { isServiceAdded, type useServiceAttachments } from './useServiceAttachments'
import { supportsWorkspaceService } from './serviceAttachments'
import type { CatalogSnapshot, DocumentListing, ServiceCatalog } from './serviceCatalog'
interface AccountProps {
  catalog: ServiceCatalog
  state: CatalogSnapshot
  project: ReturnType<typeof useServiceAttachments>
  expanded: string | null
  onExpand: (id: string) => void
}
export function ServiceAccountPanel({
  catalog,
  state,
  project,
  expanded,
  onExpand
}: AccountProps): React.JSX.Element {
  return (
    <div role="tabpanel">
      {state.status === 'loading' && <p role="status">Loading accounts…</p>}
      {state.error && <p role="alert">{state.error}</p>}
      {state.status === 'ready' && state.accounts.length === 0 && (
        <p>Connect an account in Home to add its documents.</p>
      )}
      {state.accounts.map((account) => (
        <div className="workspace-service-account" key={account.id}>
          <button
            type="button"
            aria-expanded={expanded === account.id}
            aria-label={`${account.provider} · ${account.account_login ?? account.provider}`}
            disabled={account.status !== 'connected' || !supportsWorkspaceService(account.provider)}
            onClick={() => onExpand(account.id)}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}
          >
            <ProviderMark
              entry={{ id: account.provider, mark: account.provider.slice(0, 1).toUpperCase() }}
            />
            {account.account_login ?? account.provider}
          </button>
          {account.last_error && <p role="alert">{account.last_error.message}</p>}
          {expanded === account.id && (
            <ServiceDocuments
              account={account}
              listing={state.documents[account.id]}
              catalog={catalog}
              busy={project.state.busyId !== null}
              added={(item) => isServiceAdded(project.state.sources, account, item)}
              select={(item) => void project.session.select(account, item)}
            />
          )}
        </div>
      ))}
      <button
        type="button"
        className="workspace-refresh"
        onClick={() => void catalog.loadAccounts(true)}
      >
        Refresh accounts
      </button>
    </div>
  )
}
interface DocumentProps {
  account: Connection
  listing?: DocumentListing
  catalog: ServiceCatalog
  busy: boolean
  added: (item: SelectableItem) => boolean
  select: (item: SelectableItem) => void
}
function ServiceDocuments({
  account,
  listing,
  catalog,
  busy,
  added,
  select
}: DocumentProps): React.JSX.Element {
  const loaded = listing?.status === 'ready'
  return (
    <div className="workspace-service-documents">
      <ListingStatus listing={listing} />
      {listing?.items.map((item) => (
        <button type="button" key={item.id} disabled={busy} onClick={() => select(item)}>
          {item.name}
          {added(item) ? ' · Added' : ''}
        </button>
      ))}
      <button
        type="button"
        className="workspace-refresh"
        disabled={busy || listing?.status === 'loading'}
        onClick={() => void catalog.loadDocuments(account.id, true)}
      >
        {loaded ? 'Refresh documents' : 'Load documents'}
      </button>
    </div>
  )
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
