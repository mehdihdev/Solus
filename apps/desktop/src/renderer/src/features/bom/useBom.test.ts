// SOLUSDEV-246 / STORE ST4 — the BOM data hook over the typed client: honest
// states (loading / ready / not installed / offline), writes that re-read the
// view, and a CSV export that hands the bytes to the platform.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import * as bomApi from '../../lib/api/resources.bom'
import { ApiError } from '../../lib/api/envelope.types'
import { useBom, BOM_POLL_MS } from './useBom'
import { bomView, purchaseRow } from './testing/fixtures'

vi.mock('../../lib/useInterval', () => ({ useInterval: vi.fn() }))
vi.mock('../../lib/api/resources.bom', async (importOriginal) => ({
  ...(await importOriginal<typeof bomApi>()),
  getBomView: vi.fn(),
  createBomRow: vi.fn(),
  patchBomRow: vi.fn(),
  deleteBomRow: vi.fn(),
  fetchBomCsv: vi.fn()
}))
vi.mock('../workspace/workspaceOnline', () => ({ useWorkspaceFetchEnabled: () => true }))

beforeEach(() => {
  vi.clearAllMocks()
})

describe('useBom', () => {
  registerBomLoadingAndWritesTests()

  registerBomRefusalsAndExportTests()
})

function registerBomLoadingAndWritesTests(): void {
  it('loads the view and exposes it', async () => {
    vi.mocked(bomApi.getBomView).mockResolvedValue(bomView())
    const { result } = renderHook(() => useBom('p1'))
    expect(result.current.status).toBe('loading')
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.view?.rows.map((r) => r.name)).toEqual(['MG996R', 'NEMA 17 stepper'])
    expect(BOM_POLL_MS).toBeGreaterThan(0)
  })

  it('reports a 404 as not installed, anything else as offline', async () => {
    vi.mocked(bomApi.getBomView).mockRejectedValueOnce(new ApiError(404, 'not_found', 'gone'))
    const { result, unmount } = renderHook(() => useBom('p1'))
    await waitFor(() => expect(result.current.status).toBe('not_installed'))
    unmount()

    vi.mocked(bomApi.getBomView).mockRejectedValueOnce(new Error('network'))
    const again = renderHook(() => useBom('p1'))
    await waitFor(() => expect(again.result.current.status).toBe('offline'))
  })

  it('keeps the rows on screen through a failed refresh', async () => {
    vi.mocked(bomApi.getBomView).mockResolvedValueOnce(bomView())
    const { result } = renderHook(() => useBom('p1'))
    await waitFor(() => expect(result.current.status).toBe('ready'))
    vi.mocked(bomApi.getBomView).mockRejectedValueOnce(new Error('blip'))
    await act(() => result.current.actions.refresh())
    expect(result.current.status).toBe('ready')
    expect(result.current.view?.rows).toHaveLength(2)
  })

  it('adds, edits and removes rows, re-reading the view after each write', async () => {
    vi.mocked(bomApi.getBomView).mockResolvedValue(bomView())
    vi.mocked(bomApi.createBomRow).mockResolvedValue(purchaseRow())
    vi.mocked(bomApi.patchBomRow).mockResolvedValue(purchaseRow({ state: 'ordered' }))
    vi.mocked(bomApi.deleteBomRow).mockResolvedValue(undefined)
    const { result } = renderHook(() => useBom('p1'))
    await waitFor(() => expect(result.current.status).toBe('ready'))

    expect(
      await act(() =>
        result.current.actions.addRow({ name: 'NEMA 17 stepper', category: 'purchase' })
      )
    ).toEqual({ ok: true })
    expect(bomApi.createBomRow).toHaveBeenCalledWith('p1', {
      name: 'NEMA 17 stepper',
      category: 'purchase'
    })
    expect(await act(() => result.current.actions.setState(purchaseRow().key, 'ordered'))).toEqual({
      ok: true
    })
    expect(bomApi.patchBomRow).toHaveBeenCalledWith('p1', purchaseRow().key, {
      state: 'ordered'
    })
    expect(await act(() => result.current.actions.removeRow(purchaseRow().key))).toEqual({
      ok: true
    })
    expect(bomApi.getBomView).toHaveBeenCalledTimes(4)
  })
}

function registerBomRefusalsAndExportTests(): void {
  it('reports a refused write with the server message, never throws', async () => {
    vi.mocked(bomApi.getBomView).mockResolvedValue(bomView())
    vi.mocked(bomApi.patchBomRow).mockRejectedValue(
      new ApiError(403, 'forbidden', 'Only project members can change extensions here.')
    )
    const { result } = renderHook(() => useBom('p1'))
    await waitFor(() => expect(result.current.status).toBe('ready'))
    const outcome = await act(() => result.current.actions.setState('item:x', 'ordered'))
    expect(outcome).toEqual({
      ok: false,
      message: 'Only project members can change extensions here.'
    })
  })

  it('exports the CSV through the given saver', async () => {
    vi.mocked(bomApi.getBomView).mockResolvedValue(bomView())
    vi.mocked(bomApi.fetchBomCsv).mockResolvedValue('key,kind\r\n')
    const save = vi.fn()
    const { result } = renderHook(() => useBom('p1', { save }))
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(await act(() => result.current.actions.exportCsv('bom-rover.csv'))).toEqual({
      ok: true
    })
    expect(save).toHaveBeenCalledWith('bom-rover.csv', 'key,kind\r\n')
  })
}
