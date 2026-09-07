// SOLUSDEV-250 (I3) — "Ask SOL to set it up": no composer-prefill path exists
// in the SOL feature, so the hand-off opens SOL, copies the request to the
// clipboard and says so with a toast. A clipboard that refuses is reported,
// never hidden, and SOL still opens.
import { describe, expect, it, vi } from 'vitest'
import { SOL_SETUP_MESSAGE } from '../project/codeEnvironment.constants'
import { handOffToSol, type SolHandoffDeps } from './codeEnvironmentSol'
import { useShellStore, type ShellToast } from './shellStore'

type Deps = SolHandoffDeps & { toast: ReturnType<typeof vi.fn<(t: ShellToast) => void>> }

function deps(over: Partial<Omit<SolHandoffDeps, 'toast'>> = {}): Deps {
  return {
    navigate: vi.fn(),
    writeText: vi.fn(async () => undefined),
    toast: vi.fn<(t: ShellToast) => void>(),
    ...over
  }
}

const firstToast = (d: Deps): ShellToast => d.toast.mock.calls[0]?.[0] as ShellToast

describe('handOffToSol', () => {
  it('copies the setup request, toasts, then opens the SOL screen', async () => {
    const d = deps()
    await handOffToSol(d)
    expect(d.writeText).toHaveBeenCalledWith(SOL_SETUP_MESSAGE)
    expect(d.toast).toHaveBeenCalledWith(
      expect.objectContaining({ kind: 'ok', title: 'Request copied for SOL' })
    )
    expect(d.navigate).toHaveBeenCalledWith('sol')
  })

  it('says when the clipboard refused and still opens SOL, quoting the request', async () => {
    const d = deps({ writeText: vi.fn(async () => Promise.reject(new Error('denied'))) })
    await handOffToSol(d)
    expect(d.toast).toHaveBeenCalledWith(
      expect.objectContaining({ kind: 'warn', title: "Couldn't copy the request" })
    )
    expect(firstToast(d).body).toContain(SOL_SETUP_MESSAGE)
    expect(d.navigate).toHaveBeenCalledWith('sol')
  })

  it('copes without a navigator: the toast still carries the way to SOL', async () => {
    const d = deps({ navigate: undefined })
    await handOffToSol(d)
    expect(firstToast(d)).toMatchObject({ action: 'Open SOL', screen: 'sol' })
  })

  it('defaults to the shell toast store', async () => {
    useShellStore.getState().reset()
    await handOffToSol({ navigate: vi.fn(), writeText: vi.fn(async () => undefined) })
    expect(useShellStore.getState().toast?.title).toBe('Request copied for SOL')
  })
})
