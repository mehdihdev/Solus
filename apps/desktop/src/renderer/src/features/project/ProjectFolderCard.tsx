// Local folder card for the Project Overview hub (SOLUSDEV-164). Links a
// project to a working copy on THIS machine: select an existing directory, or
// clone a repo (URL prefilled from a connected GitHub source; cloned by the
// user's own git, so private repos use their local credentials — no Solus token
// touches disk). The path lives in a machine-local store, never the API. When
// not running under the desktop app the card degrades to an honest note.
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import { Spinner } from '../../components/ui/Spinner'
import { Icons } from '../../components/ui/icons.constants'
import { getDesktopFolderBridge } from '../../lib/desktopBridge'
import { ModalShell, MODAL_INPUT_STYLE } from '../workspace/modals'
import { useProjectFolderStore } from './projectFolderStore'

export interface ProjectFolderCardProps {
  projectId: string
  /** Repo URL to prefill the clone dialog (from a connected GitHub source). */
  suggestedRepoUrl?: string
}

export function ProjectFolderCard({
  projectId,
  suggestedRepoUrl
}: ProjectFolderCardProps): React.JSX.Element {
  const bridge = getDesktopFolderBridge()
  const link = useProjectFolderStore((s) => s.folders[projectId])
  const setFolder = useProjectFolderStore((s) => s.setFolder)
  const clearFolder = useProjectFolderStore((s) => s.clearFolder)
  const [cloning, setCloning] = useState(false)

  const selectFolder = async (): Promise<void> => {
    const path = await bridge?.pick()
    if (path) setFolder(projectId, { path })
  }

  const runClone = async (repoUrl: string): Promise<{ ok: boolean; error?: string }> => {
    if (!bridge) return { ok: false, error: 'The desktop app is required to clone.' }
    const parentDir = await bridge.pick()
    if (!parentDir) return { ok: false }
    const result = await bridge.clone({ repoUrl, parentDir })
    if (result.path) {
      setFolder(projectId, { path: result.path, repoUrl })
      return { ok: true }
    }
    return { ok: false, error: result.error ?? 'Clone failed.' }
  }

  return (
    <Card pad={0}>
      {!bridge ? (
        <div style={{ padding: '16px', fontSize: 12.5, color: 'var(--mut)', lineHeight: 1.55 }}>
          Linking a local folder is available in the Solus desktop app.
        </div>
      ) : link ? (
        <LinkedFolder
          link={link}
          onOpen={() => void bridge.reveal(link.path)}
          onUnlink={() => clearFolder(projectId)}
        />
      ) : (
        <div style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ fontSize: 12.5, color: 'var(--mut)', lineHeight: 1.55 }}>
            Link a working copy on this computer so Solus can line the graph up with your files.
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <Button kind="ghost" size="sm" onClick={() => void selectFolder()}>
              <Icons.box size={13} /> Select folder
            </Button>
            <Button kind="ghost" size="sm" onClick={() => setCloning(true)}>
              <Icons.github size={13} /> Clone a repo
            </Button>
          </div>
        </div>
      )}
      {cloning && (
        <CloneModal
          initialUrl={suggestedRepoUrl ?? ''}
          onClose={() => setCloning(false)}
          onClone={runClone}
        />
      )}
    </Card>
  )
}

function LinkedFolder({
  link,
  onOpen,
  onUnlink
}: {
  link: { path: string; repoUrl?: string }
  onOpen: () => void
  onUnlink: () => void
}): React.JSX.Element {
  return (
    <div style={{ padding: '14px 16px', display: 'flex', gap: 12, alignItems: 'center' }}>
      <span style={{ color: 'var(--acc)' }}>
        <Icons.box size={16} />
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <Mono size={11} style={{ textTransform: 'none', wordBreak: 'break-all' }}>
          {link.path}
        </Mono>
        {link.repoUrl && (
          <div style={{ fontSize: 10.5, color: 'var(--mut)', marginTop: 3 }}>
            cloned from {link.repoUrl}
          </div>
        )}
      </div>
      <Button kind="ghost" size="sm" onClick={onOpen}>
        Open
      </Button>
      <Button kind="ghost" size="sm" onClick={onUnlink}>
        Unlink
      </Button>
    </div>
  )
}

function CloneModal({
  initialUrl,
  onClose,
  onClone
}: {
  initialUrl: string
  onClose: () => void
  onClone: (repoUrl: string) => Promise<{ ok: boolean; error?: string }>
}): React.JSX.Element {
  const [url, setUrl] = useState(initialUrl)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (): Promise<void> => {
    if (!url.trim()) return
    setBusy(true)
    setError(null)
    const result = await onClone(url.trim())
    setBusy(false)
    if (result.ok) {
      onClose()
      return
    }
    if (result.error) setError(result.error)
  }

  return (
    <ModalShell onClose={onClose}>
      <div style={{ fontSize: 16, fontWeight: 600 }}>Clone a repository</div>
      <div style={{ fontSize: 12, color: 'var(--mut)', marginTop: 4, lineHeight: 1.5 }}>
        Cloned with your machine&apos;s git, so private repos use your existing credentials. You
        choose where it lands.
      </div>
      <input
        aria-label="Repository URL"
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        placeholder="https://github.com/org/repo.git"
        autoFocus
        onKeyDown={(e) => e.key === 'Enter' && void submit()}
        style={{ ...MODAL_INPUT_STYLE, fontFamily: 'var(--font-mono)', fontSize: 12 }}
      />
      {error && <div style={{ marginTop: 8, fontSize: 11.5, color: 'var(--err)' }}>{error}</div>}
      <div style={{ display: 'flex', gap: 8, marginTop: 16, justifyContent: 'flex-end' }}>
        <Button kind="ghost" size="sm" onClick={onClose}>
          Cancel
        </Button>
        <Button kind="primary" size="sm" disabled={busy} onClick={() => void submit()}>
          {busy ? <Spinner size={11} color="var(--acc-ink)" /> : 'Choose folder & clone'}
        </Button>
      </div>
    </ModalShell>
  )
}
