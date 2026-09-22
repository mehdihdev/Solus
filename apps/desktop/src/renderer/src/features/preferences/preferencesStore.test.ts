// SOLUSDEV-244 / HOME H3: the renderer's view of ~/.solus/preferences.json —
// hydrated once from the main process, saved optimistically with revert, and
// attached to every SOL turn (only when non-empty).
import { emptyEngineeringPreferences, type EngineeringPreferences } from '@solus/shared-types'
import { act } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as bridge from '../../lib/desktopBridge'
import { useAuthStore } from '../../store/authStore'
import { preferencesForTurn, usePreferencesStore } from './preferencesStore'

vi.mock('../../lib/desktopBridge', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/desktopBridge')>()
  return { ...actual, getDesktopPreferencesBridge: vi.fn() }
})
const getBridge = vi.mocked(bridge.getDesktopPreferencesBridge)

const DOC: EngineeringPreferences = {
  ...emptyEngineeringPreferences(),
  electrical: 'Prefer 0.1 mm clearance minimum on all boards.'
}

function fakeBridge(
  doc: EngineeringPreferences = DOC,
  readOnly = false
): {
  read: ReturnType<typeof vi.fn>
  write: ReturnType<typeof vi.fn>
} {
  const read = vi.fn(async () => ({ preferences: doc, readOnly }))
  const write = vi.fn(async () => ({ ok: true }))
  getBridge.mockReturnValue({ read, write })
  return { read, write }
}

beforeEach(() => {
  vi.clearAllMocks()
  usePreferencesStore.getState().reset()
})

describe('preferencesStore', () => {
  registerPreferencesHydrationAndSaveTests()
  registerPreferencesPromptSanitizationTests()
})

describe('preferencesStore — identity (SEC review H1)', () => {
  it('drops the loaded document on sign-out and on an in-place identity swap', async () => {
    const b = fakeBridge()
    useAuthStore.setState({ status: 'authenticated', user: { email: 'a@example.dev' } as never })
    await act(async () => {
      await usePreferencesStore.getState().load()
    })
    expect(usePreferencesStore.getState().status).toBe('ready')
    useAuthStore.setState({ status: 'unauthenticated', user: null })
    expect(usePreferencesStore.getState().status).toBe('idle')
    expect(usePreferencesStore.getState().preferences.electrical).toBe('')

    useAuthStore.setState({ status: 'authenticated', user: { email: 'b@example.dev' } as never })
    await act(async () => {
      await usePreferencesStore.getState().load()
    })
    expect(b.read).toHaveBeenCalledTimes(2)
    useAuthStore.setState({ status: 'authenticated', user: { email: 'c@example.dev' } as never })
    expect(usePreferencesStore.getState().status).toBe('idle')
    // The next turn re-reads from disk under the new identity, never the store.
    await preferencesForTurn()
    expect(b.read).toHaveBeenCalledTimes(3)
  })

  it('dedupes concurrent loads before the first settles', async () => {
    const b = fakeBridge()
    await act(async () => {
      await Promise.all([
        usePreferencesStore.getState().load(),
        usePreferencesStore.getState().load()
      ])
    })
    expect(b.read).toHaveBeenCalledTimes(1)
  })
})

function registerPreferencesHydrationAndSaveTests(): void {
  it('starts idle and hydrates from the main process once', async () => {
    const b = fakeBridge()
    expect(usePreferencesStore.getState().status).toBe('idle')
    await act(async () => {
      await usePreferencesStore.getState().load()
      await usePreferencesStore.getState().load()
    })
    expect(b.read).toHaveBeenCalledTimes(1)
    const s = usePreferencesStore.getState()
    expect(s.status).toBe('ready')
    expect(s.preferences.electrical).toBe(DOC.electrical)
    expect(s.readOnly).toBe(false)
  })

  it('is unavailable outside Electron (no bridge) — never throws', async () => {
    getBridge.mockReturnValue(null)
    await act(async () => {
      await usePreferencesStore.getState().load()
    })
    expect(usePreferencesStore.getState().status).toBe('unavailable')
    expect(await preferencesForTurn()).toBeNull()
  })

  it('reports a file written by a newer app as read-only and refuses to save', async () => {
    const b = fakeBridge(DOC, true)
    await act(async () => {
      await usePreferencesStore.getState().load()
    })
    expect(usePreferencesStore.getState().readOnly).toBe(true)
    const ok = await usePreferencesStore.getState().save({ ...DOC, mechanical: 'x' })
    expect(ok).toBe(false)
    expect(b.write).not.toHaveBeenCalled()
  })

  it('saves optimistically through the bridge and reverts when the write fails', async () => {
    const b = fakeBridge()
    await act(async () => {
      await usePreferencesStore.getState().load()
    })
    const next = { ...DOC, mechanical: 'Metric fasteners only.' }
    let ok = false
    await act(async () => {
      ok = await usePreferencesStore.getState().save(next)
    })
    expect(ok).toBe(true)
    expect(b.write).toHaveBeenCalledWith(expect.objectContaining({ mechanical: next.mechanical }))
    expect(usePreferencesStore.getState().preferences.mechanical).toBe(next.mechanical)

    b.write.mockResolvedValueOnce({ ok: false })
    await act(async () => {
      ok = await usePreferencesStore.getState().save({ ...next, mechanical: 'lost' })
    })
    expect(ok).toBe(false)
    expect(usePreferencesStore.getState().preferences.mechanical).toBe(next.mechanical)
  })
}

function registerPreferencesPromptSanitizationTests(): void {
  it('cleans what it saves: over-cap text is truncated, control characters dropped', async () => {
    const b = fakeBridge()
    await act(async () => {
      await usePreferencesStore.getState().load()
      await usePreferencesStore.getState().save({
        ...DOC,
        codeStyle: 'a\x00b',
        electrical: 'e'.repeat(900)
      })
    })
    const written = b.write.mock.calls[0]?.[0] as EngineeringPreferences
    expect(written.codeStyle).toBe('ab')
    expect(written.electrical).toHaveLength(800)
  })

  it('attaches the document to a turn only when something is written', async () => {
    fakeBridge(emptyEngineeringPreferences())
    expect(await preferencesForTurn()).toBeNull()
    usePreferencesStore.getState().reset()
    fakeBridge(DOC)
    const forTurn = await preferencesForTurn()
    expect(forTurn?.electrical).toBe(DOC.electrical)
  })
}
