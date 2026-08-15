// The sender gate on credential-bearing IPC channels.
//
// Every privileged handler in `index.ts` routes its authorisation decision
// through this one predicate — billing/checkout and the bridge token (main), and
// the connector OAuth callback, which resolves WITH THE AUTHORIZATION CODE.
// It had no test: `index.ts` builds a BrowserWindow at import, so the decision
// was extracted rather than left uncovered.
import { describe, expect, it } from 'vitest'
import { isFromWindow } from './senderGate'

const webContents = { id: 1 }
const mainWindow = { webContents }

describe('isFromWindow', () => {
  it('accepts the app own renderer', () => {
    expect(isFromWindow(webContents, mainWindow)).toBe(true)
  })

  it('rejects any other webContents that gained IPC reach', () => {
    expect(isFromWindow({ id: 2 }, mainWindow)).toBe(false)
  })

  it('rejects everything before a window exists', () => {
    // Fails CLOSED: with no window there is no legitimate sender, so a handler
    // invoked during startup or after teardown refuses rather than allowing.
    expect(isFromWindow(webContents, null)).toBe(false)
  })

  it('does not treat the window itself as its own sender', () => {
    // Guards the easy mistake of comparing against the window rather than its
    // webContents, which would accept a sender that is merely truthy.
    expect(isFromWindow(mainWindow, mainWindow)).toBe(false)
  })
})
