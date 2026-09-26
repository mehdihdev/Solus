// SOLUSDEV-246 (STORE ST5) — the sourcing hook: derive torque, submit a request
// and poll it, select a candidate, read and save rules. Honest failures, never
// a thrown promise reaching the UI.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import * as api from '../../lib/api/resources.sourcing'
import { ApiError } from '../../lib/api/envelope.types'
import { useSourcing } from './useSourcing'
import { request, rules, torque } from './testing/fixtures'
import { preferencesForTurn } from '../preferences/preferencesStore'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceStore } from '../../store/workspaceStore'

vi.mock('../../lib/api/resources.sourcing', async (importOriginal) => ({
  ...(await importOriginal<typeof api>()),
  getSourcingRules: vi.fn(),
  putSourcingRules: vi.fn(),
  deriveTorque: vi.fn(),
  createSourcingRequest: vi.fn(),
  getSourcingRequest: vi.fn(),
  selectSourcingCandidate: vi.fn()
}))
vi.mock('../preferences/preferencesStore', () => ({
  preferencesForTurn: vi.fn(async () => ({ mechanical: 'metric only' }))
}))

beforeEach(() => {
  vi.clearAllMocks()
  useAuthStore.setState({ user: { email: 'a@example.test' } })
  useWorkspaceStore.setState({ project: { id: 'p1', name: 'A' } })
  vi.mocked(api.getSourcingRules).mockResolvedValue(rules())
})

it.each(['account', 'project', 'unmount'])(
  'does not submit credits after %s expires preference loading',
  async (boundary) => {
    let finish!: (value: null) => void
    vi.mocked(preferencesForTurn).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve
        })
    )
    const view = renderHook(() => useSourcing('p1'))
    let pending!: Promise<void>
    act(() => {
      pending = view.result.current.actions.submit({
        door: 'workspace',
        spec: { text: 'private design' }
      })
    })
    act(() => {
      if (boundary === 'unmount') view.unmount()
      else if (boundary === 'account') {
        useAuthStore.setState({ user: { email: 'b@example.test' } })
        useAuthStore.setState({ user: { email: 'a@example.test' } })
      } else {
        useWorkspaceStore.setState({ project: { id: 'p2', name: 'B' } })
        useWorkspaceStore.setState({ project: { id: 'p1', name: 'A' } })
      }
    })
    await act(async () => {
      finish(null)
      await pending
    })
    expect(api.createSourcingRequest).not.toHaveBeenCalled()
  }
)

it('rejects a submitted request completion after an account round trip', async () => {
  let finish!: (value: Awaited<ReturnType<typeof api.createSourcingRequest>>) => void
  vi.mocked(api.createSourcingRequest).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve
      })
  )
  const { result } = renderHook(() => useSourcing('p1'))
  let pending!: Promise<void>
  await act(async () => {
    pending = result.current.actions.submit({ door: 'bom', spec: { text: 'private design' } })
    await Promise.resolve()
  })
  act(() => {
    useAuthStore.setState({ user: { email: 'b@example.test' } })
    useAuthStore.setState({ user: { email: 'a@example.test' } })
  })
  await act(async () => {
    finish({ request: request(), job_id: 'job-1' })
    await pending
  })
  expect(result.current.request).toBeNull()
  expect(result.current.phase).toBe('requirement')
})

it('clears candidates on a project prop change and rejects old selection completion', async () => {
  vi.mocked(api.createSourcingRequest).mockResolvedValue({ request: request(), job_id: 'job-1' })
  vi.mocked(api.getSourcingRequest).mockResolvedValue(request())
  const { result, rerender } = renderHook(({ project }) => useSourcing(project, { pollMs: 5 }), {
    initialProps: { project: 'p1' }
  })
  await act(() => result.current.actions.submit({ door: 'bom', spec: { text: 'motor' } }))
  await waitFor(() => expect(result.current.phase).toBe('candidates'))
  let finish!: (value: Awaited<ReturnType<typeof api.selectSourcingCandidate>>) => void
  vi.mocked(api.selectSourcingCandidate).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve
      })
  )
  let pending!: Promise<void>
  act(() => {
    pending = result.current.actions.select('aaaaaaaaaaaaaaaa')
  })
  rerender({ project: 'p2' })
  expect(result.current.request).toBeNull()
  await act(async () => {
    finish({
      request: request(),
      entity: {
        id: 'old-part',
        name: 'Old design',
        type: 'part',
        domain: 'mechanical',
        source_key: '',
        properties: {}
      }
    })
    await pending
  })
  expect(result.current.selected).toBeNull()
  expect(result.current.phase).toBe('requirement')
})

describe('useSourcing', () => {
  sourcingRequestLifecycleTests()
  sourcingRequestOutcomesTests()
})

