// The shared connect surface (SOLUSDEV-165): the live catalog as launcher
// tiles plus the connect wizard for the entry being connected. Onboarding and
// the per-project Sources page both render THIS, so connecting a tool is one
// implementation and one experience everywhere.
//
// Local-bridge tiles (SOLUSDEV-72) are the one exception to the wizard: they
// carry companion guidance, not a credential flow, so they open the guidance
// modal and never enter the wizard (whose step rail only models oauth /
// export-file connects).
import { useState } from 'react'
import { Card } from '../../components/ui/Card'
import type { Connection, LocalTool } from '../../lib/api/resources'
import { LocalBridgeConnectModal } from '../project/localconnections/LocalBridgeConnectModal'
import { ConnectTile } from './ConnectTile'
import { ConnectWizardModal } from './ConnectWizardModal'
import type { CatalogEntry } from './integrationCatalog'
import { useConnectWizard } from './useConnectWizard'
import { useIntegrationCatalog } from './useIntegrationCatalog'
import { useOnboardingStore } from './onboardingStore'

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
  const catalog = useIntegrationCatalog()
  const connections = useOnboardingStore((s) => s.connections)
  const wizard = useConnectWizard({ projectId, onConnected, linkedConnections })
  // Which local-bridge tool's guidance modal is open (SOLUSDEV-72).
  const [bridgeTool, setBridgeTool] = useState<LocalTool | null>(null)

  const open = (integ: CatalogEntry): void => {
    if (integ.mode === 'local-bridge') {
      if (integ.localTool) setBridgeTool(integ.localTool)
      return
    }
    wizard.open(integ)
  }

  return (
    <>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, ...gridStyle }}>
        {catalog.map((integ) => (
          <ConnectTile
            key={integ.id}
            integration={integ}
            state={connections[integ.id]}
            onOpen={() => open(integ)}
          />
        ))}
      </div>
      {bridgeTool && (
        <LocalBridgeConnectModal tool={bridgeTool} onClose={() => setBridgeTool(null)} />
      )}
      {catalog.length === 0 && (
        <Card pad={16}>
          <div style={{ fontSize: 12, color: 'var(--mut)' }}>
            No connectors are available to add right now.
          </div>
        </Card>
      )}
      {wizard.active && (
        <ConnectWizardModal
          entry={wizard.active}
          state={connections[wizard.active.id]}
          linkedAccount={
            wizard.linkedAccount ? { login: wizard.linkedAccount.account_login } : null
          }
          onBegin={() => void wizard.begin()}
          onPickFile={(file) => void wizard.pickFile(file)}
          onSelect={wizard.select}
          onSubmitConfig={wizard.submitConfig}
          onChooseAccess={wizard.chooseAccess}
          onClose={wizard.close}
        />
      )}
    </>
  )
}
