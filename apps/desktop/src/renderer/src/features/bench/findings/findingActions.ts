// SOLUSDEV-321 P2-T7 — the six actions a finding card offers, each on exactly one route:
// Explain more / Propose a fix → the SOL message API anchored on the finding (`finding_id`);
// Open the tool → the local-folder launch of the code site; File → one `.solus` errors entry;
// Dismiss / Resolve → the finding routes (resolve files the one errors entry server-side).
import { dismissFinding, resolveFinding, type Finding } from '../../../lib/api/findings'
import { addSolusEntry, type SolusEntry } from '../../../lib/api/resources'
import {
  openLocalFolderEntity,
  type OpenLocalFolderResult
} from '../../../lib/api/resources.localfolder'
import { getDesktopSolBridge } from '../../../lib/desktopBridge'
import type { SolActionMode } from '../../sol/solApi'
import { selectSession, sendMessage, useSolChatStore } from '../../sol/solChatStore'

/** Solus-authored turn text. The finding reaches SOL through the `finding_id` anchor, fenced as
 *  data; its headline is untrusted text and is never typed into the person's message. */
export const EXPLAIN_FINDING_PROMPT =
  'Explain this finding in more detail: what was measured, what it means, and what to check first.'
export const FIX_FINDING_PROMPT = 'Propose a fix for this finding.'

export interface CodeSite {
  entity_id: string
  source_id: string
  path: string | null
  line: number | null
}

const UUID = /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i
const isId = (value: unknown): value is string => typeof value === 'string' && UUID.test(value)

/** `evidence.code_site` when it names the code entity and that entity's own source (the launch
 *  route needs both); null otherwise. Path and line are display text only. */
export function findingCodeSite(finding: Finding): CodeSite | null {
  const site = finding.evidence.code_site
  if (typeof site !== 'object' || site === null) return null
  const { entity_id, source_id, path, line } = site as Record<string, unknown>
  if (!isId(entity_id) || !isId(source_id)) return null
  return {
    entity_id,
    source_id,
    path: typeof path === 'string' ? path : null,
    line: Number.isSafeInteger(line) ? (line as number) : null
  }
}

/** Opens the SOL window and sends the turn there; false when SOL could not take it now. */
async function askSol(
  projectId: string,
  finding: Finding,
  content: string,
  actionMode: SolActionMode
): Promise<boolean> {
  getDesktopSolBridge()?.open()
  const { forceConfirmation } = selectSession(useSolChatStore.getState(), projectId)
  return sendMessage(projectId, content, actionMode, [], false, undefined, {
    findingId: finding.id,
    forceConfirmation: forceConfirmation === true
  })
}

export function explainFinding(projectId: string, finding: Finding): Promise<boolean> {
  return askSol(projectId, finding, EXPLAIN_FINDING_PROMPT, 'guide')
}

export function proposeFindingFix(projectId: string, finding: Finding): Promise<boolean> {
  return askSol(projectId, finding, FIX_FINDING_PROMPT, 'do')
}

/** ponytail: `system` is the one target the route always offers (the OS default app); offer
 *  the editor from `getLocalFolder`'s `open_targets` when people ask for it. */
export function openFindingCodeSite(
  projectId: string,
  site: CodeSite
): Promise<OpenLocalFolderResult> {
  return openLocalFolderEntity(projectId, site.source_id, {
    entity_id: site.entity_id,
    tool: 'system'
  })
}

export function fileFinding(projectId: string, finding: Finding): Promise<SolusEntry> {
  return addSolusEntry(projectId, 'errors', {
    kind: 'text',
    text: `${finding.headline}\nfinding: ${finding.id}`
  })
}

export function dismissBenchFinding(projectId: string, finding: Finding): Promise<Finding> {
  return dismissFinding(projectId, finding.id)
}

export async function resolveBenchFinding(
  projectId: string,
  finding: Finding,
  note: string,
  fixRef?: string | null
): Promise<Finding> {
  const text = note.trim()
  if (!text) throw new Error('A note is required to resolve a finding.')
  return resolveFinding(
    projectId,
    finding.id,
    fixRef ? { note: text, fix_ref: fixRef } : { note: text }
  )
}
