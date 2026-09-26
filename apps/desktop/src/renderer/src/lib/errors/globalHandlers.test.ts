// SOLUSDEV-311: boundaries cannot see event-handler or async errors, so the
// window `error` and `unhandledrejection` events route them to the reporter —
// tagged with whatever surface the user is on when it happens.
import { describe, it, expect, vi, afterEach } from 'vitest'
import { installGlobalErrorHandlers } from './globalHandlers'

let uninstall: (() => void) | null = null
afterEach(() => {
  uninstall?.()
  uninstall = null
})

describe('installGlobalErrorHandlers', () => {
  it('reports an uncaught script error with the current surface', () => {
    const report = vi.fn()
    uninstall = installGlobalErrorHandlers(window, { report }, () => 'bench')
    const error = new TypeError('from a click handler')
    window.dispatchEvent(new ErrorEvent('error', { error, message: error.message }))
    expect(report).toHaveBeenCalledWith(error, { origin: 'window_error', surface: 'bench' })
  })

  it('falls back to the message when the event carries no error object', () => {
    const report = vi.fn()
    uninstall = installGlobalErrorHandlers(window, { report }, () => 'root')
    window.dispatchEvent(new ErrorEvent('error', { message: 'Script error.' }))
    expect(report).toHaveBeenCalledWith('Script error.', {
      origin: 'window_error',
      surface: 'root'
    })
  })

  it('reports an unhandled promise rejection with its reason', () => {
    const report = vi.fn()
    uninstall = installGlobalErrorHandlers(window, { report }, () => 'sol')
    const reason = new Error('late')
    const event = new Event('unhandledrejection') as Event & { reason?: unknown }
    event.reason = reason
    window.dispatchEvent(event)
    expect(report).toHaveBeenCalledWith(reason, { origin: 'unhandled_rejection', surface: 'sol' })
  })

  it('stops reporting once uninstalled', () => {
    const report = vi.fn()
    installGlobalErrorHandlers(window, { report }, () => 'root')()
    window.dispatchEvent(new ErrorEvent('error', { error: new Error('x') }))
    expect(report).not.toHaveBeenCalled()
  })
})
