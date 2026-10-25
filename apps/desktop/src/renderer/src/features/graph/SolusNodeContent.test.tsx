import { afterEach, describe, it, expect, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import type { Entity, SolusEntry } from '../../lib/api/resources'
import { SolusNodeContent } from './SolusNodeContent'

const NOTE: Entity = {
  id: 'n1',
  type: 'solus_note',
  domain: 'project',
  name: 'Note',
  source_key: ''
}

function entry(over: Partial<SolusEntry>): SolusEntry {
  return {
    id: 'e1',
    section: 'goals',
    subsection: null,
    kind: 'text',
    author: 'user',
    text: 'Spec: 48 V bus',
    payload: null,
    name: null,
    artifact_id: null,
    entity_id: 'n1',
    media_type: null,
    size_bytes: null,
    created_by: 'u1',
    created_at: '',
    updated_at: '',
    ...over
  }
}

function mount(item: SolusEntry): void {
  render(
    <SolusNodeContent
      projectId="project"
      entity={NOTE}
      entry={item}
      section={null}
      count={0}
      online
      composer={null}
      onCompose={vi.fn()}
      onSubmit={vi.fn()}
    />
  )
}

describe('SolusNodeContent — entries', () => {
  it('renders an environment/software config entry as a CodeEnvironmentCard, not raw payload', () => {
    mount(
      entry({
        section: 'environment',
        subsection: 'software',
        kind: 'config',
        text: null,
        payload: {
          type: 'conda',
          name: 'perception',
          interpreter: '/opt/conda/envs/perception/bin/python',
          packages: [{ name: 'torch', version: '2.4.0' }],
          provenance: 'detected',
          captured_at: '2026-09-07T10:00:00Z'
        }
      })
    )
    expect(screen.getByText('conda')).toBeInTheDocument()
    expect(screen.getByText('perception')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /1 package$/ })).toBeInTheDocument()
    expect(screen.queryByText('Edit note')).not.toBeInTheDocument()
    expect(screen.queryByText(/"type"/)).not.toBeInTheDocument()
  })

  it('falls back to one honest line when a software config payload is unreadable', () => {
    mount(
      entry({
        section: 'environment',
        subsection: 'software',
        kind: 'config',
        text: null,
        payload: { nope: true }
      })
    )
    expect(screen.getByText('environment (unreadable)')).toBeInTheDocument()
  })

  it('names an unsupported config subsection instead of guessing a renderer', () => {
    mount(entry({ section: 'environment', subsection: 'spec', kind: 'config', text: null }))
    expect(screen.getByRole('status')).toHaveTextContent('Unsupported configuration section.')
  })

  it('renders an errors entry filed by SOL in monospace with the SOL marker', () => {
    mount(
      entry({
        section: 'errors',
        kind: 'sol',
        author: 'sol',
        text: 'ModuleNotFoundError: No module named "serial"\n  at flash.py:12'
      })
    )
    const body = screen.getByText(/ModuleNotFoundError/)
    expect(body).toHaveStyle({ fontFamily: 'var(--font-mono)' })
    expect(screen.getByText('filed by SOL')).toBeInTheDocument()
  })

  it('does not mark a user-typed errors entry as filed by SOL', () => {
    mount(entry({ section: 'errors', text: 'Servo 3 timed out during calibration' }))
    expect(screen.getByText(/Servo 3/)).toBeInTheDocument()
    expect(screen.queryByText('filed by SOL')).not.toBeInTheDocument()
    expect(screen.getByText('Edit note')).toBeInTheDocument()
  })
})

vi.mock('./hardware/HardwareConfigPanel', () => ({
  HardwareConfigPanel: ({ entityId }: { entityId: string }) => (
    <div>Configuration for {entityId}</div>
  )
}))
afterEach(cleanup)
const hardwareEntity: Entity = {
  id: 'config-node',
  type: 'hardware_config',
  domain: 'project',
  name: 'Config',
  source_key: ''
}
const hardwareEntry: SolusEntry = {
  id: 'entry',
  kind: 'config',
  section: 'environment',
  subsection: 'hardware',
  author: 'user',
  text: 'Configuration',
  payload: { schema_version: 2, entity_id: '00000000-0000-4000-8000-000000000001' },
  entity_id: hardwareEntity.id,
  name: null,
  artifact_id: null,
  media_type: null,
  size_bytes: null,
  created_by: null,
  created_at: '',
  updated_at: ''
}
it('renders CONFIG through its subject editor even when a note composer was requested', () => {
  render(
    <SolusNodeContent
      projectId="project"
      entity={hardwareEntity}
      entry={hardwareEntry}
      section={null}
      count={0}
      online
      composer={{
        kind: 'edit',
        section: 'environment',
        subsection: 'hardware',
        entityId: hardwareEntity.id,
        entry: hardwareEntry
      }}
      onCompose={vi.fn()}
      onSubmit={vi.fn()}
    />
  )
  expect(
    screen.getByText('Configuration for 00000000-0000-4000-8000-000000000001')
  ).toBeInTheDocument()
  expect(screen.queryByText('Edit note')).not.toBeInTheDocument()
})

// SOLUSDEV-320 P5-T3d — the environment/divergences subsection and the history
// section render their own views; history owns no rows, so no composer.
vi.mock('./EnvironmentDivergences', () => ({
  EnvironmentDivergences: ({ projectId }: { projectId: string }) => (
    <div>Divergences for {projectId}</div>
  )
}))
vi.mock('./HistoryList', () => ({
  HistoryList: ({ projectId }: { projectId: string }) => <div>History for {projectId}</div>
}))

function mountSection(section: 'environment' | 'history', subsection: string | null): void {
  render(
    <SolusNodeContent
      projectId="project"
      entity={{ ...NOTE, id: 's1', type: 'solus_section' }}
      section={section}
      subsection={subsection}
      count={0}
      online
      composer={null}
      onCompose={vi.fn()}
      onSubmit={vi.fn()}
    />
  )
}

describe('SolusNodeContent — divergences and history', () => {
  it('renders the divergences table for the environment/divergences subsection node', () => {
    mountSection('environment', 'divergences')
    expect(screen.getByText('Divergences for project')).toBeInTheDocument()
    expect(screen.queryByText('Add a note')).toBeNull()
  })

  it('renders the divergences table for a config entry filed under it', () => {
    mount(entry({ section: 'environment', subsection: 'divergences', kind: 'config', text: null }))
    expect(screen.getByText('Divergences for project')).toBeInTheDocument()
  })

  it('renders the history list for the history section and offers no composer', () => {
    mountSection('history', null)
    expect(screen.getByText('History for project')).toBeInTheDocument()
    expect(screen.queryByText('Add a note')).toBeNull()
  })

  it('other environment subsections get the plain section content — the count, no actions', () => {
    mountSection('environment', 'spec')
    expect(screen.queryByText('Add a note')).toBeNull()
    expect(screen.getByText('EMPTY')).toBeInTheDocument()
  })
})
