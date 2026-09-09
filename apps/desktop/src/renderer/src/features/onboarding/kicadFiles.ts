// Pure KiCad file handling for the connect wizard's file step (SOLUSDEV-252).
// The user may pick a netlist export (XML or S-expression) and/or a
// .kicad_pcb board in one go. Each file is classified by CONTENT — extensions
// are never trusted — and routed to its config key (`export` / `board`).
// Schematics and project files get their guidance here, instantly, instead of
// after a failed sync. No React, no I/O.

export type KicadFileKind =
  | 'xml-netlist'
  | 'sexpr-netlist'
  | 'board'
  | 'schematic'
  | 'project'
  | 'unknown'

/** One user-picked file, already read into memory. */
export interface EdaExportFile {
  fileName: string
  content: string
}

/** The routed inputs a committed-export connect sends: either key alone is
 * enough; both together is best. Absent keys are OMITTED, never null. */
export interface EdaExportFiles {
  netlist?: EdaExportFile
  board?: EdaExportFile
}

export type ExportAssembly = { ok: true; inputs: EdaExportFiles } | { ok: false; error: string }

export const SCHEMATIC_UNSUPPORTED_ERROR =
  "Solus can't read a .kicad_sch schematic directly yet. Export a netlist from KiCad " +
  '(File → Export → Netlist, any format) or add your .kicad_pcb board file.'
export const PROJECT_UNSUPPORTED_ERROR =
  'A .kicad_pro file holds project settings, not the design. Export a netlist from KiCad ' +
  'or add your .kicad_pcb board file.'
export const MULTIPLE_NETLISTS_ERROR = 'Choose one netlist export (XML or S-expression).'
export const MULTIPLE_BOARDS_ERROR = 'Choose one .kicad_pcb board file.'
export const UNRECOGNIZED_FILE_ERROR =
  "That doesn't look like a KiCad netlist or board file. Choose a netlist export " +
  '(.xml or .net) or a .kicad_pcb.'
export const NO_FILES_ERROR = 'Choose a netlist export or a .kicad_pcb board file.'
export const KICAD_TOO_MANY_FILES_ERROR =
  'Choose at most one netlist export and one .kicad_pcb board file.'
export const TOO_MANY_FILES_ERROR = 'Choose one export file.'

const KICAD_PROVIDER = 'kicad'
const NETLIST_ACCEPT = '.xml,.net'
const KICAD_ACCEPT = '.xml,.net,.kicad_pcb'
/** One netlist + one board at most; every other provider takes one file. */
const KICAD_MAX_FILES = 2
const DEFAULT_MAX_FILES = 1
/** Mirrors the API sniffer (kicad_formats._HEAD_ATOM): the root atom is
 * matched on a boundary and compared EXACTLY, so `(exportfoo` is unknown to
 * both sides and `( export` is a netlist to both. */
