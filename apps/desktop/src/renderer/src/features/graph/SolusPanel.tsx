// The project `.solus` panel (SOLUSDEV-240, docs/wireflows/workspace.md): five
// fixed sections, every one offering the same three right-click actions —
// Import files, Ask SOL to find, Type it. Entries are what the server holds;
// an empty section says EMPTY, never a placeholder. Imported files become
// `document` nodes under the `.solus` graph node; typed text does not.
import { useRef, useState } from 'react'
import { Button } from '../../components/ui/Button'
import {
  ContextMenu,
  clampMenuPosition,
  type ContextMenuItem
} from '../../components/ui/ContextMenu'
import { Mono } from '../../components/ui/Mono'
import { Icons } from '../../components/ui/icons.constants'
import {
  ARTIFACT_MAX_BYTES,
  SOLUS_SECTIONS,
  addSolusEntry,
  deleteSolusEntry,
  updateSolusEntry,
  uploadArtifact,
  type SolusEntry,
  type SolusSection
} from '../../lib/api/resources'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { DeleteConfirmModal } from '../workspace/modals'
import { useShellStore } from '../workspace/shellStore'
import { selectSession, sendMessage, startNewChat, useSolChatStore } from '../sol/solChatStore'
import { SECTION_LABELS, useSolusConfig, type SolusState } from './useSolusConfig'

/** Count chip text: the honest number, or EMPTY. Pure. */
export function sectionCountLabel(count: number): string {
  return count === 0 ? 'EMPTY' : String(count)
}

/** The user turn sent for "Ask SOL to find" — the section is named so SOL files
 *  into the right place with `add_solus_entry`. Pure. */
export function askSolMessage(sectionLabel: string, query: string): string {
  return `Find for .solus › ${sectionLabel}: ${query.trim()}`
}

