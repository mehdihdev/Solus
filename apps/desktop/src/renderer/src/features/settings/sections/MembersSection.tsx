// Members settings: full team-member management (roster, roles, invite/revoke/
// remove) reusing the shared MembersManager so Team and Settings stay in sync.
// Roles reflect FND-01 membership.
import { Section } from '../settingsUi'
import { MembersManager } from '../../team/MembersPanel'
import type { TeamData } from '../../team/useTeamData'

export function MembersSection({ team }: { team: TeamData }): React.JSX.Element {
  return (
    <Section
      title="Members"
      sub="Who's on this team and what they can do. Invites are one-time join links."
    >
      <MembersManager data={team} />
    </Section>
  )
}
