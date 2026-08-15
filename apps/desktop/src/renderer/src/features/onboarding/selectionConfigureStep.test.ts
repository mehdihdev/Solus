// The post-auth selection step. What is asserted here is that NOTHING in it
// knows what an item is: the connector's declared `selection` drives single vs
// multi, the noun, and the config key. Provider ids appear nowhere on purpose —
// GitHub picks one repo and Onshape picks many documents through this one file.
import { describe, it, expect, vi } from 'vitest'
import {
  selectionConfigureStep,
  selectionConfig,
  plural,
  NOTHING_SELECTED_ERROR,
  type SelectionConfigureDeps
} from './selectionConfigureStep'
import type { IntegrationSelection, SelectableItem } from '../../lib/api/resources'
import type { ConnectionState } from './onboardingStore'

const SINGLE: IntegrationSelection = { mode: 'single', config_key: 'repo', label: 'repository' }
const MULTI: IntegrationSelection = { mode: 'multi', config_key: 'documents', label: 'document' }

const REPO_A: SelectableItem = {
  id: 'strider/strider-fw',
  name: 'strider/strider-fw',
  config: { repo: 'strider/strider-fw', branch: 'main' }
}
const REPO_B: SelectableItem = {
  id: 'strider/strider-tools',
  name: 'strider/strider-tools',
  config: { repo: 'strider/strider-tools', branch: 'dev' }
}
const DOC_A: SelectableItem = { id: 'docA', name: 'Rover chassis' }
const DOC_B: SelectableItem = { id: 'docB', name: 'Arm' }

const CTX = { projectId: 'p1', sourceId: 's1', provider: 'someFutureCad' }

function make(
  selection: IntegrationSelection,
  items: SelectableItem[],
  onSelect: (items: SelectableItem[]) => Promise<SelectableItem[] | null> = async (i) => [i[0]]
): {
  step: ReturnType<typeof selectionConfigureStep>
  states: ConnectionState[]
  deps: SelectionConfigureDeps
} {
  const states: ConnectionState[] = []
  const deps: SelectionConfigureDeps = {
    selection,
    listSelectable: vi.fn(async () => items),
    onProgress: (s) => states.push(s),
    onSelect: vi.fn(onSelect)
  }
  return { step: selectionConfigureStep(deps), states, deps }
}

describe('selectionConfigureStep — single select', () => {
  it('auto-selects the only option and writes the config the item carries', async () => {
    const { step, deps } = make(SINGLE, [REPO_A])

    const outcome = await step(CTX)

    expect(deps.listSelectable).toHaveBeenCalledWith('p1', 's1')
    expect(deps.onSelect).not.toHaveBeenCalled()
    expect(outcome).toEqual({
      config: { repo: 'strider/strider-fw', branch: 'main' },
      label: 'strider/strider-fw'
    })
  })

  it('surfaces a picker when there is more than one option', async () => {
    const { step, states, deps } = make(SINGLE, [REPO_A, REPO_B], async () => [REPO_B])

    const outcome = await step(CTX)

    expect(deps.onSelect).toHaveBeenCalledWith([REPO_A, REPO_B])
    expect(states.some((s) => s.phase === 'busy' && s.selectable?.length === 2)).toBe(true)
    expect(outcome).toEqual({
      config: { repo: 'strider/strider-tools', branch: 'dev' },
      label: 'strider/strider-tools'
    })
  })

  it('errors when the user cancels, and when they pick nothing', async () => {
    const cancelled = make(SINGLE, [REPO_A, REPO_B], async () => null)
    expect(await cancelled.step(CTX)).toEqual({ error: NOTHING_SELECTED_ERROR })

    const empty = make(SINGLE, [REPO_A, REPO_B], async () => [])
    expect(await empty.step(CTX)).toEqual({ error: NOTHING_SELECTED_ERROR })
  })
})

describe('selectionConfigureStep — multi select', () => {
  it('writes the chosen ids under the connector’s own config key', async () => {
    const { step, states } = make(MULTI, [DOC_A, DOC_B], async () => [DOC_A, DOC_B])

    const outcome = await step(CTX)

    expect(outcome).toEqual({ config: { documents: ['docA', 'docB'] }, label: '2 documents' })
    expect(states.some((s) => s.phase === 'busy' && s.selectionMode === 'multi')).toBe(true)
  })

  it('always shows the picker, even for a single option', async () => {
    // Unlike single-select, "there is only one" is not the same as "track it".
    const { step, deps } = make(MULTI, [DOC_A], async () => [DOC_A])
    await step(CTX)
    expect(deps.onSelect).toHaveBeenCalled()
  })

  it('accepts an empty selection as a connected, idle source', async () => {
    const { step } = make(MULTI, [DOC_A, DOC_B], async () => [])

    expect(await step(CTX)).toEqual({ config: { documents: [] }, label: 'no documents' })
  })

  it('still errors when the user cancels outright', async () => {
    const { step } = make(MULTI, [DOC_A], async () => null)
    expect(await step(CTX)).toEqual({ error: NOTHING_SELECTED_ERROR })
  })
})

describe('selectionConfigureStep — provider independence', () => {
  it('names the connector’s own noun rather than a hardcoded one', async () => {
    const { step, states } = make(
      { mode: 'multi', config_key: 'assemblies', label: 'assembly' },
      [DOC_A],
      async () => [DOC_A]
    )

    await step(CTX)

    const labels = states.map((s) => (s.phase === 'busy' ? s.label : '')).join(' ')
    expect(labels).toContain('Discovering assemblies…')
    expect(labels).not.toMatch(/repositor|document/i)
  })

  it('reports an honest error when the account has nothing to offer', async () => {
    const { step } = make(MULTI, [])
    expect(await step(CTX)).toEqual({ error: 'No documents found for this account.' })
  })
})

describe('plural', () => {
  it('pluralises the connector’s own noun rather than appending a bare s', () => {
    expect(plural('repository')).toBe('repositories')
    expect(plural('assembly')).toBe('assemblies')
    expect(plural('document')).toBe('documents')
  })
})

describe('selectionConfig', () => {
  it('falls back to the plain id when an item carries no config of its own', () => {
    expect(selectionConfig(SINGLE, [{ id: 'only', name: 'only' }])).toEqual({ repo: 'only' })
  })

  it('collects ids for multi select', () => {
    expect(selectionConfig(MULTI, [DOC_A, DOC_B])).toEqual({ documents: ['docA', 'docB'] })
  })
})