export function formatSize(bytes: number | null): string {
  if (bytes === null) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function errorText(error: unknown): string {
  return error instanceof Error && error.message ? error.message : 'Unknown error'
}

type ComposerKind = 'ask' | 'type' | 'edit'

interface Composer {
  section: SolusSection
  kind: ComposerKind
  entry?: SolusEntry
}

interface Menu {
  x: number
  y: number
  section: SolusSection
  entry?: SolusEntry
}

const PLACEHOLDER: Readonly<Record<ComposerKind, string>> = {
  ask: "What should SOL find? e.g. 'FSAE EV rules on fusing'",
  type: 'Type it — plain text',
  edit: 'Edit the note'
}

const CONFIRM: Readonly<Record<ComposerKind, string>> = {
  ask: 'Ask SOL',
  type: 'Add',
  edit: 'Save'
}

function toast(kind: 'ok' | 'warn', title: string, body: string): void {
  useShellStore.getState().setToast({ kind, title, body })
}

/* ---------------------------------------------------------------- actions */

interface Actions {
  importFile: (section: SolusSection, file: File) => Promise<void>
  submit: (composer: Composer, text: string) => Promise<void>
  remove: (entry: SolusEntry) => Promise<boolean>
}

async function askSol(
  projectId: string,
  solus: SolusState,
  section: SolusSection,
  text: string
): Promise<void> {
  const label = SECTION_LABELS[section]
  const before = solus.sections[section].length
  startNewChat(projectId)
  await sendMessage(projectId, askSolMessage(label, text), 'do')
  const after = await solus.refetch()
  if ((after?.sections[section].length ?? before) > before) {
    toast('ok', `Filed to .solus › ${label}`, 'SOL filed what it found.')
  } else {
    toast(
      'warn',
      'SOL answered but filed nothing',
      'Open SOL to read the reply — nothing was invented for this section.'
    )
  }
}

function useSolusActions(
  projectId: string | null,
  solus: SolusState,
  onGraphChanged?: () => void
): Actions {
  const importFile = async (section: SolusSection, file: File): Promise<void> => {
    if (!projectId) return
    if (file.size > ARTIFACT_MAX_BYTES) {
      toast('warn', 'File too large', 'That file is over 8 MiB — Solus keeps .solus imports small.')
      return
    }
    try {
      const ref = await uploadArtifact(projectId, file)
      await addSolusEntry(projectId, section, {
        kind: 'artifact',
        artifact_id: ref.artifact_id,
        name: file.name
      })
      await solus.refetch()
      onGraphChanged?.()
      toast(
        'ok',
        `Imported ${file.name}`,
        `.solus › ${SECTION_LABELS[section]} — now a node under .solus.`
      )
    } catch (error: unknown) {
      toast('warn', 'Import failed', errorText(error))
    }
  }

  const submit = async ({ section, kind, entry }: Composer, text: string): Promise<void> => {
    if (!projectId) return
    try {
      if (kind === 'ask') await askSol(projectId, solus, section, text)
      else if (kind === 'edit' && entry) await updateSolusEntry(projectId, entry.id, text)
      else await addSolusEntry(projectId, section, { kind: 'text', text })
      if (kind !== 'ask') await solus.refetch()
      if (kind === 'type')
        toast('ok', `Added to .solus › ${SECTION_LABELS[section]}`, text.slice(0, 80))
    } catch (error: unknown) {
      toast('warn', "That didn't work", errorText(error))
    }
  }

  const remove = async (entry: SolusEntry): Promise<boolean> => {
    if (!projectId) return false
    try {
      await deleteSolusEntry(projectId, entry.id)
      await solus.refetch()
      if (entry.kind === 'artifact') onGraphChanged?.()
      return true
    } catch (error: unknown) {
      toast('warn', "Couldn't remove that entry", errorText(error))
      return false
    }
  }

  return { importFile, submit, remove }
}

/* ------------------------------------------------------------ components */

function EntryIcon({ entry }: { entry: SolusEntry }): React.JSX.Element {
  const color = entry.kind === 'sol' ? 'var(--acc)' : 'var(--mut)'
  const Icon =
    entry.kind === 'artifact' ? Icons.file : entry.kind === 'sol' ? Icons.sol : Icons.lines
  return (
    <span style={{ color, marginTop: 1, flexShrink: 0, display: 'inline-flex' }}>
      <Icon size={11} />
    </span>
  )
}

function EntryRow({
  entry,
  last,
  onMenu
}: {
  entry: SolusEntry
  last: boolean
  onMenu: (e: React.MouseEvent) => void
}): React.JSX.Element {
  const isFile = entry.kind === 'artifact'
  const sub = isFile
    ? [entry.media_type, formatSize(entry.size_bytes)].filter(Boolean).join(' · ')
    : entry.kind === 'sol'
      ? 'filed by SOL'
      : null
  return (
    <div
      onContextMenu={onMenu}
      style={{
        display: 'flex',
        gap: 8,
        padding: '6px 10px',
        borderBottom: last ? 'none' : '1px solid var(--bd)',
        alignItems: 'flex-start'
      }}
    >
      <EntryIcon entry={entry} />
      <div style={{ minWidth: 0 }}>
        <div
          style={{
            fontFamily: entry.kind === 'text' ? 'var(--font-ui)' : 'var(--font-mono)',
            fontSize: 11,
            lineHeight: 1.4,
            wordBreak: 'break-word',
            whiteSpace: 'pre-wrap'
          }}
        >
          {isFile ? entry.name : entry.text}
        </div>
        {sub && <div style={{ fontSize: 9.5, color: 'var(--mut)', marginTop: 2 }}>{sub}</div>}
      </div>
    </div>
  )
}

function ComposerBox({
  kind,
  initial,
  onCancel,
  onSubmit
}: {
  kind: ComposerKind
  initial: string
  onCancel: () => void
  onSubmit: (text: string) => Promise<void>
}): React.JSX.Element {
  const [draft, setDraft] = useState(initial)
  const [busy, setBusy] = useState(false)
  const send = async (): Promise<void> => {
    setBusy(true)
    await onSubmit(draft.trim())
    setBusy(false)
  }
  return (
    <div style={{ padding: 8 }}>
      <textarea
        autoFocus
        value={draft}
        maxLength={4000}
        onChange={(e) => setDraft(e.target.value)}
        placeholder={PLACEHOLDER[kind]}
        style={{
          width: '100%',
          boxSizing: 'border-box',
          height: 56,
          background: 'var(--sur)',
          color: 'var(--tx)',
          border: '1px solid var(--acc)',
          borderRadius: 3,
          padding: '7px 9px',
          fontSize: 11.5,
          fontFamily: 'var(--font-ui)',
          resize: 'none',
          outline: 'none'
        }}
      />
      <div
        style={{
          display: 'flex',
          gap: 6,
          justifyContent: 'flex-end',
          alignItems: 'center',
          marginTop: 6
        }}
      >
        {draft.length > 3500 && <Mono size={8}>{draft.length} / 4000</Mono>}
        <Button kind="ghost" size="sm" onClick={onCancel}>
          Cancel
        </Button>
        <Button
          kind="primary"
          size="sm"
          disabled={busy || !draft.trim()}
          onClick={() => void send()}
        >
          {CONFIRM[kind]}
        </Button>
      </div>
    </div>
  )
}

function SectionHeader({
  section,
  count,
  divided
}: {
  section: SolusSection
  count: string
  divided: boolean
}): React.JSX.Element {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        padding: '7px 10px',
        borderBottom: divided ? '1px solid var(--bd)' : 'none'
      }}
    >
      <span style={{ fontSize: 12, fontWeight: 600 }}>{SECTION_LABELS[section]}</span>
      <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
        {section === 'errors' && (
          <Mono size={7.5} color="var(--warn)">
            AUTO + YOU
          </Mono>
        )}
        <Mono size={8}>{count}</Mono>
      </span>
    </div>
  )
}

