// Card content for a synthetic `integration_account` anchor (SOLUSDEV-250 P5):
// provider mark, login, and how many documents hang under it. No id is shown.
import type { Entity } from '../../lib/api/resources'
import { ProviderMark } from '../workspace/ConnectedAccountsCard'
import { providerMark } from './accountAnchors'

export function AccountNodeContent({
  entity,
  count
}: {
  entity: Entity
  count: number
}): React.JSX.Element {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
      <ProviderMark entry={providerMark(entity)} />
      <span style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <span style={{ overflowWrap: 'anywhere' }}>{entity.name}</span>
        <span style={{ fontSize: 10.5, color: 'var(--mut)' }}>
          {count} {count === 1 ? 'document' : 'documents'}
        </span>
      </span>
    </div>
  )
}
