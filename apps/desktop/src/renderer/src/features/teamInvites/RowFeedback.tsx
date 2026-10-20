// SOLUSDEV-317: a roster row's live region (always mounted, so a later
// announcement is read) and, under it, its error — a plan limit gets the
// Upgrade path; a refusal naming another login offers to find it.
import { Button } from '../../components/ui/Button'
import type { SolMode } from '../../store/settingsStore'
import { githubText } from '../workspace/githubOrgCopy'
import { PlanLimitNotice } from '../workspace/PlanLimitNotice'
import type { RowState } from '../workspace/useGithubOrgRoster'

export interface RowFeedbackProps {
  state: RowState | undefined
  mode: SolMode
  onFind?: (login: string) => void
  onUpgrade?: () => void
}

export function RowFeedback({
  state,
  mode,
  onFind,
  onUpgrade
}: RowFeedbackProps): React.JSX.Element {
  const announce = state?.announce
  const problem = state?.error ?? null
  return (
    <>
      <div role="status" style={{ fontSize: 11, color: 'var(--ok)' }}>
        {announce ? githubText(announce.key, mode, announce.vars) : ''}
      </div>
      {problem && 'limit' in problem && (
        <PlanLimitNotice message={problem.limit} onUpgrade={onUpgrade} />
      )}
      {problem && 'key' in problem && (
        <ProblemLine
          text={githubText(problem.key, mode, problem.vars)}
          other={problem.vars.other}
          onFind={onFind}
        />
      )}
    </>
  )
}

function ProblemLine({
  text,
  other,
  onFind
}: {
  text: string
  other: string | undefined
  onFind?: (login: string) => void
}): React.JSX.Element {
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
      <span role="alert" style={{ fontSize: 11.5, color: 'var(--err)', lineHeight: 1.5 }}>
        {text}
      </span>
      {onFind && other && other !== '?' && (
        <Button kind="bare" size="sm" onClick={() => onFind(other)}>
          Find @{other}
        </Button>
      )}
    </div>
  )
}
