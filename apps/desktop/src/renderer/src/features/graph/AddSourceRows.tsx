// The Add modal's left column (design template): INTEGRATIONS — one row per connected
// account (logo tile · login · document count), a `.solus` upload row and a Hardware row.
// Rows are tabs: the right pane follows the selected one. Only real counts are shown.
import { Mono } from '../../components/ui/Mono'
import { SolusLogo } from '../../components/ui/SolusLogo'
import { Icons } from '../../components/ui/icons.constants'
import type { Connection } from '../../lib/api/resources'
import { countOf } from '../onboarding/pickerModel'
import { ProviderMark } from '../workspace/ConnectedAccountsCard'
import { supportsWorkspaceService } from './serviceAttachments'
import type { CatalogSnapshot, DocumentListing } from './serviceCatalog'

export type AddTarget = { kind: 'account'; id: string } | { kind: 'solus' } | { kind: 'hardware' }

export const sameTarget = (a: AddTarget, b: AddTarget): boolean =>
  a.kind === b.kind && (a.kind !== 'account' || b.kind !== 'account' || a.id === b.id)

export function accountUsable(account: Connection): boolean {
  return account.status === 'connected' && supportsWorkspaceService(account.provider)
}

function accountSub(account: Connection, listing: DocumentListing | undefined): string {
  if (listing?.status === 'ready') return countOf(listing.items.length, 'document')
  return account.provider
}

function Row({
  selected,
  disabled,
  label,
  tile,
  name,
  sub,
  onSelect
}: {
  selected: boolean
  disabled?: boolean
  label: string
  tile: React.ReactNode
  name: string
  sub: string
  onSelect: () => void
}): React.JSX.Element {
  return (
    <button
      type="button"
      role="tab"
      className="add-source-row"
      aria-selected={selected}
      aria-label={label}
      disabled={disabled}
      onClick={onSelect}
    >
      <span className="add-source-tile" aria-hidden="true">
        {tile}
      </span>
      <span className="add-source-text">
        <strong>{name}</strong>
        <Mono size={10}>{sub}</Mono>
      </span>
    </button>
  )
}

export function AddSourceRows({
  state,
  selected,
  onSelect,
  onRefresh
}: {
  state: CatalogSnapshot
  selected: AddTarget
  onSelect: (target: AddTarget) => void
  onRefresh: () => void
}): React.JSX.Element {
  return (
    <div
      className="add-modal-sources"
      role="tablist"
      aria-label="Add type"
      aria-orientation="vertical"
    >
      <Mono size={10} ls="0.08em" className="add-modal-sources-title">
        INTEGRATIONS
      </Mono>
      {state.status === 'loading' && <p role="status">Loading accounts…</p>}
      {state.error && <p role="alert">{state.error}</p>}
      {state.status === 'ready' && state.accounts.length === 0 && (
        <p>Connect an account in Home to add its documents.</p>
      )}
      {state.accounts.map((account) => (
        <Row
          key={account.id}
          selected={sameTarget(selected, { kind: 'account', id: account.id })}
          disabled={!accountUsable(account)}
          label={`${account.provider} · ${account.account_login ?? account.provider}`}
          tile={
            <ProviderMark
              entry={{ id: account.provider, mark: account.provider.slice(0, 1).toUpperCase() }}
            />
          }
          name={account.account_login ?? account.provider}
          sub={accountSub(account, state.documents[account.id])}
          onSelect={() => onSelect({ kind: 'account', id: account.id })}
        />
      ))}
      <Row
        selected={selected.kind === 'solus'}
        label=".solus"
        tile={<SolusLogo size={15} />}
        name=".solus"
        sub="Upload documents"
        onSelect={() => onSelect({ kind: 'solus' })}
      />
      <Row
        selected={selected.kind === 'hardware'}
        label="Hardware"
        tile={<Icons.bench size={14} />}
        name="Hardware"
        sub="Devices · search · describe"
        onSelect={() => onSelect({ kind: 'hardware' })}
      />
      <button type="button" className="workspace-refresh" onClick={onRefresh}>
        Refresh accounts
      </button>
    </div>
  )
}
