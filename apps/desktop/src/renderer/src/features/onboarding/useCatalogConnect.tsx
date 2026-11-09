// The connect plumbing behind every catalog surface (SOLUSDEV-165, lifted out
// for SOLUSDEV-323): the live catalog, live per-entry state, the open action
// (wizard, or companion guidance for local-bridge tools — SOLUSDEV-72) and the
// modals to render. ConnectCatalog's grid and the onboarding ring both use it,
// so connecting a tool stays one implementation everywhere.
import { useState } from 'react'
import type { Connection, LocalTool } from '../../lib/api/resources'
import { LocalBridgeConnectModal } from '../project/localconnections/LocalBridgeConnectModal'
import { platformUnavailableReason } from '../project/localconnections/presentation'
import { ConnectWizardModal } from './ConnectWizardModal'
import type { CatalogEntry } from './integrationCatalog'
import { useConnectWizard } from './useConnectWizard'
import { useIntegrationCatalog } from './useIntegrationCatalog'
import { useOnboardingStore, type ConnectionState } from './onboardingStore'

export interface CatalogConnectOptions {
  /** The project sources attach to; null when no linked project exists yet. */
  projectId: string | null
  onConnected?: () => void
  linkedConnections?: readonly Connection[]
}

export interface CatalogConnect {
  catalog: readonly CatalogEntry[]
  connections: Record<string, ConnectionState>
  /** Why an entry cannot connect on this platform, or null. */
  unavailableReason: (entry: CatalogEntry) => string | null
  open: (entry: CatalogEntry) => void
  /** The wizard / guidance modal for whatever is being connected. */
  modals: React.ReactNode
}

export function useCatalogConnect({
  projectId,
  onConnected,
  linkedConnections
}: CatalogConnectOptions): CatalogConnect {
  const catalog = useIntegrationCatalog()
  const connections = useOnboardingStore((s) => s.connections)
  const wizard = useConnectWizard({ projectId, onConnected, linkedConnections })
  const [bridgeTool, setBridgeTool] = useState<LocalTool | null>(null)

  const unavailableReason = (entry: CatalogEntry): string | null =>
    entry.localTool ? platformUnavailableReason(entry.localTool) : null

  const open = (entry: CatalogEntry): void => {
    if (entry.mode === 'local-bridge') {
      if (entry.localTool && !platformUnavailableReason(entry.localTool))
        setBridgeTool(entry.localTool)
      return
    }
    wizard.open(entry)
  }

  const modals = (
    <>
      {bridgeTool && (
        <LocalBridgeConnectModal tool={bridgeTool} onClose={() => setBridgeTool(null)} />
      )}
      {wizard.active && (
        <ConnectWizardModal
          entry={wizard.active}
          state={connections[wizard.active.id]}
          linkedAccount={
            wizard.linkedAccount ? { login: wizard.linkedAccount.account_login } : null
          }
          onBegin={() => void wizard.begin()}
          onPickFiles={(files) => void wizard.pickFiles(files)}
          onSelect={wizard.select}
          onRefreshSelection={wizard.refreshSelection}
          onSubmitConfig={wizard.submitConfig}
          onChooseAccess={wizard.chooseAccess}
          onClose={wizard.close}
        />
      )}
    </>
  )
  return { catalog, connections, unavailableReason, open, modals }
}
