// SOLUSDEV-328: the team overview ↔ project page switch morphs through the View Transitions API —
// the rail folds to initials, the projects column becomes the projects list, the detail slides.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { homeNavDirection, isHomeMorphing, withHomeTransition } from './homeTransition'

type Doc = { startViewTransition?: unknown }

function stubTransition(): ReturnType<typeof vi.fn> {
  let finish: () => void = () => {}
  const finished = new Promise<void>((resolve) => (finish = resolve))
  const start = vi.fn((update: () => void) => {
    update()
    queueMicrotask(finish)
    return { finished, ready: Promise.resolve(), updateCallbackDone: Promise.resolve() }
  })
  ;(document as unknown as Doc).startViewTransition = start
  return start
}

function stubReducedMotion(matches: boolean): void {
  vi.stubGlobal('matchMedia', (query: string) => ({ matches, media: query }))
}

afterEach(() => {
  delete (document as unknown as Doc).startViewTransition
  delete document.documentElement.dataset.homeNav
  vi.unstubAllGlobals()
})

describe('homeNavDirection', () => {
  it('goes in to the project page and out of it; other switches have no morph', () => {
    expect(homeNavDirection('team', 'project')).toBe('in')
    expect(homeNavDirection('project', 'team')).toBe('out')
    expect(homeNavDirection('project', 'project')).toBeNull()
    expect(homeNavDirection('team', 'members')).toBeNull()
    expect(homeNavDirection('project', 'accounts')).toBeNull()
  })
})

describe('withHomeTransition', () => {
  it('just updates when the browser has no view transitions', () => {
    stubReducedMotion(false)
    const update = vi.fn()
    withHomeTransition('in', update)
    expect(update).toHaveBeenCalledOnce()
    expect(document.documentElement.dataset.homeNav).toBeUndefined()
  })

  it('just updates when there is no direction', () => {
    stubReducedMotion(false)
    const start = stubTransition()
    const update = vi.fn()
    withHomeTransition(null, update)
    expect(update).toHaveBeenCalledOnce()
    expect(start).not.toHaveBeenCalled()
  })

  it('just updates under reduced motion', () => {
    stubReducedMotion(true)
    const start = stubTransition()
    const update = vi.fn()
    withHomeTransition('in', update)
    expect(update).toHaveBeenCalledOnce()
    expect(start).not.toHaveBeenCalled()
  })

  it('runs the update inside a view transition, marking its direction until it finishes', async () => {
    stubReducedMotion(false)
    const start = stubTransition()
    let seen: string | undefined
    withHomeTransition('out', () => (seen = document.documentElement.dataset.homeNav))
    expect(start).toHaveBeenCalledOnce()
    expect(seen).toBe('out')
    expect(isHomeMorphing()).toBe(true)
    await vi.waitFor(() => expect(isHomeMorphing()).toBe(false))
  })

  it('still updates when starting the transition throws', () => {
    stubReducedMotion(false)
    ;(document as unknown as Doc).startViewTransition = () => {
      throw new Error('InvalidStateError')
    }
    const update = vi.fn()
    withHomeTransition('in', update)
    expect(update).toHaveBeenCalledOnce()
    expect(document.documentElement.dataset.homeNav).toBeUndefined()
  })
})