function SectionCard({
  section,
  entries,
  online,
  composer,
  onMenu,
  onCancel,
  onSubmit
}: {
  section: SolusSection
  entries: SolusEntry[]
  online: boolean
  /** The open composer, already filtered to THIS section by the caller. */
  composer: Composer | null
  onMenu: (e: React.MouseEvent, section: SolusSection, entry?: SolusEntry) => void
  onCancel: () => void
  onSubmit: (text: string) => Promise<void>
}): React.JSX.Element {
  const composing = composer !== null
  return (
    <div
      onContextMenu={(e) => onMenu(e, section)}
      style={{
        marginBottom: 6,
        borderRadius: 4,
        border: '1px solid var(--bd)',
        background: 'var(--bg)'
      }}
    >
      <SectionHeader
        section={section}
        count={online ? sectionCountLabel(entries.length) : '—'}
        divided={entries.length > 0 || composing}
      />
      {entries.map((entry, i) => (
        <EntryRow
          key={entry.id}
          entry={entry}
          last={i === entries.length - 1 && !composing}
          onMenu={(e) => {
            e.stopPropagation()
            onMenu(e, section, entry)
          }}
        />
      ))}
      {composer && (
        <ComposerBox
          key={composer.kind + (composer.entry?.id ?? '')}
          kind={composer.kind}
          initial={composer.entry?.text ?? ''}
          onCancel={onCancel}
          onSubmit={onSubmit}
        />
      )}
    </div>
  )
}

/** The three actions every section offers — identical everywhere by design. */
function sectionMenuItems(
  section: SolusSection,
  streaming: boolean,
  onImport: (section: SolusSection) => void,
  onCompose: (composer: Composer) => void
): ContextMenuItem[] {
  return [
    { label: 'Import files…', onSelect: () => onImport(section) },
    {
      label: 'Ask SOL to find…',
      onSelect: () => onCompose({ section, kind: 'ask' }),
      disabled: streaming,
      hint: 'SOL is busy with another turn'
    },
    { label: 'Type it', onSelect: () => onCompose({ section, kind: 'type' }) }
  ]
}

function entryMenuItems(
  entry: SolusEntry,
  onCompose: (composer: Composer) => void,
  onDelete: (entry: SolusEntry) => void
): ContextMenuItem[] {
  const edit: ContextMenuItem[] =
    entry.kind === 'artifact'
      ? []
      : [
          {
            label: 'Edit',
            onSelect: () => onCompose({ section: entry.section, kind: 'edit', entry })
          }
        ]
  return [...edit, { label: 'Delete', danger: true, onSelect: () => onDelete(entry) }]
}

/* ----------------------------------------------------------------- panel */

