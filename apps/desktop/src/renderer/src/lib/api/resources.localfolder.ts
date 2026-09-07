// SOLUSDEV-249 (INTEGRATIONS I2) — the local-folder routes' typed client
// (docs/api/local-folder.md §3). A folder linked on THIS machine becomes a
// `local` Source keyed by the companion's instance id; the path never leaves
// the machine — only `machine_id`, `machine_name` and the folder's basename
// travel. Opening a file in a tool goes through the API to the companion
// bridge, never from the renderer directly.
import { api, type ApiClient } from './client'
import type { Source } from './resources'

export type LocalOpenTool = 'kicad' | 'altium' | 'vscode' | 'system'

/** One project the scan recognised inside the folder (a live `local_*` entity). */
export interface DetectedProject {
  entity_id: string
  entity_key: string
  /** The scan's tool tag: kicad, altium, cad, arduino, python — or the root. */
  tool: string
  name: string
  /** Folder-relative; absolute paths never enter the graph. */
  path: string
  open_targets: LocalOpenTool[]
}

export interface LocalFolderBridge {
  /** The caller's live bridge session carries this source's machine id. */
  connected: boolean
  /** From the last scan; a missing tool is false, never assumed. */
  tools_installed: Record<string, boolean>
}

export interface LocalFolderView {
  source: Source | null
  bridge: LocalFolderBridge
  detected: DetectedProject[]
}

export interface LinkLocalFolderInput {
  machine_id: string
  machine_name: string
  folder_name: string
}

export interface OpenLocalFolderInput {
  entity_id: string
  tool: LocalOpenTool
}

/** The tool's own answer, verbatim — `launched: false` with a reason is a 200. */
export interface OpenLocalFolderResult {
  launched: boolean
  tool: LocalOpenTool
  reason: string | null
}

const seg = encodeURIComponent
const base = (projectId: string): string => `/projects/${seg(projectId)}/local-folder`

export const EMPTY_LOCAL_FOLDER_VIEW: LocalFolderView = {
  source: null,
  bridge: { connected: false, tools_installed: {} },
  detected: []
}

/** Link THIS machine's folder — creates or reuses the `(project, machine)` source. */
export function linkLocalFolder(
  projectId: string,
  input: LinkLocalFolderInput,
  client: ApiClient = api
): Promise<{ source: Source; job_id: string }> {
  return client.request<{ source: Source; job_id: string }>(base(projectId), {
    method: 'POST',
    body: input
  })
}

/** This machine's local source for the project. The route answers a bare
 *  `{source: null}` when none exists; that is widened to an empty view so
 *  callers never branch on absent fields. */
export async function getLocalFolder(
  projectId: string,
  machineId: string,
  client: ApiClient = api
): Promise<LocalFolderView> {
  const raw = await client.request<Partial<LocalFolderView> & { source: Source | null }>(
    `${base(projectId)}?machine_id=${seg(machineId)}`
  )
  return {
    source: raw.source,
    bridge: raw.bridge ?? EMPTY_LOCAL_FOLDER_VIEW.bridge,
    detected: raw.detected ?? []
  }
}

/** Launch a detected project in a tool on this machine, via the companion bridge. */
export function openLocalFolderEntity(
  projectId: string,
  sourceId: string,
  input: OpenLocalFolderInput,
  client: ApiClient = api
): Promise<OpenLocalFolderResult> {
  return client.request<OpenLocalFolderResult>(`${base(projectId)}/${seg(sourceId)}/open`, {
    method: 'POST',
    body: input
  })
}

/** The root node's key is `clone:` (docs/api/local-folder.md §5); the tool tag
 *  it carries in `detected` is not pinned by the doc, so the known root kinds
 *  are accepted too. */
const ROOT_KEY = 'clone:'
const ROOT_TOOLS: ReadonlySet<string> = new Set(['clone', 'root', 'local_clone', 'local_folder'])

export function isRootProject(project: Pick<DetectedProject, 'entity_key' | 'tool'>): boolean {
  return project.entity_key === ROOT_KEY || ROOT_TOOLS.has(project.tool)
}
