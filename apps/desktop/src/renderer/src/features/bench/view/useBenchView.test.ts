// SOLUSDEV-319 — the per-project shared bench view store (wireflow live-bench-view.md §1, §3, §4).
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { EMPTY_BENCH_VIEW, type BenchView, type SetDisplayOp } from '@solus/shared-types'
import { ApiError } from '../../../lib/api/envelope.types'
import { getBenchView, patchBenchView } from '../../../lib/api/resources.benchView'
import { resetBenchViewStore, useBenchViewStore } from './useBenchView'
import { displayFor } from './viewOps'

vi.mock('../../../lib/api/resources.benchView', async (importActual) => ({
  ...(await importActual<typeof import('../../../lib/api/resources.benchView')>()),
  getBenchView: vi.fn(),
  patchBenchView: vi.fn()
}))
const get = vi.mocked(getBenchView)
const patch = vi.mocked(patchBenchView)

const P = 'p1'
const v = (version: number, extra: Partial<BenchView> = {}): BenchView => ({
  ...EMPTY_BENCH_VIEW,
  version,
  ...extra
})
const target = { kind: 'signal' as const, device_id: 'usb:1/3', signal: 'a' }
const pin: SetDisplayOp = { kind: 'set_display', target, patch: { pinned: true } }
const conflict = (current: number): ApiError =>
  new ApiError(409, 'conflict', 'stale', [{ current_version: current }])
const store = (): ReturnType<typeof useBenchViewStore.getState> => useBenchViewStore.getState()

beforeEach(() => {
  resetBenchViewStore()
  get.mockReset()
  patch.mockReset()
})

describe('loading', () => {
  it('fetches the project view', async () => {
    get.mockResolvedValue(v(3))
    await store().load(P)
    expect(store().projects[P]).toMatchObject({ status: 'ready', view: { version: 3 } })
  })

  it('never regresses to an older version from a slow response', async () => {
    get.mockResolvedValueOnce(v(5))
    await store().load(P)
    get.mockResolvedValueOnce(v(4))
    await store().load(P)
    expect(store().projects[P]?.view?.version).toBe(5)
  })

  it('a hint with a newer version refetches; an older or equal one does not', async () => {
    get.mockResolvedValue(v(3))
    await store().load(P)
    get.mockClear()
    await store().noteHint(P, 3)
    expect(get).not.toHaveBeenCalled()
    get.mockResolvedValue(v(4))
    await store().noteHint(P, 4)
    expect(get).toHaveBeenCalledTimes(1)
    expect(store().projects[P]?.view?.version).toBe(4)
  })

  it('ready refetches unconditionally', async () => {
    get.mockResolvedValue(v(3))
    await store().load(P)
    get.mockClear()
    await store().noteReady(P)
    expect(get).toHaveBeenCalledTimes(1)
  })

  it('a failed first load reads as error, keeping nothing stale', async () => {
    get.mockRejectedValue(new TypeError('offline'))
    await store().load(P)
    expect(store().projects[P]).toMatchObject({ status: 'error', view: null })
  })
})

