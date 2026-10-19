// Local folder card — on Home's project pane for the current project
// (SOLUSDEV-244; it began life on the Project Overview hub, SOLUSDEV-164).
// Links a project to a working copy on THIS machine: select an existing directory, or
// clone a repo (URL prefilled from a connected GitHub source; cloned by the
// user's own git, so private repos use their local credentials — no Solus token
// touches disk). The path lives in a machine-local store, never the API. When
// not running under the desktop app the card degrades to an honest note.
//
// SOLUSDEV-249 (I2): the linked folder is also a `local` graph source for
// THIS machine — linking tells the API the machine id + folder name (never
// the path), the companion scans it, and the card shows the scan state, what
// was recognised, and Open-in-tool for each project, via useLocalFolder.
import { useEffect, useRef, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import { Spinner } from '../../components/ui/Spinner'
import { Icons } from '../../components/ui/icons.constants'
import { getDesktopFolderBridge } from '../../lib/desktopBridge'
import { ModalShell, MODAL_INPUT_STYLE } from '../workspace/modals'
import { DetectedProjectList, ScanStateLine } from './LocalFolderDetails'
import {
  COMPANION_OFFLINE_NOTE,
  MACHINE_UNAVAILABLE_NOTE,
  OPEN_LABEL,
  detectedProjects,
  linkedFolderPresentation
} from './localFolder.constants'
import { useProjectFolderStore } from './projectFolderStore'
import { useLocalFolder, type LocalFolderController } from './useLocalFolder'

export interface ProjectFolderCardProps {
  projectId: string
  /** Repo URL to prefill the clone dialog (from a connected GitHub source). */
  suggestedRepoUrl?: string
  /** Home's Overview (SOLUSDEV-317): Change folder and Unlink move behind
   *  More, and the detected-project list stays on the Sources tab. */
  compact?: boolean
  /** A label printed inside the card, above its content. */
  heading?: string
  /** No card chrome (border, fill): the content sits inside another list. */
  bare?: boolean
}

export function ProjectFolderCard(props: ProjectFolderCardProps): React.JSX.Element {
  return <ProjectFolderCardContent key={props.projectId} {...props} />
}

function ProjectFolderCardContent({
  projectId,
  suggestedRepoUrl,
  compact = false,
  heading,
  bare = false
}: ProjectFolderCardProps): React.JSX.Element {
  const {
    bridge,
    link,
    clearFolder,
    cloning,
    setCloning,
    selectionVersion,
    setSelection,
    selecting,
    selectionError,
    folder,
    selectFolder,
    runClone
  } = useProjectFolderSelection(projectId)
  const inset = bare ? BARE_INSET : '16px'

  return (
    <FolderShell bare={bare}>
      {heading && (
        <div style={{ padding: '14px 16px 0' }}>
          <Mono size={9.5} color="var(--mut)" style={{ letterSpacing: '0.08em' }}>
            {heading}
          </Mono>
        </div>
      )}
      {!bridge ? (
        <div style={{ padding: inset, fontSize: 12.5, color: 'var(--mut)', lineHeight: 1.55 }}>
          Linking a local folder is available in the Solus desktop app.
        </div>
      ) : link ? (
        <LinkedFolder
          link={link}
          folder={folder}
          compact={compact}
          inset={bare ? BARE_INSET : '14px 16px'}
          selecting={selecting}
          onChangeFolder={() => void selectFolder()}
          onOpenFolder={() => void bridge.reveal(link.path)}
          onUnlink={() => {
            // The machine-local link goes first (instant, never blocked on the
            // API); the graph source is then disconnected best-effort.
            selectionVersion.current += 1
            setSelection(null)
            clearFolder(projectId)
            void folder.unlink()
          }}
        />
      ) : (
        <div style={{ padding: inset, display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ fontSize: 12.5, color: 'var(--mut)', lineHeight: 1.55 }}>
            Choose a project folder, then confirm “Select this folder” in the picker to link and
            scan it.
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <Button kind="ghost" size="sm" disabled={selecting} onClick={() => void selectFolder()}>
              <Icons.box size={13} /> Select folder
            </Button>
            <Button
              kind="ghost"
              size="sm"
              disabled={selecting}
              onClick={() => setCloning(projectId)}
            >
              <Icons.github size={13} /> Clone a repo
            </Button>
          </div>
        </div>
      )}
      {selectionError && (
        <div role="alert" style={{ padding: '12px 16px', color: 'var(--err)', fontSize: 12 }}>
          {selectionError}
        </div>
      )}
      {cloning === projectId && (
        <CloneModal
          initialUrl={suggestedRepoUrl ?? ''}
          onClose={() => setCloning(null)}
          onClone={runClone}
        />
      )}
    </FolderShell>
  )
}

/** Bare mode sits flush with the list it is in: no side padding of its own. */
const BARE_INSET = '10px 0 6px'

/** The card's frame: a Card, or a plain block inside another list. */
function FolderShell({
  bare,
  children
}: {
  bare: boolean
  children: React.ReactNode
}): React.JSX.Element {
  return bare ? <div>{children}</div> : <Card pad={0}>{children}</Card>
}

function LinkedFolder({
  link,
  folder,
  compact,
  inset,
  selecting,
  onChangeFolder,
  onOpenFolder,
  onUnlink
}: {
  link: { path: string; repoUrl?: string }
  folder: LocalFolderController
  compact: boolean
  /** The block's padding: card-style, or flush when bare. */
  inset: string
  selecting: boolean
  onChangeFolder: () => void
  onOpenFolder: () => void
  onUnlink: () => void
}): React.JSX.Element {
  const { view, status } = folder
  const { editorReason, rootEntityId, bridgeOffline, rowsReason, scanned } =
    linkedFolderPresentation(view, status)
  return (
    <div
      data-testid="linked-folder"
      style={{
        padding: inset,
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
        minWidth: 0,
        overflow: 'hidden'
      }}
    >
      <LinkedFolderHeader link={link} view={view} status={status} />
      <div
        style={{ display: 'flex', gap: compact ? 2 : 8, flexWrap: 'wrap', alignItems: 'center' }}
      >
        <Button
          kind="ghost"
          size="sm"
          data-testid="open-root-editor"
          disabled={editorReason !== null}
          title={editorReason ?? undefined}
          onClick={() => rootEntityId && void folder.open(rootEntityId, 'vscode')}
        >
          {OPEN_LABEL.vscode}
        </Button>
        {!compact && (
          <Button kind="ghost" size="sm" disabled={selecting} onClick={onChangeFolder}>
            Change folder
          </Button>
        )}
        <Button
          kind={compact ? 'bare' : 'ghost'}
          size="sm"
          style={compact ? COMPACT_BARE : undefined}
          onClick={onOpenFolder}
        >
          Show in file manager
        </Button>
        {compact ? (
          <MoreFolderActions
            selecting={selecting}
            onChangeFolder={onChangeFolder}
            onUnlink={onUnlink}
          />
        ) : (
          <Button kind="ghost" size="sm" onClick={onUnlink}>
            Unlink
          </Button>
        )}
      </div>
      {!folder.machineAvailable && <Note>{MACHINE_UNAVAILABLE_NOTE}</Note>}
      {bridgeOffline && <Note>{COMPANION_OFFLINE_NOTE}</Note>}
      {/* A greyed "Open in editor" says why in words, not only in a hover
          tooltip (SOLUSDEV-253) — the offline notes above already cover theirs. */}
      {editorReason !== null && !bridgeOffline && folder.machineAvailable && (
        <Note>{editorReason}</Note>
      )}
      {!compact && (
        <DetectedProjectList
          projects={detectedProjects(view)}
          scanned={scanned}
          disabledReason={rowsReason}
          onOpen={folder.open}
        />
      )}
    </div>
  )
}

/** Compact mode's More ▾: the folder actions that change or drop the link. */
function MoreFolderActions({
  selecting,
  onChangeFolder,
  onUnlink
}: {
  selecting: boolean
  onChangeFolder: () => void
  onUnlink: () => void
}): React.JSX.Element {
  const [open, setOpen] = useState(false)
  const pick = (action: () => void): void => {
    setOpen(false)
    action()
  }
  return (
    <div
      style={{ position: 'relative' }}
      onKeyDown={(e) => {
        if (e.key === 'Escape') setOpen(false)
      }}
    >
      <Button
        kind="bare"
        size="sm"
        style={COMPACT_BARE}
        aria-label="More folder actions"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        More ▾
      </Button>
      {open && (
        <>
          <div style={{ position: 'fixed', inset: 0, zIndex: 60 }} onClick={() => setOpen(false)} />
          <div role="menu" className="popover-in" style={MORE_MENU}>
            <button
              type="button"
              role="menuitem"
              className="interactive"
              disabled={selecting}
              onClick={() => pick(onChangeFolder)}
              style={MORE_ITEM}
            >
              Change folder
            </button>
            <button
              type="button"
              role="menuitem"
              className="interactive"
              onClick={() => pick(onUnlink)}
              style={MORE_ITEM}
            >
              Unlink
            </button>
          </div>
        </>
      )}
    </div>
  )
}

/** Compact mode's text buttons drop their side padding so the three actions
 *  share one row in a third of the pane. */
const COMPACT_BARE: React.CSSProperties = { paddingLeft: 6, paddingRight: 6 }

const MORE_MENU: React.CSSProperties = {
  position: 'absolute',
  left: 0,
  top: '100%',
  zIndex: 61,
  minWidth: 150,
  background: 'var(--sur)',
  border: '1px solid var(--bd)',
  borderRadius: 4,
  boxShadow: '0 10px 30px rgba(0,0,0,0.4)',
  overflow: 'hidden'
}

const MORE_ITEM: React.CSSProperties = {
  display: 'block',
  width: '100%',
  textAlign: 'left',
  background: 'transparent',
  border: 'none',
  color: 'var(--tx)',
  cursor: 'pointer',
  fontFamily: 'var(--font-ui)',
  fontSize: 12.5,
  padding: '9px 12px'
}

function LinkedFolderHeader({
  link,
  view,
  status
}: {
  link: { path: string; repoUrl?: string }
  view: LocalFolderController['view']
  status: LocalFolderController['status']
}): React.JSX.Element {
  const awaitingCompanion =
    status === 'loading' &&
    view?.source?.status === 'error' &&
    view.source.last_error?.code === 'api_unreachable'
  return (
    <div style={{ display: 'flex', gap: 10, alignItems: 'center', minWidth: 0 }}>
      <span style={{ color: 'var(--acc)', flexShrink: 0, display: 'inline-flex' }}>
        <Icons.box size={16} />
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        {/* A long path ends in "…" rather than wrapping; the title carries the whole of it. */}
        <div title={link.path} style={ONE_LINE}>
          <Mono size={11} style={{ textTransform: 'none' }}>
            {link.path}
          </Mono>
        </div>
        {link.repoUrl && (
          <div
            title={link.repoUrl}
            style={{ ...ONE_LINE, fontSize: 10.5, color: 'var(--mut)', marginTop: 3 }}
          >
            cloned from {link.repoUrl}
          </div>
        )}
        {!awaitingCompanion && <ScanStateLine source={view?.source ?? null} />}
      </div>
    </div>
  )
}

/** A quiet, honest line beneath the controls — never a hidden control. */
function Note({ children }: { children: React.ReactNode }): React.JSX.Element {
  return (
    <div role="note" style={{ fontSize: 10.5, color: 'var(--mut)', lineHeight: 1.5 }}>
      {children}
    </div>
  )
}

/** Single line, clipped with an ellipsis. */
const ONE_LINE: React.CSSProperties = {
  display: 'block',
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  whiteSpace: 'nowrap'
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

function useProjectFolderSelection(projectId: string) {
  const bridge = getDesktopFolderBridge()
  const link = useProjectFolderStore((s) => s.folders[projectId])
  const setFolder = useProjectFolderStore((s) => s.setFolder)
  const clearFolder = useProjectFolderStore((s) => s.clearFolder)
  const [cloning, setCloning] = useState<string | null>(null)
  const [selection, setSelection] = useState<{
    projectId: string
    busy: boolean
    error: string | null
  } | null>(null)
  const selectionVersion = useRef(0)
  useEffect(
    () => () => {
      selectionVersion.current += 1
    },
    [projectId]
  )
  const selecting = selection?.projectId === projectId && selection.busy
  const selectionError = selection?.projectId === projectId ? selection.error : null
  const folder = useLocalFolder(projectId, link !== undefined)

  const selectFolder = async (): Promise<void> => {
    const version = ++selectionVersion.current
    const current = (): boolean => version === selectionVersion.current
    setSelection({ projectId, busy: true, error: null })
    try {
      const path = await bridge?.pick()
      if (!path || !current()) return
      if (!(await setFolder(projectId, { path }))) {
        if (current())
          setSelection({
            projectId,
            busy: false,
            error: 'Could not link this folder on this machine. Try selecting it again.'
          })
        return
      }
      if (current()) void folder.link(path)
    } catch {
      if (current())
        setSelection({
          projectId,
          busy: false,
          error: 'Could not open the folder picker. Try again.'
        })
    } finally {
      if (current()) setSelection((previous) => (previous ? { ...previous, busy: false } : null))
    }
  }

  const runClone = cloneProjectFolder(bridge, selectionVersion, projectId, setFolder, folder)
  return {
    bridge,
    link,
    clearFolder,
    cloning,
    setCloning,
    selectionVersion,
    setSelection,
    selecting,
    selectionError,
    folder,
    selectFolder,
    runClone
  }
}

function cloneProjectFolder(
  bridge: ReturnType<typeof getDesktopFolderBridge>,
  selectionVersion: { current: number },
  projectId: string,
  setFolder: ReturnType<typeof useProjectFolderStore.getState>['setFolder'],
  folder: LocalFolderController
) {
  const runClone = async (repoUrl: string): Promise<{ ok: boolean; error?: string }> => {
    if (!bridge) return { ok: false, error: 'The desktop app is required to clone.' }
    const version = ++selectionVersion.current
    const current = (): boolean => version === selectionVersion.current
    const parentDir = await bridge.pick()
    if (!parentDir || !current()) return { ok: false }
    const result = await bridge.clone({ repoUrl, parentDir })
    if (!current()) return { ok: false }
    if (result.path) {
      if (!(await setFolder(projectId, { path: result.path, repoUrl }))) {
        return {
          ok: false,
          error: 'The repository was cloned, but its folder could not be linked on this machine.'
        }
      }
      if (!current()) return { ok: false }
      void folder.link(result.path)
      return { ok: true }
    }
    return { ok: false, error: result.error ?? 'Clone failed.' }
  }

  return runClone
}
