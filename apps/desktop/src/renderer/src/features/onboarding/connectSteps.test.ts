// The wizard's pure step model: which steps a connector's DECLARED shape
// implies, where a live ConnectionState sits on that rail, and what each step
// tells the user (SOL-mode aware, ADR-016). No provider ids anywhere — a
// connector the app has never seen must still get a correct rail.
import { describe, it, expect } from 'vitest'
import type { IntegrationAccessModes, IntegrationSelection } from '../../lib/api/resources'
import type { ConnectionState } from './onboardingStore'
import { stepInstruction, wizardPosition, wizardSteps, type WizardShape } from './connectSteps'

const NO_SHAPE: Omit<WizardShape, 'mode'> = {
  accessModes: null,
  selection: null,
  configFields: []
}

const SELECTION: IntegrationSelection = { mode: 'single', config_key: 'repo', label: 'repository' }

const ACCESS: IntegrationAccessModes = {
  default: 'read',
  modes: [
    { id: 'read', label: 'Read-only', description: 'Read models', scopes: [] },
    { id: 'write', label: 'Read and edit', description: 'Read and change models', scopes: [] }
  ]
}

describe('wizardSteps', () => {
  it('ends at the sign-in for an ACCOUNT-scoped connect (SOLUSDEV-241)', () => {
    const steps = wizardSteps({
      mode: 'oauth',
      ...NO_SHAPE,
      selection: SELECTION,
      accessModes: ACCESS,
      scope: 'account'
    })
    expect(steps.map((s) => s.id)).toEqual(['access', 'authorize'])
  })

  it('skips the grant and the sign-in when the user already holds a linked account', () => {
    const steps = wizardSteps({
      mode: 'oauth',
      ...NO_SHAPE,
      selection: SELECTION,
      accessModes: ACCESS,
      linkedAccount: true
    })
    expect(steps.map((s) => s.id)).toEqual(['configure', 'index'])
  })

  it('builds sign-in → pick → index for an OAuth connector with a selection', () => {
    const steps = wizardSteps({ mode: 'oauth', ...NO_SHAPE, selection: SELECTION })
    expect(steps.map((s) => s.id)).toEqual(['authorize', 'configure', 'index'])
    expect(steps[1].title).toBe('Pick repositories')
  })

  it('builds sign-in → details → index for an OAuth connector with config fields', () => {
    const steps = wizardSteps({ mode: 'oauth', ...NO_SHAPE, configFields: ['document_id'] })
    expect(steps.map((s) => s.id)).toEqual(['authorize', 'configure', 'index'])
    expect(steps[1].title).toBe('Enter details')
  })

  it('prepends the access choice when the connector offers more than one grant', () => {
    const steps = wizardSteps({ mode: 'oauth', ...NO_SHAPE, accessModes: ACCESS })
    expect(steps.map((s) => s.id)).toEqual(['access', 'authorize', 'index'])
  })

  it('omits the access step when only one grant is offered (nothing to decide)', () => {
    const oneMode: IntegrationAccessModes = { default: 'read', modes: [ACCESS.modes[0]] }
    const steps = wizardSteps({ mode: 'oauth', ...NO_SHAPE, accessModes: oneMode })
    expect(steps.map((s) => s.id)).toEqual(['authorize', 'index'])
  })

  it('builds file → index for a committed-export connector — no sign-in step', () => {
    const steps = wizardSteps({ mode: 'export-file', ...NO_SHAPE, configFields: ['export'] })
    expect(steps.map((s) => s.id)).toEqual(['file', 'index'])
  })
})

describe('wizardPosition', () => {
  const steps = wizardSteps({ mode: 'oauth', ...NO_SHAPE, selection: SELECTION })

  it('is idle on the first step before anything starts', () => {
    expect(wizardPosition(steps, undefined)).toEqual({ status: 'idle', stepIndex: 0 })
  })

  it('places a busy state on the step its stage names', () => {
    const state: ConnectionState = { phase: 'busy', stage: 'configure', label: 'Choose…' }
    expect(wizardPosition(steps, state)).toEqual({ status: 'busy', stepIndex: 1 })
  })

  it('maps the token-exchange link stage onto the sign-in step', () => {
    const state: ConnectionState = { phase: 'busy', stage: 'link', label: 'Linking…' }
    expect(wizardPosition(steps, state)).toEqual({ status: 'busy', stepIndex: 0 })
  })

  it('is done past the last step when the source is connected', () => {
    expect(wizardPosition(steps, { phase: 'done' })).toEqual({
      status: 'done',
      stepIndex: steps.length
    })
  })

  it('reports an error without inventing a position', () => {
    expect(wizardPosition(steps, { phase: 'error', error: 'nope' })).toEqual({
      status: 'error',
      stepIndex: 0
    })
  })

  it('falls back to the first step for a stage the rail does not carry', () => {
    const state: ConnectionState = { phase: 'busy', stage: 'access', label: '…' }
    expect(wizardPosition(steps, state)).toEqual({ status: 'busy', stepIndex: 0 })
  })
})

describe('stepInstruction', () => {
  const ctx = { name: 'FutureCAD', selectionLabel: 'document' }

  it('teaches in Guide mode and gets to the point in Expert mode', () => {
    const step = { id: 'authorize', title: 'Sign in' } as const
    const guide = stepInstruction(step, ctx, 'Guide')
    const expert = stepInstruction(step, ctx, 'Expert')
    expect(guide).toContain('FutureCAD')
    expect(guide.length).toBeGreaterThan(expert.length)
    expect(expert).not.toBe(guide)
  })

  it('names the connector selection noun in the pick instruction', () => {
    const step = { id: 'configure', title: 'Pick documents' } as const
    expect(stepInstruction(step, ctx, 'Guide')).toContain('documents')
  })

  it('covers every step id in both modes with non-empty copy', () => {
    const ids = ['access', 'authorize', 'configure', 'file', 'index'] as const
    for (const id of ids) {
      for (const mode of ['Guide', 'Expert'] as const) {
        expect(stepInstruction({ id }, ctx, mode).length).toBeGreaterThan(0)
      }
    }
  })
})
