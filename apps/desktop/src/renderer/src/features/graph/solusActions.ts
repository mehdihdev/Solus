// Existing .solus workflows, shared by real canvas nodes.
import { useWorkspaceSessionGeneration, workspaceSessionGeneration } from './workspaceSession'
import type { ContextMenuItem } from '../../components/ui/ContextMenu'
import {
  ARTIFACT_MAX_BYTES,
  addSolusEntry,
  deleteSolusEntry,
  updateSolusEntry,
  uploadArtifact,
  type SolusEntry,
  type SolusSection,
  isWritableSection
} from '../../lib/api/resources'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useAuthStore } from '../../store/authStore'
import { useShellStore } from '../workspace/shellStore'
import { sendMessage, startNewChat } from '../sol/solChatStore'
import { refreshWorkspaceFocus } from './workspaceFocus'
import { SECTION_LABELS, type SolusState } from './useSolusConfig'
/** Count chip text: the honest number, or EMPTY. Pure. */
export function sectionCountLabel(count: number): string {
  return count === 0 ? 'EMPTY' : String(count)
}

/** The user turn sent for "Ask SOL to find" — the section is named so SOL files
 *  into the right place with `add_solus_entry`. Pure. */
export function askSolMessage(sectionLabel: string, query: string): string {
  return `Find for .solus › ${sectionLabel}: ${query.trim()}`
}

/** "Documentation › guides" for a subsection target, the plain label otherwise. Pure. */
export function targetLabel(section: SolusSection, subsection?: string | null): string {
  return subsection ? `${SECTION_LABELS[section]} › ${subsection}` : SECTION_LABELS[section]
}

/** The hardware CONFIG record (environment/hardware) is written by its own routes:
 *  no context menu, no note editor, no delete from here. Pure. */
export function isHardwareConfig(entry: SolusEntry): boolean {
  return (
    entry.kind === 'config' && entry.section === 'environment' && entry.subsection === 'hardware'
  )
}

/** A section's entries, narrowed to one subsection when the node is one. Pure. */
export function entriesIn(
  sections: SolusState['sections'],
  section: SolusSection,
  subsection?: string | null
): SolusEntry[] {
  const items = sections[section]
  return subsection ? items.filter((entry) => entry.subsection === subsection) : items
}

/** How an entry is named in menus, lists and confirmations. Pure. */
export function entryTitle(entry: SolusEntry): string {
  return entry.name ?? entry.text?.slice(0, 120) ?? 'this note'
}

