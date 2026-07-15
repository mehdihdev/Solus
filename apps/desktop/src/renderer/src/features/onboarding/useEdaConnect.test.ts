// The hook is thin glue: it binds the app API singleton + onboarding store to
// runEdaConnect. We verify the binding, not the orchestration (edaConnect.test.ts).
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook } from '@testing-library/react'
import * as edaConnect from './edaConnect'
import { useEdaConnect } from './useEdaConnect'
import { useOnboardingStore } from './onboardingStore'

vi.mock('./edaConnect', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./edaConnect')>()
  return { ...actual, runEdaConnect: vi.fn() }
})

const mockedRun = vi.mocked(edaConnect.runEdaConnect)

describe('useEdaConnect', () => {
  beforeEach(() => {
    useOnboardingStore.getState().reset()
    vi.clearAllMocks()
    mockedRun.mockResolvedValue({ ok: true })
  })

  it('starts the orchestration with the project, provider, and file', async () => {
    const { result } = renderHook(() => useEdaConnect())
    const file = { fileName: 'power.xml', content: '<export/>' }

    await result.current.start('p1', 'kicad', file)

    expect(mockedRun).toHaveBeenCalledTimes(1)
    const [, projectId, provider, passedFile] = mockedRun.mock.calls[0]
    expect(projectId).toBe('p1')
    expect(provider).toBe('kicad')
    expect(passedFile).toEqual(file)
  })

  it('routes progress into the onboarding store under the provider id', async () => {
    mockedRun.mockImplementation(async (deps) => {
      deps.onProgress({ phase: 'done', result: 'Connected — 6 entities indexed' })
      return { ok: true }
    })
    const { result } = renderHook(() => useEdaConnect())

    await result.current.start('p1', 'kicad', { fileName: 'x.xml', content: '<export/>' })

    const state = useOnboardingStore.getState().connections.kicad
    expect(state?.phase).toBe('done')
  })
})
