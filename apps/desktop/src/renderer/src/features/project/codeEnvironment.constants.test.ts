// SOLUSDEV-250 (I3) — the Code environment row's words, derived honestly from
// the view: an offline companion, a code server that is not running and an
// unprobed environment each say so; only a live probe gets the summary line.
import { describe, expect, it } from 'vitest'
import type { CodeEnvironmentView, CodeProbe } from '../../lib/api/resources.codeenv'
import { EMPTY_CODE_ENVIRONMENT_VIEW } from '../../lib/api/resources.codeenv'
import { API_UNREACHABLE_NOTE, COMPANION_OFFLINE_NOTE } from './localFolder.constants'
import {
  CODE_ENVIRONMENT_POLL_MS,
  CODE_SERVER_NOT_RUNNING_NOTE,
  NOT_PROBED_NOTE,
  codeEnvironmentStatus,
  conflictLine,
  evidencePins,
  localSourceForMachine,
  plural
} from './codeEnvironment.constants'

const PROBE: CodeProbe = {
  python: { path: '/usr/bin/python3', version: '3.12.4' },
  interpreters: [],
  venv: { path: '.venv', python_version: '3.12.4', packages: [], truncated: false },
  conda: null,
  uv: null
}

const live = (over: Partial<CodeEnvironmentView> = {}): CodeEnvironmentView => ({
  ...EMPTY_CODE_ENVIRONMENT_VIEW,
  bridge: { connected: true, code_server: true },
  probe: PROBE,
  requirements: { count: 2, files: ['requirements.txt', 'pyproject.toml'] },
  ...over
})

describe('codeEnvironmentStatus', () => {
  it('says the API is unreachable when there is no view and the hook is offline', () => {
    expect(codeEnvironmentStatus(null, 'offline')).toBe(API_UNREACHABLE_NOTE)
  })

  it('says it is loading before the first view lands', () => {
    expect(codeEnvironmentStatus(null, 'loading')).toBe('Loading…')
  })

  it('names an offline companion before anything else', () => {
    const view = live({ bridge: { connected: false, code_server: false } })
    expect(codeEnvironmentStatus(view, 'ready')).toBe(COMPANION_OFFLINE_NOTE)
  })

  it('names a code server that is not running', () => {
    const view = live({ bridge: { connected: true, code_server: false } })
    expect(codeEnvironmentStatus(view, 'ready')).toBe(CODE_SERVER_NOT_RUNNING_NOTE)
  })

  it('says not probed yet when the server is up but no probe answered', () => {
    expect(codeEnvironmentStatus(live({ probe: null }), 'ready')).toBe(NOT_PROBED_NOTE)
  })

  it('summarises python, venv and requirement count from a live probe', () => {
    expect(codeEnvironmentStatus(live(), 'ready')).toBe('3.12.4 · .venv · 2 requirements')
  })

  it('is honest about a missing interpreter and a missing venv, and singular counts', () => {
    const view = live({
      probe: { ...PROBE, python: null, venv: null },
      requirements: { count: 1, files: ['requirements.txt'] }
    })
    expect(codeEnvironmentStatus(view, 'ready')).toBe(
      'no Python found · no virtual environment · 1 requirement'
    )
  })
})

describe('conflictLine', () => {
  const warning = {
    checker_id: 'pin_conflict',
    severity: 'warning' as const,
    message: 'torch pinned twice',
    evidence: {},
    suggested_area: null
  }

  it('is null without conflicts', () => {
    expect(conflictLine(live())).toBeNull()
  })

  it('counts conflicts and says a split is proposed when the proposal splits', () => {
    const view = live({
      conflicts: [warning, warning],
      proposal: { environments: [], split: true }
    })
    expect(conflictLine(view)).toBe('2 dependency conflicts — split proposed')
  })

  it('uses the singular and omits the split note when no split is proposed', () => {
    const view = live({ conflicts: [warning], proposal: { environments: [], split: false } })
    expect(conflictLine(view)).toBe('1 dependency conflict')
  })
})

describe('helpers', () => {
  it('pluralises by count', () => {
    expect(plural(1, 'package')).toBe('1 package')
    expect(plural(0, 'package')).toBe('0 packages')
  })

  it('finds the local source whose config names this machine, and only that one', () => {
    const mine = { type: 'local', config: { machine_id: 'm1' } }
    const other = { type: 'local', config: { machine_id: 'm2' } }
    const github = { type: 'github', config: { machine_id: 'm1' } }
    expect(localSourceForMachine([other, github, mine], 'm1')).toBe(mine)
    expect(localSourceForMachine([other, github], 'm1')).toBeNull()
    expect(localSourceForMachine([mine], null)).toBeNull()
  })

  it('polls slowly — the folder watcher drives real changes', () => {
    expect(CODE_ENVIRONMENT_POLL_MS).toBe(30_000)
  })
})

describe('evidencePins', () => {
  it('reads well-formed pins and drops anything else', () => {
    const evidence = {
      package: 'torch',
      pins: [
        { specifier: '==2.1.0', source_file: 'isaac/requirements.txt' },
        { specifier: 7, source_file: 'x' },
        'nonsense',
        null
      ]
    }
    expect(evidencePins(evidence)).toEqual([
      { specifier: '==2.1.0', source_file: 'isaac/requirements.txt' }
    ])
    expect(evidencePins({})).toEqual([])
    expect(evidencePins({ pins: 'no' })).toEqual([])
  })
})