/** The entry behind a graph node, if the node is a .solus entry. Pure. */
export function findSolusEntry(
  sections: SolusState['sections'],
  entityId: string
): SolusEntry | undefined {
  return Object.values(sections)
    .flat()
    .find((entry) => entry.entity_id === entityId)
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

export type ComposerKind = 'ask' | 'type' | 'edit'

export interface Composer {
  entityId?: string
  section: SolusSection
  /** Set when the target is a subsection node or the composer's picker chose one. */
  subsection?: string | null
  kind: ComposerKind
  entry?: SolusEntry
}

/** What a composer hands back: the text, plus the subsection its picker chose. */
export type ComposerSubmit = (text: string, subsection?: string) => Promise<void>

function toast(kind: 'ok' | 'warn', title: string, body: string): void {
  useShellStore.getState().setToast({ kind, title, body })
}

/** The POST body with `subsection` only when there is one (the API treats absent as null). */
function withSubsection<T extends object>(
  input: T,
  subsection?: string | null
): T & { subsection?: string } {
  return subsection ? { ...input, subsection } : input
}

/* ---------------------------------------------------------------- actions */

interface Actions {
  importFile: (section: SolusSection, file: File, subsection?: string | null) => Promise<void>
  submit: (composer: Composer, text: string) => Promise<boolean>
  remove: (entry: SolusEntry) => Promise<boolean>
}

async function askSol(
  projectId: string,
  solus: SolusState,
  section: SolusSection,
  text: string,
  isCurrent: () => boolean,
  subsection?: string | null
): Promise<void> {
  const label = targetLabel(section, subsection)
  const before = solus.sections[section].length
  startNewChat(projectId)
  await sendMessage(projectId, askSolMessage(label, text), 'do')
  if (!isCurrent()) return
  const after = await solus.refetch()
  if (!isCurrent()) return
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

export function useSolusActions(
  projectId: string | null,
  solus: SolusState,
  onGraphChanged?: () => void
): Actions {
  const identity = useAuthStore((state) => `${state.status}:${state.user?.email ?? ''}`)
  const generation = useWorkspaceSessionGeneration()
  const isCurrent = (): boolean => {
    const auth = useAuthStore.getState()
    return (
      workspaceSessionGeneration() === generation &&
      useWorkspaceStore.getState().project?.id === projectId &&
      `${auth.status}:${auth.user?.email ?? ''}` === identity
    )
  }
  const refresh = async (readSections = true, removedId?: string): Promise<boolean> => {
    if (!isCurrent()) return false
    if (readSections) await solus.refetch()
    if (!isCurrent()) return false
    if (projectId) void refreshWorkspaceFocus(projectId, removedId)
    onGraphChanged?.()
    return true
  }
  const importFile = async (
    section: SolusSection,
    file: File,
    subsection?: string | null
  ): Promise<void> => {
    if (!projectId || !isCurrent()) return
    if (file.size > ARTIFACT_MAX_BYTES) {
      toast('warn', 'File too large', 'That file is over 8 MiB — Solus keeps .solus imports small.')
      return
    }
    try {
      const ref = await uploadArtifact(projectId, file)
      if (!isCurrent()) return
      await addSolusEntry(
        projectId,
        section,
        withSubsection(
          { kind: 'artifact', artifact_id: ref.artifact_id, name: file.name },
          subsection
        )
      )
      if (!(await refresh())) return
      toast(
        'ok',
        `Imported ${file.name}`,
        `.solus › ${targetLabel(section, subsection)} — now a node under .solus.`
      )
    } catch (error: unknown) {
      if (isCurrent()) toast('warn', 'Import failed', errorText(error))
    }
  }

  const submit = async (
    { section, subsection, kind, entry }: Composer,
    text: string
  ): Promise<boolean> => {
    if (!projectId || !isCurrent()) return false
    try {
      if (kind === 'ask') await askSol(projectId, solus, section, text, isCurrent, subsection)
      else if (kind === 'edit' && entry) await updateSolusEntry(projectId, entry.id, text)
      else
        await addSolusEntry(projectId, section, withSubsection({ kind: 'text', text }, subsection))
      if (!(await refresh(kind !== 'ask'))) return false
      if (kind === 'type')
        toast('ok', `Added to .solus › ${targetLabel(section, subsection)}`, text.slice(0, 80))
      return true
    } catch (error: unknown) {
      if (isCurrent()) toast('warn', "That didn't work", errorText(error))
      return false
    }
  }

  const remove = async (entry: SolusEntry): Promise<boolean> => {
    if (!projectId || !isCurrent()) return false
    try {
      await deleteSolusEntry(projectId, entry.id)
      if (!(await refresh(true, entry.entity_id ?? undefined))) return false
      return true
    } catch (error: unknown) {
      if (isCurrent()) toast('warn', "Couldn't remove that entry", errorText(error))
      return false
    }
  }

  return { importFile, submit, remove }
}

/** The three actions every writable section (and subsection) offers — identical everywhere
 *  by design; `history` and `members` own no hand-written rows and get none. */
export function sectionMenuItems(
  section: SolusSection,
  streaming: boolean,
  onImport: (section: SolusSection, subsection?: string | null) => void,
  onCompose: (composer: Composer) => void,
  subsection?: string | null
): ContextMenuItem[] {
  if (!isWritableSection(section)) return []
  const target = withSubsection({ section }, subsection)
  return [
    { label: 'Import files…', onSelect: () => onImport(section, subsection) },
    {
      label: 'Ask SOL to find…',
      onSelect: () => onCompose({ ...target, kind: 'ask' }),
      disabled: streaming,
      hint: 'SOL is busy with another turn'
    },
    { label: 'Type it', onSelect: () => onCompose({ ...target, kind: 'type' }) }
  ]
}

export function entryMenuItems(
  entry: SolusEntry,
  onCompose: (composer: Composer) => void,
  onDelete: (entry: SolusEntry) => void
): ContextMenuItem[] {
  // Files have no text; config entries are written by their own routes (PATCH → 409).
  const edit: ContextMenuItem[] =
    entry.kind === 'artifact' || entry.kind === 'config'
      ? []
      : [
          {
            label: 'Edit',
            onSelect: () => onCompose({ section: entry.section, kind: 'edit', entry })
          }
        ]
  return [...edit, { label: 'Delete', danger: true, onSelect: () => onDelete(entry) }]
}
