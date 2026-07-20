// Settings screen (SOLUSDEV-86 / SOLUS-FND-06). Composes the settings surfaces
// over the FND-07 settings backend + subscription + team APIs. Local prefs
// (appearance) and the integrations overview always render; account, billing,
// and team management require a live connection (dev bypass shows a sign-in
// prompt instead of fabricated data).
import { Card } from '../../components/ui/Card'
import { Spinner } from '../../components/ui/Spinner'
import { useSettingsData } from './useSettingsData'
import { useTeamData } from '../team/useTeamData'
import { ProfileSection } from './sections/ProfileSection'
import { PreferencesSection } from './sections/PreferencesSection'
import { PrivacySection } from './sections/PrivacySection'
import { BillingSection } from './sections/BillingSection'
import { IntegrationsSection } from './sections/IntegrationsSection'
import { MembersSection } from './sections/MembersSection'
import { TeamSection } from './sections/TeamSection'
import { AccountSection } from './sections/AccountSection'
import { useOfflineReason } from '../workspace/workspaceOnline'

function OfflineNotice(): React.JSX.Element {
  const reason = useOfflineReason()
  return (
    <Card pad={20} style={{ marginBottom: 14 }}>
      <div style={{ fontSize: 12.5, color: 'var(--mut)', lineHeight: 1.55 }}>
        {reason === 'api_unreachable'
          ? "You're signed in, but Solus can't reach its API — profile, privacy, billing, and team management need it. Appearance and connected-tool status still work."
          : 'Sign in to Solus to manage your profile, privacy, billing, and team. Appearance and connected-tool status are available offline.'}
      </div>
    </Card>
  )
}

export function SettingsScreen(): React.JSX.Element {
  const settings = useSettingsData()
  const team = useTeamData()

  if (settings.status === 'loading') {
    return (
      <div
        style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
        data-testid="settings-loading"
      >
        <Spinner size={20} />
      </div>
    )
  }

  const online = settings.status === 'ready'

  return (
    <div style={{ flex: 1, overflowY: 'auto', minWidth: 0 }}>
      <div style={{ maxWidth: 680, margin: '0 auto', padding: '22px 24px 48px' }}>
        <h1
          style={{ margin: '0 0 18px', fontSize: 22, fontWeight: 600, letterSpacing: '-0.015em' }}
        >
          Settings
        </h1>

        {online && <ProfileSection data={settings} />}
        <PreferencesSection data={settings} />
        {online && <PrivacySection data={settings} />}
        {online && <BillingSection data={settings} />}
        <IntegrationsSection />
        {team.status === 'ready' && (
          <>
            <MembersSection team={team} />
            <TeamSection team={team} />
          </>
        )}
        {online && <AccountSection />}
        {!online && <OfflineNotice />}
      </div>
    </div>
  )
}
