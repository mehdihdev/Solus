// What a tool offers next (SOLUSDEV-241/242, shared with Home's Sources block
// for SOLUSDEV-317): derived from the connector's declared shape and whether an
// account is linked — never from its id.
import { describe, it, expect } from 'vitest'
import { nextStep } from './accountSteps'
import type { CatalogEntry } from '../onboarding/integrationCatalog'

const OAUTH: CatalogEntry = {
  id: 'github',
  name: 'GitHub',
  kind: 'Code',
  mark: 'Gh',
  mode: 'oauth',
  configFields: [],
  selection: { mode: 'multi', config_key: 'repo', label: 'repository' },
  accessModes: null,
  hosted: null
}

describe('nextStep', () => {
  it('asks an unlinked OAuth tool to connect at account scope', () => {
    expect(nextStep(OAUTH, false)).toEqual({
      action: 'Connect',
      scope: 'account',
      needsProject: false
    })
  })

  it('offers a linked tool its project-level pick', () => {
    expect(nextStep(OAUTH, true)).toEqual({
      action: 'Pick repositories',
      scope: 'project',
      needsProject: true
    })
  })

  it('falls back to details, then a plain add, when there is nothing to pick', () => {
    expect(nextStep({ ...OAUTH, selection: null, configFields: ['url'] }, true).action).toBe(
      'Enter details'
    )
    expect(nextStep({ ...OAUTH, selection: null }, true).action).toBe('Add to project')
  })

  it('gives export and local tools their own step whatever is linked', () => {
    expect(nextStep({ ...OAUTH, mode: 'export-file' }, false).action).toBe('Choose file')
    expect(nextStep({ ...OAUTH, mode: 'local-bridge' }, false)).toEqual({
      action: 'Connect',
      scope: 'project',
      needsProject: false
    })
  })
})