function sourcingRequestLifecycleTests(): void {
  it('loads the rules and derives torque from an assembly', async () => {
    vi.mocked(api.deriveTorque).mockResolvedValue(torque())
    const { result } = renderHook(() => useSourcing('p1', { pollMs: 5 }))
    await waitFor(() => expect(result.current.rules).toEqual(rules()))
    await act(() => result.current.actions.derive({ assembly_entity_id: 'asm-1' }))
    expect(api.deriveTorque).toHaveBeenCalledWith('p1', { assembly_entity_id: 'asm-1' })
    expect(result.current.torque?.required_torque_nm).toBe(8.2373)
    expect(result.current.error).toBeNull()
  })

  it('submits a request with the preferences attached and polls it to a settled state', async () => {
    vi.mocked(api.createSourcingRequest).mockResolvedValue({
      request: request({ status: 'queued', candidates: [], excluded: [] }),
      job_id: 'job-1'
    })
    vi.mocked(api.getSourcingRequest)
      .mockResolvedValueOnce(request({ status: 'running', candidates: [], excluded: [] }))
      .mockResolvedValueOnce(request())
    const { result } = renderHook(() => useSourcing('p1', { pollMs: 5 }))
    await act(() =>
      result.current.actions.submit({
        door: 'workspace',
        spec: { text: 'actuator for the arm' },
        assembly_entity_id: 'asm-1'
      })
    )
    expect(api.createSourcingRequest).toHaveBeenCalledWith('p1', {
      door: 'workspace',
      spec: { text: 'actuator for the arm' },
      assembly_entity_id: 'asm-1',
      preferences: { mechanical: 'metric only' }
    })
    expect(result.current.phase).toBe('searching')
    await waitFor(() => expect(result.current.phase).toBe('candidates'))
    expect(result.current.request?.candidates).toHaveLength(2)
    expect(result.current.request?.excluded).toHaveLength(1)
  })
}

function sourcingRequestOutcomesTests(): void {
  it('surfaces a failed request with its typed error, and a refusal as a message', async () => {
    vi.mocked(api.createSourcingRequest).mockResolvedValue({
      request: request({ status: 'queued', candidates: [] }),
      job_id: 'job-1'
    })
    vi.mocked(api.getSourcingRequest).mockResolvedValue(
      request({
        status: 'failed',
        candidates: [],
        excluded: [],
        error: { code: 'insufficient_credits', message: 'Not enough credits to run sourcing.' }
      })
    )
    const { result } = renderHook(() => useSourcing('p1', { pollMs: 5 }))
    await act(() => result.current.actions.submit({ door: 'bom', spec: { text: 'a motor' } }))
    await waitFor(() => expect(result.current.phase).toBe('failed'))
    expect(result.current.error).toBe('Not enough credits to run sourcing.')

    vi.mocked(api.createSourcingRequest).mockRejectedValueOnce(
      new ApiError(403, 'forbidden', 'Only project members can source parts.')
    )
    await act(() => result.current.actions.submit({ door: 'bom', spec: { text: 'a motor' } }))
    expect(result.current.phase).toBe('requirement')
    expect(result.current.error).toBe('Only project members can source parts.')
  })

  it('selects a candidate and reports the planned part', async () => {
    vi.mocked(api.createSourcingRequest).mockResolvedValue({ request: request(), job_id: 'job-1' })
    vi.mocked(api.getSourcingRequest).mockResolvedValue(request())
    vi.mocked(api.selectSourcingCandidate).mockResolvedValue({
      entity: {
        id: 'e-planned',
        type: 'part',
        domain: 'mechanical',
        name: 'NEMA 23 23HS22-2804S',
        source_key: '',
        properties: { lifecycle: 'planned', vendor_cad_url: 'https://v.example/x.step' }
      },
      request: request({
        selected_candidate_id: 'aaaaaaaaaaaaaaaa',
        selected_entity_id: 'e-planned'
      })
    })
    const { result } = renderHook(() => useSourcing('p1', { pollMs: 5 }))
    await act(() => result.current.actions.submit({ door: 'workspace', spec: { text: 'x' } }))
    await waitFor(() => expect(result.current.phase).toBe('candidates'))
    await act(() =>
      result.current.actions.select('aaaaaaaaaaaaaaaa', {
        category_entity_id: 'cat-1',
        quantity: 2
      })
    )
    expect(api.selectSourcingCandidate).toHaveBeenCalledWith('p1', 'req-1', {
      candidate_id: 'aaaaaaaaaaaaaaaa',
      category_entity_id: 'cat-1',
      quantity: 2
    })
    expect(result.current.phase).toBe('selected')
    expect(result.current.selected?.id).toBe('e-planned')
  })

  it('saves rules and reports a refusal', async () => {
    vi.mocked(api.putSourcingRules).mockResolvedValueOnce(rules({ max_voltage_v: 36 }))
    const { result } = renderHook(() => useSourcing('p1', { pollMs: 5 }))
    await waitFor(() => expect(result.current.rules).not.toBeNull())
    expect(await act(() => result.current.actions.saveRules(rules({ max_voltage_v: 36 })))).toBe(
      true
    )
    expect(result.current.rules?.max_voltage_v).toBe(36)
    vi.mocked(api.putSourcingRules).mockRejectedValueOnce(new ApiError(403, 'forbidden', 'No.'))
    expect(await act(() => result.current.actions.saveRules(rules()))).toBe(false)
    expect(result.current.error).toBe('No.')
  })
}
