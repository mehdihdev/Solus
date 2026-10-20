// SOLUSDEV-317: a teammate with no GitHub link, under "Unassigned teammates" —
// so an admin can work from the teammate side. Same picker as the org rows,
// offering the loaded org members nobody is linked to. The assignment itself is
// keyed by GitHub id, so this row shows the state of the account it last picked.
import { useState } from 'react'
import { Avatar } from '../../components/ui/Avatar'
import type { TeamMemberApi } from '../../lib/api/resources'
import type { SolMode } from '../../store/settingsStore'
import { AssignPicker } from './AssignPicker'
import { githubText } from './githubOrgCopy'
import type { PickerOption } from './githubOrgMembersView'
import { teammateName } from './githubOrgRoster'
import { homeStagger } from './homeMotion'
import type { RowState } from './useGithubOrgRoster'

export interface UnassignedTeammateRowProps {
  teammate: TeamMemberApi
  index: number
  options: readonly PickerOption[]
  rows: Readonly<Record<number, RowState>>
  mode: SolMode
  openRequest: number
  onAssign: (githubId: number) => void
}

export function UnassignedTeammateRow({
  teammate,
  index,
  options,
  rows,
  mode,
  openRequest,
  onAssign
}: UnassignedTeammateRowProps): React.JSX.Element {
  const [picked, setPicked] = useState<number | null>(null)
  const name = teammateName(teammate)
  const problem = picked === null ? null : rows[picked]?.error
  const pending = picked !== null && (rows[picked]?.pending ?? false)
  return (
    <li
      aria-label={name}
      className="home-row-in"
      style={{
        ...homeStagger(index),
        display: 'flex',
        alignItems: 'center',
        gap: 11,
        padding: '10px 14px',
        borderBottom: '1px solid var(--bd)',
        flexWrap: 'wrap'
      }}
    >
      <Avatar name={name} size={26} />
      <div style={{ flex: '1 1 200px', minWidth: 0 }}>
        <div style={{ fontSize: 12.5, fontWeight: 600 }}>{name}</div>
        <div style={{ fontSize: 11, color: 'var(--mut)' }}>
          {githubText('teammate_pick_hint', mode, { name })}
        </div>
      </div>
      <AssignPicker
        label="Pick GitHub account"
        listLabel={`GitHub account for ${name}`}
        options={options}
        emptyText={githubText('no_org_members_left', mode)}
        openRequest={openRequest}
        disabled={pending}
        onPick={(id) => {
          const githubId = Number(id)
          setPicked(githubId)
          onAssign(githubId)
        }}
      />
      {problem && 'key' in problem && (
        <div role="alert" style={{ flexBasis: '100%', fontSize: 11.5, color: 'var(--err)' }}>
          {githubText(problem.key, mode, problem.vars)}
        </div>
      )}
    </li>
  )
}
