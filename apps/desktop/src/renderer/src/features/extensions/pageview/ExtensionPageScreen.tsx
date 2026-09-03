// SOLUSDEV-235 / EXT-13 — `MainScreen 'ext-page'` (wireflow §2): header over
// one ExtensionFrame in `page` mode filling the screen. The screen resolves the
// bundle ONCE (useInstalledBundle) and shares it with the frame, so the header
// can name the extension while the frame is still downloading it.
import { Button } from '../../../components/ui/Button'
import { Icons } from '../../../components/ui/icons.constants'
import { useWorkspaceStore } from '../../../store/workspaceStore'
import { ScreenEmptyState } from '../../workspace/ScreenEmptyState'
import type { BridgeDeps } from '../host/bridgeDeps'
import { ExtensionFrame } from '../frame/ExtensionFrame'
import type { InstalledBundleDeps } from '../frame/installedBundle'
import { useInstalledBundle } from '../frame/useInstalledBundle'
import { headerFacts } from './headerFacts'
import { openExtensionWindow } from './openExtensionWindow'
import { useExtensionIconSvg, type IconAssetTransport } from './extensionIconAsset'
import { PageHeader } from './PageHeader'

export interface ExtensionPageScreenProps {
  readonly slug: string
  readonly onBack?: () => void
  /** The error / blocked / disabled cards' "Open in Store" (wireflow §2). */
  readonly onOpenStore?: () => void
  readonly bundleDeps?: InstalledBundleDeps
  readonly bridgeDeps?: BridgeDeps
  readonly iconTransport?: IconAssetTransport
  readonly openWindow?: typeof openExtensionWindow
}

export function ExtensionPageScreen(props: ExtensionPageScreenProps): React.JSX.Element {
  const project = useWorkspaceStore((s) => s.project)
  if (!project) {
    return (
      <ScreenEmptyState
        icon={<Icons.box size={30} />}
        title="Select a project"
        body="Extensions run inside a project. Open one from Home to use this page."
      />
    )
  }
  return <PageBody {...props} projectId={project.id} />
}

function OpenInStore({ onOpenStore }: { onOpenStore?: () => void }): React.JSX.Element | null {
  if (!onOpenStore) return null
  return (
    <Button size="sm" kind="ghost" onClick={onOpenStore}>
      Open in Store
    </Button>
  )
}

function PageBody(props: ExtensionPageScreenProps & { projectId: string }): React.JSX.Element {
  const { projectId, slug, onBack, onOpenStore } = props
  const bundle = useInstalledBundle(projectId, slug, 'page', props.bundleDeps)
  const facts = headerFacts(bundle.state, slug)
  const iconSvg = useExtensionIconSvg(slug, facts.version, facts.iconPath, props.iconTransport)
  const open = props.openWindow ?? openExtensionWindow
  const hasWindow = facts.ready?.manifest.views.window !== undefined

  return (
    <div
      className="screen-in"
      data-testid="ext-page-screen"
      style={{ flex: 1, minWidth: 0, minHeight: 0, display: 'flex', flexDirection: 'column' }}
    >
      <PageHeader
        {...facts}
        iconSvg={iconSvg}
        onBack={onBack}
        actions={
          hasWindow && (
            <Button size="sm" kind="ghost" onClick={() => void open(bundle.state)}>
              Open in window <Icons.external size={12} />
            </Button>
          )
        }
      />
      <ExtensionFrame
        projectId={projectId}
        slug={slug}
        view="page"
        bundle={bundle}
        bridgeDeps={props.bridgeDeps}
        actions={<OpenInStore onOpenStore={onOpenStore} />}
      />
    </div>
  )
}
