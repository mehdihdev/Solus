// SOLUSDEV-317: tracks approved commands' output on the chat items that hold
// them (sol-page.md "Output stays"). Store-agnostic — solChatStore hands in an
// immutable items patcher — so the store module stays focused on turns.
import { getConfirmationOutput } from '../../lib/api/resources.commands'
import { newCommandRun, startRunPoller, type CommandRun, type RunPoller } from './commandRuns'

interface RunItem {
  readonly confirmations: readonly { readonly confirmationId: string }[]
  readonly commandRuns?: readonly CommandRun[]
}

export interface RunTracker {
  /** Start polling an approved command's output while its approve is pending. */
  begin: (projectId: string, confirmationId: string, tool: string) => void
  /** The approve settled: stamp the status (null drops the run) and read the
   *  remaining output once. */
  end: (projectId: string, confirmationId: string, status: string | null) => void
  /** Teardown (sign-out): stop every poller without another read. */
  stopAll: () => void
}

/** Replace, add (`run`) or drop (`null`) one confirmation's run on its item. */
function withRun<T extends RunItem>(
  items: readonly T[],
  confirmationId: string,
  update: (run: CommandRun | undefined) => CommandRun | null
): readonly T[] {
  return items.map((m) => {
    const runs = m.commandRuns ?? []
    const current = runs.find((r) => r.confirmationId === confirmationId)
    const holds = current || m.confirmations.some((c) => c.confirmationId === confirmationId)
    if (!holds) return m
    const next = update(current)
    const others = runs.filter((r) => r.confirmationId !== confirmationId)
    return { ...m, commandRuns: next ? [...others, next] : others }
  })
}

export function createRunTracker(
  patchItems: (
    projectId: string,
    fn: <T extends RunItem>(items: readonly T[]) => readonly T[]
  ) => void,
  fetchOutput = getConfirmationOutput
): RunTracker {
  const pollers = new Map<string, RunPoller>()
  // The decided status, so a final output read landing after it keeps it.
  const finalStatus = new Map<string, string>()
  let generation = 0

  const set = (projectId: string, confirmationId: string, run: CommandRun | null): void =>
    patchItems(projectId, (items) => withRun(items, confirmationId, () => run))

  return {
    begin(projectId, confirmationId, tool) {
      const key = `${projectId}:${confirmationId}`
      pollers.get(key)?.stop()
      const initial = newCommandRun(confirmationId, tool)
      set(projectId, confirmationId, initial)
      const mine = generation
      const poller = startRunPoller(
        initial,
        (cursor) => fetchOutput(projectId, confirmationId, cursor),
        (run) => {
          if (mine !== generation) return
          set(projectId, confirmationId, { ...run, status: finalStatus.get(key) ?? null })
        }
      )
      pollers.set(key, poller)
    },
    end(projectId, confirmationId, status) {
      const key = `${projectId}:${confirmationId}`
      const poller = pollers.get(key)
      pollers.delete(key)
      if (status === null) {
        poller?.stop()
        set(projectId, confirmationId, null)
        return
      }
      finalStatus.set(key, status)
      patchItems(projectId, (items) =>
        withRun(items, confirmationId, (run) => (run ? { ...run, status } : null))
      )
      void poller?.finish().finally(() => finalStatus.delete(key))
    },
    stopAll() {
      generation += 1
      for (const poller of pollers.values()) poller.stop()
      pollers.clear()
      finalStatus.clear()
    }
  }
}

/** A refused approve keeps its output with the reason; a transport failure
 *  drops it — the card says the action is still waiting. */
export function refusalStatus(error: unknown): string | null {
  if (error instanceof Error && error.name === 'ConfirmationRefused') {
    return `refused: ${error.message.slice(0, 200)}`
  }
  return null
}
