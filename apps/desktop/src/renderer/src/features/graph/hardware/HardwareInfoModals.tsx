// Shared chrome for the Add › Hardware flows: the Close-only footer. Every
// flow (Detected, From a file, Library, Authored) lives in its own file.
import { Button } from '../../../components/ui/Button'

const FOOTER_STYLE = { display: 'flex', gap: 8, marginTop: 18, justifyContent: 'flex-end' } as const

export function CloseFooter({ onClose }: { onClose: () => void }): React.JSX.Element {
  return (
    <div style={FOOTER_STYLE}>
      <Button kind="ghost" size="sm" onClick={onClose}>
        Close
      </Button>
    </div>
  )
}
