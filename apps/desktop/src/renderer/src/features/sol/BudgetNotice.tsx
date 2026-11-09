// SOLUSDEV-321 P1-T6: SOL stopped because a turn budget ran out. It sits above the router's own
// loop_limit error, so the person learns WHICH ceiling the turn hit — and how far it got — not
// just that it ended. The limit and counts come from the server's budget_reached frame; text only.
import type { BudgetReachedInfo } from './solStream'

export function BudgetNotice({
  budget
}: {
  budget: BudgetReachedInfo | undefined
}): React.JSX.Element | null {
  if (!budget) return null
  return (
    <div
      role="status"
      data-testid="budget-notice"
      style={{ fontSize: 11, color: 'var(--warn)', marginTop: 4 }}
    >
      {`SOL stopped: ${budget.limit} budget reached (${budget.used}/${budget.cap})`}
    </div>
  )
}
