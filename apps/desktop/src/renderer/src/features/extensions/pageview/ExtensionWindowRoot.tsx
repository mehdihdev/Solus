// SOLUSDEV-235 / EXT-13 — the content root main loads into the second
// BrowserWindow at `#/ext-window/<id>` (wireflow §3, main/extensions/
// extensionWindow.ts). Same renderer, minimal chrome under the OS title bar,
// one ExtensionFrame in `window` mode bound to the project the main window has
// open (shared persisted workspace store). Like the SOL window it guards its own
// auth: signing in stays a main-window flow, so an unauthenticated window says
// so instead of fetching anything.
import { useParams } from 'react-router-dom'
import { isSafeExtensionId } from '@solus/shared-types'
import { Spinner } from '../../../components/ui/Spinner'
import { useAuthStore } from '../../../store/authStore'
import { useWorkspaceStore } from '../../../store/workspaceStore'
import type { BridgeDeps } from '../host/bridgeDeps'
import { ExtensionFrame } from '../frame/ExtensionFrame'
import type { InstalledBundleDeps } from '../frame/installedBundle'
import { useInstalledBundle } from '../frame/useInstalledBundle'
import { headerFacts } from './headerFacts'
import { PageHeader } from './PageHeader'

export interface ExtensionWindowRootProps {
  readonly bundleDeps?: InstalledBundleDeps
  readonly bridgeDeps?: BridgeDeps
}

const SHELL: React.CSSProperties = {
  height: '100vh',
  display: 'flex',
  flexDirection: 'column',
  background: 'var(--bg)',
  color: 'var(--tx)',
  fontFamily: 'var(--font-ui)',
  boxSizing: 'border-box',
  overflow: 'hidden'
}

function Centered({ children }: { children: React.ReactNode }): React.JSX.Element {
  return (
    <div
      style={{
        flex: 1,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 24,
        fontSize: 12.5,
        color: 'var(--mut)',
        textAlign: 'center'
      }}
    >
      {children}
    </div>
  )
}

function WindowBody({
  projectId,
  slug,
  bundleDeps,
  bridgeDeps
}: ExtensionWindowRootProps & { projectId: string; slug: string }): React.JSX.Element {
  const bundle = useInstalledBundle(projectId, slug, 'window', bundleDeps)
  const facts = headerFacts(bundle.state, slug)
  return (
    <>
      <PageHeader
        {...facts}
        name={facts.ready?.manifest.views.window?.title ?? facts.name}
        iconSvg={null}
      />
      <ExtensionFrame
        projectId={projectId}
        slug={slug}
        view="window"
        bundle={bundle}
        bridgeDeps={bridgeDeps}
      />
    </>
  )
}

export function ExtensionWindowRoot(props: ExtensionWindowRootProps): React.JSX.Element {
  const { extensionId } = useParams<{ extensionId: string }>()
  const status = useAuthStore((s) => s.status)
  const project = useWorkspaceStore((s) => s.project)
  const slug = extensionId !== undefined && isSafeExtensionId(extensionId) ? extensionId : null

  let body: React.JSX.Element
  if (status === 'loading') {
    body = (
      <Centered>
        <Spinner size={18} />
      </Centered>
    )
  } else if (status === 'unauthenticated') {
    body = <Centered>Sign in from the main Solus window to use extensions here.</Centered>
  } else if (slug === null) {
    body = <Centered>This window was opened for an extension Solus does not recognise.</Centered>
  } else if (!project) {
    body = <Centered>Open a project in the main Solus window to use {slug} here.</Centered>
  } else {
    body = <WindowBody {...props} projectId={project.id} slug={slug} />
  }
  return (
    <div data-testid="ext-window-root" style={SHELL}>
      {body}
    </div>
  )
}
