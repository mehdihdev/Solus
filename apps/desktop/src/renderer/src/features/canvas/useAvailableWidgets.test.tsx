// SOLUSDEV-235 / EXT-15 — what the picker can offer and what the pruner may
// trust: built-ins from discovery, extension widgets from the install snapshot.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import type { WidgetManifest } from '@solus/shared-types'
import { fakeInstall, fakeManifest } from '../extensions/frame/testing/fixtures'
import {
  WIDGETS_POLL_MS,
  extensionWidgetEntries,
  useAvailableWidgets,
  type AvailableWidgetsDeps
} from './useAvailableWidgets'

const Noop = (): null => null
const MANIFESTS: WidgetManifest[] = [
  {
    id: 'livebench',
    title: 'Live Bench',
    domains: ['runtime'],
    size: { preferred: 'wide', minimum: 'standard' },
    component: Noop
  },
  {
    id: 'reference',
    title: 'Reference',
    domains: [],
    size: { preferred: 'compact' },
    component: Noop
  }
]

const bom = fakeInstall()
const noWidget = fakeInstall({
  extension: {
    slug: 'planner',
    name: 'Planner',
    verified: false,
    publisher: { display_name: 'X' }
  },
  version: {
    ...fakeInstall().version,
    manifest: fakeManifest({
      extension: { ...fakeManifest().extension, id: 'planner', name: 'Planner' },
      views: { page: { entry: 'page.html', icon: 'i.svg', label: 'Planner' } }
    })
  }
})
const disabled = fakeInstall({
  extension: { slug: 'scope', name: 'Scope', verified: true, publisher: { display_name: 'Solus' } },
  enabled: false,
  policy: { blocked: true, default_installed: false },
  version: {
    ...fakeInstall().version,
    manifest: fakeManifest({
      extension: {
        ...fakeManifest().extension,
        id: 'scope',
        name: 'Scope',
        summary: 'Scope viewer',
        requires: [['runtime']]
      },
      views: { widget: { entry: 'w.html', preferred: 'full', minimum: 'wide' } }
    })
  }
})

function deps(overrides: Partial<AvailableWidgetsDeps> = {}): AvailableWidgetsDeps {
  return {
    discover: () => MANIFESTS,
    listInstalls: vi.fn(async () => [bom, noWidget, disabled]),
    ...overrides
  }
}

const flush = (): Promise<void> => act(async () => {})

describe('extensionWidgetEntries (pure)', () => {
  it('keeps only installs whose manifest declares a widget view, carrying the facts the picker needs', () => {
    const entries = extensionWidgetEntries([bom, noWidget, disabled])
    expect(entries.map((e) => e.ref)).toEqual(['ext:bom', 'ext:scope'])
    expect(entries[0]).toMatchObject({
      slug: 'bom',
      name: 'BOM',
      summary: 'Bill of materials',
      version: '1.2.0',
      verified: true,
      publisher: 'Solus',
      size: { preferred: 'standard', minimum: undefined },
      requires: [],
      enabled: true,
      blocked: false,
      iconPath: 'icon.svg',
      hasWindow: true
    })
    expect(entries[1]).toMatchObject({
      slug: 'scope',
      size: { preferred: 'full', minimum: 'wide' },
      requires: [['runtime']],
      enabled: false,
      blocked: true,
      iconPath: null,
      hasWindow: false
    })
  })
})

describe('useAvailableWidgets', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('offers built-ins immediately and extension availability only once the snapshot loaded', async () => {
    const d = deps()
    const { result } = renderHook(() => useAvailableWidgets('p1', d))
    expect(result.current.status).toBe('loading')
    expect(result.current.builtins.map((b) => b.ref)).toEqual([
      'builtin:livebench',
      'builtin:reference'
    ])
    expect(result.current.builtins[0]).toMatchObject({
      id: 'livebench',
      title: 'Live Bench',
      size: { preferred: 'wide', minimum: 'standard' }
    })
    expect(result.current.available).toEqual({
      builtin: new Set(['livebench', 'reference']),
      ext: null
    })
    await flush()
    expect(result.current.status).toBe('ready')
    expect(result.current.extensions.map((e) => e.ref)).toEqual(['ext:bom', 'ext:scope'])
    expect(result.current.available).toEqual({
      builtin: new Set(['livebench', 'reference']),
      ext: new Set(['bom', 'scope'])
    })
  })

  it('is offline (extension availability unknown) when the snapshot never loaded', async () => {
    const d = deps({
      listInstalls: vi.fn(async () => {
        throw new TypeError('network')
      })
    })
    const { result } = renderHook(() => useAvailableWidgets('p1', d))
    await flush()
    expect(result.current.status).toBe('offline')
    expect(result.current.extensions).toEqual([])
    expect(result.current.available?.ext).toBeNull()
  })

  it(`polls every ${WIDGETS_POLL_MS} ms and keeps the last snapshot through a failed refresh`, async () => {
    let fail = false
    const listInstalls = vi.fn(async () => {
      if (fail) throw new TypeError('blip')
      return [bom]
    })
    const d = deps({ listInstalls })
    const { result } = renderHook(() => useAvailableWidgets('p1', d))
    await flush()
    expect(listInstalls).toHaveBeenCalledTimes(1)
    fail = true
    await act(async () => vi.advanceTimersByTime(WIDGETS_POLL_MS))
    expect(listInstalls).toHaveBeenCalledTimes(2)
    expect(result.current.status).toBe('ready')
    expect(result.current.extensions.map((e) => e.ref)).toEqual(['ext:bom'])
  })

  it('resets to loading on a project switch and never shows one project the other one', async () => {
    const listInstalls = vi.fn(async (projectId: string) => (projectId === 'p1' ? [bom] : []))
    const d = deps({ listInstalls })
    const { result, rerender } = renderHook(
      ({ projectId }: { projectId: string }) => useAvailableWidgets(projectId, d),
      { initialProps: { projectId: 'p1' } }
    )
    await flush()
    expect(result.current.extensions).toHaveLength(1)
    rerender({ projectId: 'p2' })
    expect(result.current.status).toBe('loading')
    expect(result.current.extensions).toEqual([])
    await flush()
    expect(result.current.status).toBe('ready')
    expect(result.current.extensions).toEqual([])
    expect(listInstalls).toHaveBeenLastCalledWith('p2')
  })
})
