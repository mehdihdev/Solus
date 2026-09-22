// The LOCAL FOLDER card's pure words and decisions (SOLUSDEV-249 / I2). Free of
// React so the card, the graph inspector and the tests share one truth:
// which scan state to show, why an Open control is disabled, how a detected
// project is marked. Colours resolve to theme tokens only.
import type { Source } from '../../lib/api/resources'
import {
  isRootProject,
  type DetectedProject,
  type LocalFolderView,
  type LocalOpenTool
} from '../../lib/api/resources.localfolder'
import { relativeTime } from '../../lib/relativeTime'
import { sourceErrorText } from './sourcePresentation'

/** While a scan runs the source is `syncing`; the view is re-read this often. */
export const SYNCING_POLL_MS = 3_000
/** Otherwise the folder watcher drives re-syncs; a slow refresh keeps it honest. */
export const IDLE_POLL_MS = 30_000
/** Each detected row enters this much after the one before it. */
export const ROW_STAGGER_MS = 40

export const COMPANION_RECONNECTING_NOTE = 'Connecting to this machine’s companion…'
export const COMPANION_OFFLINE_NOTE = 'Solus companion is offline on this machine'
export const VSCODE_MISSING_NOTE = 'VS Code is not installed on this machine'
export const NOT_SCANNED_NOTE = 'Not scanned yet'
export const API_UNREACHABLE_NOTE = "Solus can't reach its API"
export const MACHINE_UNAVAILABLE_NOTE =
  'This machine has no companion id yet, so the folder is linked here but not to the graph.'
export const NOTHING_DETECTED_TEXT =
  'Nothing Solus recognises in this folder yet (KiCad, Altium, CAD, Arduino, Python).'
export const SCAN_FAILED_TEXT = 'Scan failed'

export const OPEN_LABEL: Readonly<Record<LocalOpenTool, string>> = {
  kicad: 'Open in KiCad',
  altium: 'Open in Altium',
  vscode: 'Open in editor',
  system: 'Open'
}

/** Graph kinds a local source lands (docs/api/local-folder.md §5). */
const LOCAL_ENTITY_KINDS: ReadonlySet<string> = new Set([
  'kicad_project',
  'altium_project',
  'cad_folder',
  'arduino_sketch',
  'python_code',
  'local_clone',
  'local_folder'
])

export function isLocalEntityKind(kind: string): boolean {
  return LOCAL_ENTITY_KINDS.has(kind)
}

interface ToolMark {
  mark: string
  color: string
}

const TOOL_MARKS: Readonly<Record<string, ToolMark>> = {
  kicad: { mark: 'Ki', color: 'var(--ee)' },
  altium: { mark: 'Al', color: 'var(--ee)' },
  cad: { mark: 'CA', color: 'var(--me)' },
  arduino: { mark: 'Ar', color: 'var(--sw)' },
  python: { mark: 'Py', color: 'var(--sw)' }
}

/** The two-letter square a detected row leads with, tinted by its domain. */
export function toolMark(tool: string): ToolMark {
  return TOOL_MARKS[tool] ?? { mark: tool.slice(0, 2).toUpperCase(), color: 'var(--mut)' }
}

/** The last path segment — what the API is told as `folder_name`. */
export function folderBasename(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).pop() ?? path
}

export type ScanStateKind = 'scanning' | 'scanned' | 'error'

export interface ScanState {
  kind: ScanStateKind
  text: string
}

/** What sits under the path: scanning, scanned <when>, or the error verbatim.
 *  Null when there is nothing honest to say (no source, not yet scanned). */
export function scanState(source: Source | null, now: number = Date.now()): ScanState | null {
  if (!source) return null
  if (source.status === 'syncing') return { kind: 'scanning', text: 'Scanning…' }
  if (source.status === 'error') {
    return { kind: 'error', text: sourceErrorText(source.last_error) ?? SCAN_FAILED_TEXT }
  }
  if (source.status === 'connected' && source.last_synced_at) {
    return { kind: 'scanned', text: `Scanned ${relativeTime(source.last_synced_at, now)}` }
  }
  return null
}

export function rootProject(view: LocalFolderView | null): DetectedProject | null {
  return view?.detected.find(isRootProject) ?? null
}

/** Every detected project except the root itself. */
export function detectedProjects(view: LocalFolderView | null): DetectedProject[] {
  return view?.detected.filter((project) => !isRootProject(project)) ?? []
}

export type LocalFolderStatus = 'idle' | 'loading' | 'ready' | 'offline'

/** Why "Open in editor" is disabled, or null when it can launch. Offline
 *  companion first: no tool opens without it, whatever is installed. */
export function editorDisabledReason(
  view: LocalFolderView | null,
  status: LocalFolderStatus
): string | null {
  if (status === 'loading') return COMPANION_RECONNECTING_NOTE
  if (!view || !view.source) return status === 'offline' ? API_UNREACHABLE_NOTE : NOT_SCANNED_NOTE
  if (!view.bridge.connected) return COMPANION_OFFLINE_NOTE
  if (view.bridge.tools_installed.vscode === false) return VSCODE_MISSING_NOTE
  const root = rootProject(view)
  if (!root) return NOT_SCANNED_NOTE
  return root.open_targets.includes('vscode') ? null : VSCODE_MISSING_NOTE
}

export interface LinkedFolderPresentation {
  /** Why the folder's own "Open in editor" is disabled, or null. */
  editorReason: string | null
  /** The root entity to open in the editor, when the scan has landed it. */
  rootEntityId: string | null
  /** The source exists but this machine's companion session is gone. */
  bridgeOffline: boolean
  /** Why every detected row's buttons are disabled, or null. */
  rowsReason: string | null
  /** A scan has finished, so an empty detected list can be called empty. */
  scanned: boolean
}

/** Every decision the linked-folder card draws from the view, in one place. */
export function linkedFolderPresentation(
  view: LocalFolderView | null,
  status: LocalFolderStatus
): LinkedFolderPresentation {
  const editorReason = editorDisabledReason(view, status)
  const source = view?.source ?? null
  const bridgeOffline =
    status !== 'loading' && source !== null && view !== null && !view.bridge.connected
  return {
    editorReason,
    rootEntityId: rootProject(view)?.entity_id ?? null,
    bridgeOffline,
    rowsReason: rowsDisabledReason(view, status),
    scanned: source?.status === 'connected' && source.last_synced_at !== null
  }
}

/** Why EVERY detected row's buttons are disabled, or null. Only reasons that
 *  apply to every tool belong here (no companion, no API, no scan yet) — a
 *  missing VS Code must not disable "Open in KiCad" on a machine that has
 *  KiCad: each row's own `open_targets` already says which tools it can open in. */
export function rowsDisabledReason(
  view: LocalFolderView | null,
  status: LocalFolderStatus
): string | null {
  if (status === 'loading') return COMPANION_RECONNECTING_NOTE
  if (!view || !view.source) return status === 'offline' ? API_UNREACHABLE_NOTE : NOT_SCANNED_NOTE
  if (!view.bridge.connected) return COMPANION_OFFLINE_NOTE
  return null
}
