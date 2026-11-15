// SOLUSDEV-326 live check: whether the chat keeps following the stream after a scroll event.
import { describe, expect, it } from 'vitest'
import { bottomTop, nextFollow } from './scrollFollow'

const geometry = (scrollTop: number, scrollHeight = 2_000, clientHeight = 600) => ({
  scrollTop,
  scrollHeight,
  clientHeight
})

describe('nextFollow', () => {
  it('keeps following when rows above grow and the list was not scrolled up', () => {
    // Pinned at the bottom (top 1400 of 2000); an off-screen row then renders at its real
    // height, so the list is now 2600 tall but nobody scrolled.
    const pinned = { following: true, lastTop: bottomTop(geometry(1_400)) }

    expect(nextFollow(pinned, geometry(1_400, 2_600)).following).toBe(true)
  })

  it('stops following when the person scrolls up to read', () => {
    const pinned = { following: true, lastTop: 1_400 }

    expect(nextFollow(pinned, geometry(900)).following).toBe(false)
  })

  it('resumes once the person scrolls back to the bottom', () => {
    const reading = { following: false, lastTop: 900 }

    expect(nextFollow(reading, geometry(1_390)).following).toBe(true)
  })

  it('stays put while the person reads mid-history and scrolls a little down', () => {
    const reading = { following: false, lastTop: 500 }

    expect(nextFollow(reading, geometry(700)).following).toBe(false)
  })

  it('remembers where the list now is', () => {
    expect(nextFollow({ following: true, lastTop: 1_400 }, geometry(900)).lastTop).toBe(900)
  })
})
