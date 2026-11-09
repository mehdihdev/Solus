// The stage footer every onboarding step shares (SOLUSDEV-323): Back on the
// left when there is somewhere to go back to, the step's actions on the right.
import { Button } from '../../components/ui/Button'

interface StepFooterProps {
  onBack?: () => void
  children: React.ReactNode
  className?: string
}

export function StepFooter({ onBack, children, className }: StepFooterProps): React.JSX.Element {
  return (
    <div
      className={className}
      style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 14 }}
    >
      {onBack ? (
        <Button kind="bare" onClick={onBack}>
          Back
        </Button>
      ) : (
        <span />
      )}
      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>{children}</div>
    </div>
  )
}
