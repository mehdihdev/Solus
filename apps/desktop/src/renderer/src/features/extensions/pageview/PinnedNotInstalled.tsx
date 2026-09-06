// SOLUSDEV-246 / STORE ST3 — what a PINNED extension's tab shows in a project
// where the bundle is not installed: the honest state, never a frame that
// pretends. "Pin for all projects" pins the TAB; installing is still a
// per-project, permission-gated act, so the way forward is the Store's detail
// page (with its permissions step), one click away.
import { Button } from '../../../components/ui/Button'
import { Icons } from '../../../components/ui/icons.constants'
import { Mono } from '../../../components/ui/Mono'
import { ScreenEmptyState } from '../../workspace/ScreenEmptyState'

export function PinnedNotInstalled({
  label,
  projectName,
  onInstall,
  onUnpin
}: {
  label: string
  projectName: string
  onInstall: () => void
  onUnpin: () => void
}): React.JSX.Element {
  return (
    <div
      data-testid="pinned-not-installed"
      style={{ flex: 1, minWidth: 0, minHeight: 0, display: 'flex' }}
    >
      <ScreenEmptyState
        icon={<Icons.hex size={30} />}
        title={`${label} isn't installed in ${projectName}`}
        body="This tab is pinned for all your projects. Install the extension here to use it in this one."
      >
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginTop: 14 }}>
          <Button kind="primary" size="sm" onClick={onInstall}>
            Install in this project
          </Button>
          <Button kind="bare" size="sm" onClick={onUnpin}>
            Unpin
          </Button>
        </div>
        <div style={{ marginTop: 12 }}>
          <Mono size={9} color="var(--mut)">
            PINNED FOR ALL PROJECTS
          </Mono>
        </div>
      </ScreenEmptyState>
    </div>
  )
}
