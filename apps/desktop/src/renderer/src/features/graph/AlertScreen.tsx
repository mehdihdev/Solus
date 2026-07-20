// Cross-domain alert detail. Live alerts (checkers + SOL analysis over the
// graph) are a future feature area; SOLUSDEV-152 removed the prototype's
// fabricated alert, diffs, and fake apply-fix/PR animation. Until real
// alerts exist this screen is an honest empty state.
import { Icons } from '../../components/ui/icons.constants'
import { ScreenEmptyState } from '../workspace/ScreenEmptyState'

interface AlertScreenProps {
  onBack: () => void
}

export function AlertScreen({ onBack }: AlertScreenProps): React.JSX.Element {
  return (
    <div
      style={{
        flex: 1,
        overflowY: 'auto',
        minWidth: 0,
        display: 'flex',
        flexDirection: 'column'
      }}
    >
      <div
        style={{
          maxWidth: 1060,
          margin: '0 auto',
          padding: '22px 28px 0',
          width: '100%',
          boxSizing: 'border-box'
        }}
      >
        <span
          role="button"
          tabIndex={0}
          onClick={onBack}
          onKeyDown={(e) => e.key === 'Enter' && onBack()}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 7,
            fontSize: 12.5,
            color: 'var(--mut)',
            cursor: 'pointer'
          }}
        >
          <Icons.arrowL size={13} /> Back
        </span>
      </div>
      <ScreenEmptyState
        icon={<Icons.warn size={28} />}
        title="No alert to show"
        body={
          <>
            When a change in one domain affects another — a schematic edit that breaks firmware, a
            CAD change that invalidates constants — SOL raises the alert here with what changed, the
            affected code, and a suggested fix. Connect sources so SOL can start checking your
            graph.
          </>
        }
      />
    </div>
  )
}
