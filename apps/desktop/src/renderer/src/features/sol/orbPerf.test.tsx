// SOLX-02 perf budget (SOL-05 carried forward — defined here, no prototype
// ever existed):
//   idle = 0 scripted animation frames — no requestAnimationFrame or timers
//   registered by the orb modules; rendering is CSS only (transform/opacity);
//   pulse ≤ 1 CSS animation, applied only while streaming/thinking;
//   prefers-reduced-motion: reduce → no pulse animation at all.
// The source ratchet + runtime spies below keep that budget honest.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { render } from '@testing-library/react'
import { MiniOrb } from './MiniOrb'
import { SolOrb } from '../../components/ui/SolOrb'
import { useOrbStore } from './orbStore'

vi.mock('./solApi', () => ({
  createSolConversation: vi.fn(),
  listSolTurns: vi.fn().mockResolvedValue([]),
  streamSolMessage: vi.fn()
}))
vi.mock('../../lib/api/resources', () => ({ classifyQuery: vi.fn() }))

const here = dirname(fileURLToPath(import.meta.url))

beforeEach(() => {
  localStorage.clear()
  useOrbStore.setState({
    corner: 'br',
    expanded: false,
    detached: false,
    streaming: false,
    conversationByProject: {}
  })
})

describe('idle orb: zero scripted animation', () => {
  it('the orb modules register no requestAnimationFrame or timers (source ratchet)', () => {
    const sources = [
      join(here, 'MiniOrb.tsx'),
      join(here, 'orbStore.ts'),
      join(here, '..', '..', 'components', 'ui', 'SolOrb.tsx')
    ]
    for (const file of sources) {
      const text = readFileSync(file, 'utf8')
      expect(text, file).not.toMatch(/requestAnimationFrame|setInterval|setTimeout/)
    }
  })

  it('rendering the idle orb schedules no animation frames or intervals', () => {
    const raf = vi.spyOn(window, 'requestAnimationFrame')
    const interval = vi.spyOn(window, 'setInterval')
    try {
      render(<MiniOrb hidden={false} onClick={vi.fn()} />)
      expect(raf).not.toHaveBeenCalled()
      expect(interval).not.toHaveBeenCalled()
    } finally {
      raf.mockRestore()
      interval.mockRestore()
    }
  })

  it('the pulse is a single CSS class, present only when asked for', () => {
    const idle = render(<SolOrb />)
    expect(idle.container.querySelector('.sol-orb-pulse')).toBeNull()
    const pulsing = render(<SolOrb pulse />)
    expect(pulsing.container.querySelector('.sol-orb-pulse')).not.toBeNull()
  })
})

describe('reduced motion (a11y)', () => {
  it('main.css guards sol-orb-pulse behind prefers-reduced-motion', () => {
    const css = readFileSync(join(here, '..', '..', 'assets', 'main.css'), 'utf8')
    // The pulse class exists…
    expect(css).toMatch(/\.sol-orb-pulse\s*\{[^}]*animation:\s*sol-orb-pulse/)
    // …and a reduced-motion block turns it off.
    const reduced = css.match(/@media \(prefers-reduced-motion: reduce\)\s*\{[\s\S]*?\n\}/g) ?? []
    const guard = reduced.find((block) => block.includes('.sol-orb-pulse'))
    expect(guard).toBeDefined()
    expect(guard).toMatch(/\.sol-orb-pulse\s*\{[^}]*animation:\s*none/)
  })
})
