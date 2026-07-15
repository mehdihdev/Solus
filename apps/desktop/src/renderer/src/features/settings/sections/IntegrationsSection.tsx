// Integrations overview: the connector catalog with each source's connection
// state (from the onboarding store). Read-only here — connect/sync lives in the
// onboarding + graph flows; this mirrors the current status. The catalog is the
// live backend registry (SOLUSDEV-100) so new connectors appear without edits.
import { Mono } from '../../../components/ui/Mono'
import { useOnboardingStore } from '../../onboarding/onboardingStore'
import { useIntegrationCatalog } from '../../onboarding/useIntegrationCatalog'
import { Section, Row } from '../settingsUi'

export function IntegrationsSection(): React.JSX.Element {
  const connections = useOnboardingStore((s) => s.connections)
  const catalog = useIntegrationCatalog()
  return (
    <Section title="Integrations" sub="Connected tools feeding your cross-domain graph.">
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
          {connections[i.id]?.phase === 'done' ? (
            <Mono size={9} color="var(--ok)">
              ● CONNECTED
            </Mono>
          ) : (
            <Mono size={9} color="var(--mut)">
              ○ NOT CONNECTED
            </Mono>
          )}
        </Row>
      ))}
    </Section>
  )
}
