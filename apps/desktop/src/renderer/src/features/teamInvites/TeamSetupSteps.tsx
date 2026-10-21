// SOLUSDEV-317 (design A, solo state): a collaborative team with only its owner
// gets two optional steps above the People table — 1 · invite a teammate
// inline (the one-time token is shown once, in the shared token modal);
// 2 · link a GitHub organization to this team (the card's `step` variant,
// only while nothing is linked and the server supports it).
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Spinner } from '../../components/ui/Spinner'
import type { SolMode } from '../../store/settingsStore'
import { EMAIL_PATTERN, INVITE_FAILURE } from '../team/MembersPanel'
import { GitHubOrgCard, StepBadge } from '../workspace/GitHubOrgCard'
import { useGithubInviteTokenStore } from '../workspace/githubInviteTokenStore'
import { PlanLimitNotice } from '../workspace/PlanLimitNotice'
import type { InviteOutcome } from '../workspace/useHomeTeam'
import type { TeamGithub } from '../workspace/useTeamGithub'
import { teamText } from './teamInvitesCopy'

export interface TeamSetupStepsProps {
  teamName: string
  github: TeamGithub
  mode: SolMode
  onInvite: (email: string) => Promise<InviteOutcome>
  onUpgrade?: () => void
}

const BOX: React.CSSProperties = {
  border: '1px solid var(--bd)',
  borderRadius: 4,
  background: 'var(--sur)',
  padding: 16,
  display: 'flex',
  flexDirection: 'column',
  gap: 10,
  minWidth: 0
}

/** Step 2 only while there is something to link (not linked, not unconfigured). */
export function showsLinkStep(github: TeamGithub): boolean {
  return github.status === 'ready' && !github.unconfigured && github.installation === null
}

export function TeamSetupSteps(props: TeamSetupStepsProps): React.JSX.Element {
  const { github } = props
  return (
    <div
      role="group"
      aria-label="Set up your team"
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
        gap: 14
      }}
    >
      <InviteStep {...props} />
      {showsLinkStep(github) && (
        <GitHubOrgCard
          github={github}
          teamName={props.teamName}
          canManage
          onUpgrade={props.onUpgrade}
          variant="step"
        />
      )}
    </div>
  )
}

type Problem = { kind: 'text'; text: string } | { kind: 'limit'; message: string } | null

function InviteStep({ mode, onInvite, onUpgrade }: TeamSetupStepsProps): React.JSX.Element {
  const [email, setEmail] = useState('')
  const [sending, setSending] = useState(false)
  const [problem, setProblem] = useState<Problem>(null)
  const showToken = useGithubInviteTokenStore((s) => s.show)
  const send = async (event: React.FormEvent): Promise<void> => {
    event.preventDefault()
    if (!EMAIL_PATTERN.test(email))
      return setProblem({ kind: 'text', text: INVITE_FAILURE.invalid_email })
    setSending(true)
    setProblem(null)
    const outcome = await onInvite(email)
    setSending(false)
    if (outcome.ok) {
      showToken({ invitee: email, token: outcome.token, kind: 'email' })
      return setEmail('')
    }
    setProblem(
      outcome.reason === 'plan_limit'
        ? { kind: 'limit', message: outcome.limit.message }
        : { kind: 'text', text: INVITE_FAILURE[outcome.reason] }
    )
  }
  return (
    <section aria-labelledby="setup-invite" style={BOX}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <StepBadge n={1} active />
        <h3 id="setup-invite" style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>
          Invite a teammate
        </h3>
      </div>
      <p style={{ margin: 0, fontSize: 12.5, color: 'var(--mut)', lineHeight: 1.55 }}>
        {teamText('setup_invite', mode)}
      </p>
      <form
        noValidate
        onSubmit={(e) => void send(e)}
        style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}
      >
        <input
          type="email"
          aria-label="Teammate email"
          placeholder="teammate@team.dev"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          style={{
            flex: '1 1 180px',
            minWidth: 0,
            background: 'var(--bg)',
            color: 'var(--tx)',
            border: '1px solid var(--bd)',
            borderRadius: 3,
            padding: '8px 10px',
            fontFamily: 'var(--font-ui)',
            fontSize: 12.5
          }}
        />
        <Button kind="primary" size="sm" type="submit" disabled={sending}>
          {sending ? <Spinner size={11} color="var(--acc-ink)" /> : 'Send invite'}
        </Button>
      </form>
      {problem?.kind === 'text' && (
        <div role="alert" style={{ fontSize: 11.5, color: 'var(--err)' }}>
          {problem.text}
        </div>
      )}
      {problem?.kind === 'limit' && (
        <PlanLimitNotice message={problem.message} onUpgrade={onUpgrade} />
      )}
    </section>
  )
}
