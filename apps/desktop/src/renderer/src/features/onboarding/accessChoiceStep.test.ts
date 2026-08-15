// The connect-time grant choice (SOLUS-ONS-A2). What these tests protect: the
// user is never granted more power than they picked, a connector that offers no
// choice is untouched, and cancelling stops the flow rather than quietly
// falling back to the widest grant.
import { describe, expect, it, vi } from 'vitest'
import { accessChoiceStep, ACCESS_CANCELLED_ERROR } from './accessChoiceStep'
import type { IntegrationAccessModes } from '../../lib/api/resources'

const MODES: IntegrationAccessModes = {
  default: 'read',
  modes: [
    { id: 'read', label: 'Read only', description: 'Solus can read your documents.', scopes: [] },
    {
      id: 'write',
      label: 'Read and edit',
      description: 'Solus can also change your models.',
      scopes: []
    }
  ]
}

describe('accessChoiceStep', () => {
  it('asks nothing when the connector offers no choice', async () => {
    const onChoose = vi.fn()

    const step = accessChoiceStep({ accessModes: null, onProgress: vi.fn(), onChoose })

    expect(await step()).toEqual({ access: undefined })
    expect(onChoose).not.toHaveBeenCalled()
  })

  it('asks nothing when there is only one mode', async () => {
    const onChoose = vi.fn()
    const single: IntegrationAccessModes = { default: 'read', modes: [MODES.modes[0]] }

    const step = accessChoiceStep({ accessModes: single, onProgress: vi.fn(), onChoose })

    expect(await step()).toEqual({ access: 'read' })
    expect(onChoose).not.toHaveBeenCalled()
  })

  it('surfaces the modes and passes the chosen one through', async () => {
    const onProgress = vi.fn()
    const step = accessChoiceStep({
      accessModes: MODES,
      onProgress,
      onChoose: async () => 'write'
    })

    expect(await step()).toEqual({ access: 'write' })
    expect(onProgress).toHaveBeenCalledWith(
      expect.objectContaining({ phase: 'busy', accessModes: MODES })
    )
  })

  it('stops the flow when the user cancels — it does not fall back to write', async () => {
    const step = accessChoiceStep({
      accessModes: MODES,
      onProgress: vi.fn(),
      onChoose: async () => null
    })

    expect(await step()).toEqual({ error: ACCESS_CANCELLED_ERROR })
  })

  it('rejects a mode the connector never offered', async () => {
    const step = accessChoiceStep({
      accessModes: MODES,
      onProgress: vi.fn(),
      onChoose: async () => 'admin'
    })

    const outcome = await step()

    expect(outcome).toEqual({ error: ACCESS_CANCELLED_ERROR })
  })
})
