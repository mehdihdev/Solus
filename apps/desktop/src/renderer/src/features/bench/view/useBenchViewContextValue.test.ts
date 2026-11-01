import { renderHook, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { EMPTY_BENCH_VIEW } from '@solus/shared-types'
import { getBenchView } from '../../../lib/api/resources.benchView'
import type { BenchDeviceRecent } from '../../../lib/api/resources'
import { useMe } from '../../workspace/useMe'
import { resetBenchViewStore } from './useBenchView'
import { useBenchViewContextValue } from './useBenchViewContextValue'

vi.mock('../../../lib/api/resources.benchView', async (importActual) => ({
  ...(await importActual<typeof import('../../../lib/api/resources.benchView')>()),
  getBenchView: vi.fn()
}))
vi.mock('./useBenchViewEvents', () => ({ useBenchViewEvents: vi.fn() }))
vi.mock('../../workspace/useMe', () => ({ useMe: vi.fn() }))

const device: BenchDeviceRecent = { device_id: 'usb:1/3', resolved_entity_id: null, signals: [] }
const meWith = (role: string): ReturnType<typeof useMe> => ({
  status: 'ready',
  name: null,
  email: 'u@example.test',
  me: {
    id: 'u',
    email: 'u@example.test',
    name: null,
    avatar_url: null,
    created_at: '',
    teams: [
      { team_id: 't1', name: 'T', role, is_personal: false, plan_status: '', trial_ends_at: '' }
    ]
  }
})

beforeEach(() => {
  resetBenchViewStore()
  vi.mocked(getBenchView).mockResolvedValue({ ...EMPTY_BENCH_VIEW, version: 2 })
})

it('loads the view, indexes devices and gates writes by team role', async () => {
  vi.mocked(useMe).mockReturnValue(meWith('member'))
  const { result } = renderHook(() => useBenchViewContextValue('p1', 't1', [device], 1))
  await waitFor(() => expect(result.current?.view?.version).toBe(2))
  expect(result.current).toMatchObject({ projectId: 'p1', canEdit: true })
  expect(result.current?.devices['usb:1/3']).toBe(device)
})

it('is read-only for a viewer and null without a project', () => {
  vi.mocked(useMe).mockReturnValue(meWith('viewer'))
  expect(
    renderHook(() => useBenchViewContextValue('p1', 't1', [], 0)).result.current?.canEdit
  ).toBe(false)
  expect(renderHook(() => useBenchViewContextValue(null, null, [], 0)).result.current).toBeNull()
})
