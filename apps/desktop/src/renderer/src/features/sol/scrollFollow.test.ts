// SOLUSDEV-326 live check: whether the chat keeps following a streaming reply. Intent comes from the
// person's input (wheel, keys, dragging the scrollbar), never from scroll events alone — the browser
// moves scrollTop by itself when rows above re-measure (content-visibility) or the list is clamped.
import { describe, expect, it } from 'vitest'
import { isUpwardKey, nextFollow } from './scrollFollow'

const geometry = (scrollTop: number, scrollHeight = 2_000, clientHeight = 600) => ({
  scrollTop,
  scrollHeight,
  clientHeight
})

describe('nextFollow (a scroll event)', () => {
  it('keeps following when the browser moves the list by itself (re-measure, clamp)', () => {
    // Seen live: scrollHeight fell from 3772 to 2781 and scrollTop was clamped from 3112 to 417.
    expect(nextFollow(true, geometry(417, 2_781, 660), { dragging: false })).toBe(true)
  })

  it('resumes following once the list reaches the bottom', () => {
    expect(nextFollow(false, geometry(1_390), { dragging: false })).toBe(true)
  })

  it('stays put while the person reads mid-history', () => {
    expect(nextFollow(false, geometry(700), { dragging: false })).toBe(false)
  })

  it('stops following while the person drags the scrollbar away from the bottom', () => {
    expect(nextFollow(true, geometry(700), { dragging: true })).toBe(false)
  })
})

describe('isUpwardKey', () => {
  it.each(['PageUp', 'ArrowUp', 'Home'])('%s scrolls up', (key) => {
    expect(isUpwardKey(key)).toBe(true)
  })

  it.each(['PageDown', 'ArrowDown', 'End', 'a'])('%s does not', (key) => {
    expect(isUpwardKey(key)).toBe(false)
  })
})
