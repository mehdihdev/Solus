// Settings › Privacy & data: data-collection consent (ADR-011) — collection is
// consent-gated, this is the opt-in/out switch persisted to the settings
// backend — plus the Privacy Policy and, since SOLUSDEV-318, the account
// delete danger row (it was its own Account card).
import { Switch } from '../../../components/ui/Switch'
import { Section, Row, InlineError } from '../settingsUi'
import { PRIVACY_POLICY_URL } from '../legalLinks.constants'
import { DeleteAccountRow } from './AccountSection'
import type { SettingsData } from '../useSettingsData'

export function PrivacySection({ data }: { data: SettingsData }): React.JSX.Element {
  const { consent, errors, actions } = data
  return (
    <Section id="privacy" title="Privacy & data">
      <Row
        label="Usage data"
        description={
          <>
            Solus logs how you use the product to improve it. This never includes your designs,
            code, or credentials.{' '}
            <a href={PRIVACY_POLICY_URL} target="_blank" rel="noopener noreferrer" style={LINK}>
              Read the Privacy Policy ↗
            </a>
          </>
        }
      >
        <Switch
          ariaLabel="Usage data"
          checked={consent}
          onChange={(on) => void actions.setConsent(on)}
        />
      </Row>
      <InlineError message={errors.consent} />
      <DeleteAccountRow />
    </Section>
  )
}

const LINK: React.CSSProperties = { color: 'var(--acc)', textDecoration: 'none' }
