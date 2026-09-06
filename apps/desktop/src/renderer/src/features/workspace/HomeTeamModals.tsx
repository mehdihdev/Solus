// Home's team dialogs (SOLUSDEV-244 / HOME H5): invite (one-time token), new
// team, join by token, rename, leave, delete — one open at a time. Every
// refusal is named; a plan limit shows the upgrade path (Billing).
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Spinner } from '../../components/ui/Spinner'
import { InviteModal } from '../team/MembersPanel'
import {
  DeleteConfirmModal,
  JoinTeamModal,
  ModalShell,
  NameModal,
  type ModalResult
} from './modals'
import type { HomeActions, TeamRefusal } from './useHomeData'
import type { HomeTeam } from './useHomeTeam'

export type HomeTeamModal = 'invite' | 'newTeam' | 'join' | 'rename' | 'leave' | 'delete' | null

const JOIN_REFUSALS: Record<Exclude<TeamRefusal['reason'], 'plan_limit'>, string> = {
  invalid_token: "That token isn't valid. It may have been revoked or already used.",
  expired: 'This invite has expired. Ask for a new one.',
  wrong_email: 'This invite was issued to a different email address.',
  already_member: "You're already a member of that team.",
  failed: "Couldn't join with that token. Please try again."
}

/** The verdict a NameModal / JoinTeamModal shows for a team refusal. */
export function modalResult(refusal: TeamRefusal): ModalResult {
  if (refusal.reason === 'plan_limit') return { message: refusal.limit.message, upgrade: true }
  return { message: JOIN_REFUSALS[refusal.reason] }
}

function LeaveTeamModal({
  teamName,
  onClose,
  onLeave
}: {
  teamName: string
  onClose: () => void
  onLeave: HomeTeam['actions']['leave']
}): React.JSX.Element {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const leave = async (): Promise<void> => {
    setBusy(true)
    setError(null)
    const outcome = await onLeave()
    if (outcome.ok) {
      onClose()
      return
    }
    setBusy(false)
    setError(
      outcome.reason === 'last_owner'
        ? 'A team must keep at least one owner. Make someone else an owner first.'
        : "Couldn't leave the team. Please try again."
    )
  }
  return (
    <ModalShell onClose={onClose}>
      <div style={{ fontSize: 16, fontWeight: 600 }}>Leave team</div>
      <div style={{ fontSize: 12.5, color: 'var(--mut)', marginTop: 8, lineHeight: 1.55 }}>
        You&apos;ll lose access to <strong style={{ color: 'var(--tx)' }}>{teamName}</strong> and
        its projects. Home moves to your personal workspace.
      </div>
      {error && <div style={{ marginTop: 8, fontSize: 11.5, color: 'var(--err)' }}>{error}</div>}
      <div style={{ display: 'flex', gap: 8, marginTop: 18, justifyContent: 'flex-end' }}>
        <Button kind="ghost" size="sm" onClick={onClose}>
          Cancel
        </Button>
        <Button kind="danger" size="sm" onClick={() => void leave()}>
          {busy ? <Spinner size={11} /> : 'Leave team'}
        </Button>
      </div>
    </ModalShell>
  )
}

export interface HomeTeamModalsProps {
  modal: HomeTeamModal
  teamName: string | null
  home: HomeActions
  team: HomeTeam
  onClose: () => void
  onUpgrade?: () => void
}

export function HomeTeamModals({
  modal,
  teamName,
  home,
  team,
  onClose,
  onUpgrade
}: HomeTeamModalsProps): React.JSX.Element | null {
  switch (modal) {
    case 'invite':
      return <InviteModal onClose={onClose} onInvite={team.actions.invite} onUpgrade={onUpgrade} />
    case 'newTeam':
      return (
        <NameModal
          title="New team"
          label="Team name"
          submitLabel="Create"
          errorText="Couldn't create the team. Please try again."
          onClose={onClose}
          onUpgrade={onUpgrade}
          onSubmit={async (name) => {
            const result = await home.createTeam(name)
            return result.ok ? true : modalResult(result)
          }}
        />
      )
    case 'join':
      return (
        <JoinTeamModal
          onClose={onClose}
          onUpgrade={onUpgrade}
          onJoin={async (token) => {
            const result = await home.joinTeam(token)
            return result.ok ? true : modalResult(result)
          }}
        />
      )
    case 'rename':
      return (
        <NameModal
          title="Rename team"
          label="Team name"
          submitLabel="Rename"
          initial={teamName ?? ''}
          errorText="Couldn't rename the team. Check your role and try again."
          onClose={onClose}
          onSubmit={(name) => team.actions.rename(name)}
        />
      )
    case 'leave':
      return (
        <LeaveTeamModal
          teamName={teamName ?? 'this team'}
          onClose={onClose}
          onLeave={team.actions.leave}
        />
      )
    case 'delete':
      return (
        <DeleteConfirmModal
          name={teamName ?? 'this team'}
          noun="team"
          detail="and every project in it"
          onClose={onClose}
          onConfirm={team.actions.deleteTeam}
        />
      )
    default:
      return null
  }
}