describe('display writes', () => {
  beforeEach(async () => {
    get.mockResolvedValue(v(3))
    await store().load(P)
  })

  it('applies optimistically, then adopts the server version and records Undo', async () => {
    let resolve: (value: Awaited<ReturnType<typeof patchBenchView>>) => void = () => undefined
    patch.mockReturnValue(new Promise((r) => (resolve = r)))
    const pending = store().setDisplay(P, [pin])
    expect(displayFor(store().projects[P]!.view, target).pinned).toBe(true)
    expect(patch).toHaveBeenCalledWith(P, { version: 3, ops: [pin] })
    const inverse = [{ ...pin, patch: { pinned: null } }]
    resolve({
      version: 4,
      view: v(4, { display: [{ ...DEFAULTS, target, pinned: true }] }),
      inverse_ops: inverse
    })
    await expect(pending).resolves.toEqual({ ok: true, version: 4, inverseOps: inverse })
    expect(store().projects[P]?.view?.version).toBe(4)
    expect(store().projects[P]?.lastEdit).toMatchObject({ version: 4, inverseOps: inverse })
  })

  it('409 refetches and retries once with the same patch on the new version', async () => {
    patch.mockRejectedValueOnce(conflict(6))
    get.mockResolvedValue(v(6))
    patch.mockResolvedValueOnce({ version: 7, view: v(7), inverse_ops: [] })
    await expect(store().setDisplay(P, [pin])).resolves.toMatchObject({ ok: true, version: 7 })
    expect(patch).toHaveBeenNthCalledWith(2, P, { version: 6, ops: [pin] })
  })

  it('a second 409 reverts and tells the user to try again', async () => {
    patch.mockRejectedValue(conflict(6))
    get.mockResolvedValue(v(6))
    const outcome = await store().setDisplay(P, [pin])
    expect(outcome).toMatchObject({ ok: false, failure: { kind: 'conflict' } })
    expect(displayFor(store().projects[P]!.view, target).pinned).toBe(false)
    expect(store().projects[P]?.notice).toBe('Bench view changed — try again')
    expect(patch).toHaveBeenCalledTimes(2)
  })

  it('a refusal reverts with the server sentence', async () => {
    patch.mockRejectedValue(new ApiError(422, 'too_many_groups', 'At most 16 plot groups.'))
    const outcome = await store().setDisplay(P, [pin])
    expect(outcome).toMatchObject({ ok: false, failure: { kind: 'refused' } })
    expect(displayFor(store().projects[P]!.view, target).pinned).toBe(false)
    expect(store().projects[P]?.notice).toBe('At most 16 plot groups.')
  })
})

describe('derived writes and undo', () => {
  beforeEach(async () => {
    get.mockResolvedValue(v(3))
    await store().load(P)
  })

  it('a derived save never auto-retries on 409', async () => {
    patch.mockRejectedValue(conflict(9))
    const outcome = await store().saveDerived(P, [
      { kind: 'upsert_derived', name: 'n', expression: '1' }
    ])
    expect(outcome).toEqual({ ok: false, failure: { kind: 'conflict', currentVersion: 9 } })
    expect(patch).toHaveBeenCalledTimes(1)
  })

  it('a derived save can pin the version the draft was based on', async () => {
    patch.mockResolvedValue({ version: 4, view: v(4), inverse_ops: [] })
    await store().saveDerived(P, [{ kind: 'delete_derived', id: 'd1' }], 2)
    expect(patch).toHaveBeenCalledWith(P, {
      version: 2,
      ops: [{ kind: 'delete_derived', id: 'd1' }]
    })
  })

  it('undo sends the chip version, the inverse ops and undo=true', async () => {
    const inverse = [{ kind: 'delete_derived' as const, id: 'd1' }]
    patch.mockResolvedValue({ version: 5, view: v(5), inverse_ops: [] })
    await expect(store().undo(P, { version: 4, inverseOps: inverse })).resolves.toMatchObject({
      ok: true,
      version: 5
    })
    expect(patch).toHaveBeenCalledWith(P, { version: 4, ops: inverse, undo: true })
    expect(store().projects[P]?.lastEdit).toBeNull()
  })

  it('an undo that gets 409 is not retried and writes nothing', async () => {
    patch.mockRejectedValue(conflict(8))
    const outcome = await store().undo(P, { version: 4, inverseOps: [pin] })
    expect(outcome).toMatchObject({ ok: false, failure: { kind: 'conflict' } })
    expect(patch).toHaveBeenCalledTimes(1)
    expect(store().projects[P]?.view?.version).toBe(3)
  })
})

const DEFAULTS = {
  pinned: false,
  hidden: false,
  order: null,
  unit: null,
  limits: null,
  plot_group: null
}
