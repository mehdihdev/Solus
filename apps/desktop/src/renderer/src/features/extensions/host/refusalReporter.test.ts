// SOLUSDEV-235 / SEC-H4+M1 — `extension.bridge_refused` reaches the data
// collection route in batches, under a per-extension budget (20 / 60 s);
// anything past the budget is dropped and counted, never sent.
import { describe, it, expect, vi } from 'vitest'
import type { DataEventInput } from '../../../lib/api/resources.extensions'
import type { BridgeRefusal } from './bridgeDeps'
import { REFUSAL_BUDGET, createRefusalReporter, type RefusalReporter } from './refusalReporter'

const refusal = (over: Partial<BridgeRefusal> = {}): BridgeRefusal => ({
  extensionId: 'bom',
  version: '1.2.0',
  method: 'graph.delete',
  code: 'unknown_method',
  ...over
})

interface Harness {
  reporter: RefusalReporter
  posted: DataEventInput[][]
  post: ReturnType<typeof vi.fn>
  advance(ms: number): void
  fire(): void
}

function harness(projectId: string | null = 'p1'): Harness {
  let t = 0
  const posted: DataEventInput[][] = []
  const post = vi.fn(async (events: readonly DataEventInput[]) => {
    posted.push([...events])
  })
  const scheduled: (() => void)[] = []
  const reporter = createRefusalReporter({
    post,
    now: () => t,
    schedule: (fn) => {
      scheduled.push(fn)
    },
    projectId: () => projectId ?? undefined
  })
  return {
    reporter,
    posted,
    post,
    advance: (ms) => (t += ms),
    fire: () => scheduled.splice(0).forEach((fn) => fn())
  }
}

describe('createRefusalReporter', () => {
  it('batches refusals into one POST of §6.4-shaped events with the project id', async () => {
    const h = harness()
    h.reporter.emit(refusal())
    h.reporter.emit(refusal({ method: 'sol.ask', code: 'scope_denied' }))
    expect(h.post).not.toHaveBeenCalled()
    h.fire()
    await h.reporter.flush()
    expect(h.posted).toEqual([
      [
        {
          event_type: 'extension.bridge_refused',
          project_id: 'p1',
          payload: { slug: 'bom', version: '1.2.0', method: 'graph.delete', code: 'unknown_method' }
        },
        {
          event_type: 'extension.bridge_refused',
          project_id: 'p1',
          payload: { slug: 'bom', version: '1.2.0', method: 'sol.ask', code: 'scope_denied' }
        }
      ]
    ])
    expect(h.reporter.stats()).toEqual({ queued: 0, dropped: 0 })
  })

  it('emits at most the budget per extension per window and counts the rest as dropped', async () => {
    const h = harness()
    for (let i = 0; i < REFUSAL_BUDGET.maxEvents + 15; i++) h.reporter.emit(refusal())
    h.fire()
    await h.reporter.flush()
    expect(h.posted.flat()).toHaveLength(REFUSAL_BUDGET.maxEvents)
    expect(h.reporter.stats().dropped).toBe(15)
  })

  it('the budget is per extension and slides with the window', async () => {
    const h = harness()
    for (let i = 0; i < REFUSAL_BUDGET.maxEvents + 1; i++) h.reporter.emit(refusal())
    h.reporter.emit(refusal({ extensionId: 'lint' }))
    h.fire()
    await h.reporter.flush()
    expect(h.posted.flat().filter((e) => e.payload.slug === 'lint')).toHaveLength(1)
    expect(h.reporter.stats().dropped).toBe(1)
    h.advance(REFUSAL_BUDGET.windowMs + 1)
    h.reporter.emit(refusal())
    h.fire()
    await h.reporter.flush()
    expect(h.posted.flat().filter((e) => e.payload.slug === 'bom')).toHaveLength(
      REFUSAL_BUDGET.maxEvents + 1
    )
  })

  it('omits project_id when no project is open and swallows a failed POST', async () => {
    const h = harness(null)
    h.post.mockRejectedValueOnce(new Error('offline'))
    h.reporter.emit(refusal())
    h.fire()
    await expect(h.reporter.flush()).resolves.toBeUndefined()
    const [batch] = h.post.mock.calls[0] as [DataEventInput[]]
    expect(batch).toHaveLength(1)
    expect(batch[0]).not.toHaveProperty('project_id')
    expect(h.reporter.stats().dropped).toBe(1)
  })

  it('schedules exactly one flush per batch and posts nothing when empty', async () => {
    const schedule = vi.fn()
    const reporter = createRefusalReporter({ post: vi.fn(), now: () => 0, schedule })
    await reporter.flush()
    reporter.emit(refusal())
    reporter.emit(refusal())
    expect(schedule).toHaveBeenCalledTimes(1)
  })
})
