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
    section: 'details',
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
  it('renders a code-section config entry as a CodeEnvironmentCard, not raw payload', () => {
    mount(
      entry({
        section: 'code',
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

  it('falls back to one honest line when a code config payload is unreadable', () => {
    mount(entry({ section: 'code', kind: 'config', text: null, payload: { nope: true } }))
    expect(screen.getByText('environment (unreadable)')).toBeInTheDocument()
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
  section: 'hardware',
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
        section: 'hardware',
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
