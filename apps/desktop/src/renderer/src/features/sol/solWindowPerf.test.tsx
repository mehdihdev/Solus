// SOLUSDEV-252 S3 perf budget (the SOLX-02 orb budget carried forward):
//   idle = 0 scripted animation frames — no requestAnimationFrame or timers
//   registered by the SOL window modules; rendering is CSS only;
//   streaming indicator ≤ 1 CSS class, applied only while streaming;
//   prefers-reduced-motion: reduce → no pulse animation at all.
// The token batcher (tokenBatcher.ts) is the one sanctioned rAF user and is
// exempt — it runs only while a turn streams.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { render, act } from '@testing-library/react'
import { SolWindow } from './SolWindow'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useSolSessionStore } from './solSessionStore'
import { disconnectSolBridge, useSolWindowStore } from './solWindowStore'
import { fakeSolBridge, installSolBridge, uninstallSolBridge } from './solWindow.fixtures'

vi.mock('./solApi', () => ({
  createSolConversation: vi.fn(),
  listSolTurns: vi.fn().mockResolvedValue([]),
  streamSolMessage: vi.fn()
}))
vi.mock('../../lib/api/resources', async (importOriginal) => ({
  // Spread the real module: ArtifactCard (via SolChat) reads SOLUS_SECTIONS at load.
  ...(await importOriginal<typeof import('../../lib/api/resources')>()),
  classifyQuery: vi.fn()
}))

const here = dirname(fileURLToPath(import.meta.url))

beforeEach(() => {
  localStorage.clear()
  disconnectSolBridge()
  useSolWindowStore.setState({ state: null, region: null })
  useSolSessionStore.setState({ streaming: false, conversationByProject: {} })
  useAuthStore.setState({ status: 'authenticated', user: { email: 'a@b.dev' }, onboarded: true })
  useWorkspaceStore.setState({ teamId: 't1', project: { id: 'p1', name: 'Rover' }, linked: true })
  installSolBridge(fakeSolBridge())
})
afterEach(() => {
  disconnectSolBridge()
  uninstallSolBridge()
})

describe('idle SOL window: zero scripted animation', () => {
  it('the SOL window modules register no requestAnimationFrame or timers (source ratchet)', () => {
    const sources = [
      'SolWindow.tsx',
      'solWindowStore.ts',
      'solSessionStore.ts',
      'ModeBadge.tsx',
      'RegionCard.tsx'
    ]
    for (const name of sources) {
      const text = readFileSync(join(here, name), 'utf8')
      expect(text, name).not.toMatch(/requestAnimationFrame|setInterval|setTimeout/)
    }
  })

  it('rendering the idle window schedules no animation frames or intervals', async () => {
    const raf = vi.spyOn(window, 'requestAnimationFrame')
    const interval = vi.spyOn(window, 'setInterval')
    try {
      render(<SolWindow />)
      await act(async () => undefined)
      expect(raf).not.toHaveBeenCalled()
      expect(interval).not.toHaveBeenCalled()
    } finally {
      raf.mockRestore()
      interval.mockRestore()
    }
  })

  it('the streaming indicator is a single CSS class, present only while streaming', async () => {
    render(<SolWindow />)
    await act(async () => undefined)
    expect(document.querySelector('.sol-pulse')).toBeNull()
    act(() => useSolSessionStore.getState().setStreaming(true))
    expect(document.querySelectorAll('.sol-pulse')).toHaveLength(1)
    act(() => useSolSessionStore.getState().setStreaming(false))
    expect(document.querySelector('.sol-pulse')).toBeNull()
  })
})

describe('reduced motion (a11y)', () => {
  it('main.css guards sol-pulse behind prefers-reduced-motion', () => {
    const css = readFileSync(join(here, '..', '..', 'assets', 'main.css'), 'utf8')
    expect(css).toMatch(/\.sol-pulse\s*\{[^}]*animation:\s*sol-pulse/)
    const reduced = css.match(/@media \(prefers-reduced-motion: reduce\)\s*\{[\s\S]*?\n\}/g) ?? []
    const guard = reduced.find((block) => block.includes('.sol-pulse'))
    expect(guard).toBeDefined()
    expect(guard).toMatch(/\.sol-pulse\s*\{[^}]*animation:\s*none/)
  })
})
