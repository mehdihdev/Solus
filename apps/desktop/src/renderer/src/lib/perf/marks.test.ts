import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { awaitMark, markAwaited, markOnce, markSafely, measureSafely, resetMarks } from './marks'

const fake = { mark: vi.fn(), measure: vi.fn() }

beforeEach(() => {
  vi.clearAllMocks()
  resetMarks()
  vi.stubGlobal('performance', fake)
})
afterEach(() => vi.unstubAllGlobals())

describe('marks', () => {
  it('marks and measures through the Performance API', () => {
    markSafely('hw:confirm_sent')
    measureSafely('hw:confirm_to_node', 'hw:confirm_sent', 'hw:node_visible')
    expect(fake.mark).toHaveBeenCalledWith('hw:confirm_sent')
    expect(fake.measure).toHaveBeenCalledWith(
      'hw:confirm_to_node',
      'hw:confirm_sent',
      'hw:node_visible'
    )
  })

  it('never throws — a missing start mark or a missing API is swallowed', () => {
    fake.measure.mockImplementation(() => {
      throw new SyntaxError('no such mark')
    })
    expect(() => measureSafely('m', 'a', 'b')).not.toThrow()
    vi.stubGlobal('performance', undefined)
    expect(() => markSafely('x')).not.toThrow()
    expect(() => measureSafely('m', 'a', 'b')).not.toThrow()
  })

  it('markOnce marks a key once per name', () => {
    expect(markOnce('hw:card_rendered', 'usb_serial:A')).toBe(true)
    expect(markOnce('hw:card_rendered', 'usb_serial:A')).toBe(false)
    expect(markOnce('hw:card_rendered', 'usb_serial:B')).toBe(true)
    expect(fake.mark).toHaveBeenCalledTimes(2)
  })

  it('markAwaited marks only a key that was awaited, and consumes it', () => {
    expect(markAwaited('hw:node_visible', 'arm')).toBe(false)
    awaitMark('arm')
    expect(markAwaited('hw:node_visible', 'arm')).toBe(true)
    expect(markAwaited('hw:node_visible', 'arm')).toBe(false)
    expect(fake.mark).toHaveBeenCalledExactlyOnceWith('hw:node_visible')
  })
})

it('correlates overlapping confirmation measurements to their own starts', async () => {
  const { startConfirmation } = await import('./marks')
  const first = startConfirmation()
  const second = startConfirmation()
  expect(first).not.toBe(second)
  awaitMark('robot-b', second)
  awaitMark('robot-a', first)
  markAwaited('hw:node_visible', 'robot-b')
  markAwaited('hw:node_visible', 'robot-a')
  expect(fake.measure).toHaveBeenCalledWith(
    'hw:confirm_to_node:robot-b',
    second,
    'hw:node_visible:robot-b'
  )
  expect(fake.measure).toHaveBeenCalledWith(
    'hw:confirm_to_node:robot-a',
    first,
    'hw:node_visible:robot-a'
  )
})

it('measures every reappearance from frame receipt, not physical plug-in', async () => {
  const { recordDeviceFrame, markDeviceRendered } = await import('./marks')
  recordDeviceFrame(['usb:A'])
  markDeviceRendered('usb:A')
  markDeviceRendered('usb:A')
  recordDeviceFrame([])
  recordDeviceFrame(['usb:A'])
  markDeviceRendered('usb:A')
  const measures = fake.measure.mock.calls.filter(([name]) => name === 'hw:receipt_to_card:usb:A')
  expect(measures).toHaveLength(2)
  expect(measures[0][1]).not.toBe(measures[1][1])
  expect(fake.measure.mock.calls.some(([name]) => String(name).includes('plug_in'))).toBe(false)
})
