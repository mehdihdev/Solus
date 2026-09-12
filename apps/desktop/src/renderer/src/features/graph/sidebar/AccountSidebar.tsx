// The sidebar for a synthetic `integration_account` anchor (SOLUSDEV-250 P5): the
// provider mark and login, the account's documents from the merged snapshot (select →
// reveal on the canvas), and "Add another" opening Add › Integrations. Anchors are
// presentation only: nothing here reads the API or the focus store.
import type { Entity, Relation } from '../../../lib/api/resources'
import { ProviderMark } from '../../workspace/ConnectedAccountsCard'
import { accountDocuments, providerMark } from '../accountAnchors'

export interface AccountSidebarProps {
  entity: Entity
  /** The merged (anchored) snapshot the navigator renders. */
  entities: readonly Entity[]
  relations: readonly Relation[]
  onReveal: (entityId: string) => void
  onOpenAdd: (tab: 'service') => void
}

export function AccountSidebar({
  entity,
  entities,
  relations,
  onReveal,
  onOpenAdd
}: AccountSidebarProps): React.JSX.Element {
  const documents = accountDocuments(entity.id, entities, relations)
  return (
    <>
      <h2 style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <ProviderMark entry={providerMark(entity)} />
        {entity.name}
      </h2>
      <h3>Documents</h3>
      <ul>
        {documents.map((document) => (
          <li key={document.id}>
            <button
              type="button"
              className="node-sidebar-link"
              onClick={() => onReveal(document.id)}
            >
              {document.name}
            </button>
          </li>
        ))}
      </ul>
      <div className="node-sidebar-actions">
        <button type="button" className="node-sidebar-link" onClick={() => onOpenAdd('service')}>
          Add another
        </button>
      </div>
    </>
  )
}
