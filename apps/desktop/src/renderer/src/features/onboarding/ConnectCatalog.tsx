// The shared connect surface (SOLUSDEV-165): the live catalog as launcher
// tiles plus the connect wizard for the entry being connected. Home's
// connected-accounts card renders THIS grid; onboarding renders the same
// plumbing as a ring (ConnectRing). Both go through useCatalogConnect, so
// connecting a tool is one implementation and one experience everywhere.
import { Card } from '../../components/ui/Card'
import type { Connection } from '../../lib/api/resources'
import { ConnectTile } from './ConnectTile'
import { useCatalogConnect } from './useCatalogConnect'

export interface ConnectCatalogProps {
  /** The project sources attach to; null when no linked project exists yet. */
  projectId: string | null
  /** Called once a connect settles successfully (refresh lists, recount, …). */
  onConnected?: () => void
  /** Style for the tile grid (surfaces differ only in spacing). */
  gridStyle?: React.CSSProperties
  /** SOLUSDEV-241: the user's linked accounts. A CONNECTED one for a tile's
   *  provider is reused by the wizard — no second sign-in. */
  linkedConnections?: readonly Connection[]
}

export function ConnectCatalog({
  projectId,
  onConnected,
  gridStyle,
  linkedConnections
}: ConnectCatalogProps): React.JSX.Element {
  const c = useCatalogConnect({ projectId, onConnected, linkedConnections })
  return (
    <>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, ...gridStyle }}>
        {c.catalog.map((integ) => (
          <ConnectTile
            key={integ.id}
            integration={integ}
            state={c.connections[integ.id]}
            unavailableReason={c.unavailableReason(integ)}
            onOpen={() => c.open(integ)}
          />
        ))}
      </div>
      {c.catalog.length === 0 && (
        <Card pad={16}>
          <div style={{ fontSize: 12, color: 'var(--mut)' }}>
            No connectors are available to add right now.
          </div>
        </Card>
      )}
      {c.modals}
    </>
  )
}