export function SolusPanel({
  onGraphChanged
}: {
  /** Called after an imported file's document node is created or removed. */
  onGraphChanged?: () => void
} = {}): React.JSX.Element {
  const projectId = useWorkspaceStore((s) => s.project?.id ?? null)
  const solus = useSolusConfig(projectId)
  const streaming = useSolChatStore((s) => selectSession(s, projectId).streaming)
  const actions = useSolusActions(projectId, solus, onGraphChanged)
  const [menu, setMenu] = useState<Menu | null>(null)
  const [composer, setComposer] = useState<Composer | null>(null)
  const [pendingDelete, setPendingDelete] = useState<SolusEntry | null>(null)
  const fileInput = useRef<HTMLInputElement | null>(null)
  const importTarget = useRef<SolusSection | null>(null)
  const online = solus.status !== 'offline' && projectId !== null

  const onMenu = (e: React.MouseEvent, section: SolusSection, entry?: SolusEntry): void => {
    e.preventDefault()
    if (!online) return
    setMenu({ section, entry, ...clampMenuPosition(e.clientX, e.clientY) })
  }
  const onImport = (section: SolusSection): void => {
    importTarget.current = section
    fileInput.current?.click()
  }
  const onDelete = (entry: SolusEntry): void => {
    if (entry.kind === 'artifact') setPendingDelete(entry)
    else void actions.remove(entry)
  }
  const onFilePicked = (input: HTMLInputElement): void => {
    const file = input.files?.[0]
    input.value = ''
    if (file && importTarget.current) void actions.importFile(importTarget.current, file)
  }
  const onSubmit = async (text: string): Promise<void> => {
    if (composer) await actions.submit(composer, text)
    setComposer(null)
  }

  return (
    <div data-testid="solus-panel" style={PANEL_STYLE}>
      <input
        ref={fileInput}
        type="file"
        aria-label="Import a file into .solus"
        style={{ display: 'none' }}
        onChange={(e) => onFilePicked(e.currentTarget)}
      />
      <div style={HEADER_STYLE}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 600 }}>
          .solus
        </span>
        <Mono size={8}>{online ? 'RIGHT-CLICK A SECTION' : 'OFFLINE'}</Mono>
      </div>
      <div style={{ flex: 1, overflowY: 'auto', padding: '6px 8px' }}>
        {!online && <div style={NOTE_STYLE}>Sign in and open a project to see its .solus.</div>}
        {SOLUS_SECTIONS.map((section) => (
          <SectionCard
            key={section}
            section={section}
            entries={solus.sections[section]}
            online={online}
            composer={composer?.section === section ? composer : null}
            onMenu={onMenu}
            onCancel={() => setComposer(null)}
            onSubmit={onSubmit}
          />
        ))}
        <div style={NOTE_STYLE}>
          Project-level — not ~/.solus, which is this machine&apos;s. SOL files what it finds here.
          Empty sections are fine — they&apos;re not placeholders, they&apos;re honest.
        </div>
      </div>
      {menu && (
        <ContextMenu
          x={menu.x}
          y={menu.y}
          title={menu.entry ? undefined : SECTION_LABELS[menu.section]}
          items={
            menu.entry
              ? entryMenuItems(menu.entry, setComposer, onDelete)
              : sectionMenuItems(menu.section, streaming, onImport, setComposer)
          }
          onClose={() => setMenu(null)}
        />
      )}
      {pendingDelete && (
        <DeleteConfirmModal
          name={pendingDelete.name ?? 'this file'}
          noun="file"
          detail="from .solus — its graph node and stored bytes go with it"
          onClose={() => setPendingDelete(null)}
          onConfirm={() => actions.remove(pendingDelete)}
        />
      )}
    </div>
  )
}

const PANEL_STYLE: React.CSSProperties = {
  width: 290,
  borderRight: '1px solid var(--bd)',
  background: 'var(--sur)',
  display: 'flex',
  flexDirection: 'column',
  flexShrink: 0,
  minHeight: 0
}

const HEADER_STYLE: React.CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'center',
  padding: '10px 14px',
  borderBottom: '1px solid var(--bd)'
}

const NOTE_STYLE: React.CSSProperties = {
  fontSize: 10.5,
  color: 'var(--mut)',
  padding: '6px 4px',
  lineHeight: 1.55
}
