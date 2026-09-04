// SOLUSDEV-235 — "+ Create extension". The authoring flow has no design yet;
// this dialog says so honestly and points at the manifest model rather than
// pretending to start something (SOLUSDEV-152 charter: no fake flows).
import { Button } from '../../components/ui/Button'
import { Icons } from '../../components/ui/icons.constants'
import { ModalShell } from '../workspace/modals'

const MANIFEST_DOCS_URL = 'https://docs.solusforge.com/extensions/manifest'

export function CreateExtensionModal({ onClose }: { onClose: () => void }): React.JSX.Element {
  return (
    <ModalShell onClose={onClose} width={440}>
      <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600 }}>Create an extension</h2>
      <div style={{ fontSize: 12.5, color: 'var(--mut)', marginTop: 10, lineHeight: 1.6 }}>
        An extension is a manifest: its id, what it contributes (widgets, checks, SOL grounding),
        the sources it needs, and the permissions it asks for. The in-app authoring flow is not
        available in this build yet.
      </div>
      <a
        href={MANIFEST_DOCS_URL}
        target="_blank"
        rel="noopener noreferrer"
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 5,
          marginTop: 12,
          fontSize: 12.5,
          color: 'var(--acc)',
          textDecoration: 'none'
        }}
      >
        Read the manifest documentation <Icons.external size={11} />
      </a>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 18 }}>
        <Button kind="ghost" size="sm" onClick={onClose}>
          Close
        </Button>
      </div>
    </ModalShell>
  )
}
