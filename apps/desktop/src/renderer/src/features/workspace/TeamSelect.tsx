// The active-team selector (SOLUSDEV-242): one control shared by Home and the
// Team screen so switching teams means the same thing everywhere — it writes
// `workspaceStore.teamId`, and both screens re-resolve off it (activeTeam.ts).
// Hidden with a single team: there is nothing to choose.
import type { TeamSummary } from '../../lib/api/resources'

export interface TeamSelectProps {
  teams: readonly TeamSummary[]
  currentId: string | undefined
  onSwitch: (teamId: string) => void
  style?: React.CSSProperties
}

export function TeamSelect({
  teams,
  currentId,
  onSwitch,
  style
}: TeamSelectProps): React.JSX.Element | null {
  if (teams.length < 2) return null
  return (
    <select
      aria-label="Switch team"
      value={currentId ?? ''}
      onChange={(e) => onSwitch(e.target.value)}
      style={{
        background: 'var(--bg)',
        color: 'var(--tx)',
        border: '1px solid var(--bd)',
        borderRadius: 3,
        padding: '5px 8px',
        fontSize: 12,
        fontFamily: 'var(--font-ui)',
        ...style
      }}
    >
      {teams.map((t) => (
        <option key={t.team_id} value={t.team_id}>
          {t.name}
          {t.is_personal ? ' (personal)' : ''}
        </option>
      ))}
    </select>
  )
}
