// SOLUSDEV-317 §11.3 "Wake": when polling sees a new prompt_seq on an
// interactive process a conversation in this renderer started, continue SOL in
// that conversation with `process_prompt` (no user bubble). At most once per
// (process_id, prompt_seq). A busy project (a turn is streaming) leaves the
// prompt un-woken, so the next poll — 1 s while anything waits — retries it.
import type { CodeProcess } from '../../lib/api/resources.commands'
import { hasWoken, markWoken, processOwner } from './processOwners'
import type { SolActionMode } from './solApi'

/** What a wake attempt did: ran, must wait for the live turn, or targets a
 *  conversation that is not the one open in the project's session. */
export type WakeStart = 'started' | 'busy' | 'elsewhere'

export type WakeStarter = (
  projectId: string,
  conversationId: string,
  prompt: { readonly processId: string; readonly promptSeq: number },
  actionMode: SolActionMode
) => WakeStart

function isAsking(process: CodeProcess): boolean {
  return (
    process.interactive &&
    process.awaiting_input &&
    process.state === 'running' &&
    process.prompt_seq > 0 &&
    !hasWoken(process.process_id, process.prompt_seq)
  )
}

export function wakeWaitingProcesses(
  projectId: string,
  processes: readonly CodeProcess[],
  actionMode: SolActionMode,
  start: WakeStarter
): void {
  for (const process of processes) {
    const owner = isAsking(process) ? processOwner(process.process_id) : null
    if (owner === null || owner.projectId !== projectId) continue
    const prompt = { processId: process.process_id, promptSeq: process.prompt_seq }
    const result = start(projectId, owner.conversationId, prompt, actionMode)
    if (result === 'elsewhere') continue
    if (result === 'started') markWoken(prompt.processId, prompt.promptSeq)
    return
  }
}
