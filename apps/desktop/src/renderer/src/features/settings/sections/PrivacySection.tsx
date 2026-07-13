// Privacy: data-collection consent (ADR-011). Collection is consent-gated —
// this is the opt-in/out switch, persisted to the settings backend.
import { Segmented } from '../../../components/ui/Segmented'
import { Section, Row, InlineError } from '../settingsUi'
import type { SettingsData } from '../useSettingsData'

const CONSENT_OPTIONS = ['On', 'Off'] as const

export function PrivacySection({ data }: { data: SettingsData }): React.JSX.Element {
  const { consent, errors, actions } = data
  return (
    <Section
      title="Privacy"
      sub="Solus logs how you use the product to improve it. This never includes your designs, code, or credentials — and you can turn it off anytime."
    >
      <Row label="Data collection">
        <Segmented
          size="sm"
          ariaLabel="Data collection"
          options={CONSENT_OPTIONS}
          value={consent ? 'On' : 'Off'}
          onChange={(v) => void actions.setConsent(v === 'On')}
        />
      </Row>
      <InlineError message={errors.consent} />
    </Section>
  )
}
