import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { SourceItem } from './AccountRows'
import type { Source } from '../../lib/api/resources'
import type { CatalogEntry } from '../onboarding/integrationCatalog'

const SOURCE: Source = {
  id: 's1',
  project_id: 'p1',
  type: 'kicad',
  name: 'Divider',
  status: 'connected',
  config: {},
  account_login: null,
  last_synced_at: null,
  last_error: null,
  created_at: '',
  updated_at: ''
}

function show(type: string, fields: string[]): void {
  const entry: CatalogEntry = {
    id: type,
    name: type,
    kind: 'EDA',
    mark: 'E',
    mode: 'export-file',
    configFields: fields,
    selection: null,
    accessModes: null,
    hosted: null
  }
  render(
    <SourceItem
      source={{ ...SOURCE, type }}
      entry={entry}
      projectId="p1"
      onSync={vi.fn()}
      onDisconnect={vi.fn(async () => true)}
      onChanged={vi.fn()}
    />
  )
}

describe('source project-link capability', () => {
  it.each(['kicad', 'altium', 'future-eda'])('shows the action for %s when advertised', (type) => {
    show(type, ['export', 'project_path'])
    expect(screen.getByRole('button', { name: /Link project file/ })).toBeInTheDocument()
  })
  it('does not infer a capability merely from a KiCad source', () => {
    show('kicad', ['export', 'board'])
    expect(screen.queryByRole('button', { name: /Link project file/ })).not.toBeInTheDocument()
  })
})
