// SOLUSDEV-326 P3: the plug-in notice the open Hardware page sends (MessageCreate.notice): once
// per session for each unclaimed device, 2 s after the page first sees it, whether it arrived
// with the page open or was there before; never for a device that is bound, dismissed or still
// being inspected.
import { StrictMode } from 'react'
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { DetectedDeviceOut } from '../../lib/api/hardware'
import { useDeviceStore } from './deviceStore'
import { device } from './testing/fixtures'
import { NOTICE_DELAY_MS, usePlugInNotice } from './usePlugInNotice'

const send = vi.fn()
const rows = (...devices: DetectedDeviceOut[]): void =>
  act(() => useDeviceStore.getState().setDevices('p1', devices))
const wait = (ms: number): Promise<void> =>
  act(async () => void (await vi.advanceTimersByTimeAsync(ms)))
const open = (projectId: string | null = 'p1'): ReturnType<typeof renderHook> =>
  renderHook(() => usePlugInNotice(projectId, send))

beforeEach(() => {
  vi.useFakeTimers()
  send.mockReset().mockResolvedValue(true)
  useDeviceStore.getState().reset()
})
afterEach(() => {
  vi.useRealTimers()
})

it('waits 2 s', () => expect(NOTICE_DELAY_MS).toBe(2000))

it('announces a device that arrives, once, 2 s after it arrived', async () => {
  rows()
  open()
  rows(device('usb_serial:A'))
  await wait(1999)
  expect(send).not.toHaveBeenCalled()
  await wait(1)
  expect(send).toHaveBeenCalledExactlyOnceWith('usb_serial:A')
  // The same rows again (every frame is the full list) are the same arrival.
  rows(device('usb_serial:A'))
  rows(device('usb_serial:A'), device('usb_serial:B', { state: 'inspecting' }))
  await wait(10_000)
  expect(send).toHaveBeenCalledOnce()
})

it('opening the page with one unclaimed device already plugged in announces it once, after 2 s', async () => {
  rows(device('usb_serial:A'))
  open()
  await wait(1999)
  expect(send).not.toHaveBeenCalled()
  await wait(1)
  expect(send).toHaveBeenCalledExactlyOnceWith('usb_serial:A')
})

it('a second open in the same session does not announce it again', async () => {
  rows(device('usb_serial:A'))
  open().unmount()
  // Closed inside its 2 s: still owed, so the next open sends the one notice.
  const page = open()
  await wait(2000)
  page.unmount()
  open()
  rows(device('usb_serial:A'))
  await wait(10_000)
  expect(send).toHaveBeenCalledExactlyOnceWith('usb_serial:A')
})

it('React StrictMode’s double mount announces once, and loses none', async () => {
  rows(device('usb_serial:A'))
  renderHook(() => usePlugInNotice('p1', send), { wrapper: StrictMode })
  await wait(10_000)
  expect(send).toHaveBeenCalledExactlyOnceWith('usb_serial:A')
})

it('a dismissed device ("Not now") is never announced, on any open', async () => {
  rows(device('usb_serial:A', { dismissed: true }))
  open().unmount()
  open()
  await wait(10_000)
  expect(send).not.toHaveBeenCalled()
})

it('a sign-out or a project switch (the store resets) starts a new session', async () => {
  rows(device('usb_serial:A'))
  const page = open()
  await wait(2000)
  page.unmount()
  act(() => useDeviceStore.getState().reset())
  rows(device('usb_serial:A'))
  open()
  await wait(2000)
  expect(send).toHaveBeenCalledTimes(2)
})

it('a device the shell toasted about while the page was closed is announced on opening once, not twice', async () => {
  rows(device('usb_serial:A'), device('usb_serial:B'))
  act(() => useDeviceStore.getState().owe(['usb_serial:B']))
  open()
  expect(useDeviceStore.getState().unannounced).toEqual([])
  await wait(1999)
  expect(send).not.toHaveBeenCalled()
  await wait(1)
  // The toasted one and the one that was there all along, each once.
  expect(send.mock.calls.map(([ref]) => ref as string)).toEqual(['usb_serial:A', 'usb_serial:B'])
  // Closing and opening again owes nothing more.
  open()
  await wait(5000)
  expect(send).toHaveBeenCalledTimes(2)
})

it('a page closed inside the 2 s still owes the notice: reopened (StrictMode remounts), it sends one', async () => {
  rows(device('usb_serial:A'))
  act(() => useDeviceStore.getState().owe(['usb_serial:A']))
  open().unmount()
  open()
  await wait(2000)
  expect(send).toHaveBeenCalledExactlyOnceWith('usb_serial:A')
})

