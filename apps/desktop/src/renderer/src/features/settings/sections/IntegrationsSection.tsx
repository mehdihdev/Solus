// Integrations overview: the connector catalog Solus can pull into the graph.
// This is a CATALOG, not a live connection ledger — sources are connected per
// PROJECT (in a project's Workspace), so a global settings list cannot
// truthfully show a single connected/disconnected state (SOLUSDEV-152: it
// previously read an un-hydrated local onboarding flag and wrongly showed every
// tool as "NOT CONNECTED" for real signed-in users). The catalog itself is the
// live backend registry (SOLUSDEV-100) so new connectors appear without edits.
import { Mono } from '../../../components/ui/Mono'
import { useIntegrationCatalog } from '../../onboarding/useIntegrationCatalog'
import { Section, Row } from '../settingsUi'

export function IntegrationsSection(): React.JSX.Element {
  const catalog = useIntegrationCatalog()
  return (
    <Section
      title="Integrations"
      sub="Tools Solus can connect into your graph. Connect and manage them in Home › Connected accounts; add their documents from Workspace › Add › Integrations."
    >
      {catalog.map((i) => (
        <Row
          key={i.id}
          label={
            <span style={{ display: 'inline-flex', gap: 10, alignItems: 'center' }}>
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 10.5,
                  width: 26,
                  height: 26,
                  borderRadius: 3,
                  background: 'var(--sur2)',
                  border: '1px solid var(--bd)',
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center'
                }}
              >
                {i.mark}
              </span>
              {i.name}
            </span>
          }
        >
          <Mono size={9} color="var(--mut)">
            AVAILABLE
          </Mono>
        </Row>
      ))}
    </Section>
  )
}