const HEAD_ATOM = /^\(\s*([A-Za-z_]+)/
const SEXPR_ROOTS: Readonly<Record<string, KicadFileKind>> = {
  export: 'sexpr-netlist',
  kicad_pcb: 'board',
  kicad_sch: 'schematic'
}
/** How far into a JSON file the project marker is looked for. */
const PROJECT_SNIFF_CHARS = 4096
const PROJECT_MARKERS = ['"kicad_pro"', '"meta"'] as const

/** Sniff a file's kind from its leading bytes (BOM and whitespace ignored). */
export function classifyKicadFile(content: string): KicadFileKind {
  const head = content.replace(/^\uFEFF/, '').trimStart()
  if (head.startsWith('(')) {
    const atom = HEAD_ATOM.exec(head)?.[1]
    return (atom && SEXPR_ROOTS[atom]) || 'unknown'
  }
  if (head.startsWith('<')) return 'xml-netlist'
  if (head.startsWith('{')) {
    const window = head.slice(0, PROJECT_SNIFF_CHARS)
    return PROJECT_MARKERS.some((marker) => window.includes(marker)) ? 'project' : 'unknown'
  }
  return 'unknown'
}

const isNetlist = (kind: KicadFileKind): boolean =>
  kind === 'xml-netlist' || kind === 'sexpr-netlist'

/** Route a KiCad pick to `{ netlist?, board? }`, or explain why it can't be.
 * Checks run in priority order: schematic, project, duplicate netlists,
 * duplicate boards, unrecognised content, nothing picked. */
export function assembleKicadInputs(files: readonly EdaExportFile[]): ExportAssembly {
  const kinds = files.map((file) => classifyKicadFile(file.content))
  const ofKind = (match: (kind: KicadFileKind) => boolean): EdaExportFile[] =>
    files.filter((_, i) => match(kinds[i]))

  if (kinds.includes('schematic')) return { ok: false, error: SCHEMATIC_UNSUPPORTED_ERROR }
  if (kinds.includes('project')) return { ok: false, error: PROJECT_UNSUPPORTED_ERROR }
  const netlists = ofKind(isNetlist)
  if (netlists.length > 1) return { ok: false, error: MULTIPLE_NETLISTS_ERROR }
  const boards = ofKind((kind) => kind === 'board')
  if (boards.length > 1) return { ok: false, error: MULTIPLE_BOARDS_ERROR }
  if (kinds.includes('unknown')) return { ok: false, error: UNRECOGNIZED_FILE_ERROR }
  if (files.length === 0) return { ok: false, error: NO_FILES_ERROR }

  return {
    ok: true,
    inputs: {
      ...(netlists[0] ? { netlist: netlists[0] } : {}),
      ...(boards[0] ? { board: boards[0] } : {})
    }
  }
}

/** Provider dispatch: KiCad sniffs and routes; every other committed-export
 * connector takes exactly one file as the netlist, unsniffed. */
export function assembleExportInputs(
  providerId: string,
  files: readonly EdaExportFile[]
): ExportAssembly {
  if (providerId === KICAD_PROVIDER) return assembleKicadInputs(files)
  if (files.length === 0) return { ok: false, error: NO_FILES_ERROR }
  if (files.length > 1) return { ok: false, error: MULTIPLE_NETLISTS_ERROR }
  return { ok: true, inputs: { netlist: files[0] } }
}

/** The hidden file input's `accept` for a committed-export provider. */
export function exportFileAccept(providerId: string): string {
  return providerId === KICAD_PROVIDER ? KICAD_ACCEPT : NETLIST_ACCEPT
}

/** Whether the provider's file step takes several files in one pick. */
export function allowsMultipleFiles(providerId: string): boolean {
  return providerId === KICAD_PROVIDER
}

/** The most files one pick may hold — checked BEFORE any file is read, so a
 * folder-sized selection never lands in renderer memory. */
export function maxPickedFiles(providerId: string): number {
  return providerId === KICAD_PROVIDER ? KICAD_MAX_FILES : DEFAULT_MAX_FILES
}

/** The refusal for a pick over `maxPickedFiles`. */
export function tooManyFilesError(providerId: string): string {
  return providerId === KICAD_PROVIDER ? KICAD_TOO_MANY_FILES_ERROR : TOO_MANY_FILES_ERROR
}

export interface ExportFilePrompt {
  /** The pick button's label. */
  button: string
  /** The hidden input's accessible name. */
  ariaLabel: string
  /** A one-line muted hint under the button, or null. */
  hint: string | null
}

/** The file step's copy for a committed-export provider. */
export function exportFilePrompt(providerId: string): ExportFilePrompt {
  if (providerId === KICAD_PROVIDER) {
    return {
      button: 'Choose netlist / board file',
      ariaLabel: 'Choose a netlist export or board file',
      hint:
        'Netlist export (.xml or .net — any KiCad format) and/or your .kicad_pcb. ' +
        "Schematics (.kicad_sch) can't be read directly yet."
    }
  }
  return {
    button: 'Choose export file',
    ariaLabel: 'Choose a committed netlist export',
    hint: null
  }
}