it('a toasted device that was claimed before the page opened is not announced', async () => {
  rows(device('usb_serial:A'), device('usb_serial:B'))
  act(() => useDeviceStore.getState().owe(['usb_serial:A', 'usb_serial:B']))
  rows(device('usb_serial:A', { bound_to: 'r1' }))
  expect(useDeviceStore.getState().unannounced).toEqual([])
  rows(device('usb_serial:A', { bound_to: 'r1' }), device('usb_serial:B'))
  open()
  await wait(5000)
  expect(send).toHaveBeenCalledExactlyOnceWith('usb_serial:B')
})

it('a device owed while the page is open ("+ Add hardware") is announced again, each press once', async () => {
  rows(device('usb_serial:A'))
  open()
  // Owed inside the first notice's 2 s: still the one notice.
  act(() => useDeviceStore.getState().owe(['usb_serial:A']))
  await wait(2000)
  expect(send).toHaveBeenCalledExactlyOnceWith('usb_serial:A')
  act(() => useDeviceStore.getState().owe(['usb_serial:A']))
  act(() => useDeviceStore.getState().owe(['usb_serial:A']))
  await wait(2000)
  expect(send).toHaveBeenCalledTimes(2)
})

it('the first rows of a page opened before any were read are announced too, once', async () => {
  open()
  rows(device('usb_serial:A'))
  await wait(2000)
  expect(send).toHaveBeenCalledExactlyOnceWith('usb_serial:A')
  rows(device('usb_serial:A'), device('usb_serial:B'))
  await wait(2000)
  expect(send).toHaveBeenLastCalledWith('usb_serial:B')
  expect(send).toHaveBeenCalledTimes(2)
})

it('waits for the inspection to settle: inspected, busy and unknown are each announced', async () => {
  rows()
  open()
  rows(
    device('usb_serial:A', { state: 'inspecting' }),
    device('usb_serial:B', { state: 'inspecting' }),
    device('usb_serial:C', { state: 'inspecting' })
  )
  await wait(5000)
  expect(send).not.toHaveBeenCalled()
  rows(
    device('usb_serial:A', { state: 'inspected' }),
    device('usb_serial:B', { state: 'busy' }),
    device('usb_serial:C', { state: 'unknown' })
  )
  await wait(2000)
  expect(send.mock.calls.map(([ref]) => ref as string)).toEqual([
    'usb_serial:A',
    'usb_serial:B',
    'usb_serial:C'
  ])
})

it('never announces a device that is bound, dismissed or has no ref', async () => {
  rows()
  open()
  rows(device('usb_serial:A', { bound_to: 'r1' }), device('usb_serial:B', { dismissed: true }), {
    ...device('x'),
    device_ref: null
  })
  await wait(5000)
  expect(send).not.toHaveBeenCalled()
})

it('a device that left, was bound or was waved off inside the 2 s is not announced', async () => {
  rows()
  open()
  rows(device('usb_serial:A'), device('usb_serial:B'), device('usb_serial:C'))
  await wait(1000)
  rows(device('usb_serial:B', { bound_to: 'r1' }), device('usb_serial:C', { dismissed: true }))
  await wait(5000)
  expect(send).not.toHaveBeenCalled()
})

it('a device plugged in again is a new arrival, and a flap inside 2 s is one', async () => {
  rows()
  open()
  rows(device('usb_serial:A'))
  await wait(2000)
  rows()
  rows(device('usb_serial:A'))
  await wait(500)
  rows()
  rows(device('usb_serial:A'))
  await wait(1999)
  expect(send).toHaveBeenCalledOnce()
  await wait(1)
  expect(send).toHaveBeenCalledTimes(2)
})

it('a notice that fails is swallowed: nothing is thrown and nothing is retried', async () => {
  send.mockRejectedValue(new Error('offline'))
  rows()
  open()
  rows(device('usb_serial:A'))
  await wait(10_000)
  expect(send).toHaveBeenCalledOnce()
})

it('sends nothing once the page is closed, or for another project', async () => {
  rows()
  const page = open()
  rows(device('usb_serial:A'))
  page.unmount()
  await wait(5000)
  expect(send).not.toHaveBeenCalled()
  open(null)
  open('p2')
  rows(device('usb_serial:A'), device('usb_serial:B'))
  await wait(5000)
  expect(send).not.toHaveBeenCalled()
})
