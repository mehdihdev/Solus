// The generic configure step: whatever `config_fields` the registry reports
// becomes the form. No provider id appears in these tests on purpose — that is
// the property being asserted.
import { describe, it, expect, vi } from 'vitest'
import {
  fieldsConfigureStep,
  CANCELLED_ERROR,
  INCOMPLETE_ERROR,
  NO_FIELDS_ERROR
} from './fieldsConfigureStep'
import type { ConnectionState } from './onboardingStore'

const CTX = { projectId: 'p1', sourceId: 's1', provider: 'someFutureCad' }
const FIELDS = ['document_id', 'workspace_id', 'element_id']

function make(
  fields: readonly string[],
  submit: (fields: readonly string[]) => Promise<Record<string, string> | null>
): { step: ReturnType<typeof fieldsConfigureStep>; states: ConnectionState[] } {
  const states: ConnectionState[] = []
  const step = fieldsConfigureStep({
    fields,
    onProgress: (s) => states.push(s),
    onSubmitConfig: submit
  })
  return { step, states }
}

describe('fieldsConfigureStep', () => {
  it('surfaces the live config fields and returns the submitted values as config', async () => {
    const submit = vi.fn(async () => ({
      document_id: 'd1',
      workspace_id: 'w1',
      element_id: 'e1'
    }))
    const { step, states } = make(FIELDS, submit)

    const outcome = await step(CTX)

    expect(submit).toHaveBeenCalledWith(FIELDS)
    expect(outcome).toEqual({ config: { document_id: 'd1', workspace_id: 'w1', element_id: 'e1' } })
    // The form is surfaced through the store the same way the repo picker is.
    expect(states.some((s) => s.phase === 'busy' && s.configFields === FIELDS)).toBe(true)
  })

  it('works for any field shape, not a known provider’s', async () => {
    const fields = ['tenant', 'model_urn']
    const { step } = make(fields, async () => ({ tenant: 't', model_urn: 'u' }))
    expect(await step(CTX)).toEqual({ config: { tenant: 't', model_urn: 'u' } })
  })

  it('trims submitted values', async () => {
    const { step } = make(['document_id'], async () => ({ document_id: '  d1  ' }))
    expect(await step(CTX)).toEqual({ config: { document_id: 'd1' } })
  })

  it('reports an honest error when the user cancels', async () => {
    const { step } = make(FIELDS, async () => null)
    expect(await step(CTX)).toEqual({ error: CANCELLED_ERROR })
  })

  it('rejects a partially filled form rather than syncing a broken source', async () => {
    const { step } = make(FIELDS, async () => ({
      document_id: 'd1',
      workspace_id: '   ',
      element_id: 'e1'
    }))
    expect(await step(CTX)).toEqual({ error: INCOMPLETE_ERROR })
  })

  it('rejects a connector with no config fields instead of syncing it unconfigured', async () => {
    const submit = vi.fn(async () => ({}))
    const { step } = make([], submit)
    expect(await step(CTX)).toEqual({ error: NO_FIELDS_ERROR })
    expect(submit).not.toHaveBeenCalled()
  })
})
