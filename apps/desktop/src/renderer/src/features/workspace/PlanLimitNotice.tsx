// SOLUSDEV-244 / HOME H5: a plan limit stated honestly, with the upgrade path
// beside it — never a silent failure, never "try again" (ADR-023: a hard block
// with a clear message). The words are the server's own sentence when we have
// one, so the UI never invents a limit it did not receive.
import { Button } from '../../components/ui/Button'

export interface PlanLimitNoticeProps {
  message: string
  /** Where "Upgrade" goes (Billing); absent ⇒ the sentence stands alone. */
  onUpgrade?: () => void
  compact?: boolean
}

export function PlanLimitNotice({
  message,
  onUpgrade,
  compact = false
}: PlanLimitNoticeProps): React.JSX.Element {
  return (
    <div
      role="note"
      data-testid="plan-limit"
      style={{
        display: 'flex',
        gap: 10,
        alignItems: 'center',
        marginTop: compact ? 0 : 10,
        padding: compact ? 0 : '9px 11px',
        background: compact ? 'transparent' : 'var(--bg)',
        border: compact ? 'none' : '1px solid var(--bd)',
        borderRadius: 4
      }}
    >
      <div
        style={{ flex: 1, fontSize: compact ? 11 : 11.5, color: 'var(--warn)', lineHeight: 1.5 }}
      >
        {message}
      </div>
      {onUpgrade && (
        <Button kind="soft" size="sm" onClick={onUpgrade}>
          Upgrade
        </Button>
      )}
    </div>
  )
}
