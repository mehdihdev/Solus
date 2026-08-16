// The shared connect surface (SOLUSDEV-165): the live catalog as launcher
// tiles plus the connect wizard for the entry being connected. Onboarding and
// the per-project Sources page both render THIS, so connecting a tool is one
// implementation and one experience everywhere.
import { Card } from '../../components/ui/Card'
import { ConnectTile } from './ConnectTile'
import { ConnectWizardModal } from './ConnectWizardModal'
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
}

export function ConnectCatalog({
  projectId,
  onConnected,
  gridStyle
}: ConnectCatalogProps): React.JSX.Element {
  const catalog = useIntegrationCatalog()
  const connections = useOnboardingStore((s) => s.connections)
  const wizard = useConnectWizard({ projectId, onConnected })

  return (
    <>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, ...gridStyle }}>
        {catalog.map((integ) => (
          <ConnectTile
            key={integ.id}
            integration={integ}
            state={connections[integ.id]}
            onOpen={() => wizard.open(integ)}
          />
        ))}
      </div>
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
